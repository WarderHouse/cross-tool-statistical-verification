"""Phase 1 — inspect the dataset as loaded and surface its shape and contents.

Reports the shape, dtypes, missing-value counts, numeric descriptives, and
categorical frequencies of the dataset as loaded, so the researcher can confirm
the file the harness sees matches their raw file.
"""

from .checks import CheckResult


def inspect(df):
    """Summarize a dataset's shape, dtypes, missingness, and value distributions.

    Builds the Phase-1 intake record: informational ``CheckResult`` lines for the
    dataset dimensions, per-column dtypes, and missing-value counts, plus rendered
    artifacts (a 10-row head, numeric ``describe()`` output, and top-10 categorical
    frequency tables) for the verification log. All entries are informational; nothing
    here passes or fails.

    Args:
        df: The dataset as loaded, inspected exactly as received without modification.

    Returns:
        A ``(results, artifacts)`` tuple, where ``results`` is a list of informational
        ``CheckResult`` records and ``artifacts`` is a dict mapping ``"head"``,
        ``"describe"``, and ``"categorical"`` to pre-rendered string blocks.
    """
    results = []
    artifacts = {}

    results.append(
        CheckResult(
            "1",
            "intake:shape",
            "Dataset dimensions",
            None,
            f"{df.shape[0]} rows x {df.shape[1]} columns",
        )
    )

    dtypes = "; ".join(f"{c}: {t}" for c, t in df.dtypes.astype(str).items())
    results.append(CheckResult("1", "intake:dtypes", "Column dtypes", None, dtypes))

    miss = {c: int(n) for c, n in df.isna().sum().items() if n > 0}
    detail = "none" if not miss else "; ".join(f"{c}: {n}" for c, n in miss.items())
    results.append(CheckResult("1", "intake:missing", "Missing values per column", None, detail))

    artifacts["head"] = df.head(10).to_string()
    numeric = df.select_dtypes("number")
    artifacts["describe"] = (
        numeric.describe().to_string() if not numeric.empty else "(no numeric columns)"
    )

    cat_blocks = []
    for col in df.select_dtypes(exclude="number").columns:
        vc = df[col].value_counts().head(10)
        cat_blocks.append(
            f"{col} (top {min(10, df[col].nunique())} of {df[col].nunique()} unique):\n{vc.to_string()}"
        )
    artifacts["categorical"] = "\n\n".join(cat_blocks) if cat_blocks else "(no categorical columns)"

    return results, artifacts


def numeric_ranges(df):
    """Compute the (min, max) range of each numeric column.

    Used by centroid-in-range consistency checks, which confirm a reported centroid
    falls within the observed span of its column.

    Args:
        df: The frame to scan; only number-dtype columns are included.

    Returns:
        A dict mapping each numeric column name to a ``(min, max)`` tuple of ``float``.
    """
    numeric = df.select_dtypes("number")
    return {c: (float(numeric[c].min()), float(numeric[c].max())) for c in numeric.columns}
