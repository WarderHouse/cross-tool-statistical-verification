# Task 1: Security review: hardening recommendations (no critical issues found)

## Objective
Implement the five hardening recommendations (F1–F5) from the automated security
review in issue #1. No critical or remotely-exploitable vulnerability was found;
the work is defense-in-depth around the tool's by-design trust boundary — running
a project bundle imports and executes user-supplied Python/R code. The changes
add an opt-out path-containment guard (`crossverify/config.py:33`), make report
rendering robust to user-edited templates (`crossverify/report.py:61`), pass a
minimal environment to the R child (`crossverify/runner.py:89`), pin dependency
ranges (`requirements.txt:2`), and document the trust boundary in the README.

## Background
The tool loads and runs user code by design:
- `crossverify/runner.py:26-29` — `spec_from_file_location(...)` + `spec.loader.exec_module(...)` executes any file named by `python.module`; module-level code runs on import.
- `crossverify/runner.py:91-93` — `["Rscript", str(r_script), ...]` executes any file named by `r.script` (list-form args, no `shell=True`).

The review confirmed a conservative posture (`yaml.safe_load` at `crossverify/config.py:30`; temp files via `tempfile.mkstemp` at `crossverify/runner.py:86`; no network/`eval`/`exec`/`pickle`). The remaining hardening items:

- **F1 — path resolution accepts anything.** `crossverify/config.py:33-37` `resolve()` returns absolute paths unchanged and applies `base / p` without checking the result stays under `base`, so `data`, `python.module`, and `r.script` can point anywhere on disk. `validate()` (`crossverify/config.py:63-74`) only checks existence, not containment.
- **F2 — template rendered with `str.format`.** `crossverify/report.py:60-61` calls `template.format(**fields)`. The bundled `templates/methodology_statement.md` uses `{python_version}`-style fields and is safe, but a user-edited template with a stray `{` or a `{seed.__class__}`-style accessor could crash or traverse object internals.
- **F3 — unpinned dependencies.** `requirements.txt:2-3,6` lists `PyYAML`, `pandas`, `statsmodels` with no version bound — non-reproducible installs for a reproducibility tool.
- **F4 — untrusted data in pandas/R (local DoS).** `crossverify/runner.py:15-16` (`pd.read_csv`) and the R `read.csv`. Documentation-only: data files are part of the trust boundary.
- **F5 — R child inherits full parent env.** `crossverify/runner.py:89` `env = dict(os.environ)` passes every environment variable (possibly tokens/secrets) into the user-supplied R script, which could harvest them.

## Implementation Plan
1. **F1 — path containment guard (`crossverify/config.py`).** Add a module-level helper that, given a resolved path and `base_dir`, returns whether the path stays within `base_dir` (compare `Path.resolve()` outputs; treat an absolute input or any `..` that escapes `base` as outside). In `validate()`, after the existing existence checks, append a problem for each of `data_path`, `python_module`, `r_script` whose resolved location escapes `base_dir`, naming the exact resolved path. Gate the guard behind an opt-out so intentional out-of-tree layouts still work — read it from the project spec, e.g. a top-level `allow_external_paths: true` (default `false`). Surface the concrete paths so the user sees what will execute before it runs.

   ```python
   def _within_base(path, base):
       try:
           Path(path).resolve().relative_to(Path(base).resolve())
           return True
       except ValueError:
           return False
   ```

   Thread the new flag through `Project.load()` (parse `spec.get("allow_external_paths", False)`) and store it as a field so `validate()` can honor it.

2. **F2 — robust template rendering (`crossverify/report.py` + `templates/methodology_statement.md`).** Convert the template placeholders from `{name}` to `$name` and render with `string.Template(template).safe_substitute(fields)` instead of `template.format(**fields)` at `crossverify/report.py:61`. `safe_substitute` never raises on an unknown or malformed placeholder and has no attribute-access syntax, so a user-edited template cannot crash the run or reach object internals. Update every field token in `templates/methodology_statement.md` (`{python_version}`, `{python_libs}`, `{tool_version}`, `{seed}`, `{r_version}`, `{n_matched}`, `{n_compared}`, `{tolerance_desc}`, `{date}`, `{analysis_name}`).

3. **F3 — pin dependency ranges (`requirements.txt`).** Replace the bare names with conservative compatible ranges: `PyYAML>=6,<7`, `pandas>=2,<3`, `statsmodels>=0.14,<1`. Keep the existing section comments.

