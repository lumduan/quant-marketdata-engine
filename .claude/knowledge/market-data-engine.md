# Market Data Engine — domain knowledge

Distilled from the umbrella design docs under
[`../../../plans/feature-market-data-engine/`](../../../plans/feature-market-data-engine/)
(`ROADMAP.md`, `request-flow.md`, `multi-timeframe-storage.md`,
`quant-infra-db-changes.md`). Read this before touching ingest, storage, or the read API.

> **Status:** **Phase 2 complete (2026-06-01)** — the modules below are built and live:
> `config/`, `db/` (asyncpg + models + repos over `db_market_data`), `cache/` (own Redis:
> write-through hot-window + single-flight lock), `ingest/` (tvkit client + service + CLI +
> backfill), `api/` (read API + owner-mode `/admin/ingest`), `snapshot/` (DB → Parquet). The
> read path is **hot/warm** (Redis → DB → write-through); cold-path auto-fetch-on-read is
> deferred (single-flight primitive built, ingest is a separate path). The gateway proxies
> `/api/v2/engines/market-data/*` here. Phases 3 (csm-set) and 4 (tfex) reader flags shipped;
> **Phase 5** is partial (csm-set cut over & verified, tfex pending); **Phase 6 docs** shipped.

> **Phase 6 documentation (2026-06-02).** Reference docs now live under
> [`../../docs/`](../../docs/) (hub: [`../../docs/README.md`](../../docs/README.md)) —
> architecture, API (with curl examples), operations, and data-model. Companion knowledge:
> [`data-flow.md`](data-flow.md), [`deployment.md`](deployment.md),
> [`api-contract.md`](api-contract.md). This file remains the design-rationale digest; the
> `docs/` tree is the operate/extend reference.

---

## The one invariant

> The tvkit cookie and the TradingView call live **entirely inside this service**. However
> a strategy's request resolves — Redis, TimescaleDB, or a fresh fetch — the strategy only
> ever talks to the gateway. **It never holds a credential and never calls TradingView.**

Everything below exists to uphold this.

---

## Canonical request flow (hot / warm / cold)

A strategy asks the gateway for `(symbol, timeframe, range)`; the gateway auth-gates and
**proxies** to this service on `:8300`, which resolves the request:

| Path | Hops | When |
|---|---|---|
| **Hot** | Redis (own sidecar) hit → return | repeated / latest-bar reads (common case) |
| **Warm** | Redis miss → TimescaleDB hit → write-through Redis → return | bar already ingested |
| **Cold** | DB miss/stale/gap → **ingest** (tvkit fetch) → idempotent upsert → write-through → return | only here does anyone call TradingView — always the engine |

Worked example — `S501!` at `5m`:

```
strategy ─GET /api/v2/engines/market-data/ohlcv?symbol=S501!&timeframe=5m&range=─▶
  gateway (auth-gate + PROXY) ─▶ quant-marketdata-engine :8300
     1. Redis HIT ───────────────▶ return
     2. TimescaleDB market_data.ohlcv HIT ─▶ write-through ▶ return
     3. MISS/gap → single-flight tvkit fetch → ON CONFLICT upsert → write-through ▶ return
```

**Edge cases the build must handle:**
- **Concurrent identical requests** → single-flight lock (dedupe on
  `(symbol, timeframe, range)` in the own Redis) so TradingView is hit once, not N times.
- **Partial range** (DB has 05-01→05-28, caller wants →now) → fetch only the missing tail,
  upsert, return the full contiguous range. Idempotent overlap is safe.
- **infra-db down** → strategies can still read the **Parquet snapshot** (offline backtest
  path). Both originate from the same DB; neither is a tvkit fetch.

---

## tvkit-cookie ownership contract

- Auth passes via **`TVKIT_AUTH_TOKEN`** — a **JSON cookie string** (NOT a JWT). Required
  key: `sessionid`; optional: `sessionid_sign`, `device_t`, `tv_ecuid` (extra keys
  allowed). `json.loads`-parse it and pass as `cookies=` to `tvkit.api.chart.OHLCV`.
- **This service is the sole holder.** No strategy / gateway / host `.env` carries it.
- **Bar depth** is set by `bars_count` / a `--bars N` flag; the account is premium
  (`max_bars=20000`). For sub-daily intervals (5m/1h) the anonymous 5,000-bar cap binds
  fast, so authentication matters even more than for dailies.
- **Never commit; never log.** Keep in a gitignored `.env` / `.tmp/` file. Inject with
  command substitution `"$(cat .tmp/tvkit_token.json)"` — **do NOT** `set -a; . file`
  (the JSON has spaces → it word-splits and silently falls back to anonymous, capped at
  5,000 bars). Sessions expire → `ProfileFetchError`; re-login and re-extract.
- Full reference: umbrella agent memory `reference-tvkit-tradingview-auth`.

---

