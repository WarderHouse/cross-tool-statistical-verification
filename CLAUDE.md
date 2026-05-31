# cross-tool-statistical-verification — project guide

`crossverify` is a command-line harness that checks whether a statistical analysis is
internally consistent, reproduces when re-run, and **agrees with an independent
implementation in a second language**: you write the analysis once in Python and once in
R, and the harness reconciles them.

## What this tool does and does NOT establish (read first)

It establishes that a result is **implementation-independent**, not that it is correct.
Keep every claim — README, `docs/PROTOCOL.md`, code comments, the generated methodology
statement — consistent with this. Specifically:

- **Agreement is not sufficient for correctness.** The analyst writes both sides, so a
  shared specification error (wrong model/variable, a biased estimator chosen twice) agrees
  perfectly. Python and R also often share the same LAPACK/BLAS kernel.
- **Disagreement is not always error.** Correct analyses legitimately differ past a tight
  tolerance for defensible reasons (robust-SE variants, `ddof`/denominator choices, factor
  contrast coding, tie handling, optimizer defaults).
- **Cross-tool comparison is meaningful only for deterministic estimators.** Python and R
  use different RNGs, so a shared seed does NOT align random streams.
- It does not judge whether the model is appropriate or an effect is meaningful.

Do not reintroduce "the numbers are real / this proves correctness" framing.

## Architecture (the six phases → modules in `crossverify/`)

| Phase | Module | Role |
|---|---|---|
| 1 Intake | `intake.py` | shape, dtypes, missingness, descriptives |
| 2 Transforms | `transforms.py` | optional `prepare()` snapshot + sanity checks |
| 3 Consistency | `consistency.py` | per-stat checks, group checks, spot-checks |
| 4 Reproducibility | `reproduce.py` | re-run, require ~identical (tight tolerance) |
| 5 Cross-tool | `triangulate.py` + `runner.py` | run R, compare within tolerance |
| 6 Report | `report.py` | verification log, comparison table, methodology statement |

Also `checks.py` (`is_close` + numeric helpers), `config.py` (project YAML), `cli.py`
(orchestration), `r/crossverify.R` (R helper: `cv_args()` / `cv_emit()`).

**The contract:** the user supplies a Python adapter exposing `run(df, seed=None) -> dict`
of named statistics (optionally `prepare(df, seed=None)`), an R script that emits the same
names via `cv_emit()`, and a `project.yaml` declaring the checks. See `examples/`.

## Running and testing

```bash
python -m pytest                                         # or: python tests/test_checks.py
python -m crossverify --project examples/project.yaml    # must report PASS
```

Every change must keep the unit tests green AND the mtcars example PASSing. Add a test in
`tests/test_checks.py` for each behavioral change. A teaching demo (R Shiny) lives in
`demo/` (see `demo/README.md`).

## Conventions & constraints

- **Runs entirely locally:** no network calls, no AI/LLM, no telemetry. Keep it that way.
- **Dependency-light:** core is `pandas` + `PyYAML`; `statsmodels` is only for the example.
  Keep ranges pinned in `requirements.txt`; don't add heavy or networked dependencies.
- **Trust boundary:** a project file is executable code (the harness imports the Python
  module and `Rscript`-runs the R script) and data is parsed locally. The README "Trust
  boundary" section and the `allow_external_paths` containment guard exist for this — keep
  them; the R child gets a minimal allowlisted environment.
- **Check-kind scope notes** (in `consistency.py`): `residual_sum ~ 0` is OLS-with-intercept
  only and scales its tolerance to the response; `loading` in [-1, 1] only when standardized;
  an unexpected coefficient sign is INFO by default (not FAIL); centroid ranges come from the
  analyzed (prepared) frame; NaN never counts as agreement.
- **Voice:** prose is plain and precise, never overstated; no marketing of correctness.

## Layout
`crossverify/` (package) · `examples/` (worked mtcars example) · `demo/` (R Shiny demo) ·
`docs/PROTOCOL.md` (two-tier explainer) · `r/crossverify.R` · `tests/`.
