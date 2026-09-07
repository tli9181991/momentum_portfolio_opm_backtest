# QQQ Trend/Momentum Monthly-Rebalance Backtest

Mechanized version of the Weinstein (Stage 2) / Minervini (Trend Template) /
O'Neil (relative strength, liquidity) stock-selection style, applied monthly
to the current QQQ (Nasdaq-100) constituent list, with a daily mechanical
exit rule layered on top of the monthly rebalance.

## Setup

### 1. Choose a data source

Price history can come from either backend, selected in `config.toml`:

```toml
[data]
data_source = "ib"        # or "yfinance"
```

| | `ib` | `yfinance` |
|---|---|---|
| Source | Interactive Brokers API | Yahoo Finance |
| Needs | TWS/IB Gateway running + market-data subscription | nothing, just the package |
| Speed | ~2 min for the universe (pacing-limited) | ~1 min |
| Quality | the data you'd actually trade on | best-effort, no SLA |

Use `yfinance` to develop and sanity-check the strategy; use `ib` for
anything you intend to act on. Override for a single run without editing
the file:

```
python main.py --source yfinance
```

### 2. Install dependencies

```
pip install -r requirements.txt
```

You only need the backend you actually use — `ib_async` for `ib`,
`yfinance` for `yfinance`; each is imported lazily. If `ib_async` isn't
available, `pip install ib_insync` works as a drop-in replacement (the code
auto-detects whichever is installed) — `ib_insync` was archived by its
author in 2023, so `ib_async` is the actively maintained option.

### 3. If using the `ib` source

1. Install and run **TWS** or **IB Gateway**, logged into your IBKR account
   (paper trading account recommended for a first run).
2. Enable API access: `File > Global Configuration > API > Settings` →
   check "Enable ActiveX and Socket Clients", note the socket port
   (default 7497 for TWS paper trading), and confirm `127.0.0.1` is trusted.
3. Check the `[ibkr]` table in `config.toml` — in particular `ibkr_port`
   (must match TWS/Gateway's configured API port) and `ibkr_client_id`
   (must not collide with another active API connection).

### 4. Run

```
python main.py
```

First run fetches ~100 symbols x 5 years of daily bars (a few minutes on
`ib`, which is pacing-limited) and caches them to
`./data_cache/<source>/`. Each backend caches separately, so switching
sources never mixes their bars. Later runs reuse the cache; pass
`--refresh` to force a re-download.

### 5. Or step through it in a notebook

```
pip install jupyterlab
jupyter lab visualize_backtest.ipynb
```

`visualize_backtest.ipynb` runs the same code as `main.py`, one cell at a
time, and plots what happens at each stage: which names survive the screen
and how they rank, what portfolio the ranking turns into, and the resulting
profit and loss. It reads the same cache, so it costs nothing extra to run
after `main.py`.

Its last part runs a **second, independent** strategy on the same data: the
mean-variance walk-forward from `M6_finalnotebook.ipynb` (max-Sharpe,
minimum-volatility and risk-parity books solved monthly from the covariance
matrix), and puts it head to head with the equal-weight momentum strategy
and with buy & hold. The optimisers live in `mvo.py`.

## Configuration

`config.toml` holds every runtime setting — data source, connection
details, backtest window, portfolio construction, and all the Trend
Template / relative-strength / liquidity thresholds. `config.py` holds the
same settings as dataclass defaults and the loader that overlays the TOML
file on top; edit `config.toml`, not the code.

Keys must be named exactly like `Config` fields, and an unrecognised key is
reported as an error rather than silently ignored. The `[tables]` exist for
readability only and are flattened before being applied, so a key can be
moved between them freely. Delete `config.toml` (or any single key in it)
to fall back to the defaults in `config.py`.

CLI flags:

- `--source {ib,yfinance}` — override `data_source` for this run
- `--refresh` — ignore the cache and re-download
- `--config PATH` — use a different TOML file (e.g. to keep several
  parameter sets side by side)

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
- **The two data sources will not agree exactly**: `yfinance` with
  `auto_adjust = true` is the closest analogue to `ADJUSTED_LAST`, but the
  two apply adjustments differently and Yahoo's volume figures in
  particular diverge from IBKR's (which cover exchange hours only). Expect
  small differences in the reported metrics when you switch backends;
  treat a backtest as valid only against the source it was run on.
- This is a research/backtesting tool. It does not place real orders.

## Files

- `config.toml` — all runtime settings, including the data source (edit this)
- `config.py` — the `Config` dataclass defaults + TOML loader
- `qqq_universe.py` — the static ticker list (re-pull periodically)
- `datasource.py` — the data-source contract, shared disk cache, and the
  factory that picks a backend from the config
- `ibkr_data.py` — IBKR backend (TWS / IB Gateway API)
- `yfinance_data.py` — Yahoo Finance backend
- `signals.py` — filter and scoring functions
- `backtest.py` — the daily-stepped simulation engine
- `main.py` — orchestration / CLI entry point
- `visualize_backtest.ipynb` — cell-by-cell walkthrough of a run: stock
  selection, portfolio construction, profit and loss, and the mean-variance
  comparison
- `mvo.py` — mean-variance optimisers (max Sharpe / min volatility / risk
  parity) and the monthly walk-forward test, ported faithfully from
  `M6_finalnotebook.ipynb`
- `M6_finalnotebook.ipynb` — reference notebook the optimisation flow comes from
- `test_synthetic.py` — runs the engine against synthetic random-walk data
  so you can sanity-check the logic runs correctly *before* touching any
  data source at all: `python test_synthetic.py`