## Multi-timeframe storage model (D10 — Option A + CAGGs)

Canonical table `market_data.ohlcv`, **PK `(symbol, timeframe, ts)`**, store each timeframe
**as tvkit returns it**:

| column | type | notes |
|---|---|---|
| `symbol` | `text` | `S501!`, `S50M2026`, `SET:SET50`, `SET:XXX` |
| `timeframe` | `text` | `'1d' \| '1h' \| '5m'` (enum-checked) |
| `ts` | `timestamptz` | **bar-open time, stored UTC** (display Asia/Bangkok) |
| `open/high/low/close` | `numeric(18,6)` | never `float`; futures `1d close` = **settlement** |
| `volume` | `numeric(20,4)` | |
| `open_interest` | `numeric(20,4)` | **futures only**, NULL for equities — carry from day one |
| `source` | `text` | provenance, e.g. `'tvkit'` |
| `ingested_at` | `timestamptz` | upsert audit |

- **Store finest grain you fetch** (e.g. 5m) as raw rows; **also store any TF that is not a
  faithful rollup as authoritative rows** — i.e. futures `1d` (settlement). **Never roll
  futures daily from intraday** — the daily close is the settlement price, respects the
  session/auction boundary, and TFEX has a night session.
- **Derive other TFs with continuous aggregates** off the base grain (`ohlcv_15m/1h/4h`).
  A new strategy wanting a new TF = one new CAGG, zero re-fetch — and because they all
  derive from the same base, every reader sees identical boundaries (cannot disagree).
- **Keep `1d` even alongside 1h/5m:** different PK (no collision); it's the smallest table;
  it carries deep history (10+ yr) intraday cannot reconstruct, and the settlement series.
- **Volume reality for S50:** ~13k 5m rows/sym/yr → tens of thousands/yr, not millions.
  **Timescale handles this trivially — do not reach for the lake (DuckDB) for S50.**
  Reserve the lake for tick / many-hundred-symbol intraday (D5).

### The `S501!` continuous question — **pinned: option (b)**

`S501!` is TradingView's **front-month continuous** future. "`S501!` 5m" has two meanings
that differ across a roll: **(a)** TradingView's native non-back-adjusted continuous (price
gap at each roll) vs **(b)** a system-derived back-adjusted continuous (no gap, matches what
strategies were validated on).

**Decision (Phase 0 ADR — option (b)):** the read API serves the **system-derived
back-adjusted continuous** as the default under `S501!`, exposed through the adjust-on-read
contract — `adjusted=true` (default) → roll-adjusted, `adjusted=false` → native (a). The
strategy was validated on the back-adjusted series (the `09` mirror builds its own
`ohlcv_continuous`; native `S501!` is only a Parquet cross-check there). **Dated contracts**
(`S50M2026`, …) are **independently addressable**. Store **roll dates** so back-adjustment
is adjust-on-read (the futures analogue of dividend adjustment, D2). `5m` is base grain →
stored raw, never CAGG-derived. Source of truth:
[`../../../.claude/knowledge/feature-market-data-engine.md`](../../../.claude/knowledge/feature-market-data-engine.md).

Symbol convention:

| symbol | meaning | role |
|---|---|---|
| `S501!` (`TFEX:S501!`) | front-month continuous | **primary fetch + signal source** |
| `S502!` | second-month continuous | optional (roll detection / term structure) |
| `S50H26`/`S50M26`/`S50U26`/`S50Z26` | dated contracts | optional — per-contract OI / basis / settlement |
| `SET:SET50` | underlying cash index | reference |

---

## Companion tables (in `quant-infra-db`)

| table | purpose |
|---|---|
| `market_data.corporate_actions` | splits / dividends (equities) **+ futures roll dates** — adjust-on-read |
| `market_data.adjusted_view` (or CAGG) | split/div/roll adjust applied on read (D2) |
| `market_data.universe_membership` | as-of dated SET constituents (point-in-time; no survivorship bias) |
| `market_data.contract_specs` *(optional, future)* | per-contract tick size, multiplier, expiry, roll dates |

Idempotent upsert contract: `INSERT … ON CONFLICT (symbol, timeframe, ts) DO UPDATE`.

---

## Realized schema (Phase 1 — COMPLETE, in `quant-infra-db`)

> Phase 1 shipped in `quant-infra-db` (`feat/market-data-schema-phase1`). This is the exact
> contract Phase 2 ingest/read code writes/reads. Connect via `Settings.market_data_dsn`.

- **Database:** **`db_market_data`** (dedicated DB, not a `db_gateway` schema — decided in
  Phase 1 per D4/D7); schema **`market_data`**. DSN host inside containers: `quant-postgres:5432`.
