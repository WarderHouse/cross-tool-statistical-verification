# The verification protocol

`crossverify` runs one analysis through six phases. This document describes each
phase twice: once as a brief overview for a statistically literate reader, and
once in technical detail for someone wiring up their own analysis.

---

## In brief

Computational results can fail to replicate for reasons that have nothing to do
with the data: a transformation applied in the wrong order, a statistic read off
the wrong object, an estimator whose default differs between packages, or an
unset seed. `crossverify` runs an analysis through six checks aimed at those
failure modes, with an independent reimplementation in a second language as the
backstop. You provide the analysis twice, in Python and in R, each emitting the
same named statistics, and the harness reconciles them.

**1. Intake.** The dataset is summarized as loaded: dimensions, dtypes,
missingness, descriptives, and category frequencies. This is a provenance check
against the source file, so a silent wrong-file or bad-parse error surfaces
before it propagates.

**2. Transformations.** If the analysis declares a preparation step, the harness
snapshots the data before and after and tests the invariants you assert about it:
bounds on a rescaled variable, no unintended row duplication from a merge, an
expected N. A large share of wrong numbers downstream originate here.

**3. Consistency and spot-checks.** Each reported statistic is range- and
sign-checked against what its type permits: an R-squared or proportion in [0, 1],
a p-value in [0, 1], a standardized loading or correlation in [-1, 1], an
OLS-with-intercept residual sum near zero, a coefficient of a hypothesized sign
(a mismatch is flagged for review, not failed — it is often the finding),
convergence flags, centroids inside the analyzed variable's support. Group
invariants are checked too, such as cluster sizes summing to N or a variance
decomposition summing to one. Then at least one statistic is recomputed directly
from the raw data along an independent path, so the estimate cannot silently
disagree with its own inputs.

**4. Reproducibility.** The Python analysis is re-executed and required to return
essentially identical results (a very tight tolerance, not bit-exact, so a
multithreaded BLAS reducing sums in a different order does not fail correct
deterministic code). A value that drifts beyond that signals uncontrolled state
or unseeded randomness. This tests determinism *within one process*; it is not a
guarantee of reproducibility on another machine or BLAS build. A fixed seed makes
a same-tool re-run reproducible, but that does not carry across tools (see
Phase 5).

**5. Cross-tool triangulation.** The core check. The analysis is re-estimated in
R, written independently, and the two result sets are compared statistic by
statistic within tolerance. Agreement is strong evidence that a result is
**implementation-independent** — not an artifact of one library's conventions
(estimator defaults, denominator choices, tie or missing handling). It is not
proof of correctness: you write both sides, so a shared specification error
agrees perfectly. Nor is disagreement always error — defensible convention
differences (robust SEs, `ddof`, contrast coding) can exceed a tight tolerance on
correct code, so a mismatch is a prompt to understand *why*, not a signal to
force one tool to mimic the other. Crucially, the comparison is meaningful only
for **deterministic** estimators: Python and R use different RNGs, so a shared
seed does not align random streams, and genuinely stochastic procedures will not
match across tools even when both are correct. Tolerances are configurable per
statistic, including magnitude-only comparison for sign-indeterminate quantities
such as PCA loadings. Mismatches, and statistics present in one tool but not the
other, are reported explicitly.

**6. Reporting.** Everything is compiled into a verification log, the cross-tool
comparison table, a machine-readable results file, and a methodology paragraph
pre-filled with versions, seed, tolerance, and match counts for adaptation into a
manuscript. The run returns a nonzero exit code on any failure, so it composes
with CI.

**Scope.** The harness establishes that results are internally consistent,
reproducible within a process, and implementation-independent. It does *not*
establish correctness: agreement is not sufficient (a shared specification error,
or a shared BLAS kernel, agrees perfectly) and not strictly necessary (correct
analyses can differ for defensible reasons). It also does not adjudicate
specification — whether the model is appropriate, the identifying assumptions
hold, or an effect is substantively meaningful. Those judgments stay with the
analyst, and the log says so explicitly.

---

## In detail

### The setup

Before any phase runs, the command-line tool reads your `project.yaml`, validates
it (the data file exists, a Python analysis is declared, the R script resolves),
loads the dataset as a CSV, and imports your Python analysis module. You supply
three things: a Python adapter exposing `run(df, seed=None)` that returns a flat
dictionary of named statistics, an R script that computes the same-named
statistics independently, and the project file that declares which checks to
apply. The harness then runs the phases you select (all six by default) and
writes its outputs to `crossverify_out/<project>/`.

### Phase 1: Data intake and inspection

The harness reports the dataset exactly as it loaded it: the row-and-column
count, every column's data type, the count of missing values per column, the
first ten rows, descriptive statistics for the numeric columns, and frequency
counts for the categorical ones. Nothing here passes or fails; it is all
informational. The point is to let you confirm that the file the harness sees is
your raw file, before a single number is computed. This phase also
records the minimum and maximum of each numeric column, which a later phase uses
to sanity-check cluster centroids.

### Phase 2: Transformation sanity checks

This phase is opt-in and only does something if your Python adapter defines a
`prepare(df)` step. When it does, the harness runs that cleaning step, records a
before-and-after shape snapshot, and applies any transformation checks you
declared: that a standardized column actually falls inside its expected range,
that no rows were silently duplicated (the classic symptom of a bad merge key),
or that the row count is what you expected. If there is no `prepare()` step, the
phase records that the analysis consumes the raw data as loaded. The purpose is
to catch data-wrangling errors that would otherwise quietly corrupt everything
downstream.

