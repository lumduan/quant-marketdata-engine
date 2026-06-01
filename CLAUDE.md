# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this
repository.

## Project

`quant-marketdata-engine` is the platform's **Market Data Engine** — a standalone
`EXTERNAL` engine that is the **single canonical producer of OHLCV** and the **sole owner
of the TradingView (tvkit) auth cookie**. It is a FastAPI service on container port `:8000`
(host port `:8300`) that joins the external **`quant-network`** and is **proxied by
`quant-api-gateway`** under `/api/v2/engines/market-data/*`. It writes the canonical
`market_data.*` tables in `quant-infra-db` (TimescaleDB) and ships its **own Redis
sidecar** (hot-window cache + single-flight fetch lock).

> **Current state: docs-and-scaffold only.** There is **no** fetch, storage, read-API, or
> Redis code yet. The build-out is sequenced in
> [`docs/plans/ROADMAP.md`](docs/plans/ROADMAP.md) (Phase 2+) and is gated on the **Phase 0
> ADR** (the umbrella `.claude/knowledge/feature-market-data-engine.md`).

### Ownership boundaries (the whole point of this service)

1. **Sole tvkit-cookie owner.** Only this service holds `TVKIT_AUTH_TOKEN`. No strategy,
   no gateway, and no host fetches tvkit or holds the cookie.
2. **Canonical OHLCV producer.** It fetches once and idempotently upserts raw bars +
   corporate actions / roll dates into `quant-infra-db`. The DB is the source of truth;
   Parquet is a derived snapshot cache.
3. **Gateway-proxied.** Consumers (strategies, OpenBB) call the gateway's
   `/api/v2/engines/market-data/*`; the gateway proxies to `:8300`. The gateway holds **no**
   credential.
4. **Strategies are read-only.** `csm-set` and `tfex-s50-multi-tf-swing` **read** the store
   and **never fetch tvkit**. Raw OHLCV is private-side only (the read API is auth-gated).

## Tech stack

FastAPI / Python 3.11, `uv`-managed, async-first. TimescaleDB (via `quant-infra-db`) for
the canonical store; an own Redis sidecar for the hot-window cache + single-flight lock;
tvkit for TradingView access; Parquet (PyArrow) for the derived backtest snapshot.

## Network & ports (`quant-network`)

| Item | Value |
|---|---|
| Service hostname (in-container) | `quant-marketdata-engine` |
| Container port | `:8000` (always — like every other service) |
| Host port | `:8300` |
| Health check | `curl http://localhost:8300/health` *(once the FastAPI app lands, Phase 2)* |
| Canonical DB | `quant-postgres:5432` (TimescaleDB, `market_data.*`) |
| Own Redis sidecar | in this repo's compose (distinct from the gateway's Redis) |

Use **service hostnames inside containers**, not `localhost`. Host ports exist only for
developer access. This service is **registered in the umbrella `CLAUDE.md`** (repo/remote
table, Docker network contract, engine catalog, bring-up order, health checks, per-service
quick reference) as of the Phase 0 ADR (2026-06-01). The ADR is the source of truth for the
architecture decisions: [`../.claude/knowledge/feature-market-data-engine.md`](../.claude/knowledge/feature-market-data-engine.md)
(see ROADMAP §0.3/§0.4).

## Commands

Everything runs through `uv`. Never call `python` / `pip` / `poetry` / `conda` directly.

```bash
uv sync --all-groups                                  # install deps (incl. dev)
uv run pytest                                         # full test suite + coverage gate
uv run pytest tests/test_main.py -v                   # a single test file
uv run ruff check .                                   # lint
uv run ruff format --check .                          # format check (passive)
uv run mypy src tests                                 # strict type check
uv run python -m src.quant_marketdata_engine.main     # run the scaffold entrypoint
```

Combined quality gate (must pass before every push, matching CI):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

Docker (compose lands in Phase 2):

```bash
docker compose up                                                     # public mode, host :8300
docker compose -f docker-compose.yml -f docker-compose.private.yml up # owner/ingest mode (cookie)
```

## Quality gates

`ruff` (E, F, I, UP, B, SIM) · `mypy --strict` · `pytest` with **≥90% coverage on core
modules** (`--cov-fail-under=90`), enforced in CI and `pyproject.toml`. Pre-commit hooks
run ruff-check / ruff-format / mypy.

## Bring-up order (relative to infra-db & gateway)

