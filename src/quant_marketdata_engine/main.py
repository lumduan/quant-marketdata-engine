"""Placeholder entrypoint.

This service is currently a docs-and-scaffold bootstrap: there is **no** market-data
fetching, storage, read API, or Redis logic yet. The build-out (FastAPI app on
container ``:8000`` / host ``:8300``, tvkit ingest, TimescaleDB upsert, read API, own
Redis sidecar) is sequenced in ``docs/plans/ROADMAP.md`` starting at Phase 2.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info(
        "quant-marketdata-engine scaffold — no application logic yet; "
        "see docs/plans/ROADMAP.md (Phase 2+)"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
