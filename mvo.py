"""
Mean-variance portfolio optimisation, walk-forward.

A second, independent way to turn a list of names into a book: instead of
giving every name an equal slot (what `backtest.py` does), solve for weights
each month from the covariance matrix of past returns.

The optimisers and the testing flow are ported from the `M6_finalnotebook.ipynb`
"Protfolio Omptization" section and are kept faithful to it, so results here are
comparable with that notebook rather than being a re-derivation:

  - monthly returns, month-end sampled, from adjusted closes
  - at each analysis month, fit on an EXPANDING window of all history up to
    that month: sample covariance, and `annualize_rets` as expected returns
  - solve three long-only, fully-invested books under a box bound
  - apply those weights to the FOLLOWING month's realised return

One quirk is carried over deliberately: expected returns are annualised while
the covariance stays monthly, so the Sharpe ratio inside `msr` mixes units.
That is what the source notebook does, and changing it would silently move the
tangency portfolio. `annualise_cov=True` on `walk_forward` puts both on an
annual footing if you want to see the difference -- it is off by default.

Needs scipy (see requirements.txt).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

# The three books solved at every rebalance, in the order they are reported.
SCHEMES = ("MaxSharpe", "MinVol", "RiskParityMaxRet")


# ---------------------------------------------------------------------------
# Portfolio maths
# ---------------------------------------------------------------------------

def annualize_rets(ret: pd.DataFrame | pd.Series, periods_per_year: int = 12):
    """Annualised (geometric) return of each column."""
    compounded_growth = (1 + ret).prod()
    n_periods = ret.shape[0]
    return compounded_growth ** (periods_per_year / n_periods) - 1


def portfolio_return(weights, returns):
    """Portfolio return for a set of weights."""
    return weights.T @ returns


def portfolio_vol(weights, covmat):
    """Portfolio volatility for a set of weights."""
    return (weights.T @ covmat @ weights) ** 0.5


def risk_contribution(weights, cov_matrix):
    """Each asset's contribution to total portfolio risk."""
    total_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
    marginal_contrib = np.dot(cov_matrix, weights)
    return np.multiply(marginal_contrib, weights) / total_vol


def risk_parity_objective(weights, cov_matrix):
    """Dispersion of risk contributions -- zero when every asset risks the same."""
    contribs = risk_contribution(weights, cov_matrix)
    return np.sum(np.square(contribs - np.mean(contribs)))


# ---------------------------------------------------------------------------
# Optimisers. All are long-only and fully invested (weights sum to 1), with a
# box bound applied to every asset.
# ---------------------------------------------------------------------------

def _sum_to_one():
    return {"type": "eq", "fun": lambda w: np.sum(w) - 1}


def msr(riskfree_rate, ret, covmat, bound=(0.008, 0.1)):
    """Maximum-Sharpe (tangency) portfolio."""
    n = ret.shape[0]
    init_guess = np.repeat(1 / n, n)

    def neg_sharpe(weights, riskfree_rate, er, cov):
        r = portfolio_return(weights, er)
        vol = portfolio_vol(weights, cov)
        return -(r - riskfree_rate) / vol

    weights = minimize(neg_sharpe, init_guess, args=(riskfree_rate, ret, covmat),
                       method="SLSQP", options={"disp": False},
                       constraints=(_sum_to_one(),), bounds=(bound,) * n)
    return weights.x


def min_volatility(risk_free_rate, returns, cov_matrix, bound):
    """Global minimum-variance portfolio (the expected returns are unused)."""
    n = returns.shape[0]
    weights = minimize(portfolio_vol, np.ones(n) / n,
                       args=(cov_matrix,), method="SLSQP",
                       options={"disp": False},
                       constraints=(_sum_to_one(),), bounds=(bound,) * n)
    return weights.x


def min_risk_parity(risk_free_rate, returns, cov_matrix, bound):
    """Equal-risk-contribution portfolio."""
    n = returns.shape[0]
    result = minimize(risk_parity_objective, np.ones(n) / n,
                      args=(cov_matrix,), method="SLSQP",
                      bounds=(bound,) * n, constraints=(_sum_to_one(),),
                      options={"ftol": 1e-12, "maxiter": 1000})
    return result.x


def minimize_vol(target_return, ret, cov, bound=(0.008, 0.1)):
    """Lowest-volatility portfolio achieving a target return -- one frontier point."""
    n = ret.shape[0]
    return_is_target = {"type": "eq", "args": (ret,),
                        "fun": lambda w, ret: target_return - portfolio_return(w, ret)}
    weights = minimize(portfolio_vol, np.repeat(1 / n, n), args=(cov,),
                       method="SLSQP", options={"disp": False},
                       constraints=(_sum_to_one(), return_is_target),
                       bounds=(bound,) * n)
    return weights.x


