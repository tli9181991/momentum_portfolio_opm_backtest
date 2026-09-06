"""
Mechanized versions of the Weinstein / Minervini / O'Neil-style selection
criteria discussed. Each is a deliberate simplification of a rule that, in
the original methodology, often also relies on visual chart judgment --
see the "Limitations" section of README.md for what this does and doesn't
capture faithfully.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import Config


def add_indicators(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Add all moving averages / rolling stats needed by the filters."""
    out = df.copy()
    out["sma_short"] = out["close"].rolling(cfg.sma_short).mean()
    out["sma_mid"] = out["close"].rolling(cfg.sma_mid).mean()
    out["sma_long"] = out["close"].rolling(cfg.sma_long).mean()

    out["roll_52w_high"] = out["close"].rolling(252, min_periods=100).max()
    out["roll_52w_low"] = out["close"].rolling(252, min_periods=100).min()
    out["pct_below_52w_high"] = (
        (out["roll_52w_high"] - out["close"]) / out["roll_52w_high"] * 100
    )
    out["pct_above_52w_low"] = (
        (out["close"] - out["roll_52w_low"]) / out["roll_52w_low"] * 100
    )

    out["avg_volume"] = out["volume"].rolling(cfg.avg_volume_lookback_days).mean()

    base_high = out["close"].rolling(cfg.base_lookback_weeks * 5).max()
    base_low = out["close"].rolling(cfg.base_lookback_weeks * 5).min()
    out["base_range_pct"] = (base_high - base_low) / base_low * 100

    return out


def trend_template_pass(row: pd.Series, prev_sma_long: float, cfg: Config) -> bool:
    """Minervini/Weinstein Stage-2 uptrend confirmation, evaluated at one row."""
    if pd.isna(row[["sma_short", "sma_mid", "sma_long"]]).any():
        return False
    conditions = [
        row["close"] > row["sma_mid"] > row["sma_long"],
        row["sma_short"] > row["sma_mid"],
        not pd.isna(prev_sma_long) and row["sma_long"] > prev_sma_long,
        row["pct_above_52w_low"] >= cfg.pct_above_52w_low_min,
        row["pct_below_52w_high"] <= cfg.pct_below_52w_high_max,
    ]
    return all(conditions)


def base_is_tight(row: pd.Series, cfg: Config) -> bool:
    if pd.isna(row["base_range_pct"]):
        return False
    return row["base_range_pct"] <= cfg.base_max_range_pct


def liquidity_ok(row: pd.Series, cfg: Config) -> bool:
    if pd.isna(row["avg_volume"]):
        return False
    return row["close"] >= cfg.min_price and row["avg_volume"] >= cfg.min_avg_volume


def relative_strength_score(close_series: pd.Series, bench_close: pd.Series,
                             asof_idx: int, cfg: Config) -> float:
    """
    O'Neil-style weighted multi-period return relative to a broad-market
    benchmark (SPY by default -- NOT QQQ; see the discussion on why
    RS-within-QQQ dilutes the signal).
    """
    score = 0.0
    total_weight = 0.0
    for days, weight in zip(cfg.rs_lookback_days, cfg.rs_weights):
        start = asof_idx - days
        if start < 0:
            continue
        stock_ret = close_series.iloc[asof_idx] / close_series.iloc[start] - 1
        bench_ret = bench_close.iloc[asof_idx] / bench_close.iloc[start] - 1
        score += weight * (stock_ret - bench_ret)
        total_weight += weight
    if total_weight == 0:
        return np.nan
    return score / total_weight


def exit_triggered(row: pd.Series, cfg: Config) -> bool:
    if not cfg.exit_on_close_below_sma_long:
        return False
    if pd.isna(row["sma_long"]):
        return False
    return row["close"] < row["sma_long"]
