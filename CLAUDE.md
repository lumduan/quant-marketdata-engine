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

> **Current state: live (Phase 5 in progress, 2026-06-02).** The service is a running FastAPI
> app — read API (`GET /health`, `/ohlcv`, `/ohlcv/adjusted`, `/universe`) + owner-mode
> `POST /admin/ingest`, an own Redis sidecar (hot-window cache + single-flight lock), the
> asyncpg layer over `db_market_data`, the tvkit ingest path (CLI + admin endpoint), and the
> Parquet snapshot exporter. The read path is **hot/warm** (Redis → DB → write-through);
> cold-path auto-fetch-on-read is deferred (the single-flight primitive is built).
> **Phase 3 (reader cutover — csm-set) is complete** (2026-06-01); **Phase 4 (reader cutover
> — tfex-s50-multi-tf-swing) is complete** (2026-06-02). **Phase 5 (end-to-end verification &
> cutover) is in progress** — verification plan, scripts, and unit tests built
> (`docs/plans/phase5-end-to-end-verification-cutover.md`, `tests/verification/`); live Tier 1
> verification + cutover pending. **Phase 6 (documentation — tvkit-ref style,
> AI-agent-first) is planned.** See [`docs/plans/ROADMAP.md`](docs/plans/ROADMAP.md).

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
| Health check | `curl http://localhost:8300/health` (live; returns DB + Redis + cookie-presence) |
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
uv run uvicorn src.quant_marketdata_engine.api.main:app --port 8000   # run the read API
# Owner-mode ingest (needs MARKETDATA_ENGINE_PUBLIC_MODE=false + TVKIT_AUTH_TOKEN):
uv run python -m src.quant_marketdata_engine.ingest fetch --symbol SET:PTT --timeframe 1d --bars 5000
uv run python -m src.quant_marketdata_engine.ingest backfill --dir ../strategies/csm-set/data/raw/dividends
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

### Documentation standards (Phase 6)

- Every new public API endpoint must include a curl example in `docs/api/` (planned or
  written).
- The `docs/` directory follows the tvkit 7-category layout (`getting-started/`,
  `concepts/`, `guides/`, `reference/`, `architecture/`, `data/`, `operations/`).