def maximize_return(target_vol, ret, cov, bound=(0.008, 0.1)):
    """Highest-return portfolio at a given volatility.

    Used to lift the risk-parity book onto the frontier: solve for equal risk
    contributions, take that portfolio's volatility as the target, then buy the
    most return available at the same risk.
    """
    n = ret.shape[0]
    volatility_is_target = {"type": "eq", "args": (ret,),
                            "fun": lambda w, ret: target_vol - portfolio_vol(w, cov)}

    def neg_portfolio_return(weights, ret):
        return -1.0 * portfolio_return(weights, ret)

    weights = minimize(neg_portfolio_return, np.repeat(1 / n, n), args=(ret,),
                       method="SLSQP", options={"disp": False},
                       constraints=(_sum_to_one(), volatility_is_target),
                       bounds=(bound,) * n)
    return weights.x


def solve_books(expected_returns, cov_matrix, risk_free_rate, bound) -> dict:
    """The three weight vectors solved at one rebalance, keyed by scheme name."""
    w_msr = msr(risk_free_rate, expected_returns, cov_matrix, bound)
    w_vol = min_volatility(risk_free_rate, expected_returns, cov_matrix, bound)

    w_risky = min_risk_parity(risk_free_rate, expected_returns, cov_matrix, bound)
    vol_risky_parity = portfolio_vol(w_risky, cov_matrix)
    w_risky_max_ret = maximize_return(vol_risky_parity, expected_returns,
                                      cov_matrix, bound)

    return {"MaxSharpe": w_msr, "MinVol": w_vol, "RiskParityMaxRet": w_risky_max_ret}


# ---------------------------------------------------------------------------
# Data prep and the walk-forward test
# ---------------------------------------------------------------------------

def monthly_returns_from_bars(raw_data: dict[str, pd.DataFrame], symbols,
                              price_col: str = "close") -> pd.DataFrame:
    """Month-end sampled returns for `symbols`, from this repo's daily bars.

    The cached closes are already split- and dividend-adjusted by both backends,
    so they play the role of the source notebook's `Adj Close`.
    """
    prices = {}
    for sym in symbols:
        if sym not in raw_data:
            continue
        prices[sym] = raw_data[sym][price_col].resample("ME").last()
    if not prices:
        raise ValueError("none of the requested symbols are in raw_data")
    monthly_price = pd.DataFrame(prices).sort_index()
    return monthly_price.pct_change().dropna()


def walk_forward(monthly_returns: pd.DataFrame, analysis_months,
                 risk_free_rate: float = 0.04, bound=(0, 1),
                 annualise_cov: bool = False) -> dict:
    """Run the monthly fit-then-hold loop over `analysis_months`.

    At each month the fit uses every return up to and including that month; the
    weights it produces are then held through the *next* month and scored on
    that month's realised return, so nothing is scored on data it was fitted on.

    Returns {"returns": DataFrame indexed by the scored month, one column per
    scheme; "weights": {scheme: DataFrame of the weights held that month}}.
    """
    analysis_months = pd.DatetimeIndex(analysis_months)
    scored_months: list[pd.Timestamp] = []
    rets: dict[str, list[float]] = {s: [] for s in SCHEMES}
    weights: dict[str, list[np.ndarray]] = {s: [] for s in SCHEMES}

    for i_date, date in enumerate(analysis_months):
        if i_date + 1 == len(analysis_months):
            break
        next_date = analysis_months[i_date + 1]
        if next_date not in monthly_returns.index:
            continue

        historical_returns = monthly_returns.loc[:date]
        if len(historical_returns) < 2:
            continue

        cov_matrix = historical_returns.cov()
        if annualise_cov:
            cov_matrix = cov_matrix * 12
        expected_returns = annualize_rets(historical_returns)

        books = solve_books(expected_returns, cov_matrix, risk_free_rate, bound)
        realised = monthly_returns.loc[next_date]
        for scheme, w in books.items():
            rets[scheme].append(portfolio_return(w, realised))
            weights[scheme].append(w)
        scored_months.append(next_date)

    index = pd.DatetimeIndex(scored_months, name="date")
    return {
        "returns": pd.DataFrame({s: rets[s] for s in SCHEMES}, index=index),
        "weights": {s: pd.DataFrame(weights[s], index=index,
                                    columns=monthly_returns.columns)
                    for s in SCHEMES},
    }


def efficient_frontier(expected_returns, cov_matrix, bound=(0, 1),
                       n_points: int = 60) -> pd.DataFrame:
    """Volatility and return along the frontier, for plotting."""
    targets = np.linspace(expected_returns.min(), expected_returns.max() * 1.5,
                          n_points)
    rows = []
    for target in targets:
        w = minimize_vol(target, expected_returns, cov_matrix, bound)
        rows.append({"vol": portfolio_vol(w, cov_matrix),
                     "ret": portfolio_return(w, expected_returns)})
    return pd.DataFrame(rows)