- **`market_data.ohlcv`** (hypertable on `ts`, 30-day chunks): columns
  `symbol text`, `timeframe text` (CHECK ∈ `1d|1h|5m`), `ts timestamptz` (bar-open UTC),
  `open/high/low/close numeric(18,6)` (CHECK >0; `high>=low`), `volume numeric(20,4)` (CHECK ≥0,
  default 0), `open_interest numeric(20,4)` (NULL for equities; CHECK NULL or ≥0),
  `source text` (default `'tvkit'`), `ingested_at timestamptz` (default now()).
  **PK `(symbol, timeframe, ts)`** → upsert `ON CONFLICT (symbol, timeframe, ts) DO UPDATE`.
  Read index `(symbol, timeframe, ts DESC)`. Compression `segmentby (symbol, timeframe)` after 7d.
  **Prices are `numeric(18,6)`** (not the 08/09 mirror's `(18,4)`) — shared multi-asset store.
- **`market_data.corporate_actions`** — PK `(symbol, ex_date, action_type)`;
  `action_type ∈ split|dividend|roll`; `ratio numeric(18,8)` (>0, the **price back-adjustment
  multiplier** the engine computes); `amount numeric(18,6)` (raw magnitude, audit); `note text`.
- **`market_data.universe_membership`** — PK `(as_of, symbol, index_name)`; `index_name` default
  `'SET'`. As-of dated; the engine seeds it in Phase 2.
- **`market_data.ohlcv_adjusted`** (VIEW) — `price * exp(sum(ln(ratio)))` over actions dated
  strictly after each bar; exposes `adjustment_factor`. Recomputes on read (reflects new actions
  immediately). Equity split/dividend path is live; exact futures-roll parity ports in Phase 4.
- **`cagg_ohlcv_1h` / `cagg_ohlcv_4h`** — continuous aggregates off the `timeframe='5m'` base
  (`first/max/min/last/sum`), `WITH NO DATA` + refresh policies. Fetched `1d` stays authoritative.
- **`src/db/` (in `quant-infra-db`):** `OHLCVBarRow`, `CorporateActionRow`,
  `UniverseMembershipRow` (Pydantic v2, `Decimal`, UTC validators) + `upsert_ohlcv`,
  `fetch_ohlcv`, `upsert_corporate_actions`, `upsert_universe_membership`; `Settings.market_data_dsn`.

## infra-db schema touchpoints (the Phase-1 reconciliation context)
- **Reconcile vs retire** the existing tfex mirror
  `09_schema_db_tfex_s50_multi_tf_swing_ohlcv.sql` (`ohlcv_raw` per-contract `S50H2026`/… +
  its own back-adjusted `ohlcv_continuous`, currently Parquet-sourced). Phase 1 *inverts*
  it to DB-canonical. **Pinned (Phase 0 ADR): RETIRE — build the shared `market_data` schema
  fresh, then migrate.** `09`'s shape (per-contract column + separate continuous table, no
  `1d`, in the strategy's DB) is incompatible with the unified `(symbol,timeframe,ts)` +
  adjust-on-read target; seeding would lock in the wrong shape. Phase 4 ports `09`'s roll
  logic (volume-crossover, `roll_offset_days=5`, `adjustment_factor`) into adjust-on-read +
  roll dates, backfills the data into `market_data.*`, demotes tfex `db_writer.py` to a
  reader, then drops `ohlcv_raw`/`ohlcv_continuous`. Source of truth:
  [`../../../.claude/knowledge/feature-market-data-engine.md`](../../../.claude/knowledge/feature-market-data-engine.md).
- Data stays on **local SSD**; NAS migration deferred (D9 — Mongo unsupported on NFS;
  Postgres fragile; NAS = backups/WAL archive only, or an iSCSI zvol if live data must move).

---

## Decision Log D1–D10 (one-liners)

D1 Timescale canonical (daily) · D2 store raw + adjust-on-read · D3 Parquet snapshot =
backtest cache · D4 standalone service + gateway proxy · D5 lake-first only for heavy
intraday (not S50) · D6 flagged/incremental migration (`CSM_OHLCV_SOURCE`) · D7 own
repo/service (this one) · D8 own Redis sidecar + single-flight lock · D9 local SSD, NAS
deferred · D10 Option A multi-TF PK + CAGGs, futures `1d`=settlement, `S501!` continuous.

---

## Where this maps in code (Phase 2 target layout)

```
src/quant_marketdata_engine/
  ingest/   tvkit_client.py (sole cookie owner) · upsert.py (ON CONFLICT) · single-flight lock
  api/      FastAPI app (:8000): /health · /ohlcv · /ohlcv/adjusted · /universe (auth-gated)
  snapshot/ exporter.py (DB → Parquet for offline backtest scans)
  config/   pydantic-settings Settings (MARKETDATA_ENGINE_* + TVKIT_AUTH_TOKEN)
```

See [`../../docs/plans/ROADMAP.md`](../../docs/plans/ROADMAP.md) Phase 2 for the full
deliverable list and exit criteria.
