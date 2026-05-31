"""quant-marketdata-engine — canonical OHLCV store + sole tvkit-cookie owner.

Standalone EXTERNAL engine (host :8300, container :8000) proxied by
``quant-api-gateway``. This package is a **scaffold only** — the fetch, storage,
read-API, and Redis layers are sequenced in ``docs/plans/ROADMAP.md`` (Phase 2+)
and have not been implemented yet.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
