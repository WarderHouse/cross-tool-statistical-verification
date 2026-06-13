"""Load and validate a verification project file (YAML)."""

from __future__ import annotations  # PEP 604 (X | None) annotations on Python 3.9

from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _within_base(path, base) -> bool:
    """Report whether ``path`` resolves to a location inside ``base``.

    Used to keep a project file from pointing its data/scripts at arbitrary
    locations on disk (absolute paths or ``..`` traversal).

    Args:
        path: Candidate path to test, resolved before comparison.
        base: Base directory the path must resolve inside, resolved before comparison.

    Returns:
        ``True`` if ``path`` resolves inside ``base``; ``False`` otherwise.
    """
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


@dataclass
class Project:
    """Hold a parsed and resolvable verification project specification.

    Built by :meth:`load` from a YAML project file; paths are resolved relative to the
    file's directory (``base_dir``). Use :meth:`validate` to check the resolved project
    for problems before running it.

    Attributes:
        analysis_name: Human-readable analysis name; defaults to the project file stem.
        data_path: Resolved path to the dataset to verify.
        base_dir: Directory containing the project file; the root for relative paths and
            the external-path containment check.
        seed: Optional random seed passed to adapter steps that accept one.
        python_module: Resolved path to the Python analysis module to verify, if declared.
        r_script: Resolved path to the independent R script, if declared.
        checks: Mapping of declared value checks.
        group_checks: List of declared group-wise check specifications.
        spot_checks: List of declared spot-check specifications.
        transform_checks: List of declared Phase 2 transformation-check specifications.
        tolerance: Tolerance configuration, with ``default_atol``/``default_rtol`` filled in.
        metadata: Free-form project metadata mapping.
        reproducibility: Reproducibility configuration mapping.
        allow_external_paths: When ``False`` (default), ``data``/``python.module``/``r.script``
            must resolve inside ``base_dir``; set ``True`` to permit out-of-tree paths.
    """

    analysis_name: str
    data_path: Path
    base_dir: Path
    seed: int | None = None
    python_module: Path | None = None
    r_script: Path | None = None
    checks: dict = field(default_factory=dict)
    group_checks: list = field(default_factory=list)
    spot_checks: list = field(default_factory=list)
    transform_checks: list = field(default_factory=list)
    tolerance: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    reproducibility: dict = field(default_factory=dict)
    # When False (default), data/python.module/r.script must resolve inside the
    # project folder; set true in the project file to permit out-of-tree paths.
    allow_external_paths: bool = False

    @classmethod
    def load(cls, path) -> Project:
        """Load a project from a YAML file, resolving its paths relative to that file.

        Relative ``data``, ``python.module``, and ``r.script`` paths are resolved against
        the project file's directory; absolute paths are kept as-is. Tolerance defaults
        (``default_atol``, ``default_rtol``) are filled in when not specified.

        Args:
            path: Path to the YAML project file.

        Returns:
            A :class:`Project` populated from the file's contents.

        Raises:
            FileNotFoundError: If ``path`` does not exist.
            ValueError: If the file omits the required ``data`` key.
        """
        path = Path(path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Project file not found: {path}")
        spec = yaml.safe_load(path.read_text()) or {}
        base = path.parent

        def resolve(rel):
            """Resolve a relative path against ``base``; absolute/falsy values pass through."""
            if not rel:
                return None
            p = Path(rel)
            return p if p.is_absolute() else (base / p)

        if "data" not in spec:
            raise ValueError(f"{path.name}: missing required 'data' key (path to the dataset).")

        py = spec.get("python") or {}
        r = spec.get("r") or {}
        tol = spec.get("tolerance") or {}
        tol.setdefault("default_atol", 1e-8)
        tol.setdefault("default_rtol", 1e-6)

        return cls(
            analysis_name=spec.get("analysis_name", path.stem),
            data_path=resolve(spec["data"]),
            base_dir=base,
            seed=spec.get("seed"),
            python_module=resolve(py.get("module")),
            r_script=resolve(r.get("script")),
            checks=spec.get("checks") or {},
            group_checks=spec.get("group_checks") or [],
            spot_checks=spec.get("spot_checks") or [],
            transform_checks=spec.get("transform_checks") or [],
            tolerance=tol,
            metadata=spec.get("metadata") or {},
            reproducibility=spec.get("reproducibility") or {},
            allow_external_paths=bool(spec.get("allow_external_paths", False)),
        )

    def validate(self, *, force_contain: bool = False) -> list:
        """Check the resolved project and return human-readable problems.

        Verifies that the dataset and declared Python module exist, that any declared R
        script exists, and — unless ``allow_external_paths`` is set — that ``data``,
        ``python.module``, and ``r.script`` all resolve inside ``base_dir``.

        Args:
            force_contain: When ``True``, enforce path containment even if the project
                file sets ``allow_external_paths: true``. The MCP server passes this so
                that a project's own opt-out cannot disable containment for code that
                will then be executed; the opt-out moves to the server operator instead.

        Returns:
            A list of human-readable problem strings; an empty list means the project is
            valid.
        """
        problems = []
        if not self.data_path or not self.data_path.exists():
            problems.append(f"data file not found: {self.data_path}")
        if not self.python_module:
            problems.append("no python.module declared (the analysis to verify)")
        elif not self.python_module.exists():
            problems.append(f"python module not found: {self.python_module}")
        if self.r_script and not self.r_script.exists():
            problems.append(f"r script declared but not found: {self.r_script}")
        if force_contain or not self.allow_external_paths:
            # When containment is forced (e.g. by the MCP server), the project's own
            # allow_external_paths cannot help, so don't suggest it.
            hint = (
                ""
                if force_contain
                else " (set 'allow_external_paths: true' in the project file to permit this)"
            )
            for label, p in (
                ("data", self.data_path),
                ("python.module", self.python_module),
                ("r.script", self.r_script),
            ):
                if p and not _within_base(p, self.base_dir):
                    problems.append(
                        f"{label} resolves outside the project folder: {Path(p).resolve()}{hint}"
                    )
        return problems
