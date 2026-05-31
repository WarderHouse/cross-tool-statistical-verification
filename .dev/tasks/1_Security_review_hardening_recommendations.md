# Task 1: Security review: hardening recommendations (no critical issues found)

## Objective
Implement the five hardening recommendations (F1–F5) from the automated security
review in issue #1. No critical or remotely-exploitable vulnerability was found;
the work is defense-in-depth around the tool's by-design trust boundary — running
a project bundle imports and executes user-supplied Python/R code. The changes add
an opt-out path-containment guard in `Project.validate()` (`crossverify/config.py:63`),
make report rendering robust to user-edited templates (`crossverify/report.py:61`),
pass a minimal allowlisted environment to the R child (`crossverify/runner.py:89`),
pin dependency ranges (`requirements.txt:2`), and document the trust boundary in the
README. This plan was hardened after a devil's-advocate pass (see Background).

## Background
The tool loads and runs user code by design:
- `crossverify/runner.py:26-29` — `spec_from_file_location(...)` + `spec.loader.exec_module(...)` executes any file named by `python.module`; module-level code runs on import (driven from `crossverify/cli.py:57`).
- `crossverify/runner.py:91-93` — `["Rscript", str(r_script), ...]` executes any file named by `r.script` (list-form args, no `shell=True`).
- `crossverify/cli.py:49-54` — `Project.validate()` problems abort the run (`return 2`) **before** `load_data`/`load_adapter`, so `validate()` is the correct gate for a containment check.

The review confirmed a conservative posture (`yaml.safe_load` at `crossverify/config.py:30`; temp files via `tempfile.mkstemp` at `crossverify/runner.py:86`; no network/`eval`/`exec`/`pickle`). Remaining hardening items:

- **F1 — path resolution accepts anything.** `crossverify/config.py:33-37` `resolve()` returns absolute paths unchanged and applies `base / p` without checking the result stays under `base`; `validate()` (`crossverify/config.py:63-74`) only checks existence. The worked example's paths (`examples/project.yaml`: `data/mtcars.csv`, `analysis.py`, `analysis.R`) are all inside `examples/`, so a default-on guard does not break it.
- **F2 — template rendered with `str.format`.** `crossverify/report.py:60-61` calls `template.format(**fields)`; `templates/methodology_statement.md` uses `{python_version}`-style fields. A user-edited template with a stray `{` or a `{seed.__class__}` accessor could crash or traverse object internals.
- **F3 — unpinned dependencies.** `requirements.txt:2-3,6` — `PyYAML`, `pandas`, `statsmodels` with no version bound.
- **F4 — untrusted data in pandas/R (local DoS).** `crossverify/runner.py:15-16` (`pd.read_csv`) and the R `read.csv`. Documentation-only.
- **F5 — R child inherits the full parent env.** `crossverify/runner.py:89` `env = dict(os.environ)` passes every variable (possibly tokens/secrets) into the user-supplied R script.

**Devil's-advocate findings folded into this plan:** (D1) the R env allowlist must keep `LD_LIBRARY_PATH`/`DYLD_LIBRARY_PATH`/`R_*`/`TZ`/`LC_*` or `jsonlite` loading breaks; (D2/D5) rendering and env logic are extracted into helpers (`_render`, `_r_child_env`) so robustness is unit-testable without spawning R; (D3) the `--init` scaffold and the error message must advertise the opt-out; (D4) the opt-out is an explicit dataclass field parsed in `load()`.

## Implementation Plan
1. **F1 — path containment guard (`crossverify/config.py`).** Add a module-level `_within_base(path, base)` helper that returns whether `Path(path).resolve()` is inside `Path(base).resolve()` (via `relative_to`, catching `ValueError`). Add an `allow_external_paths: bool = False` field to the `Project` dataclass; parse it in `load()` from `spec.get("allow_external_paths", False)`. In `validate()`, after the existence checks, and only when `not self.allow_external_paths`, append a problem for each of `data_path`/`python_module`/`r_script` that escapes `base_dir`, naming the resolved path and instructing the user to set `allow_external_paths: true` to override.

   ```python
   def _within_base(path, base):
       try:
           Path(path).resolve().relative_to(Path(base).resolve())
           return True
       except ValueError:
           return False
   ```

2. **F2 — robust template rendering (`crossverify/report.py` + `templates/methodology_statement.md`).** Extract `def _render(template_text, fields): return string.Template(template_text).safe_substitute(fields)`. Call it from `_methodology` in place of `template.format(**fields)` (`crossverify/report.py:61`). Convert every `{name}` token in `templates/methodology_statement.md` to `$name` (`python_version`, `python_libs`, `tool_version`, `seed`, `n_matched`, `n_compared`, `tolerance_desc`, `r_version`, `date`, `analysis_name`). `safe_substitute` never raises on an unknown/malformed placeholder and has no attribute-access syntax.

3. **F3 — pin dependency ranges (`requirements.txt`).** `PyYAML>=6,<7`, `pandas>=2,<3`, `statsmodels>=0.14,<1`; keep the section comments.

