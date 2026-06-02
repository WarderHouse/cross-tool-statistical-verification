# cross-tool-statistical-verification

[![CI](https://github.com/WarderHouse/cross-tool-statistical-verification/actions/workflows/ci.yml/badge.svg)](https://github.com/WarderHouse/cross-tool-statistical-verification/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20448660.svg)](https://doi.org/10.5281/zenodo.20448660)

Check a statistical analysis the way a careful reviewer would: confirm the
numbers are internally consistent, reproduce identically on a second run, and
**agree with an independent implementation in another tool**. `crossverify` runs
your analysis through a documented six-phase protocol and writes the evidence —
a verification log, a Python-vs-R comparison table, and a methodology statement
you can adapt for a manuscript.

It establishes that a result is **implementation-independent**, not that it is
correct. Agreement across Python and R is strong evidence that a number is not an
artifact of one library's defaults. It is *not* proof the analysis is right — you
write both sides, so a shared specification error agrees perfectly — and correct
analyses can legitimately disagree for defensible reasons (robust-SE variants,
`ddof`/denominator choices, contrast coding). See
[Scope](#scope-what-this-does-and-does-not-establish) for the limits.

Built for researchers who use AI assistance to write analysis code and need to
show editors, reviewers, and co-authors that their results hold up.

**Try it in your browser:** a [live demo](https://olivercrocco.shinyapps.io/ctsv-demo/)
runs the verification on the mtcars example and lets you watch the cross-tool check
catch a bug. Its source is in [demo/](demo/).

## What it checks

| Phase | What happens |
|---|---|
| 1. Data intake | Shape, dtypes, missing-value counts, descriptives, and category frequencies of the data **as loaded**, so you can confirm it matches your raw file. |
| 2. Transformations | If your analysis declares a `prepare()` step, a before/after snapshot plus range and integrity checks. |
| 3. Consistency + spot-checks | Every reported statistic is checked to be the kind of number it claims to be (R² in [0, 1], a p-value in [0, 1], a loading in [-1, 1], residuals summing to ~0, a coefficient of the expected sign), and selected values are **recomputed directly from the raw data**. |
| 4. Reproducibility | The analysis is re-run and every statistic must come back **essentially identical** (a tight tolerance, so deterministic code isn't failed by last-ULP BLAS drift). Tests determinism within one process, not cross-machine reproducibility. |
| 5. Cross-tool triangulation | Your results are compared, statistic by statistic, against an **independent R implementation**, within tolerance. Catches artifacts of one tool's defaults — and is meaningful only for deterministic estimators (a shared seed does not align Python's and R's RNG streams). |
| 6. Report | A compiled verification log, a comparison table, a machine-readable JSON, and a methodology-statement paragraph. |

For a step-by-step description of each phase, as a brief overview and in
technical detail, see **[docs/PROTOCOL.md](docs/PROTOCOL.md)**.

## Confidentiality

`crossverify` runs **entirely on your machine**. It makes **no network calls**,
contacts **no AI/LLM service**, and sends **no telemetry**. Your data and
results never leave your computer. Generated outputs and a `projects/` directory
for your real studies are git-ignored, so nothing sensitive is committed even
though this repository is public.

### Trust boundary

A project file is **executable code**, not just configuration: the harness
imports and runs the Python module and `Rscript`-executes the R script it names,
and pandas/R parse the dataset you point it at. **Run only project bundles and
datasets you trust** — running someone else's bundle is equivalent to running
their program. As a guardrail, the `data`, `python.module`, and `r.script` paths
must resolve **inside the project folder**; a path that escapes it (an absolute
path or `..`) is reported and the run aborts before any code executes. Set
`allow_external_paths: true` in the project file if you deliberately keep data or
scripts elsewhere. The user-supplied R script also receives only a minimal
environment (no inherited tokens or credentials).

## Install

This project uses [uv](https://docs.astral.sh/uv/). From a checkout:

```bash
uv sync                      # PyYAML, pandas, statsmodels + dev tools
```

`uv sync` creates a local virtual environment and installs from the committed
`uv.lock`, so installs are byte-reproducible. The canonical way to run the tool
is `uv run crossverify ...` (used throughout this README). Equivalent
alternatives: `crossverify ...` in an activated environment
(`source .venv/bin/activate`), or `python -m crossverify ...` to run from a
checkout without installing. If you do not use uv, `pip install -e .` installs
the runtime dependencies from `pyproject.toml` (the `dev` group, e.g. `pytest`,
is installed by `uv sync` but not by `pip install -e .`).

The cross-tool phase additionally needs **R** on your PATH with the `jsonlite`
package (`install.packages("jsonlite")`). Everything else runs without R; use
`--skip-r` to skip Phase 5.

## Quickstart

Run the worked example — an OLS regression (`mpg ~ wt + hp`) implemented in both
Python and R on the public-domain `mtcars` dataset:

```bash
uv run crossverify --project examples/project.yaml
```

```
crossverify 0.1.0 — OLS regression: mpg ~ wt + hp (mtcars)
  Phase 1 intake           3 info
  Phase 2 transforms       1 info
  Phase 3 consistency      8 pass
  Phase 4 reproducibility  11 pass
  Phase 5 triangulation    11 pass
  Cross-tool: 11/11 statistics matched within tolerance.

Result: PASS (30 passed, 0 failed, 4 informational)
```

The Python-vs-R comparison it writes:

| Statistic | Python | R | \|Δ\| | Match |
|---|---|---|---|---|
| coef_hp | -0.0317729 | -0.0317729 | 2.9e-15 | yes |
| coef_intercept | 37.2273 | 37.2273 | 1.7e-13 | yes |
| coef_wt | -3.87783 | -3.87783 | 2.6e-14 | yes |
| model_r2 | 0.826785 | 0.826785 | 5.6e-16 | yes |
| p_wt | 1.11965e-06 | 1.11965e-06 | 3.4e-20 | yes |
| ... | ... | ... | ... | ... |

## How it works

You supply the analysis; the harness orchestrates and checks it. There are three
pieces, all in [examples/](examples/):

**1. A Python adapter** exposing `run(df, seed=None)` that returns a flat dict of
the statistics you want verified:

```python
import statsmodels.api as sm

def run(df, seed=None):
    model = sm.OLS(df["mpg"], sm.add_constant(df[["wt", "hp"]])).fit()
    return {
        "model_r2": float(model.rsquared),
        "coef_wt": float(model.params["wt"]),
        "coef_hp": float(model.params["hp"]),
        "resid_sum": float(model.resid.sum()),
    }
```

The adapter may also expose `prepare(df, seed=None) -> DataFrame` (e.g. to
standardize features before clustering). When it does, `prepare()` is the single
source of truth for the analyzed data: it is called **once**, and the resulting
frame is what Phase 2 snapshots, what the Phase-3 consistency ranges are derived
from, **and** what `run()` receives — so the statistics and the checks they are
measured against always live in the same space. With no `prepare()`, `run()`
receives the raw data as loaded. (Spot-checks always recompute against the raw
source, as an independent cross-reference.)

**2. An R script** that computes the same statistics and emits them under the
same names:

```r
source(Sys.getenv("CROSSVERIFY_R"))
args <- cv_args()
d <- read.csv(args$data)
fit <- lm(mpg ~ wt + hp, data = d)
cv_emit(list(
  model_r2 = summary(fit)$r.squared,
  coef_wt  = coef(fit)["wt"],
  coef_hp  = coef(fit)["hp"],
  resid_sum = sum(residuals(fit))
), args$out)
```

**3. A project file** that ties them together and declares the checks:

```yaml
analysis_name: "OLS regression: mpg ~ wt + hp"
seed: null
data: data/mtcars.csv
python: {module: analysis.py}
r:      {script: analysis.R}
checks:
  model_r2:  {kind: r_squared}
  coef_wt:   {kind: coefficient, expected_sign: negative}
  resid_sum: {kind: residual_sum}
spot_checks:
  - {stat: mean_mpg, op: mean, column: mpg}
tolerance:
  default_atol: 1.0e-8
  default_rtol: 1.0e-6
```

Start your own with `uv run crossverify --init my_study/`.

### Consistency check kinds

`r_squared`, `p_value`, `proportion`, `variance_explained` (a proportion in
[0, 1], not a percentage or eigenvalue); `correlation` and standardized `loading`
(in [-1, 1]; pass `standardized: false` for covariance-based/unstandardized
loadings); `count` (optionally `equals: N`); `coefficient` (with `expected_sign` —
a mismatch is **informational** by default, since a flipped sign is often the
finding; set `severity: fail` to harden it); `residual_sum` (the
OLS-with-intercept "sums to ~0" property — declare a `column` so the tolerance
scales to the response and it doesn't false-fail on large-scale data);
`converged`; and `centroid` (within the observed range of a named `column`, in
the analyzed/prepared space). Group checks (`sum_to_n`, `sum_to_one`,
`sum_le_one`) cover cluster sizes and variance decompositions.

## Outputs

Written to `crossverify_out/<project>/` (git-ignored):

- `verification_log.md` — every phase and check, plus the intake summary
- `comparison_table.md` — the Python-vs-R table
- `methodology_statement.md` — a paragraph to adapt for your manuscript
- `verification_results.json` — the same results, machine-readable

## Exit codes and CI

`crossverify` exits `0` when nothing failed and `1` when any check failed, so it
drops into a Makefile or CI step:

```bash
uv run crossverify --project analysis/project.yaml || exit 1
```

## Notes and gotchas

- **Sign-flipped quantities.** PCA loadings and eigenvectors have an arbitrary
  sign that can differ between Python and R. Set `abs: true` on a statistic's
  tolerance to compare magnitudes only.
- **Stochastic analyses.** Set `seed:` in the project file; the harness passes it
  to both `run(df, seed=...)` and the R side. A seed makes a **same-tool re-run**
  (Phase 4) reproducible, but Python and R use **different RNGs**, so a shared
  seed does *not* produce the same random stream across tools. Phase 5 cross-tool
  comparison is meaningful only for **deterministic** estimators (or for
  expectations compared within a sampling-error tolerance), not seed-matched
  random draws. Compare a coefficient and its standard error rather than a
  p-value, which diverges near the boundary on small SE/df-convention differences.
- **Defensible cross-tool divergence.** A correct analysis can legitimately differ
  across tools past a tight tolerance — robust-SE variants, `ddof`/denominator
  choices, contrast coding, tie handling. So that the exit code does not pressure
  you into degrading correct code to turn the build green, declare
  `severity: info` in that statistic's per-key tolerance: a Phase-5 mismatch is
  then reported as **INFO** (surfaced for a human to interpret) rather than a
  **FAIL**. A statistic that is simply absent in one tool is always a hard
  failure regardless of severity — the replication is incomplete.

  ```yaml
  tolerance:
    per_key:
      coef_robust_se: {severity: info}   # known SE-convention difference: advise, don't fail
  ```
- **No R installed.** Use `--skip-r` to run phases 1-4 and 6. Phase 5 reports as
  skipped rather than failing.
- **Data format.** The harness reads your dataset as CSV (both the Python and R
  sides load it for intake and spot-checks). Convert SPSS, Stata, or Excel
  sources to CSV first, which is good practice for a reproducibility package
  anyway.
- **Parsing differences.** pandas `read_csv` and R's `read.csv` can infer types,
  decimal marks, and NA tokens differently, so a Phase 5 mismatch can originate in
  *parsing* rather than the analysis. The Phase 1 intake summary reflects the
  Python side; if a statistic mismatches unexpectedly, confirm both tools parsed
  the column the same way.

## Scope: what this does and does not establish

It checks that numbers are internally consistent, reproducible within a process,
and **tool-independent**. Three limits matter:

- **Agreement is not correctness (not sufficient).** You write both
  implementations, so a shared specification error (wrong model, wrong variable,
  a biased estimator chosen on both sides) produces perfect agreement that
  certifies the mistake. Python and R also often share the same LAPACK/BLAS
  kernel. The tool measures implementation-independence, not validity.
- **Disagreement is not always error (not necessary).** Correct analyses
  legitimately differ past a tight tolerance — HC/HAC robust SEs, `ddof`
  conventions, factor contrast coding, tie handling, optimizer defaults. Treat a
  Phase 5 mismatch as a prompt to understand *why*; do not "fix" correct code by
  forcing one tool to mimic the other's convention.
- **It does not judge the model.** Whether the specification is appropriate, or a
  coefficient is substantively meaningful, remains your call. The verification log
  ends with a short checklist of the judgments that stay with you.

## Development

Run the same checks CI does — lint, format, and the test suite:

```bash
uv run ruff check .         # lint   (add --fix to auto-fix what's safe)
uv run ruff format .        # format (add --check to verify without writing)
uv run pytest               # tests  (or a single file: uv run python tests/test_checks.py)
```

CI also runs the worked example end-to-end on every push and pull request
(Python-only across 3.10–3.13, plus one job with R for the cross-tool phase).
To mirror the lint/format checks as a git hook, install
[pre-commit](https://pre-commit.com/) and run `pre-commit install`
(config in `.pre-commit-config.yaml`).

## License

MIT. See [LICENSE](LICENSE).
