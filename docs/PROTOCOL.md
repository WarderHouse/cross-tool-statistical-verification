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
a p-value in [0, 1], a loading or correlation in [-1, 1], residuals summing to
zero, a coefficient of the hypothesized sign, convergence flags, centroids inside
the variable's support. Group invariants are checked too, such as cluster sizes
summing to N or a variance decomposition summing to one. Then at least one
statistic is recomputed directly from the raw data along an independent path, so
the estimate cannot silently disagree with its own inputs.

**4. Reproducibility.** The Python analysis is re-executed and required to return
identical results, under a fixed seed if it is stochastic. A value that drifts
between runs signals uncontrolled state or unseeded randomness, which would defeat
replication regardless of anything else.

**5. Cross-tool triangulation.** The core check. The analysis is re-estimated in
R, written independently, and the two result sets are compared statistic by
statistic within tolerance. Agreement across two implementations is strong
evidence that a result reflects the data rather than one library's conventions
(estimator defaults, denominator choices, handling of ties or missing values).
Tolerances are configurable per statistic, including magnitude-only comparison
for sign-indeterminate quantities such as PCA loadings. Mismatches, and
statistics present in one tool but not the other, are reported explicitly.

**6. Reporting.** Everything is compiled into a verification log, the cross-tool
comparison table, a machine-readable results file, and a methodology paragraph
pre-filled with versions, seed, tolerance, and match counts for adaptation into a
manuscript. The run returns a nonzero exit code on any failure, so it composes
with CI.

**Scope.** The harness establishes that results are internally consistent,
reproducible, and implementation-independent. It does not adjudicate
specification: whether the model is appropriate, the identifying assumptions
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
the file you downloaded, before a single number is computed. This phase also
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
or a variance-explained must lie in [0, 1], a p-value in [0, 1], a factor loading
or correlation in [-1, 1], a count must be a non-negative integer, a residual sum
must be approximately zero, a coefficient must carry the sign you expected, an
iterative procedure must report convergence, and a cluster centroid must fall
within the observed range of its variable. Group checks cover cases that span
several statistics, such as cluster sizes summing to N or a variance
decomposition summing to one. The second kind is the spot-check: the harness
recomputes a reported value directly from the raw data (a mean, sum, median, and
so on, optionally filtered to a subgroup) and confirms the analysis's reported
value matches. This is the step that catches an impossible number or an analysis
that has quietly drifted away from its own source data.

### Phase 4: Reproducibility

The harness runs your Python analysis a second time and requires every statistic
to come back exactly identical, not merely close. If you set a seed, both runs
use it, so a stochastic procedure must reproduce once the seed is fixed. Any
statistic that differs between the two runs, or that appears on one run but not
the other, is flagged. This confirms the analysis is deterministic and free of
hidden randomness or order-dependence, which is a precondition for anyone else
being able to reproduce it.

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
rather than counted as a failure. The purpose is to prove a result is a property
of the data and not an artifact of one tool's defaults.

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
and tool-independent. It does not judge whether you chose the right model or
whether a coefficient is substantively meaningful. That line is deliberate, and
the verification log restates it at the end so the human judgment stays with the
human.
