"""
Sanity-check the signals/backtest logic with synthetic random-walk data,
since this environment has no network access to IBKR. This does NOT
validate the strategy's real-world performance -- it only confirms the
code runs end-to-end without errors and produces sane, internally
consistent output (equity curve moves, trades get logged, no crashes on
edge cases like zero candidates qualifying).
"""

import numpy as np
import pandas as pd

from config import Config
import backtest as bt

np.random.seed(42)


def make_fake_ohlcv(n_days: int, start_price: float, drift: float, vol: float,
                     start_date: str = "2021-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start_date, periods=n_days)
    rets = np.random.normal(drift, vol, n_days)
    close = start_price * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(np.random.normal(0, 0.005, n_days)))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, n_days)))
    open_ = close * (1 + np.random.normal(0, 0.002, n_days))
    volume = np.random.randint(500_000, 5_000_000, n_days)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def main():
    cfg = Config()
    cfg.backtest_years = 1          # keep the test fast
    cfg.max_positions = 5
    n_days = 252 * 3                # 3 years of data -> 2y warmup + 1y measured

    # Benchmark: modest steady uptrend
    bench_df = make_fake_ohlcv(n_days, 400, 0.0003, 0.010)
    compare_df = bench_df.copy()  # reuse as the "QQQ" buy&hold comparison too

    # Universe: mix of strong uptrends, weak/flat, and a volatile decliner,
    # so filters and the exit rule both get exercised.
    raw_data = {}
    for i in range(15):
        drift = np.random.choice([0.0010, 0.0002, -0.0006])
        vol = np.random.choice([0.012, 0.018, 0.025])
        raw_data[f"FAKE{i}"] = make_fake_ohlcv(n_days, 100 + i * 10, drift, vol)

    print(f"Universe: {len(raw_data)} synthetic symbols, {n_days} trading days each")

    result = bt.run_backtest(raw_data, bench_df, compare_df, cfg)
    report = bt.performance_report(result["equity_curve"], cfg)

    print("\nEquity curve head/tail:")
    print(result["equity_curve"].head(3))
    print(result["equity_curve"].tail(3))

    print("\nPerformance report:")
    for k, v in report.items():
        print(f"  {k}: {v}")

    print(f"\nTrade log rows: {len(result['trade_log'])}")
    if len(result["trade_log"]) > 0:
        print(result["trade_log"].head(10))
        print("\nAction counts:")
        print(result["trade_log"]["action"].value_counts())

    n_positions = result["equity_curve"]["n_positions"]
    print(f"\nPositions held over time -- min {n_positions.min()}, "
          f"max {n_positions.max()}, mean {n_positions.mean():.2f}")

    # Basic sanity assertions
    assert result["equity_curve"]["value"].min() > 0, "portfolio value went to/below zero"
    assert n_positions.max() <= cfg.max_positions, "exceeded max_positions"
    assert len(result["trade_log"]) > 0, "expected at least some trades over 1 year"
    print("\nAll sanity checks passed.")


if __name__ == "__main__":
    main()