- All planned doc files are listed in the [Documentation](#documentation) section below
  with `(TODO: Phase 6)` suffix until created.
- Cross-references use project-relative paths (e.g. `docs/architecture/overview.md`) or
  GitHub absolute paths for external repos.
- Every ADR must carry a date and status.
- AI-agent context files (`.claude/knowledge/`, `.claude/playbooks/`) must be refreshed
  whenever a phase completes.

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

## Documentation

### Repo-level Docs

| File | Summary |
|------|---------|
| [`README.md`](README.md) | Service overview, architecture diagram, quickstart, env vars |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history by phase |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Dev workflow, quality gates, PR process |
| [`SECURITY.md`](SECURITY.md) | Vulnerability reporting |
| [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) | Community standards |
| [`LICENSE`](LICENSE) | MIT license |

### docs/ — Architecture (TODO: Phase 6)

| File | Summary |
|------|---------|
| `docs/architecture/overview.md` (TODO: Phase 6) | System topology, component interaction, data flow |
| `docs/architecture/data-model.md` (TODO: Phase 6) | Schema, PKs, indexes, CAGGs, compression policy |
| `docs/architecture/security-boundary.md` (TODO: Phase 6) | Auth gate, cookie ownership, public-data boundary |

### docs/ — API Reference (TODO: Phase 6)

| File | Summary |
|------|---------|
| `docs/api/ohlcv.md` (TODO: Phase 6) | GET /ohlcv — raw bars request/response with curl examples |
| `docs/api/ohlcv-adjusted.md` (TODO: Phase 6) | GET /ohlcv/adjusted — adjust-on-read view |
| `docs/api/universe.md` (TODO: Phase 6) | GET /universe — as-of dated constituents |
| `docs/api/health.md` (TODO: Phase 6) | GET /health — health check response shape |
| `docs/api/admin-ingest.md` (TODO: Phase 6) | POST /admin/ingest — owner-mode ingest endpoint |

### docs/ — Operations (TODO: Phase 6)

| File | Summary |
|------|---------|
| `docs/operations/bring-up.md` (TODO: Phase 6) | Service bring-up order, compose files, network prerequisites |
| `docs/operations/configuration.md` (TODO: Phase 6) | All `MARKETDATA_ENGINE_*` env vars, public vs owner mode |
| `docs/operations/monitoring.md` (TODO: Phase 6) | Health checks, logging, alerting |
| `docs/operations/troubleshooting.md` (TODO: Phase 6) | Common issues: cookie expiry, DB connection, Redis sidecar |
| `docs/operations/scheduled-ingest.md` (TODO: Phase 6) | Cron/scheduler setup, idempotency guarantees |

### docs/ — Data (TODO: Phase 6)

| File | Summary |
|------|---------|
| `docs/data/ohlcv-schema.md` (TODO: Phase 6) | OHLCV table schema, PK, constraints, compression, retention |
| `docs/data/corporate-actions.md` (TODO: Phase 6) | Corporate actions table, roll dates, adjust-on-read math |
| `docs/data/universe-membership.md` (TODO: Phase 6) | As-of dated constituents, point-in-time correctness |
| `docs/data/parquet-snapshot.md` (TODO: Phase 6) | Parquet backtest cache, export format, offline usage |

### docs/ — Getting Started (TODO: Phase 6)

| File | Summary |
|------|---------|
| `docs/getting-started/quickstart.md` (TODO: Phase 6) | 5-minute setup: clone → env → compose up → health check |
| `docs/getting-started/local-development.md` (TODO: Phase 6) | Full local dev env, test data, mocking tvkit |
| `docs/getting-started/public-vs-owner-mode.md` (TODO: Phase 6) | Running in public read-only vs owner ingest mode |

### docs/ — Concepts (TODO: Phase 6)

| File | Summary |
|------|---------|
| `docs/concepts/adjust-on-read.md` (TODO: Phase 6) | Why raw + corporate actions, not cached adjusted series |
| `docs/concepts/single-flight-fetch.md` (TODO: Phase 6) | Deduping concurrent identical fetches via Redis lock |
| `docs/concepts/tvkit-cookie-ownership.md` (TODO: Phase 6) | Why only this service holds the cookie |
| `docs/concepts/continuous-vs-per-contract.md` (TODO: Phase 6) | S501! continuous, dated contracts, roll back-adjustment |

### docs/ — Reference (TODO: Phase 6)

| File | Summary |
|------|---------|
| `docs/reference/settings.md` (TODO: Phase 6) | All settings with defaults, types, descriptions |
| `docs/reference/docker-compose-reference.md` (TODO: Phase 6) | Compose file structure, network, volumes, healthchecks |
| `docs/reference/gateway-proxy-contract.md` (TODO: Phase 6) | Proxy URL mapping, timeout/error code mapping |
| `docs/reference/error-codes.md` (TODO: Phase 6) | All typed error codes and user-facing messages |

### docs/ — Guides (TODO: Phase 6)

| File | Summary |
|------|---------|
| `docs/guides/adding-a-new-reader.md` (TODO: Phase 6) | How to add a new strategy as a reader of the engine |
| `docs/guides/tvkit-token-rotation.md` (TODO: Phase 6) | Cookie refresh/renewal procedure |

### docs/ — Plans (tracked)

| File | Summary |
|------|---------|
| [`docs/plans/ROADMAP.md`](docs/plans/ROADMAP.md) | Canonical build roadmap, all phases |
| [`docs/plans/phase0-adr-repo-bootstrap.md`](docs/plans/phase0-adr-repo-bootstrap.md) | Phase 0: ADR + repo bootstrap detail |
| [`docs/plans/phase1-quant-infra-db-market-data-schema.md`](docs/plans/phase1-quant-infra-db-market-data-schema.md) | Phase 1: shared market_data schema |
| [`docs/plans/phase2-service-build-and-gateway-proxy.md`](docs/plans/phase2-service-build-and-gateway-proxy.md) | Phase 2: service build + gateway proxy |
| [`docs/plans/phase3-csm-set-read-from-store.md`](docs/plans/phase3-csm-set-read-from-store.md) | Phase 3: csm-set reads from store |
| [`docs/plans/phase4-tfex-consume-shared-store.md`](docs/plans/phase4-tfex-consume-shared-store.md) | Phase 4: tfex consumes shared store |

### .claude/ — Knowledge

| File | Summary |
|------|---------|
| [`.claude/knowledge/market-data-engine.md`](.claude/knowledge/market-data-engine.md) | Domain knowledge: request flow, TF storage, cookie contract |
| [`.claude/knowledge/architecture.md`](.claude/knowledge/architecture.md) | Service architecture notes |
| [`.claude/knowledge/coding-standards.md`](.claude/knowledge/coding-standards.md) | Python coding conventions |
| [`.claude/knowledge/commands.md`](.claude/knowledge/commands.md) | Common CLI commands reference |
| [`.claude/knowledge/stack-decisions.md`](.claude/knowledge/stack-decisions.md) | Technology stack decisions |
| [`.claude/knowledge/project-skill.md`](.claude/knowledge/project-skill.md) | Project-level skill definition |
| `.claude/knowledge/data-flow.md` (TODO: Phase 6) | Read/write paths, cache hierarchy, single-flight lock |
| `.claude/knowledge/deployment.md` (TODO: Phase 6) | Compose topology, host ports, env var reference |
| `.claude/knowledge/api-contract.md` (TODO: Phase 6) | Full request/response shape, error codes, status codes |

### .claude/ — Playbooks

| File | Summary |
|------|---------|
| [`.claude/playbooks/development-workflow.md`](.claude/playbooks/development-workflow.md) | Bring-up, gates, safe tvkit testing, PR sequence |
| [`.claude/playbooks/bugfix-workflow.md`](.claude/playbooks/bugfix-workflow.md) | Bug investigation and fix process |
| [`.claude/playbooks/code-review.md`](.claude/playbooks/code-review.md) | Code review checklist |
| [`.claude/playbooks/dependency-upgrade.md`](.claude/playbooks/dependency-upgrade.md) | Dep upgrade process |
| [`.claude/playbooks/feature-development.md`](.claude/playbooks/feature-development.md) | Feature dev workflow |
| [`.claude/playbooks/release-checklist.md`](.claude/playbooks/release-checklist.md) | Release checklist |
| `.claude/playbooks/docs-workflow.md` (TODO: Phase 6) | How to add a doc, cross-ref rules, review process |
| `.claude/playbooks/data-refresh.md` (TODO: Phase 6) | Trigger full historical refresh, monitor, verify integrity |
| `.claude/playbooks/troubleshooting.md` (TODO: Phase 6) | Common failure modes: cookie expiry, Redis OOM, 502s |

### .claude/ — Memory

| File | Summary |
|------|---------|
| [`.claude/memory/anti-patterns.md`](.claude/memory/anti-patterns.md) | Anti-patterns learned |
| [`.claude/memory/lessons-learned.md`](.claude/memory/lessons-learned.md) | Lessons learned |
| [`.claude/memory/recurring-bugs.md`](.claude/memory/recurring-bugs.md) | Recurring bug patterns |
| `.claude/memory/cookie-management.md` (TODO: Phase 6) | tvkit token refresh schedule, expiry, debugging auth |

### Umbrella cross-references

| File | Summary |
|------|---------|
| [`../CLAUDE.md`](../CLAUDE.md) | Umbrella system map, engine catalog, network contract |
| [`../.claude/knowledge/feature-market-data-engine.md`](../.claude/knowledge/feature-market-data-engine.md) | Umbrella ADR: architecture decisions D1–D10 |
| [`../.claude/knowledge/feature-market-data-engine-reader-cutover.md`](../.claude/knowledge/feature-market-data-engine-reader-cutover.md) | Strategy cutover decisions (Phase 3/4) |
| [`../plans/feature-market-data-engine/ROADMAP.md`](../plans/feature-market-data-engine/ROADMAP.md) | Umbrella feature roadmap |

## Where to look next

- **Documentation index (every file, planned and written):** see [Documentation](#documentation)
  above
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
