"""Phase 4 — reproducibility.

Re-run the same Python analysis a second time (with the same seed, if any) and
confirm every statistic comes back identical. Deterministic procedures must
match exactly; stochastic procedures must match exactly once the seed is fixed.
"""

from .checks import CheckResult, is_close, fmt


def reproducibility(run1, run2):
    out = []
    for k in sorted(set(run1) | set(run2)):
        a, b = run1.get(k), run2.get(k)
        if k not in run1 or k not in run2:
            out.append(CheckResult("4", f"repro:{k}", f"{k} present on both runs", False,
                                   f"run1={fmt(a)} run2={fmt(b)}"))
            continue
        ok = is_close(a, b, atol=0.0, rtol=0.0)  # exact: identical re-run
        out.append(CheckResult("4", f"repro:{k}", f"Re-run identical: {k}", ok,
                               f"run1 = {fmt(a)}, run2 = {fmt(b)}"))
    return out
