# Phase 2: Service Build + Gateway Proxy Route

**Feature:** feature-market-data-engine — Phase 2: `quant-marketdata-engine` service build + gateway proxy
**Branch (this repo):** `feat/phase2-service-build`
**Sibling branch (gateway):** `quant-api-gateway` → `feat/market-data-engine-proxy`
**Sibling branch (umbrella):** `quant-trading-system` → `docs/market-data-phase2`
**Created:** 2026-06-01
**Status:** In progress
**Depends On:** Phase 0 (ADR + bootstrap, complete) · Phase 1 (`quant-infra-db` shared `market_data` schema, complete)

---

## Table of Contents

1. [Overview](#overview)
2. [Originating prompt](#originating-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [ADR decisions implemented](#adr-decisions-implemented)
6. [Implementation Steps](#implementation-steps)
7. [File Changes](#file-changes)
8. [HTTP surface](#http-surface)
9. [DB / schema touchpoints](#db--schema-touchpoints)
10. [Test strategy & coverage](#test-strategy--coverage)
11. [Rollout / bring-up impact](#rollout--bring-up-impact)
12. [Success Criteria](#success-criteria)
13. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 2 is the **first phase that writes application code in this repo.** It stands
`quant-marketdata-engine` up as a live FastAPI service over the Phase-1 shared `market_data`
schema (new `db_market_data` DB in `quant-infra-db`), ships its own Redis sidecar + Docker
compose, and wires `quant-api-gateway` to **proxy** `/api/v2/engines/market-data/*` to it —
flipping the catalogued Market Data engine from `EXTERNAL stub` to **active**.

This service is the **sole owner of the tvkit cookie** and the **single canonical OHLCV
producer**: it fetches once, idempotently upserts raw bars + corporate actions into
`market_data.*`, and serves a private/auth-gated read API. Strategies and OpenBB read
through the gateway proxy; they never hold the cookie and never call TradingView.

### Parent plan references

- Per-service roadmap (scope of record): [`ROADMAP.md`](ROADMAP.md) §"Phase 2"
- Umbrella feature roadmap: [`../../../plans/feature-market-data-engine/ROADMAP.md`](../../../plans/feature-market-data-engine/ROADMAP.md)
- ADR (D1–D10, read contract): [`../../../.claude/knowledge/feature-market-data-engine.md`](../../../.claude/knowledge/feature-market-data-engine.md)
- Design notes: `request-flow.md`, `multi-timeframe-storage.md`, `quant-infra-db-changes.md`
- Per-service domain knowledge: [`../../.claude/knowledge/market-data-engine.md`](../../.claude/knowledge/market-data-engine.md)

### Key deliverables

1. FastAPI read API on container `:8000` (host `:8300`): `/health`, `/ohlcv`, `/ohlcv/adjusted`, `/universe`, `/admin/ingest`.
2. Own asyncpg DB layer over `db_market_data` (models + pool + repositories incl. adjusted view + CAGG routing).
3. Own Redis sidecar layer: hot-window write-through cache + single-flight lock primitive.
4. Ingest side (sole tvkit-cookie owner): `tvkit_client`, ingest `service`, `cli`, best-effort `backfill`.
5. Parquet snapshot exporter (DB → columnar, offline backtest path).
6. Docker compose (public-safe) + `.private.yml` overlay (owner/ingest with cookie).
7. **Gateway PR:** httpx proxy route + catalog `active`.
8. Docs/knowledge/memory updates across this repo + umbrella.

---

## Originating prompt

> The following prompt initiated this phase (verbatim):

```
Task: Implement Phase 2 of `feature-market-data-engine` — build the `quant-marketdata-engine` service + add the gateway proxy route

You are working in the `quant-trading-system` umbrella repo (multi-repo workspace).
`quant-marketdata-engine/`, `quant-api-gateway/`, and `quant-infra-db/` are each
INDEPENDENT git repos with their own remotes — never edit one repo's history from
another. Do per-service work inside that sub-repo, on its own branch, with its own PR.

## Step 0 — Read before doing anything (do NOT skip, do NOT assume)
Read and internalize these, in order, before writing any plan or code:
1. `CLAUDE.md` (umbrella system map, engine catalog, Docker network contract, ingestion contract, cross-cutting rules)
2. `plans/feature-market-data-engine/ROADMAP.md` (umbrella roadmap — this is where you tick the Phase 2 checkmarks when done)
3. `plans/feature-market-data-engine/request-flow.md`, `plans/feature-market-data-engine/multi-timeframe-storage.md`,
`plans/feature-market-data-engine/quant-infra-db-changes.md` (design specs Phase 2 must honor)
4. `quant-marketdata-engine/docs/plans/ROADMAP.md` (the authoritative per-repo roadmap — Phase 2 scope of record)
5. `quant-marketdata-engine/CLAUDE.md` (service quality gate: FastAPI / Python 3.11, `uv`, ruff, mypy **strict**, pytest ≥90% on core modules)
6. `.claude/knowledge/feature-market-data-engine.md` (the ADR — D1–D10 accepted decisions; Phase 2 must not contradict them)
7. `quant-api-gateway/CLAUDE.md` and the existing `/api/v2/engines/*` router code (you will add the market-data proxy route here)
8. `strategies/csm-set/docs/plans/examples/phase1-sample.md` (the exact format your plan file must follow)

If, after reading, the actual Phase 2 scope in `quant-marketdata-engine/docs/plans/ROADMAP.md`
diverges from the summary below, the ROADMAP wins — reconcile and call out the delta in your plan.

## Step 1 — Plan before code (mandatory gate)
Write the implementation plan FIRST, before touching any application code, and save it to:
`quant-marketdata-engine/docs/plans/{phase_name}.md`
where `{phase_name}` matches the Phase 2 slug used in `quant-marketdata-engine/docs/plans/ROADMAP.md`
(e.g. `phase2-service-build-and-gateway-proxy.md`).

The plan file MUST:
- Follow the structure of `strategies/csm-set/docs/plans/examples/phase1-sample.md`.
- Embed THIS prompt verbatim in a section near the top (e.g. "## Originating prompt").
- Enumerate: objective, scope (in/out), the ADR decisions it implements, file-by-file change list across BOTH repos, the new `market_data` DB / schema
touchpoints (read-side this phase), the public HTTP surface, test strategy + coverage target, rollout/bring-up impact, and a checklist mirroring the ROADMAP
items it closes.
- Explicitly mark which work lands in `quant-marketdata-engine` vs `quant-api-gateway` (two repos → likely two PRs).

## Step 2 — Branches (one per repo you touch)
Create a fresh feature branch in each sub-repo you modify (do NOT work on `main`):
- In `quant-marketdata-engine/`: e.g. `feat/phase2-service-build`
- In `quant-api-gateway/`: e.g. `feat/market-data-engine-proxy`
- In the umbrella repo: e.g. `docs/market-data-phase2` (for roadmap checkmarks + knowledge updates)

## Step 3 — Implement Phase 2 (`quant-marketdata-engine` service build)
Build the standalone engine per the ROADMAP and ADR. At minimum (reconcile against the ROADMAP):
- FastAPI app on internal `:8000` (host `:8300`), with its own Redis sidecar, joining `quant-network` (`external: true`).
- The OHLCV ingest path (settfex + tvkit) — the service is the **sole tvkit-cookie owner**; the cookie comes from `.env` only, is NEVER committed, NEVER
logged, and is validated at startup.
- The read API serving canonical OHLCV from the shared `market_data` schema in the new `db_market_data` DB (Phase 1 shipped the schema — connect read-side;
honor multi-timeframe storage design).
- `GET /health` (and readiness) returning DB + Redis + cookie-presence status.
- Flip the engine state the catalog reports from `EXTERNAL stub` → `active` per the ADR (only once the read path genuinely works).

Engineering quality bar (non-negotiable, this repo is mypy **strict** / pytest ≥90% on core):
- Full type annotations; passes `uv run mypy` in strict mode. Use `uv run` for ALL commands (never bare `python`/`pip`).
- Async-correct DB and HTTP I/O (no blocking calls in async paths; bounded connection pools; proper timeouts on tvkit/settfex fetches; retry/backoff with
caps).
- Comprehensive error handling + structured logging (no secrets in logs); typed error responses.
- Monetary/price values handled with `Decimal` at boundaries where the contract requires; store UTC, display Asia/Bangkok; tz-aware end-to-end.
- Input validation on all request params (symbol, timeframe, date range) — reject malformed/oversized ranges; OWASP-aware (no injection via symbol/timeframe).
- Idempotent ingestion (`INSERT … ON CONFLICT`) consistent with the platform's ingestion contract.
- Unit + integration tests; mock tvkit/external network; cover the read API, health, validation, and error paths to ≥90% on core modules.
- Backward compatibility: do not break existing `/api/v2/engines/market-data/*` stub consumers — evolve, don't surprise. Note any migration impact.
- Performance: index-aware queries against the multi-timeframe layout; flag any obvious N+1 or unbounded scan; cache hot reads via the Redis sidecar where the
ADR allows.

## Step 4 — Gateway proxy route (`quant-api-gateway`)
Add/finalize the proxy so the gateway forwards `/api/v2/engines/market-data/*` to
`http://quant-marketdata-engine:8000` (Docker service name, not localhost):
- Reuse the gateway's existing engine-proxy pattern; async httpx client with timeouts, connection reuse, and graceful upstream-down handling (clear 502/503,
not a stack trace).
- Update the engine catalog entry so it reflects `active` (or the exact state the ADR mandates for Phase 2).
- Meet the gateway's quality gate (ruff, mypy **strict**, pytest ≥90%); add tests for the proxy (success, upstream error, timeout).

## Step 5 — Docs / knowledge / memory updates (create or update as needed)
- Tick the completed Phase 2 items in BOTH `plans/feature-market-data-engine/ROADMAP.md` (umbrella) and `quant-marketdata-engine/docs/plans/ROADMAP.md`.
- Update `quant-marketdata-engine/CLAUDE.md` and `quant-marketdata-engine/.claude/*` with anything newly true (run commands, env vars, endpoints, cookie
handling playbook, test invocation).
- Update the umbrella `CLAUDE.md` (engine catalog status, Docker network contract, bring-up order, health checks) and
`.claude/knowledge/feature-market-data-engine.md` / relevant `.claude/*` to mark the service live and record any decisions made during the build.
- If any cross-repo workflow emerged (e.g. bring infra-db → marketdata-engine → gateway), capture it as/within a `.claude/playbooks/*` entry.

## Step 6 — Verify locally before pushing (CI-equivalent gate)
In each touched repo, run the full gate and paste results into the PR description:
`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
(Any post-format edit/`sed` invalidates formatting — re-run `ruff format --check` last.)
Bring the stack up in order and curl the health endpoints to prove the proxy path works end-to-end:
`docker compose up -d` infra-db → marketdata-engine → gateway, then
`curl http://localhost:8300/health` and `curl http://localhost:8000/api/v2/engines/market-data/...`.

## Step 7 — Commit + PR (per repo)
Commit logically-scoped changes and open a PR for EACH repo you modified
(`quant-marketdata-engine`, `quant-api-gateway`, umbrella). In each PR body:
- Summarize scope, link the plan file, list the ROADMAP items closed, and paste the green quality-gate output.
- Cross-link the sibling PRs and state the required merge/bring-up order.
- End commit messages with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- End PR bodies with: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`

## Guardrails
- Treat the plan as a hard gate: do not write application code until `quant-marketdata-engine/docs/plans/{phase_name}.md` exists and reflects the real ROADMAP
scope.
- Never commit the tvkit cookie or any secret; secrets live only in each repo's gitignored `.env`.
- Stay within Phase 2 scope — if you discover work that belongs to a later phase, note it in the plan, don't build it.
- If a critical decision is genuinely ambiguous after reading the ADR + ROADMAPs, stop and ask rather than guessing.
```

### Clarifications resolved with the user before coding

- **Read-path scope = hot/warm only.** Read API resolves Redis → DB → write-through. A
  separate ingest path populates the DB. The **cold path** (auto-fetch-on-miss) is
  scaffolded (single-flight lock primitive built) but on-read auto-ingest is **deferred**
  to a follow-up — matches the ROADMAP exit criterion "one ingest run populates the DB".
- **Ingest trigger = CLI module + owner-mode admin endpoint** (`python -m
  quant_marketdata_engine.ingest` + `POST /admin/ingest`). **No APScheduler** (Phase 5).
- **Execution = build + verify locally, stop before pushing/PRs** (user reviews diff first).
- **Backfill** = best-effort, owner-mode, idempotent CLI that no-ops when source data absent.
- **Snapshot exporter** = included. **tvkit fetch** = fully mocked in tests.

---

## Scope

### In scope (Phase 2 — this repo unless marked GATEWAY)

| Component | Description |
|---|---|
| Dependencies | fastapi, uvicorn, asyncpg, redis, httpx, pydantic-settings, tvkit, pyarrow |
| `config/` | `pydantic-settings` Settings (`MARKETDATA_ENGINE_*` + `TVKIT_AUTH_TOKEN`) |
| `db/` | asyncpg pool + row models + repositories over `db_market_data` (read-side + ingest upserts) |
| `cache/` | own Redis: write-through hot cache + single-flight lock primitive |
| `ingest/` | tvkit client (sole cookie owner), ingest service, CLI, best-effort backfill |
| `api/` | FastAPI read API + owner-mode admin ingest endpoint |
| `snapshot/` | DB → Parquet exporter |
| plumbing | docker-compose (+private overlay), Dockerfile CMD, .dockerignore |
| tests | ≥90% on core (`ingest/`, `api/`, `db/`, `cache/`, `snapshot/`) |
| **GATEWAY** | httpx proxy route `/api/v2/engines/market-data/*`; catalog `active`; proxy tests |
| docs | both ROADMAPs, both CLAUDE.md, knowledge, ADR note, playbook, memory |

### Out of scope (later phases — noted, not built)

- **Cold-path auto-fetch-on-read** (lock primitive built; on-read auto-ingest deferred).
- In-process scheduler / daily cron — **Phase 5**.
- Futures-roll back-adjustment math + `09` mirror retirement — **Phase 4**.
- csm-set `CSM_OHLCV_SOURCE = parquet|db` — **Phase 3**.
- Intraday lake / DuckDB — reserved (D5).
- `market_data.contract_specs` table — optional/future per ADR.

---

## Design Decisions

1. **Own DB code, not a shared package.** `quant-infra-db` is not pip-installable by other
   services (platform pattern: each service owns its connectivity). The engine reimplements
   `OHLCVBarRow`/`CorporateActionRow`/`UniverseMembershipRow` + the `market_data.*` upsert/fetch
   SQL, using `quant-infra-db/src/db/{models,repositories}.py` as the authoritative reference
   (same `ON CONFLICT (symbol,timeframe,ts) DO UPDATE`, `ingested_at` DB-defaulted).
2. **`/ohlcv/adjusted` reads the existing view.** Phase-1 `market_data.ohlcv_adjusted` already
   does equity split/dividend adjustment. Futures-roll parity is Phase 4, so Phase 2 does no
   roll math — it SELECTs the view (and routes 1h/4h to `cagg_ohlcv_*`, 5m/1d direct).
3. **Public mode is the safe default.** `MARKETDATA_ENGINE_PUBLIC_MODE=true` → read-only, no
   cookie, ingest refused. Owner mode (`false`, cookie present) enables ingest. The cookie is
   validated only when ingest runs, and never logged.
4. **Gateway proxy is a new outbound httpx pattern.** The gateway's "backtest engine" reads its
   own DB (not a proxy), so this introduces the gateway's first reverse-proxy route, mirroring the
   existing `csm_set_service_url` config convention. Upstream-down → clean 502/503/504.
5. **Hot/warm read resolution.** Redis hit → return; miss → DB (index-backed) → write-through →
   return. Redis failure degrades gracefully (DB still serves). Single-flight lock built for the
   deferred cold path and to serialise concurrent ingests of the same key.

## ADR decisions implemented

| ADR | How Phase 2 honors it |
|---|---|
| D1 TimescaleDB canonical | Engine reads/writes `db_market_data` (`quant-postgres:5432`). |
| D2 store raw + adjust-on-read | `/ohlcv` = raw rows; `/ohlcv/adjusted` = `ohlcv_adjusted` view. |
| D3 Parquet snapshot = cache | `snapshot/exporter.py` DB → Parquet (offline path). |
| D4 standalone engine + gateway proxy | This service + the gateway proxy route. |
| D5 lake only for heavy intraday | S50 stays in Timescale; no lake. |
| D7 own repo/service | All code in this repo; gateway stays thin. |
| D8 own Redis sidecar + single-flight | `cache/` over the engine's own Redis. |
| D10 Option A multi-TF + CAGGs | Read routes timeframe → base rows vs `cagg_ohlcv_*`. |
| §5 read contract | `api/schemas.py`: Decimal-as-string, UTC `ts`, `adjusted` default. |
| §6 `S501!` (b) back-adjusted | Read contract surfaces `adjusted` flag; roll math deferred to Phase 4. |

## Implementation Steps

See [File Changes](#file-changes). Build order: deps → config/errors/logging → db → cache →
ingest → api → snapshot → plumbing → tests → gateway proxy → docs → verify.

## File Changes

### `quant-marketdata-engine` (branch `feat/phase2-service-build`)

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | Add runtime deps; keep gates. `uv.lock` regenerated. |
| `src/quant_marketdata_engine/errors.py` | CREATE | Base `MarketDataEngineError`. |
| `src/quant_marketdata_engine/logging_config.py` | CREATE | Structured logging setup. |
| `src/quant_marketdata_engine/config/{__init__,settings}.py` | CREATE | `Settings` + `get_settings()`. |
| `src/quant_marketdata_engine/db/{__init__,errors,models,postgres,repositories}.py` | CREATE | asyncpg layer. |
| `src/quant_marketdata_engine/cache/{__init__,errors,redis_client,ohlcv_cache,single_flight}.py` | CREATE | Redis layer. |
| `src/quant_marketdata_engine/ingest/{__init__,errors,tvkit_client,service,cli,backfill}.py` | CREATE | Ingest side. |
| `src/quant_marketdata_engine/api/{__init__,main,deps,schemas,routes}.py` | CREATE | FastAPI app. |
| `src/quant_marketdata_engine/snapshot/{__init__,exporter}.py` | CREATE | Parquet export. |
| `src/quant_marketdata_engine/main.py` | MODIFY | Keep scaffold entry or delegate to uvicorn note. |
| `src/quant_marketdata_engine/__main__.py` / `ingest/__main__.py` | CREATE | `python -m …ingest`. |
| `docker-compose.yml` | CREATE | engine + own Redis, `quant-network`, host `:8300`, public defaults. |
| `docker-compose.private.yml` | CREATE | owner/ingest overlay (cookie env_file). |
| `.dockerignore` | MODIFY/CREATE | exclude `.env`, `.tmp/`, `data/`. |
| `Dockerfile` | MODIFY | CMD → uvicorn `src.quant_marketdata_engine.api.main:app`. |
| `tests/**` | CREATE | unit suite ≥90% on core. |
| `docs/plans/phase2-service-build-and-gateway-proxy.md` | CREATE | this file. |
| `docs/plans/ROADMAP.md`, `CLAUDE.md`, `.claude/knowledge/market-data-engine.md`, `.env.example` | MODIFY | mark live; record decisions. |

### `quant-api-gateway` (branch `feat/market-data-engine-proxy`)

| File | Action | Description |
|---|---|---|
| `src/config.py` | MODIFY | add `marketdata_engine_service_url` + timeout. |
| `src/api/v2/engines/market_data.py` | MODIFY | replace stub with httpx proxy (`/health`, `/ohlcv`, `/ohlcv/adjusted`, `/universe`). |
| `src/api/v2/engines/catalog.py` | MODIFY | market-data description reflects live engine (status `active`). |
| `tests/api/v2/test_engines.py` | MODIFY | proxy success / 5xx→502 / timeout→504 / param+header forwarding. |

### `quant-trading-system` umbrella (branch `docs/market-data-phase2`)

| File | Action | Description |
|---|---|---|
| `plans/feature-market-data-engine/ROADMAP.md` | MODIFY | tick Phase 2; mark cold-path/scheduler deferred. |
| `CLAUDE.md` | MODIFY | catalog Market Data → active; drop "live in Phase 2" qualifiers. |
| `.claude/knowledge/feature-market-data-engine.md` | MODIFY | Phase-2 realized-build note. |
| `.claude/playbooks/*` | MODIFY/CREATE | cross-repo bring-up + PR sequence. |

## HTTP surface

Engine (container `:8000`, host `:8300`) — private/auth-gated (`X-API-Key`) except `/health`:

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{status, db, redis, cookie_present}` (presence bool, never the value) |
| GET | `/ohlcv?symbol&timeframe&start&end&limit` | raw bars; Redis→DB→write-through |
| GET | `/ohlcv/adjusted?…` | adjust-on-read view; equity adj live |
| GET | `/universe?as_of&index_name` | as-of constituents |
| POST | `/admin/ingest` | owner-mode + API-key gated; body `{symbol,timeframe,start,end}` |

Gateway proxy (host `:8000`): `GET /api/v2/engines/market-data/{health,ohlcv,ohlcv/adjusted,universe}`
→ `http://quant-marketdata-engine:8000/...`.

Response per ADR §5: `{symbol, timeframe, adjusted, bars:[{ts, open, high, low, close, volume, open_interest}]}`,
all numerics `Decimal` serialised as strings, `ts` UTC.

## DB / schema touchpoints

Read-side over `db_market_data` (Phase-1 schema, no DDL this phase):
`market_data.ohlcv` (PK `(symbol,timeframe,ts)`, index `(symbol,timeframe,ts DESC)`),
`market_data.ohlcv_adjusted` (view), `cagg_ohlcv_1h`/`cagg_ohlcv_4h`,
`market_data.corporate_actions`, `market_data.universe_membership`.
Ingest writes via `ON CONFLICT … DO UPDATE` (idempotent). DSN: `MARKETDATA_ENGINE_PG_DSN`.

## Test strategy & coverage

Mock tvkit and external network; no live DB/Redis in unit tests (fakes/stubs). Cover:
models (Decimal/UTC/high≥low/enums), repositories (SQL builders + row mapping), cache
(write-through + degrade), single-flight, ingest service (idempotency, public-mode refusal,
tvkit error surfacing), backfill (fixture + absent-source no-op), exporter (round-trip), API
(health, ohlcv hot/warm, adjusted, universe, auth 401/403, validation 422, admin owner-mode
gating), config (cookie JSON validation, never-logged). **Target ≥90% on core modules.**
Gateway: proxy success, upstream 5xx→502/503, timeout→504, param + `X-API-Key` forwarding.

## Rollout / bring-up impact

Bring-up order unchanged: `quant-infra-db` → `quant-marketdata-engine` (+own Redis) →
`quant-api-gateway` → strategies → openbb. Public-mode default keeps the service safe without
the cookie. Backward-compatible: gateway `/api/v2/engines/market-data/health` still answers
(now via proxy with stub fallback semantics documented). No DB migration (Phase-1 schema reused).

## Success Criteria

Mirrors ROADMAP §"Phase 2" exit criteria:

- [ ] Service stands up on `quant-network` (FastAPI `:8000` / host `:8300`); `/health` healthy.
- [ ] Engine catalog status flips `EXTERNAL stub → active` (gateway).
- [ ] One ingest run populates `market_data.ohlcv` (idempotent re-run = no-op for unchanged bars).
- [ ] Gateway proxy returns both raw (`/ohlcv`) and adjusted (`/ohlcv/adjusted`) bars.
- [ ] Snapshot export round-trips (DB → Parquet → readable).
- [ ] Read API auth-gated; validation rejects bad symbol/timeframe/oversized range.
- [ ] Hot/warm: second identical read is a Redis hit; read survives Redis down.
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest` green, ≥90% core, both repos.
- [ ] No cookie/secret committed or logged.

## Completion Notes

_(filled in on completion)_
