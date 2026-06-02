# quant-marketdata-engine Roadmap

The **Market Data Engine** — a single standalone service that is the **canonical
producer of OHLCV** for the whole quant platform and the **sole owner of the
TradingView (tvkit) auth cookie**. It runs on container port `:8000` (host `:8300`),
joins the external `quant-network`, and is **proxied by `quant-api-gateway`** under
`/api/v2/engines/market-data/*`. Strategies (`csm-set`, `tfex-s50-multi-tf-swing`, …)
**read** pre-fetched data from it and **never fetch tvkit themselves**.

Development phases are ordered by dependency — each phase must be complete and validated
before the next begins. The goal is **one fresh, correct, point-in-time store every
reader agrees on**, not a pile of per-strategy Parquet copies.

> **This service is a cross-cutting feature realised across repos.** This roadmap is the
> per-service decomposition of the umbrella feature roadmap
> [`../../../plans/feature-market-data-engine/ROADMAP.md`](../../../plans/feature-market-data-engine/ROADMAP.md).
> Phases here mirror the feature roadmap's cross-cutting phases; work that lands in a
> *different* repo (`quant-infra-db`, `quant-api-gateway`, the strategies) is called out
> as such and ships in that repo's own PR.
>
> **Status:** the whole feature is **Proposed / not started**, gated on the **Phase 0
> ADR**. This repo currently contains the **bootstrap scaffold only** — no fetch,
> storage, read-API, or Redis logic exists yet.

---

## Why build this

**In one line:** make this service the *only* thing that fetches market data and holds
the tvkit cookie, so every strategy reads pre-fetched data from one shared store and
never fetches tvkit itself.

The end-state this delivers:

- **One credential owner.** Only `quant-marketdata-engine` holds the tvkit cookie
  (`TVKIT_AUTH_TOKEN`). No strategy, no gateway, no host needs it anymore — blast radius
  shrinks from "every machine" to one service's gitignored `.env`.
- **Fetch once, read everywhere.** `csm-set` and `tfex` overlap heavily on SET symbols;
  today each re-pulls them, doubling premium-account load and rate-limit exposure. After
  this, data is fetched once and read by all strategies on any host.
- **Single source of truth.** Strategies can no longer disagree on the same day's close —
  one canonical store (`quant-infra-db`) instead of N per-strategy Parquet copies.
