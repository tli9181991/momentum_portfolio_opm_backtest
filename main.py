"""
Run with:  python main.py

Settings live in config.toml -- including which data source to use:

    [data]
    data_source = "ib"        # or "yfinance"

The "ib" source requires TWS or IB Gateway running locally with API access
enabled (see README.md); "yfinance" needs neither, just `pip install yfinance`.
Override for one run with --source. First run is slow (fetching ~103 symbols
x 5 years of daily bars); later runs read from ./data_cache/<source>/ unless
you pass --refresh.
"""

import argparse
import sys

import matplotlib.pyplot as plt

from config import Config
from datasource import create_data_source
import backtest as bt
from qqq_universe import get_qqq_universe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                         help="Ignore local cache and re-fetch all data")
    parser.add_argument("--source", choices=["ib", "yfinance"],
                         help="Data source for this run, overriding "
                              "data_source in config.toml")
    parser.add_argument("--config", default=None,
                         help="Path to the TOML config file (default: config.toml)")
    args = parser.parse_args()

    cfg = Config.load(args.config)
    universe = get_qqq_universe()
    use_cache = not args.refresh

    source = create_data_source(cfg, override=args.source)
    print(f"Data source: {source.name}")

    with source:
        print(f"Fetching benchmark ({cfg.benchmark_ticker}) and comparison "
              f"({cfg.compare_ticker}) data ...")
        bench_df = source.fetch_daily_bars(cfg.benchmark_ticker, use_cache=use_cache)
        compare_df = source.fetch_daily_bars(cfg.compare_ticker, use_cache=use_cache)

        print(f"Fetching {len(universe)} QQQ constituent symbols "
              f"(this can take a while on first run) ...")
        raw_data = source.fetch_universe_bars(universe, use_cache=use_cache)
        print(f"  got data for {len(raw_data)}/{len(universe)} symbols")

    print("Running backtest ...")
    result = bt.run_backtest(raw_data, bench_df, compare_df, cfg)
    report = bt.performance_report(result["equity_curve"], cfg)

    print("\n=== Strategy performance ===")
    for k, v in report.items():
        print(f"  {k}: {v:.2f}" if isinstance(v, float) else f"  {k}: {v}")

    bench_total_return = (
        result["benchmark_curve"].iloc[-1] / result["benchmark_curve"].iloc[0] - 1
    ) * 100
    print(f"\n=== {cfg.compare_ticker} buy & hold ===")
    print(f"  total_return_pct: {bench_total_return:.2f}")

    n_trades = len(result["trade_log"])
    print(f"\nTotal trades executed: {n_trades}")
    print(f"Total turnover notional: ${result['turnover_notional']:,.0f}")

    result["equity_curve"]["value"].to_csv("equity_curve.csv")
    result["trade_log"].to_csv("trade_log.csv", index=False)
    print("\nSaved equity_curve.csv and trade_log.csv")

    plt.figure(figsize=(11, 6))
    plt.plot(result["equity_curve"].index, result["equity_curve"]["value"],
              label="Momentum strategy")
    plt.plot(result["benchmark_curve"].index, result["benchmark_curve"],
              label=f"{cfg.compare_ticker} buy & hold", linestyle="--")
    plt.legend()
    plt.title("Strategy vs. buy & hold")
    plt.ylabel("Portfolio value ($)")
    plt.tight_layout()
    plt.savefig("backtest_result.png", dpi=150)
    print("Saved backtest_result.png")


if __name__ == "__main__":
    sys.exit(main())
