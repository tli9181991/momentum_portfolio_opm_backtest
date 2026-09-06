"""
QQQ (Nasdaq-100) constituent snapshot.

Pulled as of 2026-09-03. This is a POINT-IN-TIME snapshot of *today's*
holdings, applied across the whole backtest window -- this is the
survivorship-biased "current holdings only" mode you selected. Names that
were removed from the index during the backtest period (bankruptcy,
acquisition, demotion) are simply absent, which will flatter the backtest's
historical results versus reality.

To reduce staleness, re-pull this list before re-running the backtest --
e.g. from Invesco's official holdings file:
https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?ticker=QQQ
or any ETF data provider that publishes the daily holdings CSV.

Excludes non-equity line items (index futures overlay, cash & equivalents,
cash collateral) that appear in the fund's actual holdings but aren't
tradable single-name equities for this strategy.
"""

QQQ_TICKERS = [
    "NVDA", "AAPL", "MSFT", "MU", "AMZN", "AMD", "GOOGL", "TSLA", "GOOG",
    "META", "AVGO", "WMT", "INTC", "CSCO", "PLTR", "COST", "LRCX", "NFLX",
    "AMAT", "PANW", "AMGN", "TXN", "SNDK", "KLAC", "LIN", "CRWD", "TMUS",
    "PEP", "GILD", "MRVL", "STX", "QCOM", "SHOP", "ADI", "WDC", "BKNG",
    "ASML", "VRTX", "ISRG", "SBUX", "ADBE", "FTNT", "ADP", "CEG", "ARM",
    "MELI", "APP", "CMCSA", "INTU", "DASH", "CSX", "MAR", "REGN", "MNST",
    "CDNS", "CTAS", "SNPS", "MDLZ", "ABNB", "ROST", "ORLY", "WBD", "DDOG",
    "AEP", "HON", "LITE", "PCAR", "BKR", "MPWR", "FANG", "NXPI", "FAST",
    "PDD", "TER", "PYPL", "ADSK", "CCEP", "ALAB", "MSTR", "XEL", "NBIS",
    "EXC", "PAYX", "KDP", "AXON", "TRI", "ROP", "FER", "IDXX", "WDAY",
    "MCHP", "TTWO", "ODFL", "CRWV", "RKLB", "ALNY", "DXCM", "GEHC", "CPRT",
    "KHC",
]

# A couple of very recently listed / spun-off names (e.g. SPCX, HONA) were
# deliberately dropped from this list: they won't have 5 years of price
# history, which would just produce NaNs through the whole warmup window.
# Add them back once they have enough history for your lookback windows.

def get_qqq_universe() -> list[str]:
    return list(QQQ_TICKERS)