- **No more stale / mixed-date data.** Idempotent fetch scripts currently *skip* existing
  files, leaving some symbols stale and others fresh (observed 2026-05-29: index + ~445
  symbols stuck at 04-30 while others were at 05-29). A single upsert-driven producer ends
  this.

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]` | Not started |
| `[~]` | In progress |
| `[x]` | Complete |
| `[-]` | Skipped / deferred |

---

## Target Architecture

```
        tvkit (premium cookie)  +  settfex (symbol list / actions)
                         │   (owned ONLY by quant-marketdata-engine)
                         ▼
        ┌────────────────────────────────────────────────┐
        │  quant-marketdata-engine   (host :8300 / :8000)  │  EXTERNAL engine
        │   - fetch + idempotent upsert                    │
        │   - corporate-action / futures-roll ingest       │
        │   - read API  +  OWN Redis sidecar (hot window)  │
        └──────────┬───────────────────────▲─────────────┘
            writes │                        │ reads
                   ▼                        │
        quant-infra-db (TimescaleDB)  ← canonical store
          market_data.ohlcv             (RAW bars; PK symbol,timeframe,ts)
          market_data.corporate_actions (splits / dividends / roll dates)
          market_data.adjusted_view / CAGGs  (adjust-on-read, derived TFs)
          market_data.universe_membership (as-of, point-in-time)
                   ▲
                   │  GET /api/v2/engines/market-data/*   (PROXY)
        ┌──────────┴───────────────┐
        │  quant-api-gateway        │  thin proxy · NO tvkit cookie · Redis-cached
        └──────────┬───────────────┘
                   │                         ┌───────────────────────────┐
                   ▼                         ▼                           │
   strategies (csm-set, tfex, …)     quant-openbb (v2 proxy panels)      │
   + Parquet snapshot (derived cache, fast columnar backtest scans) ◄────┘
            read — they NEVER fetch tvkit
```

### Design principles (inherited from the feature roadmap)

1. **Store RAW + corporate actions; adjust on read.** Adjusted series change
   retroactively whenever a new action lands, so any cached adjusted bar is stale on the
   next action. Raw bars are immutable once closed; adjustment is a view / continuous
   aggregate.
2. **One producer owns the credential.** Only this service holds the tvkit cookie.
3. **DB is source of truth; Parquet is a derived cache** materialised from the DB for
   heavy historical backtest scans — not a parallel source.
4. **Point-in-time correctness.** `universe_membership` is as-of dated to prevent
   look-ahead / survivorship bias.
5. **Respect the public-data boundary.** Raw OHLCV is private-side only; the read API is
   private/auth-gated (preserves csm-set's `test_public_data_boundary_*`).
6. **Daily → TimescaleDB; heavy intraday → lake-first.** Daily volume is tiny. If
   intraday/tick volume explodes a Parquet/object-store lake (DuckDB) becomes the better
   canonical store. The intraday threshold is a Phase 0 decision (for S50 specifically the
   lake is **not** needed — ~13k rows/sym/yr).

---

## Decision Log (confirmed in the Phase 0 ADR)

These are the umbrella feature roadmap's D1–D10. They are **proposed** until the Phase 0
ADR merges; this roadmap restates them so implementation phases are self-contained.

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Canonical store = **TimescaleDB** for daily bars | Already operated; SQL + ACID upserts + concurrent multi-host; daily volume trivial. |
| D2 | Store **raw/unadjusted** + `corporate_actions`; **adjust on read** | Avoids retroactive-staleness of cached adjusted series; clean point-in-time. |
| D3 | **Parquet snapshot** exported from DB as backtest cache | Backtests need fast columnar full-history scans; don't stream millions of rows per run. |
| D4 | Ingestion owned by **this standalone service** (host `:8300`); gateway **proxies** `/api/v2/engines/market-data/*` | Realises the `EXTERNAL` catalog entry; one credential owner; strategies read a contract, not raw tables. |
| D5 | Intraday/tick → re-evaluate **lake-first** (DuckDB + object store) | Timescale row counts blow up sub-daily. **For S50 the lake is not needed** (~13k rows/sym/yr). |
| D6 | Migration is **flagged + incremental**, not a rip-out | csm-set's "Parquet is the durable store" becomes "DB canonical, Parquet derived" behind `CSM_OHLCV_SOURCE`. |
| D7 | **Extract into its own repo/service** (this repo), not a gateway module | Isolates the tvkit credential + fetch logic; independent deploy/restart/version; keeps the gateway thin. |
| D8 | **Own Redis sidecar** (not the gateway's Redis) | Self-contained bring-up; OHLCV hot-window cache next to its producer; houses the **single-flight fetch lock**. |
| D9 | DB data on **local SSD**; **NAS migration deferred** | Compressed footprint ~40 MB/decade today. Revisit at 1m/tick or all-SET intraday. NAS = backups/WAL only. |
| D10 | Multi-TF = **Option A** (`timeframe` in PK `(symbol,timeframe,ts)`, store bars as fetched) **+ derive extra TFs via continuous aggregates** | Futures `1d` = **settlement, never rolled up from intraday**; carry `open_interest` from day one; fetch the **`S501!` continuous**. |

---

## Canonical request flow (what every phase serves)

**The one invariant:** the tvkit cookie and the TradingView call live **entirely inside
this service**. However a strategy's request resolves — Redis, TimescaleDB, or a fresh
fetch — the strategy only ever talks to the gateway. It never holds a credential and never
calls TradingView. *(Full detail:
[`../../../plans/feature-market-data-engine/request-flow.md`](../../../plans/feature-market-data-engine/request-flow.md).)*

Worked example — a strategy asks for **`S501!` at `5m`**:

```
strategy ─GET /api/v2/engines/market-data/ohlcv?symbol=S501!&timeframe=5m&range=─▶
  quant-api-gateway (auth-gate + PROXY)
     └─▶ quant-marketdata-engine :8300
            1. Redis (own sidecar)  ──HIT──────────────▶ return bars
            2. TimescaleDB market_data.ohlcv ──HIT──────▶ write-through Redis ▶ return
            3. MISS/stale/gap → INGEST side (tvkit cookie)
                 single-flight fetch S501! 5m → ON CONFLICT upsert → write-through ▶ return
  strategy gets bars — never touched tvkit
```

| Path | Hops | When |
|---|---|---|
| **Hot** | Redis hit | repeated / latest-bar reads (common case) |
| **Warm** | Redis miss → DB hit → write-through | bar already ingested |
| **Cold** | DB miss/gap → tvkit fetch + upsert → write-through | only here does anyone call TradingView — **always the engine, never the strategy** |

**Edge cases the build must handle:** concurrent identical requests → single-flight the
fetch (lock/dedupe on `(symbol, timeframe, range)`) so TradingView is hit once; partial
range → fetch only the missing tail and upsert (idempotent overlap is safe); infra-db
down → strategies can still read the **Parquet snapshot** for offline backtest scans.

### The `S501!` continuous question (Phase 0 ADR must pin this)

`S501!` is TradingView's **front-month continuous** futures contract. "Give me `S501!`
5m" has two possible meanings that differ **across a roll boundary**:

| Option | Series returned | Roll behaviour |
|---|---|---|
| **(a)** native TradingView | TradingView's own `S501!` continuous | non-back-adjusted → price gap at each roll |
| **(b)** system-derived | the system's roll-adjusted continuous, built from per-contract bars | back-adjusted → continuous, no gap (matches what the strategy was validated on) |

The ADR must decide **which series the read API serves under `S501!`** (and whether dated
contracts like `S50M2026` are independently addressable). `5m` is base grain → stored raw,
not CAGG-derived. *(Detail:
[`../../../plans/feature-market-data-engine/multi-timeframe-storage.md`](../../../plans/feature-market-data-engine/multi-timeframe-storage.md).)*

---

## Phase 0 — ADR + Repo Bootstrap (current gating milestone)

> Goal: a working repo, clean tooling, a merged ADR that pins D1–D10 and the read
> contract, and the service registered in the umbrella. **No application code.**

### 0.1 Repository & Tooling

- [x] GitHub repo created: `lumduan/quant-marketdata-engine` (public)
- [x] Local skeleton synced from `lumduan/python-template` (uv, ruff, mypy strict, pytest)
- [x] Feature branch `feat/bootstrap-marketdata-engine`
- [x] Personalise `pyproject.toml`: name `quant-marketdata-engine`, package
  `src/quant_marketdata_engine/`, coverage gate ≥90%
- [x] `.env.example` documenting `TVKIT_AUTH_TOKEN` (cookie JSON), `MARKETDATA_ENGINE_*`
  vars (public mode, host port, PG DSN, own-Redis URL, API key)
- [x] Verify gates on the empty project:
  `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest`

### 0.2 Roadmap & Agent Context

- [x] `docs/plans/ROADMAP.md` — this document
- [x] `CLAUDE.md` — per-service agent guide (ownership boundaries, ports, conventions)
- [x] `.claude/knowledge/market-data-engine.md` — request flow, multi-TF storage,
  cookie-ownership contract, infra-db touchpoints
- [x] `.claude/playbooks/development-workflow.md` — bring-up order, gates, safe tvkit
  testing without committing the cookie, PR sequence
- [x] `README.md` rewritten for the service

### 0.3 ADR (the gate) — *umbrella `.claude/knowledge/`*

- [x] Author `.claude/knowledge/feature-market-data-engine.md` in the **umbrella** repo
  (architecture rationale + schema + trade-offs)
- [x] Confirm Decision Log **D1–D10** (all ACCEPTED; no new D-decision)
- [x] Set the **intraday lake-first threshold** as a number — **~50M rows/yr** (S50 ≈ 152k
  rows/yr stays in Timescale)
- [x] Define the **Market Data read contract** (request/response shape; daily + adjusted;
  the `S501!` continuous question above)
- [x] Decide **seed-vs-retire** for the existing tfex `09` TimescaleDB mirror — **RETIRE**
  (build fresh + migrate; see Phase 4)

### 0.4 Umbrella registration — *done (ADR merged)*

- [x] Add `quant-marketdata-engine` to the umbrella `CLAUDE.md` **repo/remote table**
- [x] Add to the **Docker network contract** (`quant-marketdata-engine`, container `:8000`,
  host `:8300`)
- [x] Add to the **local bring-up order** (after infra-db, before/with the gateway)
- [x] Add the **health check** (`curl http://localhost:8300/health`)
- [x] Flip the `feature-market-data-engine` registry status as appropriate

> **Out of scope (Phase 0):** any fetch / storage / read-API / Redis code; any SQL; the
> gateway proxy route. Until the ADR merges, umbrella registration tables stay as a
> documented TODO — we do **not** invent D-decisions.

**Exit criteria:** ADR merged; D1–D10 + read contract + intraday threshold agreed; the
service registered in the umbrella; repo gates green on the scaffold; **no application
code**.

---

## Phase 1 — `quant-infra-db`: shared `market_data` schema 🗄️

> **Lands in `quant-infra-db`'s own PR**, not this repo. This service is the eventual
> *writer*; the schema is a prerequisite. Detail:
> [`../../../plans/feature-market-data-engine/quant-infra-db-changes.md`](../../../plans/feature-market-data-engine/quant-infra-db-changes.md)
> and [`../../../plans/feature-market-data-engine/multi-timeframe-storage.md`](../../../plans/feature-market-data-engine/multi-timeframe-storage.md).

- [x] **`10_schema_market_data.sql`** — `market_data.ohlcv` hypertable, **PK
  `(symbol, timeframe, ts)`** (Option A, D10):
  - `open/high/low/close numeric(18,6)` (never `float`), `volume numeric(20,4)`,
    **`open_interest numeric(20,4)` (futures; from day one, NULL for equities)**,
    `source text`, `ingested_at timestamptz`
  - `ts` = **bar-open time, stored UTC** (display Asia/Bangkok)
  - 30-day chunks; compression `compress_segmentby = 'symbol, timeframe'` after 7d;
    keep 1d forever (no drop policy). CHECK constraints: timeframe∈{1d,1h,5m}, prices>0,
    volume≥0, OI≥0, high≥low
  - **Futures `1d` close = settlement, never rolled up from intraday** (D10)
- [x] **`11_market_data_caggs.sql`** — `cagg_ohlcv_1h` / `cagg_ohlcv_4h` continuous
  aggregates off the 5m base + `add_continuous_aggregate_policy` refresh jobs, following the
  `06_continuous_aggregates.sql` `WITH NO DATA` + `if_not_exists` pattern
- [x] `market_data.corporate_actions` — `(symbol, ex_date, action_type, ratio, amount)`,
  PK `(symbol, ex_date, action_type)`; holds equity splits/dividends **and** futures roll
  dates (`action_type='roll'`) for `S501!` back-adjustment (adjust-on-read, D2/D10)
- [x] `market_data.ohlcv_adjusted` — adjust-on-read **view** (recomputes on action insert)
- [x] `market_data.universe_membership` — as-of dated constituents, PK
  `(as_of, symbol, index_name)` (schema only; seeding is Phase 2)
- [-] *(optional, deferred)* `market_data.contract_specs` — per-contract tick size, multiplier,
  expiry, roll dates (future, not Phase-1-required per ADR)
- [x] Idempotent upsert contract `ON CONFLICT (symbol, timeframe, ts) DO UPDATE`
- [x] `src/db/` Pydantic row models (`OHLCVBarRow`, `CorporateActionRow`,
  `UniverseMembershipRow`) with `Decimal` prices + UTC validators; asyncpg upsert helpers
  (`upsert_ohlcv`/`fetch_ohlcv`/`upsert_corporate_actions`/`upsert_universe_membership`)
- [x] Destination decided: **new `db_market_data` database** (own DB, not a `db_gateway`
  schema) — keeps the store independently owned per D4/D7
- [x] Data stays on **local SSD** — NAS migration deferred (D9; unchanged)

**Exit criteria:** schema applies on `quant-network`; upsert is idempotent; the adjusted
view recomputes when a `corporate_actions` row is added; ≥80% coverage per the
`quant-infra-db` repo gate. ✅ **MET** — lands in `quant-infra-db`'s PR
(`feat/market-data-schema-phase1`); unit 96 passed @ 98.4%, infra 19/19. Plan:
[`phase1-quant-infra-db-market-data-schema.md`](phase1-quant-infra-db-market-data-schema.md).

> **Out of scope:** any code in this repo; the read API; the lake.

---

## Phase 2 — This service (build) + gateway proxy route 🚦

> Goal: stand this service up as the live producer + read API, and wire the gateway proxy.
> **This is the first phase that writes code in this repo.** The gateway route lands in
> `quant-api-gateway`'s own PR.

### 2.1 Ingest side (sole tvkit-cookie owner)

- [x] `src/quant_marketdata_engine/ingest/tvkit_client.py` — wraps tvkit; the **only**
  holder of `TVKIT_AUTH_TOKEN` (cookie JSON; see
  [`.claude/knowledge/market-data-engine.md`](../../.claude/knowledge/market-data-engine.md)
  and the umbrella `reference-tvkit-tradingview-auth` memory). Fetches via tvkit
  `get_historical_ohlcv` (`bars_count`/`start`/`end`, `Adjustment.SPLITS`); **async**.
- [x] `src/quant_marketdata_engine/ingest/service.py` + `db/repositories.py` — idempotent
  upsert of raw bars into `market_data.*` (`ON CONFLICT (symbol,timeframe,ts) DO UPDATE`)
- [x] **Single-flight fetch lock** in the own Redis sidecar (D8) — dedupe on
  `(symbol, timeframe, range)` so two callers don't both trigger a fetch
- [x] One-time **backfill** (`ingest/backfill.py`) seeded from the on-disk fetch in
  `csm-set/data/raw/dividends/` — best-effort, idempotent, no-ops when the (gitignored)
  source is absent; tagged `source='csm-backfill-div'` (dividend-adjusted; parity is a
  Phase-5 concern)
- [x] Robust error handling: upstream tvkit failures / session-expiry surfaced as typed
  `TvkitFetchError` (never the cookie); public-mode refuses ingest (`IngestDisabledError`)

### 2.2 Read side (private/auth-gated)

- [x] `src/quant_marketdata_engine/api/` — FastAPI app on container `:8000`; routes:
  `GET /health`; `GET /ohlcv` (raw); `GET /ohlcv/adjusted`; `GET /universe`; owner-mode
  `POST /admin/ingest`
- [x] Resolve `(symbol, timeframe, range)` via **hot/warm** (Redis → TimescaleDB →
  write-through). *Cold path (auto-fetch-on-miss) is **deferred** — the single-flight lock
  primitive is built and ingest is a separate path (CLI + `/admin/ingest`).*
- [x] Uniform read contract (ADR §5) so strategies bind to a contract, never a table name
- [x] **Auth-gate** the read API (`X-API-Key`, constant-time; raw OHLCV is private-side)
- [x] Input validation on symbol / timeframe enum (`1d|1h|5m`) / range (rejects malformed)

### 2.3 Parquet snapshot exporter

- [x] `src/quant_marketdata_engine/snapshot/exporter.py` — DB → columnar Parquet
  (decimal128-exact) for offline backtest scans; round-trips with the DB

### 2.4 Service plumbing

- [x] `docker-compose.yml` — service + **own Redis sidecar** (`marketdata-redis`), joins
  external `quant-network`, host `:8300`, public-safe defaults (no cookie, read-only)
- [x] `docker-compose.private.yml` — owner/ingest mode (`env_file` with the cookie;
  `public_mode=false`)
- [x] `pydantic-settings` `Settings` reading `MARKETDATA_ENGINE_*` + `TVKIT_AUTH_TOKEN`;
  structured logging (`logging.getLogger(__name__)`); module-local `errors.py`

### 2.5 Gateway proxy — *`quant-api-gateway`'s own PR*

- [x] Add thin **proxy route** `GET /api/v2/engines/market-data/*` → `:8000` (in-network
  service name) — `/health`, `/ohlcv`, `/ohlcv/adjusted`, `/universe`; forwards `X-API-Key`;
  upstream-down → clean `502/503/504`
- [x] Engine catalog entry reports **`active`** (description updated to the standalone
  engine; `engine_registry` + static fallback were already `active`)
- [x] Gateway holds **no** tvkit cookie; keeps its own Redis for v1/v2 response caching
  (separate from this service's sidecar)

**Exit criteria:** ✅ **MET** — service stands up on `quant-network`; engine status reports
active; ingest (CLI / `/admin/ingest`) populates the DB idempotently; the gateway proxy
returns adjusted + raw; the snapshot export round-trips; **coverage 98.9%** on core modules,
mypy strict clean, structured logging + typed error handling in place; single-flight + batch
upsert (no N+1). Plan: [`phase2-service-build-and-gateway-proxy.md`](phase2-service-build-and-gateway-proxy.md).

> **Out of scope (deferred):** cold-path auto-fetch-on-read (lock primitive built); the
> in-process scheduler (Phase 5); futures-roll back-adjustment math + `09` retirement
> (Phase 4); strategy cutover (Phase 3/4); the intraday lake (D5).

---

## Phase 3 — `strategies/csm-set`: read from the store behind a flag 🧠 ✅ flag complete (2026-06-01)

> **Lands in `csm-set`'s own PR.** This service is the data source; csm-set becomes a
> reader. Shipped as `1de4d65` on `origin/live-test` (csm-set).

- [x] Add `CSM_OHLCV_SOURCE = parquet | db` (default `parquet`); `db` reads this engine's
  read API / Parquet snapshot instead of fetching tvkit
- [x] Demote csm-set's local Parquet to a **derived backtest cache** (materialised from the
  DB); **stop the per-strategy tvkit fetch** in `daily_refresh` when `source=db`
- [ ] Fix the 2026-05-29 live-test gap: include `SET:SET` index + sectors so
  `residual_momentum` / composite compute every session — **⏭ deferred** (not in `1de4d65`;
  different code area: universe / feature pipeline). Tracked as a csm-set follow-up.

**Exit criteria:** csm-set runs identically on `db` source; `test_public_data_boundary_*`
still pass; no behaviour change vs Parquet for the same dates. — **MET for the reader flag**
(2026-06-01); the index/sectors gap fix is the only outstanding Phase 3 item.

---

## Phase 4 — `strategies/tfex-s50-multi-tf-swing`: consume shared store 📉 ✅ in progress (2026-06-02)

> **Lands in tfex's own PR.** Reconciles the existing `09` mirror against this engine's
> canonical schema. Plan: [`phase4-tfex-consume-shared-store.md`](phase4-tfex-consume-shared-store.md).
> Shipped on `feat/phase4-consume-marketdata-engine` (off `main`, tfex repo).

- [x] Point tfex's data layer at the shared `market_data` store —
  `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE = mirror | engine` (default `mirror`); `engine`
  reads `/ohlcv` via the gateway proxy at the `refresh_all` seam; no tvkit cookie on that path
- [x] **Reconcile or retire** tfex's Phase-1 standalone TimescaleDB OHLCV mirror
  (`db_tfex_s50_multi_tf_swing.ohlcv_raw` / `.ohlcv_continuous`, schema `09`) so there is
  one canonical store — **demoted to a derived local cache** in code + docs; the physical
  DROP is a tracked `quant-infra-db` follow-up (default `mirror` path still writes 09)
- [~] Multi-TF (5m / 1h / 4h **+ 1d**) via Option A; `1d` futures = settlement (never
  rolled up) — **5m/1h served from the engine as-stored**; `1d` settlement available
  engine-side (tfex consumes later); **4h deferred** — the engine read API has no 4h route
  (`cagg_ohlcv_4h` unrouted), declined client-side with a typed error, **no local rollup**
  (D10). Follow-up: engine 4h route → one-line tfex enablement
- [x] Consume the **`S501!` continuous** per the ADR's (a)/(b) decision; carry
  `open_interest` — option **(b)** back-adjusted, **built locally** from raw dated contracts
  (`/ohlcv?adjusted=false`) because the engine's native futures-roll back-adjustment is
  unbuilt (Phase-5 adjustment-parity); `open_interest` carried (NULL for equities)
- [x] Decide intraday handling per Phase 0 (Timescale hot window — the lake is not needed
  for S50) — **resolved: Timescale hot window** (D5)

**Exit criteria:** tfex backtests/live read the shared store; the duplicate mirror is
removed or demoted to a cache; no per-host tvkit credential needed. — **MET**: `engine` path
reads the shared store with no cookie; the 09 mirror is demoted to a cache. Outstanding
follow-ups: engine 4h route, engine native back-adjusted S501! (Phase-5), infra-db 09 drop.

---

## Phase 5 — End-to-end verification & cutover 🔬

> Goal: prove the whole system runs off one producer with one credential, then
> decommission the per-strategy fetch.

- [x] Verification plan authored: [`phase5-end-to-end-verification-cutover.md`](phase5-end-to-end-verification-cutover.md)
- [x] Verification scripts built: `tests/verification/` (verify_csm_parity.py, verify_tfex_parity.py, verification_utils.py)
- [x] Verification unit tests (21 tests, all green — `uv run pytest tests/verification/`)
- [~] Run Tier 1 verification (engine vs Parquet): **csm-set done** (691 symbols, 100% parity —
  `reports/verification-csm.json`); **tfex deferred** (no mirror Parquet / no TFEX data)
- [~] If 100% parity: flip defaults + deprecation + docs — **csm-set done** (`CSM_OHLCV_SOURCE`
  default `db`, PR `lumduan/csm-set#15`); **tfex cutover pending Phase 5.x** (still `mirror`)
- [ ] If <100% parity: gap analysis — **N/A** (csm 100%; tfex deferred is no-data, not a gap)
- [~] Confirm **no strategy fetches tvkit directly**: csm ✓ (default `db`); **tfex still
  defaults to tvkit-direct `mirror`** — pending Phase 5.x
- [ ] Confirm backtest read performance (Parquet snapshot path as fast as local Parquet) —
  **not yet documented** (pending)
- [x] Runbook authored in the umbrella `.claude/playbooks/` —
  `marketdata-engine-cutover.md` (csm done; tfex flagged pending Phase 5.x)

**Exit criteria:** single daily ingest ✓; both strategies consistent on the same closes —
csm verified (100%), **tfex pending**; per-strategy tvkit fetch decommissioned — csm ✓,
**tfex pending**; cutover runbook exists ✓.

---

## Phase 6 — Documentation (tvkit-ref style, AI-agent-first) 📚

> Goal: documentation parity with [tvkit](https://github.com/lumduan/tvkit) — a structured
> `docs/` hierarchy under 7 categories, comprehensive `.claude/` resources, and a
> fully-indexed `CLAUDE.md`. Every planned file is listed in the Documentation section of
> `CLAUDE.md`. (Follow-up: write the actual content in Phase 6 sub-tasks.)

**Status:** planned · **Depends on:** Phase 5 (end-to-end verification & cutover)
**Reference:** [tvkit docs structure](https://github.com/lumduan/tvkit/tree/main/docs)
**Created:** 2026-06-02

### 6.1 Agent Context refresh

- [x] `CLAUDE.md` — Documentation section indexes all doc files + `.claude/` resources;
  focused-core files flipped to live links, remaining tree marked `(TODO: Phase 6.x)`;
  Current State updated (Phase 4 done, Phase 5 partial, Phase 6 docs shipped); documentation
  standards in Quality gates
- [x] `.claude/knowledge/` — authored `data-flow.md`, `deployment.md`, `api-contract.md`
  (`architecture.md` already existed)
- [x] `.claude/knowledge/market-data-engine.md` — refreshed with cross-refs to the new
  architecture/api/data docs
- [ ] `.claude/playbooks/` — author missing playbooks:
  `docs-workflow.md`, `data-refresh.md`, `troubleshooting.md` — **(TODO: Phase 6.x)**
- [ ] `.claude/playbooks/development-workflow.md` — refresh for verification scripts +
  cutover runbook reference — **(TODO: Phase 6.x)**
- [ ] `.claude/playbooks/feature-development.md` — add documentation checklist step
  — **(TODO: Phase 6.x)**
- [ ] `.claude/memory/` — add `cookie-management.md` — **(TODO: Phase 6.x)**

### 6.2 docs/ Structure (tvkit-inspired hierarchy)

> **Focused-core set shipped (2026-06-02).** The high-value architecture/api/operations/data
> docs + the hub are written; the getting-started/concepts/reference/guides subtrees are
> deferred to Phase 6.x (tracked below).

- [x] `docs/architecture/` — `overview.md`, `data-model.md`, `security-boundary.md`
- [x] `docs/api/` — `health.md`, `ohlcv.md`, `ohlcv-adjusted.md`, `universe.md`,
  `admin-ingest.md` (each with curl request + response examples)
- [~] `docs/operations/` — `bring-up.md`, `configuration.md`, `troubleshooting.md` **done**;
  `monitoring.md`, `scheduled-ingest.md` **(TODO: Phase 6.x)**
- [x] `docs/data/` — `ohlcv-schema.md`, `corporate-actions.md`, `universe-membership.md`,
  `parquet-snapshot.md`
- [ ] `docs/getting-started/` — `quickstart.md`, `local-development.md`,
  `public-vs-owner-mode.md` — **(TODO: Phase 6.x)**
- [ ] `docs/concepts/` — `adjust-on-read.md`, `single-flight-fetch.md`,
  `tvkit-cookie-ownership.md`, `continuous-vs-per-contract.md` — **(TODO: Phase 6.x)**
- [ ] `docs/reference/` — `settings.md`, `docker-compose-reference.md`,
  `gateway-proxy-contract.md`, `error-codes.md` — **(TODO: Phase 6.x)**
- [ ] `docs/guides/` — `adding-a-new-reader.md`, `tvkit-token-rotation.md` — **(TODO: Phase 6.x)**
- [x] `docs/README.md` — hub page linking every sub-doc (README-as-hub pattern)

### 6.3 Repo-level Docs refresh

- [ ] `README.md` — update to reflect live Phase 2–4 state (replace "Scaffold only"
  warning); add hub link to new `docs/README.md`; refresh architecture diagram
- [ ] `CHANGELOG.md` — summarise Phases 2–5 (already shipped) and add Phase 6 entry
- [ ] `CONTRIBUTING.md` — add documentation standards section (required docs per PR,
  `docs/` structure overview, review process for doc changes)
- [ ] `.claude/templates/pr-template.md` — add "Documentation updated?" checkbox

### 6.4 Acceptance criteria

- [ ] Every engine endpoint has a curl example in `docs/api/`
- [ ] Every knowledge file has a 2–4 sentence executive summary and a `last_verified` date
- [ ] `CLAUDE.md` Documentation section indexes every doc file and `.claude/` resource —
  no file is discoverable only by browsing the repo
- [ ] `docs/` hierarchy mirrors tvkit's 7-category structure adapted for this service
- [ ] No broken cross-references: every project-relative path resolves or is marked
  `(TODO: Phase 6)`
- [ ] `README.md` acts as a hub with one-line descriptions linking every sub-doc
- [ ] All files under `docs/` are git-tracked (following the existing rule that
  `docs/plans/` is tracked)
- [ ] Playbooks are step-by-step executable by an AI agent (every command is
  copy-pasteable, no "adjust as needed" ambiguity)

---

## Dependency Map

```
Phase 0 (ADR + Repo Bootstrap)         ← gate for everything
    └── Phase 1 (quant-infra-db schema)
            └── Phase 2 (this service build + gateway proxy)
                    ├── Phase 3 (csm-set reads behind flag)
                    └── Phase 4 (tfex consumes shared store)
                            └── Phase 5 (end-to-end verification & cutover)
                                    └── Phase 6 (documentation — tvkit-ref, AI-agent-first)
```

---

## Quality bar (applies to every code phase in this repo)

These are enforced as phase exit criteria where relevant:

- **Strict typing** — `mypy --strict` clean on `src` and `tests`; full annotations, no
  bare `Any`; Pydantic models at boundaries (never raw dicts).
- **Async correctness** — all I/O-bound fetching is async (`httpx.AsyncClient`);
  `requests` is forbidden in `src/`.
- **Structured logging** — `logging.getLogger(__name__)`, `%`-formatting; never `print`.
- **Comprehensive error handling** — upstream tvkit failures, rate limits, partial bars,
  session expiry; module-local `errors.py` inheriting a shared base; never
  `except Exception: pass`.
- **Input validation** — symbol/timeframe-enum/range validated at the read boundary.
- **Secret handling** — `TVKIT_AUTH_TOKEN` only via gitignored `.env`/`.tmp/`; never
  committed; never logged.
- **Idempotent writes** — `ON CONFLICT … DO UPDATE`; re-running an ingest is safe.
- **Performance** — single-flight fetch lock; batch upserts; characterise bulk-history
  fetches; per-timeframe compression/retention.
- **Coverage** — **≥90%** on core modules (`ingest/`, `api/`, `snapshot/`), enforced in
  CI and `pyproject.toml`.
- **Money & time** — `Decimal` (never `float`) for OHLC; store UTC, display Asia/Bangkok.

---

## Non-goals / Anti-patterns

| Anti-pattern | Why it is forbidden |
|---|---|
| A strategy fetching tvkit directly | Defeats the single-credential-owner invariant. Strategies read the gateway proxy only. |
| Caching adjusted bars as the source of truth | Adjusted series go stale on the next corporate action / roll. Store raw; adjust on read (D2). |
| Rolling futures `1d` up from intraday | The daily close is the **settlement price**, not a 5m rollup. Persist the fetched settlement bar (D10). |
| Putting the tvkit cookie in the gateway or a strategy `.env` | This service is the sole owner (D4/D7). |
| Live DB files on NFS/SMB | Corruption risk (Mongo unsupported; Postgres fragile). Local SSD now; NAS = backups/WAL only (D9). |
| Reaching for the lake for S50 | ~13k rows/sym/yr — Timescale handles it trivially. Reserve DuckDB for tick / many-hundred-symbol intraday (D5). |
| `float` for prices, or tz-naive timestamps | `Decimal` at boundaries; UTC storage, Asia/Bangkok display. |

---

## Cross-references

- **Umbrella feature roadmap (primary source):**
  [`../../../plans/feature-market-data-engine/ROADMAP.md`](../../../plans/feature-market-data-engine/ROADMAP.md)
- **Request flow:**
  [`../../../plans/feature-market-data-engine/request-flow.md`](../../../plans/feature-market-data-engine/request-flow.md)
- **Multi-timeframe storage + `S501!`:**
  [`../../../plans/feature-market-data-engine/multi-timeframe-storage.md`](../../../plans/feature-market-data-engine/multi-timeframe-storage.md)
- **quant-infra-db Phase 1 changes + NAS/sizing:**
  [`../../../plans/feature-market-data-engine/quant-infra-db-changes.md`](../../../plans/feature-market-data-engine/quant-infra-db-changes.md)
- **Per-service domain knowledge:** [`.claude/knowledge/market-data-engine.md`](../../.claude/knowledge/market-data-engine.md)
- **Dev playbook:** [`.claude/playbooks/development-workflow.md`](../../.claude/playbooks/development-workflow.md)
- **Umbrella system map + engine catalog + ingestion contract:** [`../../CLAUDE.md`](../../CLAUDE.md)
- **tvkit auth + bulk-fetch method:** umbrella agent memory `reference-tvkit-tradingview-auth`
- **Existing tfex mirror to reconcile:**
  `quant-infra-db/init-scripts/09_schema_db_tfex_s50_multi_tf_swing_ohlcv.sql`

---

## Current Status

> Update this section as phases complete.

- **Active phase:** Phase 5 — End-to-end verification & cutover (**partial**): csm-set is
  **cut over and verified** (`CSM_OHLCV_SOURCE` default `db`; 691 symbols, 100% parity —
  `reports/verification-csm.json`); **tfex verification + cutover are deferred** (no mirror
  Parquet / no TFEX data; `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE` still defaults `mirror`).
  **Phase 4 is complete** (2026-06-02). **Phase 6 — Documentation: the focused-core `docs/`
  set is shipped** (hub + architecture ×3, api ×5, operations ×3, data ×4; remaining
  tvkit-tree subtrees are Phase 6.x). Plan: [`phase6-documentation.md`](phase6-documentation.md).
- **Completed:** Phase 0 (§0.1–§0.4); **Phase 1** (schema + `src/db` in `quant-infra-db`;
  unit 96 @ 98.4%, infra 19/19); **Phase 2** (this repo: ingest/api/cache/db/snapshot +
  compose, 95 tests @ 98.9%; gateway proxy + catalog, 336 tests @ 90.6%); **Phase 3** (reader
  flag — csm-set, `1de4d65`); **Phase 4** (tfex reader flag, 2026-06-02). Phase plans:
  [`phase0-adr-repo-bootstrap.md`](phase0-adr-repo-bootstrap.md),
  [`phase1-quant-infra-db-market-data-schema.md`](phase1-quant-infra-db-market-data-schema.md),
  [`phase2-service-build-and-gateway-proxy.md`](phase2-service-build-and-gateway-proxy.md),
  [`phase3-csm-set-read-from-store.md`](phase3-csm-set-read-from-store.md),
  [`phase4-tfex-consume-shared-store.md`](phase4-tfex-consume-shared-store.md),
  [`phase5-end-to-end-verification-cutover.md`](phase5-end-to-end-verification-cutover.md).
- **Phase 5 (in progress — scripts built):** verification plan authored; `tests/verification/`
  package with verify_csm_parity.py, verify_tfex_parity.py, verification_utils.py; 21 unit
  tests green. Live Tier 1 verification + cutover pending (requires running stack).
- **Phase 6 (focused core shipped, 2026-06-02):** `docs/` hub + architecture/api/operations/
  data docs (example-driven, AI-agent-first) and the 3 `.claude/knowledge` files
  (data-flow, deployment, api-contract). Consolidated cutover runbook authored in the umbrella
  (`.claude/playbooks/marketdata-engine-cutover.md`). Remaining tvkit subtrees
  (getting-started/concepts/reference/guides, extra playbooks, repo-level CHANGELOG/CONTRIBUTING
  refresh) are tracked as Phase 6.x. Plan: [`phase6-documentation.md`](phase6-documentation.md).
