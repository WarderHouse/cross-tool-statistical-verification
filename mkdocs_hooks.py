"""MkDocs build hook: scope what ``--strict`` fails on.

We keep ``mkdocs build --strict`` enabled so the build fails on *structural*
problems — broken links, missing nav entries, unresolved cross-references. But
griffe also emits a stylistic notice ("No type or annotation for parameter /
returned value") for every documented parameter or return that doesn't carry a
type. These functions are documented in Google style with prose ``Args:`` /
``Returns:`` sections and are not all type-annotated, by design; duplicating a
type onto all ~140 sites would be noise, not clarity. So we drop just those
notices while leaving every other warning fatal.

mkdocstrings routes griffe's logs through the ``mkdocs.plugins.griffe`` logger
(a child of ``mkdocs``). Dropping the record at that source logger stops it
before it can propagate to mkdocs's ``--strict`` warning counter, so we attach
the filter there (and to the bare ``griffe`` logger as a belt) rather than
walking every logger/handler in the process. ``getLogger`` is idempotent, so
adding the filter pre-emptively in ``on_config`` covers the logger mkdocstrings
creates lazily during rendering.
"""

import logging

_DROP_SUBSTRING = "No type or annotation for"
# The loggers mkdocstrings emits griffe notices through. mkdocs.plugins.griffe is
# the bridge child of `mkdocs`; `griffe` is its upstream name, filtered for safety.
_TARGET_LOGGERS = ("mkdocs.plugins.griffe", "griffe")


class _DropGriffeNoTypeNotices(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return _DROP_SUBSTRING not in record.getMessage()


_FILTER = _DropGriffeNoTypeNotices()


def _install() -> None:
    for name in _TARGET_LOGGERS:
        logging.getLogger(name).addFilter(_FILTER)


def on_startup(**kwargs) -> None:
    _install()


def on_config(config, **kwargs):
    _install()
    return config