```
quant-infra-db          # creates quant-network + TimescaleDB (must be first)
quant-marketdata-engine # this service + its own Redis sidecar  (host :8300)
quant-api-gateway       # proxies /api/v2/engines/market-data/* → :8300
strategies (csm-set, tfex-s50-multi-tf-swing)   # read-only consumers
quant-openbb            # v2 proxy panels
```

Tear down in reverse; only `quant-infra-db` down removes `quant-network`.

## Hard rules — service-specific

1. **The tvkit cookie lives only here.** `TVKIT_AUTH_TOKEN` is a JSON cookie string (NOT a
   JWT), required key `sessionid`. It is read from a **gitignored** `.env` (or a gitignored
   `.tmp/` file). **Never commit it; never log it.** See
   [`.claude/playbooks/development-workflow.md`](.claude/playbooks/development-workflow.md)
   for safe injection (`"$(cat file)"`, never `set -a`).
2. **Store raw; adjust on read.** Persist raw/unadjusted bars + `corporate_actions` (and
   futures roll dates). Adjusted/continuous series are views / continuous aggregates, never
   cached as the source of truth (D2/D10).
3. **Futures `1d` = settlement, never a rollup of intraday bars** (D10). Carry
   `open_interest` from day one (NULL for equities).
4. **Idempotent writes.** All upserts are `ON CONFLICT (symbol, timeframe, ts) DO UPDATE`;
   re-running an ingest is a no-op for unchanged bars.
5. **Single-flight fetches.** Dedupe concurrent identical fetches on
   `(symbol, timeframe, range)` via the own Redis sidecar so TradingView is hit once.
6. **Read API is private/auth-gated.** Raw OHLCV never crosses the public-data boundary.

## Hard rules — inherited from the umbrella

1. **Always `uv run`** — never bare `python` / `pip` / `poetry` / `conda`.
2. **Async-first I/O** — all HTTP via `httpx.AsyncClient`. `requests` is forbidden in
   `src/` (it blocks the event loop).
3. **Pydantic at boundaries** — module/external I/O goes through Pydantic models, never raw
   dicts.
4. **Monetary values are `Decimal`, never `float`,** at boundaries; serialise as strings on
   the wire. OHLC prices are `numeric(18,6)` in the DB.
5. **Timezone:** store UTC, display `Asia/Bangkok`. `ts` is the **bar-open** time, in UTC.
6. **No secrets in repo.** All config via env + `pydantic-settings`, prefix
   `MARKETDATA_ENGINE_*` (plus the shared, unprefixed `TVKIT_AUTH_TOKEN`).
7. **Ingestion is idempotent** (see service rule 4).
8. **`docs/plans/` is git-tracked.** The roadmap is part of the product — never gitignore it.

## Coding conventions worth knowing up front

- `from __future__ import annotations` at the top of every `src/` module.
- Module-local exceptions in each subpackage's `errors.py`, inheriting a shared base.
  Never `raise Exception(...)` or `except Exception: pass`.
- `logger = logging.getLogger(__name__)` — never `print` in `src/`; `%`-formatting in logs.
- File-size target ≤ 400 lines; functions ≤ ~50 lines.
- Tests mirror the source layout under `tests/`; `asyncio_mode = "auto"`.

## Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
`docs:`, `test:`, `chore:`, `refactor:`. Keep scope tight
(`feat(ingest): single-flight fetch lock`, `docs(plans): add Phase 2 detail`).

## Where to look next

- **Roadmap (canonical source of truth for what to build next):**
  [`docs/plans/ROADMAP.md`](docs/plans/ROADMAP.md)
- **Domain knowledge (request flow, multi-TF storage, cookie contract, schema touchpoints):**
  [`.claude/knowledge/market-data-engine.md`](.claude/knowledge/market-data-engine.md)
- **Development playbook (bring-up, gates, safe tvkit testing, PR sequence):**
  [`.claude/playbooks/development-workflow.md`](.claude/playbooks/development-workflow.md)
- **Umbrella feature roadmap + design docs:**
  [`../plans/feature-market-data-engine/ROADMAP.md`](../plans/feature-market-data-engine/ROADMAP.md),
  `request-flow.md`, `multi-timeframe-storage.md`, `quant-infra-db-changes.md`
- **Umbrella system map (engine catalog, ingestion contract, network contract):**
  [`../CLAUDE.md`](../CLAUDE.md)
- **tvkit auth + bulk-fetch method:** umbrella agent memory `reference-tvkit-tradingview-auth`
