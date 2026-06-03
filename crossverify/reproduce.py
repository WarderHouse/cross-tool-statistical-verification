"""Phase 4 — reproducibility.

Re-run the same Python analysis a second time (with the same seed, if any) and
confirm every statistic comes back essentially identical. This tests
*determinism within one process* — it is not a guarantee of reproducibility on a
different machine, OS, or BLAS/library build.

The default tolerance is extremely tight (rtol = 1e-12) rather than bit-exact, so
genuinely deterministic code still passes when a multithreaded BLAS reduces sums
in a slightly different order between two calls (last-ULP drift). Set
``reproducibility: {atol, rtol}`` in the project to tighten or loosen it, or pin
``OMP_NUM_THREADS=1`` if you require bit-for-bit equality.

Note on randomness: a shared seed makes a *same-tool* re-run reproducible, but it
does NOT align random streams across Python and R (the two use different RNGs),
so the Phase 5 cross-tool comparison is meaningful only for deterministic
estimators, not seed-matched random draws.
"""

from .checks import CheckResult, fmt, is_close

DEFAULT_ATOL = 0.0
DEFAULT_RTOL = 1e-12


def reproducibility(run1, run2, tol=None):
    tol = tol or {}
    atol = tol.get("atol", DEFAULT_ATOL)
    rtol = tol.get("rtol", DEFAULT_RTOL)
    out = []
    for k in sorted(set(run1) | set(run2)):
        a, b = run1.get(k), run2.get(k)
        if k not in run1 or k not in run2:
            out.append(
                CheckResult(
                    "4",
                    f"repro:{k}",
                    f"{k} present on both runs",
                    False,
                    f"run1={fmt(a)} run2={fmt(b)}",
                )
            )
            continue
        ok = is_close(a, b, atol=atol, rtol=rtol)
        out.append(
            CheckResult(
                "4", f"repro:{k}", f"Re-run identical: {k}", ok, f"run1 = {fmt(a)}, run2 = {fmt(b)}"
            )
        )
    return out
