"""
Historical data access via the Interactive Brokers API.

Requires TWS or IB Gateway running locally with API access enabled:
  TWS: File > Global Configuration > API > Settings >
       check "Enable ActiveX and Socket Clients", set the socket port,
       and add 127.0.0.1 to trusted IPs if needed.

Uses whichever of these two libraries is installed (same API surface):
  - ib_async   (actively maintained community fork, recommended)
  - ib_insync  (original library, archived by its author in 2023)

Selected via config.toml with `data_source = "ib"`. For a no-login
alternative that needs neither TWS nor a market-data subscription, see
yfinance_data.py.
"""

from __future__ import annotations

import os

import pandas as pd

from config import Config
from datasource import DataSource


class IBKRDataSource(DataSource):
    name = "ib"

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self.pacing_delay_sec = cfg.ibkr_pacing_delay_sec
        self.ib = None
        self._ibi = None

    # -- lifecycle -------------------------------------------------------

    @property
    def ibi(self):
        """Import the IB library lazily so yfinance-only users need not install it."""
        if self._ibi is None:
            try:
                import ib_async as ibi
            except ImportError:
                try:
                    import ib_insync as ibi
                except ImportError as e:
                    raise ImportError(
                        "The 'ib' data source needs ib_async (or ib_insync) installed: "
                        "pip install ib_async -- or switch to data_source = \"yfinance\" "
                        "in config.toml"
                    ) from e
            self._ibi = ibi
        return self._ibi

    def connect(self) -> None:
        cfg = self.cfg
        print(f"Connecting to IBKR at {cfg.ibkr_host}:{cfg.ibkr_port} ...")
        self.ib = self.ibi.IB()
        self.ib.connect(cfg.ibkr_host, cfg.ibkr_port, clientId=cfg.ibkr_client_id)

    def disconnect(self) -> None:
        if self.ib is not None and self.ib.isConnected():
            self.ib.disconnect()
        self.ib = None

    def _require_connection(self):
        if self.ib is None or not self.ib.isConnected():
            raise RuntimeError(
                "Not connected to IBKR -- call connect() before fetching bars."
            )
        return self.ib

    # -- cache -----------------------------------------------------------

    def legacy_cache_path(self, symbol: str) -> str | None:
        # Caches written before the multi-backend split lived flat in
        # cache_dir/ and were always IBKR bars, so they are still valid here.
        return os.path.join(self.cfg.cache_dir, f"{symbol}.csv")

    # -- fetching --------------------------------------------------------

    def _download_daily_bars(self, symbol: str) -> pd.DataFrame:
        ib = self._require_connection()
        cfg = self.cfg

        contract = self.ibi.Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(contract)

        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=cfg.fetch_duration_str,
            barSizeSetting=cfg.bar_size,
            whatToShow=cfg.what_to_show,
            useRTH=True,
            formatDate=1,
        )
        df = self.ibi.util.df(bars)
        if df is None or df.empty:
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date")

    def get_category(self, symbol: str) -> str:
        """
        Rough sector/category proxy using IBKR's own contract classification
        (not GICS). Used only to group QQQ names for a same-category relative
        strength comparison -- see signals.py.
        """
        ib = self._require_connection()
        details = ib.reqContractDetails(self.ibi.Stock(symbol, "SMART", "USD"))
        if not details:
            return "UNKNOWN"
        d = details[0]
        return getattr(d, "category", None) or getattr(d, "industry", None) or "UNKNOWN"