4. **F5 — minimal env for the R child (`crossverify/runner.py`).** Extract `def _r_child_env(helper_path)` that copies only an allowlist from `os.environ` and sets `CROSSVERIFY_R`. Use it in `run_r` in place of `env = dict(os.environ)` (`crossverify/runner.py:89`).

   ```python
   _R_ENV_ALLOW = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR",
                   "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH")

   def _r_child_env(helper_path):
       env = {k: v for k, v in os.environ.items()
              if k in _R_ENV_ALLOW or k.startswith(("R_", "LC_"))}
       env["CROSSVERIFY_R"] = str(helper_path)
       return env
   ```

5. **F1 discoverability (`crossverify/cli.py`).** Add a single commented line to the `_INIT_PROJECT` scaffold noting `# allow_external_paths: false   # set true to permit data/scripts outside this folder`.

6. **F1 + F4 — document the trust boundary (`README.md`).** Add a short "Trust boundary" subsection near "Confidentiality": a project file is executable code and a data file is parsed locally by pandas/R, so only run bundles and datasets you trust; referenced paths must stay inside the project folder unless `allow_external_paths: true`, and the resolved paths are surfaced before execution.

7. **Tests (`tests/test_hardening.py`).** Unit-test the extracted helpers (see Testing).

## Files to Modify
| File | Change |
|---|---|
| `crossverify/config.py` | Add `_within_base` helper and an `allow_external_paths` dataclass field parsed in `load()`; in `validate()` flag `data_path`/`python_module`/`r_script` escaping `base_dir` unless opted out, naming the path and the override (F1). |
| `crossverify/report.py` | Add `_render` helper using `string.Template(...).safe_substitute(...)` and call it from `_methodology` instead of `str.format` (F2). |
| `templates/methodology_statement.md` | Convert `{name}` placeholders to `$name` for `safe_substitute` (F2). |
| `crossverify/runner.py` | Add `_r_child_env` allowlist helper and use it in `run_r` instead of copying all of `os.environ` (F5). |
| `crossverify/cli.py` | Add a commented `allow_external_paths` line to the `_INIT_PROJECT` scaffold (F1 discoverability). |
| `requirements.txt` | Pin `PyYAML`, `pandas`, `statsmodels` to compatible version ranges (F3). |
| `README.md` | Document the executable-bundle / data trust boundary and `allow_external_paths` (F1, F4). |
| `tests/test_hardening.py` | New test module: containment rejection + opt-out, env allowlist, `safe_substitute` robustness. |

## Dependencies
None. All changes use the standard library (`pathlib`, `string`, `os`) and the
already-declared `PyYAML`/`pandas`. The `requirements.txt` change only adds
version bounds to existing dependencies — no new packages.

## Acceptance Criteria
- [ ] A project file whose `data`, `python.module`, or `r.script` resolves outside `base_dir` (absolute path or `..`) is reported by `Project.validate()` with the resolved offending path and the `allow_external_paths` hint, and is **not** executed.
- [ ] Setting `allow_external_paths: true` in the project file suppresses the containment problems, preserving prior behavior for intentional out-of-tree layouts.
- [ ] `_within_base` accepts a normal in-tree relative path and rejects an absolute path outside the base.
- [ ] `crossverify/report.py` renders via `string.Template.safe_substitute`; a template with a stray `{` or a `$missing` placeholder renders without raising and leaves unknown tokens intact.
- [ ] `templates/methodology_statement.md` uses `$name` placeholders and the worked example still produces a correct methodology paragraph.
- [ ] `_r_child_env` returns only allowlisted variables plus `CROSSVERIFY_R`; a parent variable like `AWS_SECRET_ACCESS_KEY` is absent from the result while `PATH` and (when present) `LD_LIBRARY_PATH`/`R_LIBS` survive.
- [ ] `requirements.txt` pins `PyYAML`, `pandas`, and `statsmodels` to bounded ranges.
- [ ] `README.md` states project files are executable code and data is parsed locally, and documents `allow_external_paths`.
- [ ] `tests/test_checks.py` and `tests/test_hardening.py` both pass, and `python -m crossverify --project examples/project.yaml` still reports `PASS`.

## Testing
Run the suites plus the end-to-end example:

```bash
python tests/test_checks.py
python tests/test_hardening.py
python -m pytest                                         # discovers both modules
python -m crossverify --project examples/project.yaml    # must still PASS
```

Tests added in `tests/test_hardening.py`:
- `test_external_path_rejected` — a `Project` whose `python_module`/`r_script`/`data_path` is an absolute path outside `base_dir` yields a containment problem from `validate()`.
- `test_allow_external_paths_optout` — the same project with `allow_external_paths=True` yields no containment problem.
- `test_within_base_relative_ok` — an in-tree relative path passes `_within_base`; an outside absolute path fails.
- `test_r_child_env_drops_secrets` — `_r_child_env` excludes a secret-looking variable, keeps `PATH`, and sets `CROSSVERIFY_R`.
- `test_render_tolerates_bad_template` — `_render` leaves unknown `$placeholder` / stray `{` intact and does not raise; a fully-populated template substitutes correctly.
