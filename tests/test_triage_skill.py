"""Structural validator for triage-ticket plan files.

The `triage-ticket` skill calls `validate_plan_structure` (Step 7) before it
commits a generated plan under `.dev/tasks/`. It returns a list of human-readable
violation strings (empty list == the plan is well-formed).

Run directly or under pytest:
    python tests/test_triage_skill.py
    python -m pytest tests/test_triage_skill.py
    uv run python -c "from tests.test_triage_skill import validate_plan_structure; \
        print(validate_plan_structure('.dev/tasks/1_Foo.md'))"

Pure standard library so it runs in a bare `uv run python` with no project deps.
"""

import re
import tempfile
from pathlib import Path

# H2 sections that every plan must contain, in this order (see SKILL.md Step 6).
REQUIRED_SECTIONS = [
    "Objective",
    "Background",
    "Implementation Plan",
    "Files to Modify",
    "Dependencies",
    "Acceptance Criteria",
    "Testing",
]

# Words the plan body must not contain (SKILL.md Rule 6): the plan describes
# *what* to change, never *how hard* it is.
FORBIDDEN_WORDS = ["trivial", "quick fix", "should be easy"]


def validate_plan_structure(path):
    """Return a list of structural violations for the plan at `path`.

    An empty list means the plan satisfies every rule the skill enforces.
    """
    violations = []
    p = Path(path)
    if not p.is_file():
        return [f"plan file not found: {path}"]

    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()

    # H1 must be the first non-empty line and match "# Task {N}: {Title}".
    h1 = next((ln for ln in lines if ln.strip()), "")
    if not re.match(r"^#\s+Task\s+\d+:\s+\S", h1):
        violations.append(f'H1 must match "# Task {{N}}: {{Title}}", got: {h1!r}')

    # Required H2 sections must all be present and in the canonical order.
    headings = [ln[3:].strip() for ln in lines if ln.startswith("## ")]
    last_index = -1
    for section in REQUIRED_SECTIONS:
        if section not in headings:
            violations.append(f"missing required section: ## {section}")
            continue
        idx = headings.index(section)
        if idx < last_index:
            violations.append(f"section out of order: ## {section}")
        last_index = max(last_index, idx)

    # `## Files to Modify` must hold a markdown table with File | Change columns
    # and at least one data row.
    body = _section_body(text, "Files to Modify")
    if body is not None:
        rows = [r for r in body.splitlines() if r.strip().startswith("|")]
        header_ok = any(
            "file" in r.lower() and "change" in r.lower() for r in rows
        )
        data_rows = [r for r in rows if "---" not in r]
        if not header_ok:
            violations.append(
                "## Files to Modify must contain a markdown table with "
                "`File | Change` columns"
            )
        elif len(data_rows) < 2:
            violations.append(
                "## Files to Modify table must list at least one file row"
            )

    # `## Acceptance Criteria` must use an unchecked markdown checkbox list.
    ac = _section_body(text, "Acceptance Criteria")
    if ac is not None and not re.search(r"^\s*-\s+\[ \]", ac, re.MULTILINE):
        violations.append(
            "## Acceptance Criteria must use a markdown checkbox list (`- [ ]`)"
        )

    # Forbidden words anywhere in the plan body (case-insensitive).
    lowered = text.lower()
    for word in FORBIDDEN_WORDS:
        if word in lowered:
            violations.append(f"forbidden word in plan body: {word!r}")

    return violations


def _section_body(text, heading):
    """Return the text between `## {heading}` and the next `## ` (or EOF)."""
    pattern = re.compile(
        r"^##\s+" + re.escape(heading) + r"\s*$(.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# Tests (runnable directly or via pytest)
# --------------------------------------------------------------------------- #

_GOOD = """# Task 1: Sample Task

## Objective
Do the thing. See `crossverify/cli.py:1`.

## Background
Current state described at `crossverify/runner.py:26`.

## Implementation Plan
1. Step one.
2. Step two.

## Files to Modify
| File | Change |
| --- | --- |
| `crossverify/runner.py` | Harden path resolution. |

## Dependencies
None.

## Acceptance Criteria
- [ ] It works.

## Testing
Run `uv run python -m pytest tests/`.
"""


def _write(body):
    f = Path(tempfile.mkdtemp()) / "1_Sample.md"
    f.write_text(body, encoding="utf-8")
    return str(f)


def test_good_plan_has_no_violations():
    assert validate_plan_structure(_write(_GOOD)) == []


def test_missing_section_flagged():
    body = _GOOD.replace("## Testing\nRun `uv run python -m pytest tests/`.\n", "")
    assert any("Testing" in v for v in validate_plan_structure(_write(body)))


def test_section_out_of_order_flagged():
    body = _GOOD.replace(
        "## Dependencies\nNone.\n\n## Acceptance Criteria",
        "## Acceptance Criteria",
    ).replace(
        "## Testing\n", "## Dependencies\nNone.\n\n## Testing\n"
    )
    assert any("out of order" in v for v in validate_plan_structure(_write(body)))


def test_forbidden_word_flagged():
    body = _GOOD.replace("Do the thing.", "Do the thing. This is trivial.")
    assert any("trivial" in v for v in validate_plan_structure(_write(body)))


def test_bad_h1_flagged():
    body = _GOOD.replace("# Task 1: Sample Task", "# Sample Task")
    assert any("H1" in v for v in validate_plan_structure(_write(body)))


def test_files_table_requires_data_row():
    body = _GOOD.replace("| `crossverify/runner.py` | Harden path resolution. |\n", "")
    assert any("file row" in v for v in validate_plan_structure(_write(body)))


def test_missing_acceptance_checkbox_flagged():
    body = _GOOD.replace("- [ ] It works.", "It works.")
    assert any("checkbox" in v for v in validate_plan_structure(_write(body)))


def test_missing_file_returns_violation():
    v = validate_plan_structure("/nonexistent/path/plan.md")
    assert v and "not found" in v[0]


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