4. **F5 — minimal env for the R child (`crossverify/runner.py`).** In `run_r` replace `env = dict(os.environ)` (`crossverify/runner.py:89`) with an allowlisted environment: carry only `PATH`, `HOME`, any `R_*`/`LANG`/`LC_*` variables R needs, then set `CROSSVERIFY_R`. This stops the user-supplied R script from reading unrelated secrets in the parent environment.

   ```python
   keep = ("PATH", "HOME", "LANG", "TMPDIR")
   env = {k: v for k, v in os.environ.items()
          if k in keep or k.startswith(("R_", "LC_"))}
   env["CROSSVERIFY_R"] = str(helper_path)
   ```

5. **F1 + F4 — document the trust boundary (`README.md`).** Add a short subsection (near "Confidentiality") stating plainly that a project file is executable code and a data file is parsed by pandas/R, so users should only run project bundles and datasets they trust; note the `allow_external_paths` default and that referenced paths are reported before execution. This is the primary mitigation for F1 (untrusted-bundle model) and the entire fix for F4.

6. **Tests (`tests/test_hardening.py`).** Add unit tests for the new behavior (see Testing).

## Files to Modify
| File | Change |
|---|---|
| `crossverify/config.py` | Add `_within_base` containment helper and an `allow_external_paths` field; in `validate()` flag `data_path`/`python_module`/`r_script` that escape `base_dir` unless opted out (F1). |
| `crossverify/report.py` | Render the methodology template with `string.Template(...).safe_substitute(...)` instead of `str.format` (F2). |
| `templates/methodology_statement.md` | Convert `{name}` placeholders to `$name` for `safe_substitute` (F2). |
| `crossverify/runner.py` | In `run_r`, build a minimal allowlisted env for the `Rscript` child instead of copying all of `os.environ` (F5). |
| `requirements.txt` | Pin `PyYAML`, `pandas`, `statsmodels` to compatible version ranges (F3). |
| `README.md` | Document the executable-bundle / data trust boundary and the `allow_external_paths` default (F1, F4). |
| `tests/test_hardening.py` | New test module covering containment rejection, the opt-out, and `safe_substitute` robustness. |

## Dependencies
None. All changes use the standard library (`pathlib`, `string`, `os`) and the
already-declared `PyYAML`/`pandas`. The `requirements.txt` change only adds
version bounds to existing dependencies — no new packages.

## Acceptance Criteria
- [ ] A project file whose `data`, `python.module`, or `r.script` resolves outside `base_dir` (via an absolute path or `..`) is reported by `Project.validate()` with the exact offending path, and is **not** executed.
- [ ] Setting `allow_external_paths: true` in the project file suppresses the containment problems, preserving the prior behavior for intentional out-of-tree layouts.
- [ ] `crossverify/report.py` renders the methodology statement via `string.Template.safe_substitute`; a template containing a stray `{` or a `$missing` placeholder produces output without raising.
- [ ] `templates/methodology_statement.md` uses `$name` placeholders and the worked example still produces a correct methodology paragraph.
- [ ] The `Rscript` child receives only the allowlisted variables plus `CROSSVERIFY_R`; a variable like `AWS_SECRET_ACCESS_KEY` set in the parent is absent from the child's environment.
- [ ] `requirements.txt` pins `PyYAML`, `pandas`, and `statsmodels` to bounded ranges.
- [ ] `README.md` states that project files are executable code and data files are parsed locally, and documents the `allow_external_paths` default.
- [ ] `python tests/test_checks.py` and `python tests/test_hardening.py` both pass, and the worked example (`python -m crossverify --project examples/project.yaml`) still reports `PASS`.

## Testing
Run the existing and new suites plus the end-to-end example:

```bash
python tests/test_checks.py
python tests/test_hardening.py
python -m pytest                          # discovers both modules
python -m crossverify --project examples/project.yaml   # must still PASS, 9/9 matched
```

Tests added in `tests/test_hardening.py`:
- `test_external_path_rejected` — a `Project` with an absolute or `..`-escaping `python_module`/`r_script`/`data_path` yields a containment problem from `validate()`.
- `test_allow_external_paths_optout` — the same project with `allow_external_paths=True` yields no containment problem.
- `test_within_base_accepts_relative` — a normal in-tree relative path passes containment.
- `test_safe_substitute_tolerates_bad_template` — rendering a template with a stray `{`/unknown `$placeholder` does not raise and leaves unknown tokens intact.
