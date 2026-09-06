"""
Configuration for the QQQ trend/momentum monthly-rebalance backtest.

Strategy basis: Stan Weinstein (Stage 2 uptrend) + Mark Minervini (Trend
Template) + William O'Neil (relative strength / liquidity filters),
restricted to the current QQQ (Nasdaq-100) constituent universe.

NOTE ON SURVIVORSHIP BIAS: this config uses TODAY's QQQ holdings applied
retroactively across the whole backtest window. Stocks that were removed
from QQQ (bankrupt, acquired, delisted, demoted) during the backtest period
are NOT included, which will overstate the strategy's historical returns
versus what a real point-in-time investor would have experienced. This was
a deliberate simplification choice -- see README.md.

These are the DEFAULTS. Anything here can be overridden without touching
code by editing config.toml next to this file -- see Config.load() at the
bottom and the comments in config.toml itself.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields

DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "config.toml")


@dataclass
class Config:
    # ---------------------------------------------------------------
    # Data source: where price history comes from.
    #   "ib"       -- Interactive Brokers (needs TWS/IB Gateway running and
    #                 a market-data subscription); authoritative, rate-limited.
    #   "yfinance" -- Yahoo Finance (no login, no subscription); convenient
    #                 for development, best-effort quality.
    # Aliases accepted: ibkr/tws -> ib, yahoo/yf -> yfinance.
    # ---------------------------------------------------------------
    data_source: str = "ib"

    # ---------------------------------------------------------------
    # IBKR connection (TWS or IB Gateway must be running and API access
    # enabled: File > Global Configuration > API > Settings)
    # ---------------------------------------------------------------
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497          # 7497 = TWS paper, 7496 = TWS live,
                                    # 4002 = IB Gateway paper, 4001 = IB Gateway live
    ibkr_client_id: int = 17
    ibkr_pacing_delay_sec: float = 1.2   # sleep between live historical-data
                                          # requests; IBKR allows roughly 6 per
                                          # 2 seconds before pacing violations

    # ---------------------------------------------------------------
    # Backtest window
    # ---------------------------------------------------------------
    backtest_years: int = 3            # the period you actually want measured
    warmup_years: float = 1.5          # extra history fetched before the
                                        # measured window, needed for 200-day
                                        # SMA / 52-week-high / RS lookbacks
    fetch_duration_str: str = "5 Y"    # IBKR reqHistoricalData duration string
                                        # (backtest_years + warmup_years, rounded up)
    bar_size: str = "1 day"
    what_to_show: str = "ADJUSTED_LAST"   # splits/dividends adjusted close

    # yfinance equivalents of the three IBKR fetch settings above (the two
    # backends take different arguments for the same idea)
    yf_period: str = "5y"              # history window: 1y/2y/5y/10y/max
    yf_auto_adjust: bool = True        # split- AND dividend-adjusted OHLC,
                                        # i.e. the analogue of ADJUSTED_LAST
    yf_pacing_delay_sec: float = 0.0   # Yahoo needs no pacing under normal
                                        # use; raise it if you get throttled

    # ---------------------------------------------------------------
    # Universe
    # ---------------------------------------------------------------
    benchmark_ticker: str = "SPY"      # broad-market benchmark for relative
                                        # strength (NOT QQQ itself -- see the
                                        # discussion on why RS-within-QQQ is diluted)
    compare_ticker: str = "QQQ"        # what we display the strategy against

    # ---------------------------------------------------------------
    # Portfolio construction
    # ---------------------------------------------------------------
    max_positions: int = 20
    # If fewer than max_positions stocks pass ALL filters in a given month,
    # the strategy holds fewer names and leaves the rest in cash -- it does
    # NOT force weaker names in just to fill 20 slots.
    rebalance_mode: str = "full_equal_weight"   # or "entries_exits_only"
    # "fixed_slot": each qualifying name gets a fixed 1/max_positions share
    #   of portfolio value, so a thin month (few qualifiers) leaves the rest
    #   in cash instead of concentrating capital into 1-2 names.
    # "equal_weight_of_qualifiers": splits 100% of capital evenly across
    #   however many names qualify, however few -- can mean full concentration
    #   into a single name in a thin month. NOT recommended; kept for comparison.
    position_sizing: str = "fixed_slot"
    initial_capital: float = 28_000.0

    # Simple transaction-cost assumption (spread + slippage), applied to
    # both buys and sells, as a fraction of trade notional.
    txn_cost_bps: float = 5.0   # 0.05% per trade leg

    # ---------------------------------------------------------------
    # Trend Template (Minervini / Weinstein Stage 2) thresholds
    # ---------------------------------------------------------------
    sma_short: int = 50
    sma_mid: int = 150
    sma_long: int = 200
    sma_long_uptrend_lookback_days: int = 21   # 200-SMA must be higher now
                                                # than ~1 month ago
    pct_above_52w_low_min: float = 30.0        # price at least 30% above 52w low
    pct_below_52w_high_max: float = 25.0       # price within 25% of 52w high

    # ---------------------------------------------------------------
    # "Properly formed base" proxy (mechanized approximation -- true base
    # quality is visual/judgmental; see README limitations section)
    # ---------------------------------------------------------------
    base_lookback_weeks: int = 10
    base_max_range_pct: float = 35.0   # (high-low)/low over lookback window
                                        # must be under this to count as "tight"

    # ---------------------------------------------------------------
    # Relative strength (O'Neil-style multi-period weighted RS vs benchmark)
    # ---------------------------------------------------------------
    rs_lookback_days: tuple = (63, 126, 189, 252)   # ~3, 6, 9, 12 months
    rs_weights: tuple = (0.4, 0.2, 0.2, 0.2)        # most recent quarter weighted heaviest

    # ---------------------------------------------------------------
    # Liquidity / quality floor (non-binding for virtually all QQQ names,
    # kept as a cheap safety check / in case a name gaps below $10 or
    # volume collapses)
    # ---------------------------------------------------------------
    min_price: float = 10.0
    min_avg_volume: int = 200_000
    avg_volume_lookback_days: int = 50

    # ---------------------------------------------------------------
    # Exit rule -- checked EVERY trading day, independent of the monthly
    # rebalance clock
    # ---------------------------------------------------------------
    exit_on_close_below_sma_long: bool = True

    # ---------------------------------------------------------------
    # Misc
    # ---------------------------------------------------------------
    cache_dir: str = "./data_cache"
    risk_free_rate_annual: float = 0.0   # used for Sharpe ratio; set to
                                          # your T-bill/BOXX-equivalent yield
                                          # if you want excess-return Sharpe

    # ---------------------------------------------------------------
    # Loading overrides from config.toml
    # ---------------------------------------------------------------
    @classmethod
    def load(cls, path: str | None = None, required: bool = False) -> "Config":
        """
        Build a Config from the defaults above, overlaid with any values set
        in config.toml.

        The TOML file is organised into tables purely for readability -- they
        are flattened before matching, so every key must be named exactly like
        a field on this class, and an unknown key is an error rather than a
        silently ignored typo. If the file is absent, the defaults are used
        (unless required=True).
        """
        path = path or DEFAULT_CONFIG_FILE
        if not os.path.exists(path):
            if required:
                raise FileNotFoundError(f"Config file not found: {path}")
            return cls()

        with open(path, "rb") as fh:
            raw = tomllib.load(fh)

        flat: dict = {}
        for key, value in raw.items():
            if isinstance(value, dict):        # a [table] -- flatten one level
                for sub_key, sub_value in value.items():
                    flat[sub_key] = sub_value
            else:                              # a top-level key
                flat[key] = value

        valid = {f.name: f for f in fields(cls)}
        unknown = sorted(set(flat) - set(valid))
        if unknown:
            raise ValueError(
                f"Unknown setting(s) in {path}: {', '.join(unknown)}. "
                f"Keys must match Config field names."
            )

        # TOML has no tuple type; the tuple-typed fields arrive as lists.
        for key, value in flat.items():
            if valid[key].type is tuple or valid[key].type == "tuple":
                flat[key] = tuple(value)

        return cls(**flat)
