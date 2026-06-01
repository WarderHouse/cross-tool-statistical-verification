# Worked example

A complete, runnable verification of an ordinary least squares regression
(`mpg ~ wt + hp`) on the public-domain `mtcars` dataset. The analysis is
implemented twice — once in Python ([analysis.py](analysis.py), via
`statsmodels`) and once in R ([analysis.R](analysis.R), via `lm`) — and the
harness confirms the two agree.

Run it from the repository root:

```bash
uv run crossverify --project examples/project.yaml
```

Outputs land in `crossverify_out/project/`:

- `verification_log.md` — every phase, every check, plus the data-intake summary
- `comparison_table.md` — the Python-vs-R table for each statistic
- `methodology_statement.md` — a paragraph you can adapt for a manuscript
- `verification_results.json` — the same results, machine-readable

## What each file shows you

- **[project.yaml](project.yaml)** declares the dataset, the two analysis scripts,
  the internal consistency checks (an R-squared must be in [0, 1], the `wt` and
  `hp` coefficients must be negative, residuals must sum to ~0), one spot-check
  (recompute mean `mpg` from the raw data), and the comparison tolerances.
- **[analysis.py](analysis.py)** is the contract: `run(df, seed=None)` returns a
  flat dict of named statistics.
- **[analysis.R](analysis.R)** emits the *same names* so they line up one-to-one.

## Make it fail on purpose

To see a real failure, edit `analysis.R` and change `lm(mpg ~ wt + hp, ...)` to
`lm(mpg ~ wt, ...)`. The intercept and coefficients will no longer match Python,
and Phase 5 will report the mismatched statistics in the comparison table.
