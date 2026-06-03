"""Phase 1 — data intake and inspection.

Reports the shape, dtypes, missing-value counts, numeric descriptives, and
categorical frequencies of the dataset as loaded, so the researcher can confirm
the file the harness sees matches their raw file.
"""

from .checks import CheckResult


def inspect(df):
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
    """min/max per numeric column, used by centroid-in-range consistency checks."""
    numeric = df.select_dtypes("number")
    return {c: (float(numeric[c].min()), float(numeric[c].max())) for c in numeric.columns}
