"""Package-root exception base.

Every subpackage defines its own ``errors.py`` whose exceptions inherit from
:class:`MarketDataEngineError`, so callers can catch one project-local base.
"""

from __future__ import annotations


class MarketDataEngineError(Exception):
    """Base for every error raised inside ``quant_marketdata_engine``."""
