"""
Pluggable historical-data backends.

The backtest itself does not care where bars come from -- it just wants a
dict of {symbol: DataFrame} indexed by date with open/high/low/close/volume
columns. This module defines that contract, the on-disk cache shared by all
backends, and the factory that picks a backend from the config.

Backends:
  - "ib"       -> ibkr_data.IBKRDataSource      (TWS / IB Gateway API)
  - "yfinance" -> yfinance_data.YFinanceDataSource  (Yahoo Finance, no login)

Select one in config.toml:

    [data]
    data_source = "yfinance"

or override for a single run with `python main.py --source ib`.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod

import pandas as pd

from config import Config

BAR_COLUMNS = ["open", "high", "low", "close", "volume"]

# Accepted spellings for each backend, so config.toml / --source are forgiving.
_ALIASES = {
    "ib": "ib",
    "ibkr": "ib",
    "tws": "ib",
    "interactive_brokers": "ib",
    "yfinance": "yfinance",
    "yahoo": "yfinance",
    "yf": "yfinance",
}


def normalize_source_name(name: str) -> str:
    """Map a user-supplied data-source name onto a canonical backend key."""
    key = str(name).strip().lower().replace("-", "_").replace(" ", "_")
    if key not in _ALIASES:
        raise ValueError(
            f"Unknown data_source {name!r}. Valid options: "
            f"{', '.join(sorted(set(_ALIASES.values())))} "
            f"(aliases: {', '.join(sorted(_ALIASES))})"
        )
    return _ALIASES[key]


class DataSource(ABC):
    """
    Base class handling everything that is identical across backends:
    the disk cache, the fetch loop, and request pacing. Subclasses only
    implement the actual download.
    """

    # Used as the cache sub-directory name, so switching backends does not
    # mix Yahoo bars into the IBKR cache (or vice versa).
    name: str = "base"

    # Seconds to sleep between live downloads; overridden per backend.
    pacing_delay_sec: float = 0.0

    def __init__(self, cfg: Config):
        self.cfg = cfg

    # -- lifecycle -------------------------------------------------------
    # Only the IBKR backend actually needs a session; yfinance is stateless.

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def __enter__(self) -> "DataSource":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()

    # -- cache -----------------------------------------------------------

    def cache_path(self, symbol: str) -> str:
        d = os.path.join(self.cfg.cache_dir, self.name)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{symbol}.csv")

    def legacy_cache_path(self, symbol: str) -> str | None:
        """
        Pre-multi-backend caches were written flat into cache_dir/. Backends
        that produced them can point here so an existing cache is still a hit
        instead of triggering a full re-download.
        """
        return None

    def _read_cache(self, symbol: str) -> pd.DataFrame | None:
        for path in (self.cache_path(symbol), self.legacy_cache_path(symbol)):
            if path and os.path.exists(path):
                df = pd.read_csv(path, parse_dates=["date"])
                return df.set_index("date")
        return None

    # -- fetching --------------------------------------------------------

    @abstractmethod
    def _download_daily_bars(self, symbol: str) -> pd.DataFrame:
        """Download daily bars for one symbol; index=date, columns=BAR_COLUMNS."""

    def fetch_daily_bars(self, symbol: str, use_cache: bool = True) -> pd.DataFrame:
        """Fetch (or load cached) adjusted daily OHLCV bars for one symbol."""
        if use_cache:
            cached = self._read_cache(symbol)
            if cached is not None:
                return cached

        df = self._download_daily_bars(symbol)
        if df is None or df.empty:
            raise RuntimeError(f"No historical data returned for {symbol}")

        df = df[BAR_COLUMNS]
        df.to_csv(self.cache_path(symbol))
        return df

    def fetch_universe_bars(self, symbols: list[str],
                            use_cache: bool = True) -> dict[str, pd.DataFrame]:
        """
        Fetch daily bars for a list of symbols. Sleeps between *live*
        downloads to respect the backend's rate limits (IBKR in particular
        throttles historical data requests hard).
        """
        data: dict[str, pd.DataFrame] = {}
        for i, sym in enumerate(symbols):
            from_cache = use_cache and self._read_cache(sym) is not None
            try:
                data[sym] = self.fetch_daily_bars(sym, use_cache=use_cache)
            except Exception as e:
                print(f"  [WARN] failed to fetch {sym}: {e}")
                continue
            if not from_cache and self.pacing_delay_sec > 0:
                time.sleep(self.pacing_delay_sec)
            if (i + 1) % 10 == 0:
                print(f"  ...fetched {i + 1}/{len(symbols)}")
        return data

    def get_category(self, symbol: str) -> str:
        """
        Rough sector/category label, used only to group names for a
        same-category relative strength comparison. Backends that cannot
        supply one return "UNKNOWN".
        """
        return "UNKNOWN"


def create_data_source(cfg: Config, override: str | None = None) -> DataSource:
    """Build the data source named by `override` or by cfg.data_source."""
    source = normalize_source_name(override or cfg.data_source)

    if source == "ib":
        from ibkr_data import IBKRDataSource
        return IBKRDataSource(cfg)

    from yfinance_data import YFinanceDataSource
    return YFinanceDataSource(cfg)
