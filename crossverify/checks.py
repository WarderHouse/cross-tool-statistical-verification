"""Shared numeric utilities: the check record, float comparison, tolerances."""

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class CheckResult:
    """One line in the verification log.

    passed is True/False for a real check, or None for an informational entry
    (e.g. a data-intake summary line that reports a fact but does not pass/fail).
    """

    phase: str
    name: str
    description: str
    passed: Optional[bool]
    detail: str = ""

    @property
    def status(self) -> str:
        if self.passed is None:
            return "INFO"
        return "PASS" if self.passed else "FAIL"


def is_close(a, b, atol: float = 1e-8, rtol: float = 1e-6, use_abs: bool = False) -> bool:
    """True if a and b agree within atol + rtol*|b|.

    use_abs compares magnitudes only, which is what you want for quantities
    whose sign is implementation-defined (e.g. PCA loadings, eigenvectors,
    discriminant-function coefficients), where Python and R can legitimately
    return the same result with opposite signs.
    """
    try:
        a = float(a)
        b = float(b)
    except (TypeError, ValueError):
        return False
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if use_abs:
        a, b = abs(a), abs(b)
    return abs(a - b) <= atol + rtol * abs(b)


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
    return f"{xf:.6g}"
