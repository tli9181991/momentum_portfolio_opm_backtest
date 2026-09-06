"""
Historical data access via the Interactive Brokers API.

Requires TWS or IB Gateway running locally with API access enabled:
  TWS: File > Global Configuration > API > Settings >
       check "Enable ActiveX and Socket Clients", set the socket port,
       and add 127.0.0.1 to trusted IPs if needed.

Uses whichever of these two libraries is installed (same API surface):
  - ib_async   (actively maintained community fork, recommended)
  - ib_insync  (original library, archived by its author in 2023)
"""

from __future__ import annotations

import os
import time
import pandas as pd

try:
    import ib_async as ibi
except ImportError:
    import ib_insync as ibi

from config import Config


def connect(cfg: Config) -> "ibi.IB":
    ib = ibi.IB()
    ib.connect(cfg.ibkr_host, cfg.ibkr_port, clientId=cfg.ibkr_client_id)
    return ib


def _cache_path(cfg: Config, symbol: str) -> str:
    os.makedirs(cfg.cache_dir, exist_ok=True)
    return os.path.join(cfg.cache_dir, f"{symbol}.csv")


def fetch_daily_bars(ib: "ibi.IB", cfg: Config, symbol: str,
                      use_cache: bool = True) -> pd.DataFrame:
    """Fetch (or load cached) adjusted daily OHLCV bars for one symbol."""
    cache_file = _cache_path(cfg, symbol)
    if use_cache and os.path.exists(cache_file):
        df = pd.read_csv(cache_file, parse_dates=["date"])
        df = df.set_index("date")
        return df

    contract = ibi.Stock(symbol, "SMART", "USD")
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
    df = ibi.util.df(bars)
    if df is None or df.empty:
        raise RuntimeError(f"No historical data returned for {symbol}")

    df = df.rename(columns={"date": "date"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")[["open", "high", "low", "close", "volume"]]

    df.to_csv(cache_file)
    return df


def fetch_universe_bars(ib: "ibi.IB", cfg: Config, symbols: list[str],
                         use_cache: bool = True,
                         pacing_delay_sec: float = 1.2) -> dict[str, pd.DataFrame]:
    """
    Fetch daily bars for a list of symbols, respecting IBKR's historical
    data pacing limits (roughly: no more than ~6 requests per 2 seconds,
    and identical requests are further throttled). A conservative sleep
    between requests avoids pacing violations for a ~100-symbol universe.
    """
    data = {}
    for i, sym in enumerate(symbols):
        try:
            data[sym] = fetch_daily_bars(ib, cfg, sym, use_cache=use_cache)
        except Exception as e:
            print(f"  [WARN] failed to fetch {sym}: {e}")
            continue
        # Only sleep for symbols actually hitting the API, not cache hits
        cache_file = _cache_path(cfg, sym)
        just_fetched = os.path.exists(cache_file) and not use_cache
        if not use_cache:
            time.sleep(pacing_delay_sec)
        if (i + 1) % 10 == 0:
            print(f"  ...fetched {i + 1}/{len(symbols)}")
    return data


def get_contract_category(ib: "ibi.IB", symbol: str) -> str:
    """
    Rough sector/category proxy using IBKR's own contract classification
    (not GICS). Used only to group QQQ names for a same-category relative
    strength comparison -- see signals.py.
    """
    contract = ibi.Stock(symbol, "SMART", "USD")
    details = ib.reqContractDetails(contract)
    if not details:
        return "UNKNOWN"
    d = details[0]
    return getattr(d, "category", None) or getattr(d, "industry", None) or "UNKNOWN"
