"""``python -m src.quant_marketdata_engine.ingest`` entrypoint."""

from __future__ import annotations

from src.quant_marketdata_engine.ingest.cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(0 if main() >= 0 else 1)
