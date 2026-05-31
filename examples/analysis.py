"""Worked example (Python side): OLS regression of mpg on weight and horsepower.

This is the contract every crossverify Python adapter follows: define
run(df, seed=None) and return a flat dict of {statistic_name: number}. The same
statistic names are emitted by analysis.R, and the harness compares them.
"""

import statsmodels.api as sm


def run(df, seed=None):
    X = sm.add_constant(df[["wt", "hp"]])
    model = sm.OLS(df["mpg"], X).fit()
    return {
        "n_obs": float(model.nobs),
        "model_r2": float(model.rsquared),
        "coef_intercept": float(model.params["const"]),
        "coef_wt": float(model.params["wt"]),
        "coef_hp": float(model.params["hp"]),
        "se_wt": float(model.bse["wt"]),
        "se_hp": float(model.bse["hp"]),
        "p_wt": float(model.pvalues["wt"]),
        "p_hp": float(model.pvalues["hp"]),
        "resid_sum": float(model.resid.sum()),
        "mean_mpg": float(df["mpg"].mean()),
    }
