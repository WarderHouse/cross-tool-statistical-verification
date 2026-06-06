"""Execute the Python adapter and the R replication, collecting key statistics."""

import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd


def load_data(path):
    """Load the analysis dataset from a CSV file.

    Args:
        path: Filesystem path to the CSV file, as accepted by :func:`pandas.read_csv`.

    Returns:
        The dataset as a :class:`pandas.DataFrame`.
    """
    return pd.read_csv(path)


def load_adapter(module_path):
    """Import a Python analysis module from a file path.

    The module must define ``run(df, seed=None) -> dict`` and may define
    ``prepare(df, seed=None) -> DataFrame``. When ``prepare`` is declared, cli
    runs it once and hands its output to ``run`` (and to the Phase-3 consistency
    ranges), so the statistics and the checks share one data space; without it,
    ``run`` receives the raw data as loaded.

    Args:
        module_path: Filesystem path/str to the Python analysis module; its stem is
            used to derive the imported module name.

    Returns:
        The imported module object.
    """
    module_path = Path(module_path)
    spec = importlib.util.spec_from_file_location(
        f"crossverify_adapter_{module_path.stem}", str(module_path)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call_with_optional_seed(fn, df, seed):
    """Call ``fn(df, seed=seed)`` if it accepts a ``seed`` parameter, else ``fn(df)``.

    Args:
        fn: Callable to invoke, typically the adapter's ``run`` or ``prepare``.
        df: The :class:`pandas.DataFrame` passed as the first positional argument.
        seed: Random seed forwarded only when ``fn`` declares a ``seed`` parameter.

    Returns:
        Whatever ``fn`` returns.
    """
    if "seed" in inspect.signature(fn).parameters:
        return fn(df, seed=seed)
    return fn(df)


def _to_num(v):
    """Coerce a scalar to ``float``, mapping ``bool`` to ``1.0``/``0.0``.

    Args:
        v: Value to coerce; ``bool`` is special-cased, otherwise ``float(v)`` is used.

    Returns:
        The value as a ``float``.

    Raises:
        TypeError: If ``v`` cannot be converted to ``float``.
        ValueError: If ``v`` cannot be converted to ``float``.
    """
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return float(v)


def _coerce(mapping):
    """Coerce every value in a statistics mapping to ``float`` with stringified keys.

    Args:
        mapping: Mapping of statistic name to value; keys are coerced via ``str`` and
            values via :func:`_to_num`.

    Returns:
        A new dict mapping ``str`` keys to ``float`` values.

    Raises:
        ValueError: If any value is not numeric (non-coercible to ``float``); the
            offending key and value are named in the message.
    """
    coerced = {}
    for k, v in mapping.items():
        try:
            coerced[str(k)] = _to_num(v)
        except (TypeError, ValueError):
            raise ValueError(
                f"statistic '{k}' is not numeric (got {v!r}); "
                "the harness verifies numbers, so emit scalars only."
            ) from None
    return coerced


def run_python(adapter, df, seed):
    """Run the adapter's ``run`` function and return its coerced statistics.

    Invokes ``adapter.run`` on a copy of ``df`` (forwarding ``seed`` when accepted),
    then coerces the returned mapping to ``{str: float}`` via :func:`_coerce`.

    Args:
        adapter: Imported analysis module that must define
            ``run(df, seed=None) -> dict``.
        df: Input :class:`pandas.DataFrame`; a copy is passed so ``run`` cannot mutate
            the caller's frame.
        seed: Random seed forwarded to ``run`` only when it declares a ``seed`` parameter.

    Returns:
        A dict mapping statistic name to ``float``.

    Raises:
        AttributeError: If ``adapter`` does not define ``run``.
        TypeError: If ``run`` does not return a ``dict``.
        ValueError: If a returned statistic is not numeric (propagated from
            :func:`_coerce`).
    """
    if not hasattr(adapter, "run"):
        raise AttributeError("the Python adapter must define run(df, seed=None) -> dict")
    result = call_with_optional_seed(adapter.run, df.copy(), seed)
    if not isinstance(result, dict):
        raise TypeError("run() must return a dict of {statistic_name: number}")
    return _coerce(result)


# Variables the R child legitimately needs; everything else in the parent
# environment (tokens, cloud credentials, etc.) is withheld from the
# user-supplied R script. R_* / LC_* families are matched by prefix below.
_R_ENV_ALLOW = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TZ",
    "TMPDIR",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
)


def _r_child_env(helper_path):
    """Build a minimal environment for the Rscript child.

    Copies only an allowlist from the parent environment so secrets the parent
    holds are not exposed to the user-supplied R script, then points
    CROSSVERIFY_R at the helper library. The allowlist is :data:`_R_ENV_ALLOW`
    plus any variable whose name starts with ``R_`` or ``LC_``.

    Args:
        helper_path: Path to the crossverify R helper library; stringified into the
            ``CROSSVERIFY_R`` variable.

    Returns:
        A dict of environment variables for the child process.
    """
    env = {k: v for k, v in os.environ.items() if k in _R_ENV_ALLOW or k.startswith(("R_", "LC_"))}
    env["CROSSVERIFY_R"] = str(helper_path)
    return env


def r_available():
    """Report whether the ``Rscript`` executable is on the ``PATH``.

    Returns:
        ``True`` if ``Rscript`` is found; ``False`` otherwise.
    """
    return shutil.which("Rscript") is not None


def r_version():
    """Return the first line of ``Rscript --version`` output.

    Returns:
        The version string, or ``"unknown"`` if ``Rscript`` is unavailable, errors,
        or produces no output.
    """
    try:
        out = subprocess.run(["Rscript", "--version"], capture_output=True, text=True)
        text = (out.stdout or out.stderr).strip()
        return text.splitlines()[0] if text else "unknown"
    except Exception:
        return "unknown"


def run_r(r_script, data_path, seed, helper_path):
    """Run the R replication and return ``(results dict, stdout)``.

    The harness passes three positional arguments to the R script — data path,
    output path, seed — and sets CROSSVERIFY_R to the helper library so the
    script can ``source(Sys.getenv("CROSSVERIFY_R"))``. The R script writes its
    statistics as JSON to a temporary output path, which is read back, coerced to
    ``{str: float}``, and the temporary file removed.

    Args:
        r_script: Path/str to the user-supplied R replication script.
        data_path: Path/str to the dataset, passed to the script as its first argument.
        seed: Random seed passed as the third argument; ``None`` is sent as an empty
            string.
        helper_path: Path to the crossverify R helper library, exposed via the
            ``CROSSVERIFY_R`` environment variable.

    Returns:
        A ``(results, stdout)`` tuple: ``results`` is a dict mapping statistic name to
        ``float``, and ``stdout`` is the R process's captured standard output.

    Raises:
        RuntimeError: If the R script exits with a non-zero return code; the message
            includes the captured stdout and stderr.
        ValueError: If a statistic emitted by the script is not numeric (propagated
            from :func:`_coerce`).
    """
    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        env = _r_child_env(helper_path)
        cmd = [
            "Rscript",
            str(r_script),
            str(data_path),
            out_path,
            "" if seed is None else str(seed),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                f"R script exited {proc.returncode}.\n--- R stdout ---\n{proc.stdout}\n"
                f"--- R stderr ---\n{proc.stderr}"
            )
        raw = json.loads(Path(out_path).read_text())
        return _coerce(raw), proc.stdout
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass
