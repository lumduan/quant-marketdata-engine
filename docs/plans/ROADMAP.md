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

- [ ] **`10_schema_market_data.sql`** — `market_data.ohlcv` hypertable, **PK
  `(symbol, timeframe, ts)`** (Option A, D10):
  - `open/high/low/close numeric(18,6)` (never `float`), `volume numeric(20,4)`,
    **`open_interest numeric(20,4)` (futures; from day one, NULL for equities)**,
    `source text`, `ingested_at timestamptz`
  - `ts` = **bar-open time, stored UTC** (display Asia/Bangkok)
  - partition by time; compression `compress_segmentby = 'symbol, timeframe'`;
    per-timeframe retention (compress 5m after ~7d; keep 1d forever)
  - **Futures `1d` close = settlement, never rolled up from intraday** (D10)
- [ ] **`11_market_data_caggs.sql`** — continuous aggregates for coarser TFs a strategy
  didn't fetch (e.g. `ohlcv_15m/1h/4h` off a 5m base) + `add_continuous_aggregate_policy`
  refresh jobs, following the existing `06_continuous_aggregates.sql` `WITH NO DATA` +
  `if_not_exists` pattern
- [ ] `market_data.corporate_actions` — `(symbol, ex_date, type, ratio/amount)` **plus the
  futures roll dates** for `S501!` back-adjustment (adjust-on-read, D2/D10)
- [ ] `market_data.adjusted_view` (or CAGG) — split/div/roll adjust on read
- [ ] `market_data.universe_membership` — as-of dated SET constituents (seed from the
  monthly universe snapshots)
- [ ] *(optional)* `market_data.contract_specs` — per-contract tick size, multiplier,
  expiry, roll dates (future, not Phase-1-required)
- [ ] Idempotent upsert contract `ON CONFLICT (symbol, timeframe, ts) DO UPDATE`
- [ ] `src/db/` Pydantic row models (`OHLCVBarRow`, `CorporateActionRow`,
  `UniverseMembershipRow`) with `Decimal` prices + UTC validators; asyncpg upsert helpers
- [ ] Decide destination: `db_market_data` (own DB) vs `db_gateway.market_data` schema
  (Phase 0 call)
- [ ] Data stays on **local SSD** — NAS migration deferred (D9)

**Exit criteria:** schema applies on `quant-network`; upsert is idempotent; the adjusted
view recomputes when a `corporate_actions` row is added; ≥80% coverage per the
`quant-infra-db` repo gate.

> **Out of scope:** any code in this repo; the read API; the lake.

---

## Phase 2 — This service (build) + gateway proxy route 🚦

> Goal: stand this service up as the live producer + read API, and wire the gateway proxy.
> **This is the first phase that writes code in this repo.** The gateway route lands in
> `quant-api-gateway`'s own PR.

### 2.1 Ingest side (sole tvkit-cookie owner)

- [ ] `src/quant_marketdata_engine/ingest/tvkit_client.py` — wraps tvkit; the **only**
  holder of `TVKIT_AUTH_TOKEN` (cookie JSON; see
  [`.claude/knowledge/market-data-engine.md`](../../.claude/knowledge/market-data-engine.md)
  and the umbrella `reference-tvkit-tradingview-auth` memory). Fetch via the documented
  `--bars`/`bars_count` path; **async** (`httpx.AsyncClient`, never `requests`).
- [ ] `src/quant_marketdata_engine/ingest/upsert.py` — idempotent upsert of raw bars +
  corporate actions / roll dates into `market_data.*` (`ON CONFLICT … DO UPDATE`)
- [ ] **Single-flight fetch lock** in the own Redis sidecar (D8) — dedupe on
  `(symbol, timeframe, range)` so two strategies don't both trigger a fetch
- [ ] One-time **backfill** seeded from the fresh 2026-05-29 fetch already on disk in
  `csm-set/data/raw/dividends/` (import, don't re-pull 700 symbols)
- [ ] Robust error handling: upstream tvkit failures, rate limits, partial/incomplete
  bars, session-expiry (`ProfileFetchError` → surfaced, not swallowed)

### 2.2 Read side (private/auth-gated)

- [ ] `src/quant_marketdata_engine/api/` — FastAPI app on container `:8000`; routes:
  `GET /health`; `GET /ohlcv` (raw); `GET /ohlcv/adjusted`; `GET /universe`
- [ ] Resolve `(symbol, timeframe, range)` via the hot/warm/cold flow above (Redis →
  TimescaleDB → ingest); write-through to Redis
- [ ] Uniform read contract so strategies bind to a contract, never a table name; the
  engine decides "stored row vs continuous aggregate"
- [ ] **Auth-gate** the read API (raw OHLCV is private-side only)
- [ ] Input validation on symbol / timeframe enum (`1d|1h|5m|…`) / range

### 2.3 Parquet snapshot exporter

- [ ] `src/quant_marketdata_engine/snapshot/exporter.py` — DB → columnar Parquet for
  heavy backtest scans (offline path); round-trips with the DB

### 2.4 Service plumbing

- [ ] `docker-compose.yml` — service + **own Redis sidecar**, joins external
  `quant-network`, host `:8300`, public-safe defaults
- [ ] `docker-compose.private.yml` — owner/ingest mode (`env_file` with the cookie)
- [ ] `pydantic-settings` `Settings` reading `MARKETDATA_ENGINE_*` + `TVKIT_AUTH_TOKEN`;
  structured logging (`logging.getLogger(__name__)`); module-local `errors.py`

### 2.5 Gateway proxy — *`quant-api-gateway`'s own PR*

- [ ] Add thin **proxy route** `GET /api/v2/engines/market-data/*` → `:8300`
- [ ] Flip the engine catalog entry **`EXTERNAL stub → active`**
- [ ] Gateway holds **no** tvkit cookie; keeps its own Redis for v1/v2 response caching
  (separate from this service's sidecar)

**Exit criteria:** service stands up on `quant-network`; engine status flips
EXTERNAL→active; one ingest run populates the DB; the gateway proxy returns adjusted + raw;
the snapshot export round-trips; **≥90% coverage on core modules** (ingest/api/snapshot),
mypy strict clean, structured logging + comprehensive error handling in place; bulk-history
fetch performance characterised (single-flight, batch upsert, no N+1 fetches).

> **Out of scope:** strategy cutover (Phase 3/4); the intraday lake.

---

## Phase 3 — `strategies/csm-set`: read from the store behind a flag 🧠

> **Lands in `csm-set`'s own PR.** This service is the data source; csm-set becomes a
> reader.

- [ ] Add `CSM_OHLCV_SOURCE = parquet | db` (default `parquet`); `db` reads this engine's
  read API / Parquet snapshot instead of fetching tvkit
- [ ] Demote csm-set's local Parquet to a **derived backtest cache** (materialised from the
  DB); **stop the per-strategy tvkit fetch** in `daily_refresh` when `source=db`
- [ ] Fix the 2026-05-29 live-test gap: include `SET:SET` index + sectors so
  `residual_momentum` / composite compute every session

**Exit criteria:** csm-set runs identically on `db` source; `test_public_data_boundary_*`
still pass; no behaviour change vs Parquet for the same dates.

---

## Phase 4 — `strategies/tfex-s50-multi-tf-swing`: consume shared store 📉

> **Lands in tfex's own PR.** Reconciles the existing `09` mirror against this engine's
> canonical schema.

- [ ] Point tfex's data layer at the shared `market_data` store
- [ ] **Reconcile or retire** tfex's Phase-1 standalone TimescaleDB OHLCV mirror
  (`db_tfex_s50_multi_tf_swing.ohlcv_raw` / `.ohlcv_continuous`, schema `09`) so there is
  one canonical store — per the Phase 0 seed-vs-retire decision
- [ ] Multi-TF (5m / 1h / 4h **+ 1d**) via Option A; `1d` futures = settlement (never
  rolled up)
- [ ] Consume the **`S501!` continuous** per the ADR's (a)/(b) decision; carry
  `open_interest`
- [ ] Decide intraday handling per Phase 0 (Timescale hot window — the lake is not needed
  for S50)

**Exit criteria:** tfex backtests/live read the shared store; the duplicate mirror is
removed or demoted to a cache; no per-host tvkit credential needed.

---

## Phase 5 — End-to-end verification & cutover 🔬

> Goal: prove the whole system runs off one producer with one credential, then
> decommission the per-strategy fetch.

- [ ] Bring-up order: `quant-infra-db` → `quant-marketdata-engine` → `quant-api-gateway`
  → strategies → `quant-openbb`
- [ ] One scheduled ingest serves **both** strategies (deduped at the store)
- [ ] Verify **point-in-time + adjusted correctness** on a known corporate action
  (adjustment-math parity vs the tvkit dividend-adjusted series strategies were validated
  on — diff-test before cutover)
- [ ] Confirm **no strategy fetches tvkit directly** anymore
- [ ] Confirm backtest read performance (Parquet snapshot path as fast as today's local
  Parquet; DB must not become a backtest bottleneck)
- [ ] Runbook authored in the umbrella `.claude/playbooks/`

**Exit criteria:** single daily ingest; both strategies consistent on the same closes; the
per-strategy tvkit fetch is decommissioned; the cutover runbook exists.

---

## Dependency Map

```
Phase 0 (ADR + Repo Bootstrap)         ← gate for everything
    └── Phase 1 (quant-infra-db schema)
            └── Phase 2 (this service build + gateway proxy)
                    ├── Phase 3 (csm-set reads behind flag)
                    └── Phase 4 (tfex consumes shared store)
                            └── Phase 5 (end-to-end verification & cutover)
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

- **Active phase:** Phase 1 — `quant-infra-db` shared `market_data` schema (lands in the
  `quant-infra-db` repo's own PR). **Phase 0 is complete** — the ADR is authored
  (`.claude/knowledge/feature-market-data-engine.md` in the umbrella) and the service is
  registered in the umbrella `CLAUDE.md`, so Phase 1 is now unblocked.
- **Completed:** §0.1 (repo + tooling), §0.2 (roadmap + agent context), §0.3 (ADR — D1–D10
  accepted, intraday threshold ~50M rows/yr, read contract, `S501!` = option (b)
  back-adjusted, `09` = retire), §0.4 (umbrella registration). Phase plan:
  [`phase0-adr-repo-bootstrap.md`](phase0-adr-repo-bootstrap.md).
- **No application code exists yet** — Phase 2 is the first code phase in this repo.
