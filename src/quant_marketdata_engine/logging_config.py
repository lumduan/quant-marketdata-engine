"""Structured logging setup.

A single :func:`configure_logging` call wires the root logger to emit
single-line, level-prefixed records on stderr. Never log secrets (the tvkit
cookie, API keys) — modules use ``%``-formatting so interpolation is deferred.
"""

from __future__ import annotations

import logging

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once (idempotent).

    Args:
        level: Logging level name (e.g. ``"INFO"``, ``"DEBUG"``).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(level=level.upper(), format=_FORMAT)
    _CONFIGURED = True
