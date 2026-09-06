# QQQ Trend/Momentum Monthly-Rebalance Backtest

Mechanized version of the Weinstein (Stage 2) / Minervini (Trend Template) /
O'Neil (relative strength, liquidity) stock-selection style, applied monthly
to the current QQQ (Nasdaq-100) constituent list, with a daily mechanical
exit rule layered on top of the monthly rebalance.

## Setup

1. Install and run **TWS** or **IB Gateway**, logged into your IBKR account
   (paper trading account recommended for a first run).
2. Enable API access: `File > Global Configuration > API > Settings` →
   check "Enable ActiveX and Socket Clients", note the socket port
   (default 7497 for TWS paper trading), and confirm `127.0.0.1` is trusted.
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
   If `ib_async` isn't available, `pip install ib_insync` works as a drop-in
   replacement (the code auto-detects whichever is installed) — `ib_insync`
   was archived by its author in 2023, so `ib_async` is the actively
   maintained option.
4. Check `config.py` — in particular `ibkr_port` (must match TWS/Gateway's
   configured API port) and `ibkr_client_id` (must not collide with another
   active API connection).
5. Run:
   ```
   python main.py
   ```
   First run fetches ~103 symbols x 5 years of daily bars from IBKR (a few
   minutes, respecting IBKR's pacing limits) and caches them to
   `./data_cache/`. Later runs reuse the cache; pass `--refresh` to
   force a re-download.

Outputs: `equity_curve.csv`, `trade_log.csv`, `backtest_result.png`, and a
console summary (total return, CAGR, volatility, Sharpe, max drawdown,
average positions held) compared against QQQ buy-and-hold over the same
window.

## What this does, mechanically

- **Universe**: today's QQQ holdings (`qqq_universe.py`), applied across
  the whole backtest window.
- **Monthly rebalance** (first trading day of each month): re-screen every
  symbol against —
  - Minervini/Weinstein Stage-2 trend template (price > 150-day SMA >
    200-day SMA, 50-day SMA > 150-day SMA, 200-day SMA rising, price ≥30%
    above its 52-week low, price within 25% of its 52-week high)
  - a mechanized "tight base" proxy (10-week price range under a threshold)
  - liquidity floor (price ≥ $10, 50-day avg volume ≥ 200k — non-binding
    for virtually all QQQ names, kept as a cheap safety check)
  - rank survivors by an O'Neil-style weighted relative-strength score
    **vs. SPY** (a broad-market benchmark), not vs. QQQ itself
  - take the top `max_positions` (currently 20); if fewer names qualify,
    hold fewer and leave the rest in cash — never force-fill with weaker
    names
  - each qualifying slot gets a **fixed** 1/max_positions share of
    portfolio value (`position_sizing = "fixed_slot"`), so a thin month
    doesn't concentrate the whole account into one or two names
- **Daily exit rule**, checked every trading day regardless of the
  rebalance calendar: close below the 200-day SMA triggers an immediate
  sell.

## Known limitations — read before trusting the numbers

- **Survivorship bias (as chosen)**: this uses *today's* QQQ constituents
  for the whole backtest period. Names removed from the index during the
  window (delisted, acquired, demoted) are absent, which overstates
  historical returns relative to what a real investor lived through. If
  you want an apples-to-apples comparison against QQQ itself, keep this in
  mind — QQQ's actual return reflects the real, evolving index membership;
  this strategy's backtest does not.
- **"Proper base" is approximated, not truly judged**: the real
  methodology involves visually assessing base quality (depth, number of
  contractions, volume dry-up). The 10-week range threshold here is a
  rough proxy and will pass some ugly consolidations and reject some
  genuinely tight ones a human chartist would read differently.
- **Sector relative strength was intentionally left out** of this
  mechanization. Within a 100-name, tech/comm-services-heavy universe like
  QQQ, sector-RS carries little discriminating power — most names cluster
  in a handful of sectors, so it doesn't reliably surface genuine
  sector-rotation the way it would across the full market. Ranking is by
  market-wide (SPY) relative strength alone.
- **No tax modeling**: the report shows trade count and turnover notional
  so you can estimate short-term-gains drag yourself, but it does not
  compute after-tax returns — this depends on your specific tax situation.
- **Transaction costs are a flat basis-point assumption**
  (`txn_cost_bps`), not a real bid-ask/slippage model. Increase it to
  stress-test sensitivity to costs, especially given the turnover this
  style produces.
- **`rebalance_mode = "entries_exits_only"` is not implemented** — only
  full equal-weight rebalancing at each monthly reconstitution is
  functional. Extend `backtest.py` if you want a lower-turnover variant
  that only trades the deltas.
- **Adjusted-close caveat**: IBKR's `ADJUSTED_LAST` accounts for splits and
  (typically) dividends, but reinvestment mechanics can differ slightly
  from a true total-return series — minor over a 3-year window, worth
  knowing if you're reconciling against another data source.
- This is a research/backtesting tool. It does not place real orders.

## Files

- `config.py` — all strategy parameters
- `qqq_universe.py` — the static ticker list (re-pull periodically)
- `ibkr_data.py` — IBKR historical data fetch + local disk cache
- `signals.py` — filter and scoring functions
- `backtest.py` — the daily-stepped simulation engine
- `main.py` — orchestration / CLI entry point
- `test_synthetic.py` — runs the engine against synthetic random-walk data
  so you can sanity-check the logic runs correctly *before* connecting to
  IBKR at all: `python test_synthetic.py`
