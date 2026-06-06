"""MkDocs build hook: scope what ``--strict`` fails on.

We keep ``mkdocs build --strict`` enabled so the build fails on *structural*
problems — broken links, missing nav entries, unresolved cross-references. But
griffe also emits a stylistic notice ("No type or annotation for parameter /
returned value") for every documented parameter or return that doesn't carry a
type. These functions are documented in Google style with prose ``Args:`` /
``Returns:`` sections and are not all type-annotated, by design; duplicating a
type onto all ~140 sites would be noise, not clarity. So we drop just those
notices (by exact message substring) while leaving every other warning fatal.
"""

import logging

_DROP_SUBSTRING = "No type or annotation for"


class _DropGriffeNoTypeNotices(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return _DROP_SUBSTRING not in record.getMessage()


_FILTER = _DropGriffeNoTypeNotices()


def _install() -> None:
    # Attach at both logger and handler level across every existing logger, so
    # the record is dropped at its source AND at mkdocs's strict warning-counter
    # handler (wherever it lives), regardless of propagation.
    loggers = [logging.getLogger()] + [
        logging.getLogger(name) for name in list(logging.root.manager.loggerDict)
    ]
    for logger in loggers:
        logger.addFilter(_FILTER)
        for handler in getattr(logger, "handlers", []):
            handler.addFilter(_FILTER)


def on_startup(**kwargs) -> None:
    _install()


def on_config(config, **kwargs):
    _install()
    return config