### Phase 3: Analysis, internal consistency, and spot-checks

The harness runs your Python analysis and collects the statistics it returns. It
then applies two kinds of automatic checks. The first is internal consistency:
each statistic is checked to be the kind of number it claims to be. An R-squared
or a variance-explained (a proportion, not a percentage or eigenvalue) must lie
in [0, 1], a p-value in [0, 1], a standardized factor loading or correlation in
[-1, 1] (unstandardized loadings legitimately exceed 1, so declare
`standardized: false` for them), a count must be a non-negative integer, and an
iterative procedure must report convergence. A residual sum near zero is a
property of OLS *with an intercept* only — not of GLM/logistic, no-intercept,
WLS/GLS, or penalized fits — and its tolerance scales to the response magnitude
when you declare a `column`, so a correct large-scale fit is not failed by
floating-point accumulation. A coefficient with the wrong sign is reported as
*informational* by default rather than failed, because a flipped sign is often
the substantive finding (set `severity: fail` to harden it). A cluster centroid
is checked against the observed range of its variable in the *analyzed* space.
When the adapter declares a `prepare()` step, that step is run once and its
output is the analyzed frame: it is what `run()` receives and what these ranges
are derived from, so a statistic and the range it is checked against cannot end
up in different spaces. Group
checks cover cases that span several statistics, such as cluster sizes summing to
N or a variance decomposition summing to one. The second kind is the spot-check:
the harness recomputes a reported value directly from the raw data (a mean, sum,
median, standard deviation with a configurable `ddof`, and so on, optionally
filtered to a subgroup) and confirms the analysis's reported value matches. This
is the step that catches an impossible number or an analysis that has quietly
drifted away from its own source data.

### Phase 4: Reproducibility

The harness runs your Python analysis a second time and requires every statistic
to come back essentially identical. The default tolerance is extremely tight
(rtol = 1e-12) rather than bit-exact, so genuinely deterministic code is not
failed when a multithreaded BLAS reduces sums in a slightly different order
between two calls; set `reproducibility: {atol, rtol}` to change it, or pin
`OMP_NUM_THREADS=1` for bit-for-bit equality. If you set a seed, both runs use
it, so a stochastic procedure reproduces once the seed is fixed. Any statistic
that drifts beyond tolerance, or appears on one run but not the other, is flagged
(a NaN is treated as a failure, not as two runs "agreeing"). This tests
determinism *within one process* — not reproducibility on a different machine,
OS, or library build, which is what the word can connote — and a seed that fixes
this same-tool re-run does *not* align random streams across Python and R.

### Phase 5: Cross-tool triangulation

This is the centerpiece. The harness runs your independent R implementation as a
separate process, handing it the data path, an output path, and the seed, and
pointing it at the bundled R helper so it can emit its results as JSON. It then
compares the Python and R results one statistic at a time, within tolerance. The
default tolerance is tight, but you can loosen it per statistic, and you can tell
it to compare magnitudes only for quantities whose sign is implementation-defined,
such as PCA loadings that legitimately flip sign between the two tools. Any
statistic present in one tool but missing in the other is flagged. The result is
a comparison table showing the Python value, the R value, the absolute
difference, and whether they matched. If R is unavailable, or you pass
`--skip-r`, or no R script is declared, the phase is skipped and reported as such
rather than counted as a failure.

The purpose is to establish that a result is *implementation-independent*, not
that it is correct. Two correctly-disagreeing tools (robust-SE variants, `ddof`
or denominator conventions, factor contrast coding, optimizer defaults) can
exceed the tolerance on a correct analysis, so read a mismatch as a question, not
a verdict, and resist "fixing" sound code to satisfy a verifier. When you have
identified such a divergence as expected, declare `severity: info` in that
statistic's per-key tolerance: the harness then reports the disagreement as
informational instead of failing the build, so the exit code stops rewarding the
degradation of correct code (a statistic missing from one tool stays a hard
failure regardless, since that means the replication is incomplete). The comparison
is also only meaningful for deterministic estimators: because Python and R use
different random number generators, a shared seed does not produce the same
random stream, so stochastic procedures (bootstrap, k-means initialization,
permutation tests) will not match across tools even when both are right — compare
their expectations within a sampling-error tolerance instead. Prefer triangulating
a coefficient and its standard error over a p-value, which compresses the test
statistic through a nonlinear tail and diverges near the boundary.

### Phase 6: Compiled log and methodology statement

The harness assembles everything into durable, reviewer-facing evidence. It
writes a verification log that lists every phase and every check with a PASS,
FAIL, or INFO status, embeds the Phase 1 intake summary and the Phase 5
comparison table, and ends with a short checklist of the judgments that remain
yours. It writes the comparison table as its own file, a machine-readable JSON of
all results, and a methodology-statement paragraph pre-filled with your tool
versions, seed, tolerance, and how many statistics matched across tools, marked
clearly as a template to adapt for a manuscript. Finally it prints a console
summary and sets its exit code: zero if nothing failed, one if any check failed,
so the whole run drops cleanly into a Makefile or CI step.

### The boundary

Across all six phases the tool checks that numbers are consistent, reproducible,
and tool-independent. It does not establish that they are *correct*: agreement
across two implementations you both wrote cannot catch a shared specification
error, and correct analyses can disagree for defensible reasons. And it does not
judge whether you chose the right model or whether a coefficient is substantively
meaningful. Those lines are deliberate, and the verification log restates them at
the end so the human judgment stays with the human.
