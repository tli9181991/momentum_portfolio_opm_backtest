"""
Historical data access via Yahoo Finance (the `yfinance` package).

No TWS/IB Gateway, no login, and no market-data subscription -- the trade-off
is that Yahoo's data is best-effort: occasional bad ticks, no SLA, and it can
rate-limit or change its endpoints without notice. Good for developing and
sanity-checking the strategy; prefer the IBKR backend for anything you intend
to trade on.

Selected via config.toml with `data_source = "yfinance"`.
"""

from __future__ import annotations

import pandas as pd

from config import Config
from datasource import DataSource


class YFinanceDataSource(DataSource):
    name = "yfinance"

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self.pacing_delay_sec = cfg.yf_pacing_delay_sec
        self._yf = None

    @property
    def yf(self):
        """Import lazily so IBKR-only users need not install yfinance."""
        if self._yf is None:
            try:
                import yfinance
            except ImportError as e:
                raise ImportError(
                    "The 'yfinance' data source needs yfinance installed: "
                    "pip install yfinance"
                ) from e
            self._yf = yfinance
        return self._yf

    def connect(self) -> None:
        print(f"Using Yahoo Finance data (period={self.cfg.yf_period}, "
              f"auto_adjust={self.cfg.yf_auto_adjust}) ...")

    @staticmethod
    def to_yahoo_symbol(symbol: str) -> str:
        """
        IBKR writes share classes with a space or dot (BRK B / BRK.B);
        Yahoo uses a hyphen (BRK-B). Plain tickers pass through unchanged.
        """
        return symbol.strip().upper().replace(" ", "-").replace(".", "-")

    def _download_daily_bars(self, symbol: str) -> pd.DataFrame:
        cfg = self.cfg
        ticker = self.yf.Ticker(self.to_yahoo_symbol(symbol))
        df = ticker.history(
            period=cfg.yf_period,
            interval="1d",
            # auto_adjust=True gives split- AND dividend-adjusted OHLC, the
            # closest match to IBKR's ADJUSTED_LAST.
            auto_adjust=cfg.yf_auto_adjust,
        )
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns=str.lower)
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df.index.name = "date"
        return df

    def get_category(self, symbol: str) -> str:
        try:
            info = self.yf.Ticker(self.to_yahoo_symbol(symbol)).info
        except Exception:
            return "UNKNOWN"
        return info.get("sector") or info.get("industry") or "UNKNOWN"
