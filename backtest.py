"""
Daily-stepped backtest engine.

Each trading day: check the mechanical exit rule on every held position
(independent of the rebalance calendar). On scheduled monthly rebalance
days: re-screen the whole universe against the trend/base/liquidity
filters, rank survivors by relative strength, and reweight to the target
list -- holding fewer than max_positions (rest in cash) if fewer names
qualify.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import Config
import signals as sig


class Portfolio:
    def __init__(self, cash: float):
        self.cash = cash
        self.positions: dict[str, float] = {}   # symbol -> shares (fractional ok)
        self.trade_log: list[dict] = []

    def value(self, prices_today: dict[str, float]) -> float:
        v = self.cash
        for sym, shares in self.positions.items():
            price = prices_today.get(sym)
            if price is not None and not np.isnan(price):
                v += shares * price
        return v


def _first_trading_day_of_month_flags(dates: pd.DatetimeIndex) -> np.ndarray:
    months = pd.Series(dates).dt.to_period("M")
    return (months != months.shift(1)).to_numpy()


def run_backtest(raw_data: dict[str, pd.DataFrame], bench_df: pd.DataFrame,
                  compare_df: pd.DataFrame, cfg: Config) -> dict:
    """
    raw_data: {symbol: OHLCV DataFrame indexed by date} for the QQQ universe
    bench_df: OHLCV DataFrame for cfg.benchmark_ticker (relative strength)
    compare_df: OHLCV DataFrame for cfg.compare_ticker (buy&hold comparison)
    """
    # --- Master calendar: benchmark's trading days ---
    master_dates = bench_df.index

    # --- Compute indicators per symbol, reindexed onto the master calendar ---
    ind = {}
    for sym, df in raw_data.items():
        d = sig.add_indicators(df, cfg)
        d = d.reindex(master_dates).ffill(limit=3)
        ind[sym] = d

    bench_ind = sig.add_indicators(bench_df, cfg).reindex(master_dates).ffill(limit=3)
    compare_ind = compare_df.reindex(master_dates).ffill(limit=3)

    # --- Restrict to the measured window (after the warmup buffer) ---
    end_date = master_dates.max()
    start_date = end_date - pd.DateOffset(years=cfg.backtest_years)
    sim_dates = master_dates[master_dates >= start_date]
    rebal_flags = _first_trading_day_of_month_flags(sim_dates)

    fee_rate = cfg.txn_cost_bps / 10000.0
    symbols = list(ind.keys())

    portfolio = Portfolio(cfg.initial_capital)
    equity_curve = []
    turnover_notional = 0.0

    for day_pos_in_sim, current_date in enumerate(sim_dates):
        i = master_dates.get_loc(current_date)  # absolute index into full series

        prices_today = {
            sym: ind[sym]["close"].iloc[i] if i < len(ind[sym]) else np.nan
            for sym in symbols
        }

        # --- 1. Daily mechanical exit check (independent of rebalance day) ---
        for sym in list(portfolio.positions.keys()):
            row = ind[sym].iloc[i]
            if sig.exit_triggered(row, cfg):
                shares = portfolio.positions.pop(sym)
                price = prices_today[sym]
                if not np.isnan(price):
                    proceeds = shares * price
                    cost = proceeds * fee_rate
                    portfolio.cash += proceeds - cost
                    turnover_notional += proceeds
                    portfolio.trade_log.append(
                        {"date": current_date, "symbol": sym, "action": "EXIT_TREND_BREAK",
                         "shares": shares, "price": price}
                    )

        # --- 2. Monthly rebalance: rescreen + reweight ---
        if rebal_flags[day_pos_in_sim]:
            candidates = []
            for sym in symbols:
                if i >= len(ind[sym]):
                    continue
                row = ind[sym].iloc[i]
                prev_long = ind[sym]["sma_long"].iloc[max(0, i - cfg.sma_long_uptrend_lookback_days)]
                if not sig.trend_template_pass(row, prev_long, cfg):
                    continue
                if not sig.base_is_tight(row, cfg):
                    continue
                if not sig.liquidity_ok(row, cfg):
                    continue
                rs = sig.relative_strength_score(
                    ind[sym]["close"], bench_ind["close"], i, cfg
                )
                if np.isnan(rs):
                    continue
                candidates.append((sym, rs))

            candidates.sort(key=lambda x: x[1], reverse=True)
            target_symbols = [s for s, _ in candidates[: cfg.max_positions]]

            if cfg.rebalance_mode != "full_equal_weight":
                raise NotImplementedError(
                    "Only rebalance_mode='full_equal_weight' is implemented. "
                    "See README for extending 'entries_exits_only'."
                )

            # Liquidate everything currently held, then re-buy equal-weight
            # across the new target list (simplest correct way to hit exact
            # equal weights; real-world you'd only trade the deltas).
            for sym in list(portfolio.positions.keys()):
                shares = portfolio.positions.pop(sym)
                price = prices_today.get(sym)
                if price is not None and not np.isnan(price):
                    proceeds = shares * price
                    cost = proceeds * fee_rate
                    portfolio.cash += proceeds - cost
                    turnover_notional += proceeds
                    portfolio.trade_log.append(
                        {"date": current_date, "symbol": sym, "action": "SELL_REBAL",
                         "shares": shares, "price": price}
                    )

            n = len(target_symbols)
            if n > 0:
                total_value = portfolio.cash
                if cfg.position_sizing == "fixed_slot":
                    target_value_each = total_value / cfg.max_positions
                else:  # "equal_weight_of_qualifiers"
                    target_value_each = total_value / n
                for sym in target_symbols:
                    price = prices_today.get(sym)
                    if price is None or np.isnan(price) or price <= 0:
                        continue
                    spend = min(target_value_each, portfolio.cash / (1 + fee_rate))
                    shares = spend / price
                    portfolio.cash -= spend * (1 + fee_rate)
                    portfolio.positions[sym] = shares
                    turnover_notional += spend
                    portfolio.trade_log.append(
                        {"date": current_date, "symbol": sym, "action": "BUY_REBAL",
                         "shares": shares, "price": price}
                    )
            # else: nothing qualified this month -- stay in cash

        # --- 3. Mark to market ---
        equity_curve.append(
            {"date": current_date, "value": portfolio.value(prices_today),
             "n_positions": len(portfolio.positions)}
        )

    equity_df = pd.DataFrame(equity_curve).set_index("date")

    # --- Buy & hold comparison over the same measured window ---
    cmp_window = compare_ind.loc[compare_ind.index >= start_date, "close"].dropna()
    cmp_shares = cfg.initial_capital / cmp_window.iloc[0]
    cmp_curve = cmp_window * cmp_shares

    return {
        "equity_curve": equity_df,
        "benchmark_curve": cmp_curve,
        "trade_log": pd.DataFrame(portfolio.trade_log),
        "turnover_notional": turnover_notional,
    }


def performance_report(equity_df: pd.DataFrame, cfg: Config) -> dict:
    v = equity_df["value"]
    daily_ret = v.pct_change().dropna()
    n_years = (v.index[-1] - v.index[0]).days / 365.25

    total_return = v.iloc[-1] / v.iloc[0] - 1
    cagr = (v.iloc[-1] / v.iloc[0]) ** (1 / n_years) - 1 if n_years > 0 else np.nan
    ann_vol = daily_ret.std() * np.sqrt(252)
    excess_daily = daily_ret - cfg.risk_free_rate_annual / 252
    sharpe = (excess_daily.mean() / daily_ret.std()) * np.sqrt(252) if daily_ret.std() > 0 else np.nan

    running_max = v.cummax()
    drawdown = v / running_max - 1
    max_dd = drawdown.min()

    return {
        "total_return_pct": total_return * 100,
        "cagr_pct": cagr * 100,
        "annual_vol_pct": ann_vol * 100,
        "sharpe": sharpe,
        "max_drawdown_pct": max_dd * 100,
        "avg_positions_held": equity_df["n_positions"].mean(),
    }
