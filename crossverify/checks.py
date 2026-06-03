"""Shared numeric utilities: the check record, float comparison, tolerances."""

import math
from dataclasses import dataclass


@dataclass
class CheckResult:
    """One line in the verification log.

    passed is True/False for a real check, or None for an informational entry
    (e.g. a data-intake summary line that reports a fact but does not pass/fail).
    """

    phase: str
    name: str
    description: str
    passed: bool | None
    detail: str = ""

    @property
    def status(self) -> str:
        if self.passed is None:
            return "INFO"
        return "PASS" if self.passed else "FAIL"


def is_close(a, b, atol: float = 1e-8, rtol: float = 1e-6, use_abs: bool = False) -> bool:
    """True if a and b agree within atol + rtol * max(|a|, |b|).

    NaN never counts as agreement: a NaN almost always signals a broken
    computation, not consensus, so two NaNs do not "match" and are not
    "reproducible". Infinities compare by exact equality. use_abs compares
    magnitudes only, for quantities whose sign is implementation-defined (PCA
    loadings, eigenvectors, discriminant-function coefficients), where Python and
    R may legitimately return the same result with opposite signs.
    """
    try:
        a = float(a)
        b = float(b)
    except (TypeError, ValueError):
        return False
    if math.isnan(a) or math.isnan(b):
        return False
    if use_abs:
        a, b = abs(a), abs(b)
    # Infinities compare by exact equality (+inf == +inf passes; +inf vs a finite
    # value or -inf fails), consistent with the NaN policy above.
    if math.isinf(a) or math.isinf(b):
        return a == b
    # Symmetric relative term anchored to max(|a|, |b|), so the cross-tool
    # comparison does not depend on which result is named b.
    return abs(a - b) <= atol + rtol * max(abs(a), abs(b))


def tol_for(tolerance: dict, key: str):
    """Resolve (atol, rtol, use_abs) for a statistic, applying per-key overrides."""
    atol = tolerance.get("default_atol", 1e-8)
    rtol = tolerance.get("default_rtol", 1e-6)
    use_abs = False
    over = (tolerance.get("per_key") or {}).get(key)
    if over:
        atol = over.get("atol", atol)
        rtol = over.get("rtol", rtol)
        use_abs = over.get("abs", use_abs)
    return atol, rtol, use_abs


def severity_for(tolerance: dict, key: str) -> str:
    """Resolve a statistic's cross-tool severity: 'fail' (default) or 'info'.

    A cross-tool mismatch is a hard failure by default — agreement across an
    independent implementation is the whole point of Phase 5. But correct
    analyses legitimately differ past a tight tolerance for defensible reasons
    (robust-SE variants, ddof/denominator choices, contrast coding, tie
    handling). Declaring ``severity: info`` in a statistic's per-key tolerance
    reports such a divergence as INFO rather than failing the build, so a
    researcher is not pushed to degrade correct code just to turn the run green.
    """
    over = (tolerance.get("per_key") or {}).get(key) or {}
    sev = str(over.get("severity", "fail")).lower()
    return sev if sev in ("fail", "info") else "fail"


def fmt(x) -> str:
    """Format a number for the log without lying about precision."""
    if x is None:
        return "—"
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return str(x)
    if math.isnan(xf):
        return "NaN"
    if xf == int(xf) and abs(xf) < 1e15:
        return str(int(xf))
    # Enough significant digits that two values which differ only at the 7th-8th
    # digit (and a row that therefore FAILED) do not print as identical.
    return f"{xf:.10g}"
