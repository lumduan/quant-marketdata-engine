# Phase 1: quant-infra-db — shared `market_data` schema

**Feature:** feature-market-data-engine — Phase 1: Shared `market_data` schema
**Branch:** `feat/market-data-schema-phase1` (in the **`quant-infra-db`** repo)
**Created:** 2026-06-01
**Status:** Complete
**Completed:** 2026-06-01
**Depends On:** Phase 0 — ADR + Repo Bootstrap (Complete, 2026-06-01)

> **Repo boundary.** This phase's schema/code lands in **`quant-infra-db`'s own PR**, not
> this repo. This document (the plan) plus the ROADMAP/knowledge updates land in
> `quant-marketdata-engine` (this repo). The umbrella ROADMAP checkmark + ADR realized-schema
> note land in the umbrella repo. One branch + PR per repo.

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Schema](#schema)
6. [Implementation Steps](#implementation-steps)
7. [File Changes](#file-changes)
8. [Test Strategy](#test-strategy)
9. [Edge Cases](#edge-cases)
10. [Success Criteria](#success-criteria)
11. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 1 creates the **shared canonical `market_data` store** in `quant-infra-db` — the
prerequisite for everything downstream in `feature-market-data-engine`. The standalone
`quant-marketdata-engine` service (this repo) becomes the **sole writer** of these tables in
Phase 2; the gateway proxies reads; strategies become readers (Phases 3–4). Phase 1 is
**schema + Pydantic row models + idempotent upsert helpers + tests only** — no fetch, no
read API, no engine code.

### Parent Plan Reference

- Umbrella feature roadmap: [`../../../plans/feature-market-data-engine/ROADMAP.md`](../../../plans/feature-market-data-engine/ROADMAP.md) (Phase 1)
- This repo's roadmap: [`ROADMAP.md`](ROADMAP.md) (Phase 1)
- The binding ADR: `quant-trading-system/.claude/knowledge/feature-market-data-engine.md` (D1–D10)
- Design notes: `plans/feature-market-data-engine/quant-infra-db-changes.md`, `multi-timeframe-storage.md`

### Key Deliverables (in `quant-infra-db`)

1. **`init-scripts/01_create_databases.sql`** — add `db_market_data` (`\gexec` guard)
2. **`init-scripts/02_enable_timescaledb.sql`** — enable TimescaleDB in `db_market_data`
3. **`init-scripts/10_schema_market_data.sql`** — `market_data.ohlcv` hypertable +
   `corporate_actions` + `universe_membership` + `ohlcv_adjusted` view
4. **`init-scripts/11_market_data_caggs.sql`** — `cagg_ohlcv_1h` / `cagg_ohlcv_4h`
5. **`src/db/models.py`** — `OHLCVBarRow`, `CorporateActionRow`, `UniverseMembershipRow`
6. **`src/db/repositories.py`** — `upsert_ohlcv`, `fetch_ohlcv`, `upsert_corporate_actions`,
   `upsert_universe_membership`
7. **`src/config.py`** — `market_data_dsn`
8. **Tests** — unit (`test_models.py`, `test_repositories.py`) + infra (`test_postgres.py`)

---

## AI Prompt

The following prompt was used to generate this phase:

```
You are a senior backend/data-platform engineer working in the `quant-trading-system`
meta-repo (a Claude Code session). You are implementing Phase 1 — quant-infra-db: shared
`market_data` schema of the `feature-market-data-engine` initiative. Work autonomously,
plan before you code, and respect the multi-repo boundaries described below.

STEP 0 — READ BEFORE YOU TOUCH ANYTHING
Read these docs in full and reconcile them before planning. Quote/derive the actual schema
decisions from them — do not invent a schema:
- CLAUDE.md (umbrella system map, network/ingestion contract, cross-cutting rules)
- plans/feature-market-data-engine/ROADMAP.md (you will tick the Phase 1 checkmark here when done)
- plans/feature-market-data-engine/quant-infra-db-changes.md (authoritative DB-change design for this phase, if present)
- plans/feature-market-data-engine/multi-timeframe-storage.md and request-flow.md (storage model + access pattern)
- .claude/knowledge/feature-market-data-engine.md (the accepted ADR — D1–D10 decisions; treat as binding)
- quant-marketdata-engine/docs/plans/ROADMAP.md (the engine repo's own roadmap)
- quant-marketdata-engine/CLAUDE.md (engine repo conventions)
- quant-infra-db/CLAUDE.md (the repo you are actually changing — its layout, migration tooling, quality gate)
- strategies/csm-set/docs/plans/examples/phase1-sample.md (the EXACT plan-document format you must mirror)

CRITICAL MULTI-REPO RULE
The sub-directories are independent git repositories with their own remotes/CI and are
gitignored by the umbrella. The schema implementation belongs to the `quant-infra-db/` repo
and must be branched/committed/PR'd there. Do NOT commit sub-repo code from the umbrella. The
plan markdown and some knowledge updates land in `quant-marketdata-engine/` and the umbrella
per the instructions below — be explicit about which repo each change/commit/PR belongs to and
create a separate branch + PR per affected repo.

STEP 1 — PLAN BEFORE CODE (gated)
Before writing any schema/migration code, author a complete implementation plan and save it to:
  quant-marketdata-engine/docs/plans/{phase_name}.md
where {phase_name} is a clear slug for this phase (e.g. phase1-quant-infra-db-market-data-schema.md
— match the naming style already used in that docs/plans/ directory).
The plan document MUST:
- Follow the structure/sections of strategies/csm-set/docs/plans/examples/phase1-sample.md.
- Embed the ORIGINAL TASK PROMPT (this prompt / the user's instruction) verbatim in a clearly
  labelled section, as the sample does.
- Specify the concrete `market_data` schema: tables, columns + Postgres types, primary/unique
  keys, the multi-timeframe storage model, TimescaleDB hypertable(s) + chunk interval +
  partitioning/compression policy, indexes for the documented read path, and retention if
  specified by the ADR/design docs.
- Honor the cross-cutting rules: monetary/price values as NUMERIC/Decimal (never float),
  timestamps stored in UTC (timestamptz), idempotent upserts (INSERT … ON CONFLICT) where the
  engine will write OHLCV.
- Define migration mechanics consistent with quant-infra-db's existing migration tooling
  (discover and reuse it — do NOT introduce a new framework): forward migration + verified
  rollback, ordering, and how it's applied in the compose/bootstrap flow.
- List the test strategy (schema/migration tests against a real Postgres/TimescaleDB,
  idempotency of upserts, constraint enforcement, hypertable creation) with the repo's stated
  coverage target.
- Enumerate edge cases (duplicate bars, gap handling, timeframe enum/validation, timezone
  correctness, large-row-count partitioning per the ADR's ~50M rows/yr intraday threshold) and
  backward-compatibility/migration impact on existing infra.
- Note the doc/checkmark/knowledge updates required (Step 3).
Keep the plan tight and senior-level — decisions with rationale, not narration.

STEP 2 — IMPLEMENT (in quant-infra-db)
1. In quant-infra-db/, create a new feature branch (e.g. feat/market-data-schema-phase1).
2. Implement the `market_data` schema exactly as planned: migration file(s), any seed/enum
   types, TimescaleDB hypertable + policies, and indexes.
3. Add tests proving: migration applies cleanly + rolls back, hypertable is created, OHLCV
   upsert is idempotent, constraints reject bad rows (negative/zero where invalid, wrong
   timeframe, naive timestamps), and the documented read query is index-backed.
4. Quality gate (run via uv run, never bare python/pip), and meet quant-infra-db's stated bar
   (ruff check + ruff format, mypy, pytest ≥80%). Re-run ruff format --check AFTER any final
   edits/seds so formatting isn't invalidated. Do not push with a red gate.
5. Bring-up sanity: confirm the schema applies in the quant-infra-db compose path (infra-db is
   first in the bring-up order and owns quant-network).
Constraints: strict typing, structured errors/logging in any helper code, input validation on
any schema-management script, no secrets committed, simplest correct design over clever.

STEP 3 — DOCS, ROADMAPS, KNOWLEDGE
Update all of the following that apply, each in its correct repo:
- Tick the Phase 1 checkmark / update status in plans/feature-market-data-engine/ROADMAP.md
  (umbrella) and reflect progress in quant-marketdata-engine/docs/plans/ROADMAP.md.
- Update the engine-catalog/Phase status lines in umbrella CLAUDE.md only if the phase change
  warrants it. Do not over-edit.
- Create/update knowledge or playbook notes for the realized schema in the appropriate
  locations: quant-marketdata-engine/CLAUDE.md, quant-marketdata-engine/.claude/*, umbrella
  CLAUDE.md, and umbrella .claude/* (e.g. record the final market_data table/column contract in
  the feature knowledge doc so downstream Phase 2 work can rely on it).
- If quant-infra-db/CLAUDE.md documents its schemas/migrations, add the market_data schema there too.

STEP 4 — COMMIT & PR (per repo)
Only after the gate is green:
- Commit and open a PR in EACH affected repo on its own branch — at minimum quant-infra-db
  (schema + tests) and quant-marketdata-engine (plan doc + roadmap/knowledge), plus the umbrella
  repo (ROADMAP checkmark + knowledge). Keep each repo's commit scoped to that repo.
- Use clear conventional-commit messages and PR descriptions that link the phase, summarize the
  schema, list tests run + results, and note migration/rollback impact.
- Do NOT edit sub-repo history from the umbrella; cd into each repo for its commit/PR.

DELIVERABLES
- New market_data schema migration(s) + tests merged-ready in quant-infra-db (gate green).
- quant-marketdata-engine/docs/plans/{phase_name}.md plan doc (with the original prompt embedded,
  csm-set format).
- Updated ROADMAP checkmarks and knowledge/playbook notes across the four locations listed.
- One PR per affected repo, each summarizing scope, tests, and migration impact.
Report back with: the chosen {phase_name}, the final schema (tables/keys/hypertable policy),
test results, and the PR links per repo. If a design doc and the ADR disagree on any schema
decision, STOP and surface the conflict instead of guessing.
```

---

## Scope

### In Scope (Phase 1)

| Component | Description | Status |
|---|---|---|
| `db_market_data` database | Dedicated shared store (ADR D4/D7) | Complete |
| `market_data.ohlcv` hypertable | PK `(symbol, timeframe, ts)`; raw bars | Complete |
| `market_data.corporate_actions` | splits/dividends + futures roll dates | Complete |
| `market_data.universe_membership` | as-of dated point-in-time constituents | Complete |
| `market_data.ohlcv_adjusted` view | adjust-on-read (D2); recomputes on action insert | Complete |
| `cagg_ohlcv_1h` / `cagg_ohlcv_4h` | derived TFs off the 5m base | Complete |
| Pydantic row models + upsert/fetch helpers | `src/db/` | Complete |
| `market_data_dsn` | `src/config.py` | Complete |
| Unit + infra tests | ≥80% coverage gate | Complete |

### Out of Scope (Phase 1)

- Any engine / gateway / strategy code (Phase 2+)
- The tvkit fetch path, read API, Redis sidecar (Phase 2, this repo)
- `market_data.contract_specs` (ADR: optional/future)
- The Parquet snapshot exporter and the intraday lake (D3/D5)
- One-time data backfill from `csm-set/data/raw/` (Phase 2)
- Retiring the tfex `09` mirror (Phase 4, in tfex's PR)

---

## Design Decisions

### 1. Destination = a new `db_market_data` database (not a `db_gateway` schema)

The ADR §7 / ROADMAP left this an open "Phase 0 call". Chosen: a **dedicated database**.
Rationale: the whole feature exists to make Market Data a standalone, independently-owned
service (D4/D7). Putting its canonical store inside the gateway's database re-couples at the
data layer what D7 decoupled at the service layer. Tables remain schema-qualified
`market_data.*` (a Postgres schema inside the dedicated DB), matching all docs. Cost: one DSN
+ two init-script edits — small and one-time.

### 2. Price precision = `numeric(18,6)`, volume/OI = `numeric(20,4)`

Documented divergence: ROADMAP Phase 1 + `multi-timeframe-storage.md` + the ADR §5 wire example
(`"912.400000"`) all specify `numeric(18,6)`; the looser `quant-infra-db-changes.md` scoping note
said `(18,4)` "to match 08/09". Chosen: **`(18,6)`** — this is a shared multi-asset store and the
binding ADR/ROADMAP are explicit; the 08/09 mirror is being retired (ADR §7) so matching it is not
a constraint. Surfaced to the user, who confirmed. (No ADR-vs-design *conflict* requiring a STOP —
the authoritative ROADMAP/ADR text is consistent; only the scoping note differed.)

### 3. Option A multi-timeframe — `timeframe` in the PK; bars stored as fetched (D10)

`PK (symbol, timeframe, ts)`. Futures `1d` close = settlement, stored authoritative, **never**
rolled up from intraday. Coarser TFs a strategy didn't fetch are derived via continuous
aggregates off the 5m base (`11_*`), so all readers see identical boundaries. `5m` is base grain,
stored raw, never CAGG-derived.

### 4. Adjust-on-read as a VIEW, not a CAGG (D2)

`ohlcv_adjusted` is a plain SQL view: each bar's price is multiplied by the cumulative product
(`exp(sum(ln(ratio)))`) of `corporate_actions.ratio` over actions dated strictly after the bar.
A view recomputes on read → it **automatically reflects a newly inserted action row** (the Phase 1
success criterion), and never caches a stale adjusted series. Phase 1 ships the equity split/
dividend path as the proven, testable case; the exact futures-roll back-adjustment parity is ported
in Phase 4 (ADR §7), diff-tested before cutover. The `ratio` column holds the engine-computed price
multiplier; `amount` holds the raw magnitude for audit.

### 5. Migration mechanics = numbered idempotent init-scripts (reuse, no new framework)

`quant-infra-db` has no migration framework — it applies numbered idempotent SQL via
`docker-entrypoint-initdb.d` on first container boot, lexically ordered (`10`/`11` run after
`01`/`02`/`09`). Forward migration = the new/edited scripts. Rollback (documented in the `10_*`
header): `DROP SCHEMA market_data CASCADE;` + `DROP DATABASE db_market_data;`. A fresh container
volume re-applies the scripts from scratch — the forward/rollback round-trip the infra suite
exercises. All scripts are idempotent (`IF NOT EXISTS`, `if_not_exists => TRUE`, `\gexec`).

---

## Schema

### `market_data.ohlcv` (hypertable on `ts`, 30-day chunks)

| column | type | notes |
|---|---|---|
| `symbol` | `text` NOT NULL | `S501!`, `SET:PTT`, `S50M2026`, `SET:SET50` |
| `timeframe` | `text` NOT NULL | CHECK ∈ {`1d`,`1h`,`5m`} |
| `ts` | `timestamptz` NOT NULL | bar-open, UTC |
| `open/high/low/close` | `numeric(18,6)` NOT NULL | CHECK > 0; `high >= low`; futures `1d` close = settlement |
| `volume` | `numeric(20,4)` NOT NULL DEFAULT 0 | CHECK ≥ 0 |
| `open_interest` | `numeric(20,4)` NULL | futures only; CHECK NULL or ≥ 0 |
| `source` | `text` NOT NULL DEFAULT `'tvkit'` | provenance |
| `ingested_at` | `timestamptz` NOT NULL DEFAULT now() | upsert audit |

- **PK `(symbol, timeframe, ts)`** → `ON CONFLICT (symbol, timeframe, ts) DO UPDATE`.
- Index `idx_ohlcv_symbol_tf_ts (symbol, timeframe, ts DESC)` (read path).
- Compression `segmentby (symbol, timeframe)`, `orderby ts DESC`, policy after 7 days. No drop policy.

### `market_data.corporate_actions`
PK `(symbol, ex_date, action_type)`; `action_type` ∈ {`split`,`dividend`,`roll`};
`ratio numeric(18,8)` (>0, price back-adjustment multiplier), `amount numeric(18,6)` (audit), `note text`.

### `market_data.universe_membership`
PK `(as_of, symbol, index_name)`; `index_name` default `'SET'`; index `(index_name, as_of DESC)`.

### `market_data.ohlcv_adjusted` (view)
`open/high/low/close * cumulative_product(ratio of later-dated actions)`, plus `adjustment_factor`;
volume/OI passed through.

### `cagg_ohlcv_1h` / `cagg_ohlcv_4h` (continuous aggregates)
`time_bucket` + `first(open)/max(high)/min(low)/last(close)/sum(volume)` off `timeframe='5m'`,
`WITH NO DATA` + `add_continuous_aggregate_policy`.

---

## Implementation Steps

1. Branch `feat/market-data-schema-phase1` in `quant-infra-db`.
2. Edit `01_create_databases.sql` (add `db_market_data`) + `02_enable_timescaledb.sql`.
3. Write `10_schema_market_data.sql` (schema, hypertable, indexes, compression, companion tables, view).
4. Write `11_market_data_caggs.sql` (1h/4h CAGGs + policies).
5. Add `OHLCVBarRow` / `CorporateActionRow` / `UniverseMembershipRow` to `models.py`.
6. Add `upsert_ohlcv` / `fetch_ohlcv` / `upsert_corporate_actions` / `upsert_universe_membership`
   to `repositories.py`; export in `__init__.py`; add `market_data_dsn` to `config.py`.
7. Extend `test_models.py`, `test_repositories.py` (unit) and `test_postgres.py` (infra).
8. Apply scripts to the live container; run `uv run pytest` (unit) + `uv run pytest -m infra`.
9. Gate green (ruff/format/mypy/pytest ≥80%); re-run `ruff format --check` after final edits.

---

## File Changes

| File (in `quant-infra-db`) | Action | Description |
|---|---|---|
| `init-scripts/01_create_databases.sql` | MODIFY | Add `db_market_data` (`\gexec`) |
| `init-scripts/02_enable_timescaledb.sql` | MODIFY | Enable TimescaleDB in `db_market_data` |
| `init-scripts/10_schema_market_data.sql` | CREATE | Schema + ohlcv + companions + view |
| `init-scripts/11_market_data_caggs.sql` | CREATE | 1h/4h continuous aggregates |
| `src/db/models.py` | MODIFY | 3 new row models + timeframe/action enums |
| `src/db/repositories.py` | MODIFY | 4 new upsert/fetch helpers |
| `src/db/__init__.py` | MODIFY | Export new symbols |
| `src/config.py` | MODIFY | `market_data_dsn` |
| `tests/test_models.py` | MODIFY | Unit tests for new models |
| `tests/test_repositories.py` | MODIFY | Unit tests for new helpers |
| `tests/test_postgres.py` | MODIFY | Infra tests (`-m infra`) |
| `CHANGELOG.md`, `CLAUDE.md` | MODIFY | Schema doc + Compose diagram |

---

## Test Strategy

- **Unit (default run, mocked asyncpg pools; coverage gate ≥80%):** model validation (valid rows,
  bad timeframe/action-type rejected, naive→UTC coercion, non-UTC rejected, non-positive price /
  negative volume / negative OI / high<low rejected, `Decimal` round-trip); repository SQL shape
  (`INSERT … ON CONFLICT (<natural key>)`, param counts, empty-input short-circuit,
  `RepositoryError` wrapping, `fetch_ohlcv` 3-/4-param query forms).
- **Infra (`@pytest.mark.infra`, live TimescaleDB; transaction-rolled-back so the DB stays
  pristine):** `db_market_data` reachable + TimescaleDB present; `market_data.ohlcv` is a
  hypertable; column types are `numeric(18,6)`/`(20,4)` + timeframe CHECK; companion tables + view
  exist; CAGGs registered; **upsert idempotency** (same key twice → 1 row, updated); **constraint
  rejection** (bad timeframe, non-positive price, negative volume, high<low); **adjusted view
  recomputes** when an action is inserted (prior bar back-adjusts, ex-date bar unchanged);
  documented read query is **index-backed** (`EXPLAIN` shows Index Scan, not Seq Scan).

---

## Edge Cases

| Case | Handling |
|---|---|
| Duplicate bars | Idempotent `ON CONFLICT (symbol, timeframe, ts) DO UPDATE` |
| Partial range / gaps | Upsert overlap is safe (a Phase-2 fetch concern; schema-neutral) |
| Invalid timeframe | DB CHECK + Pydantic enum |
| Invalid action type | DB CHECK + Pydantic enum |
| Naive / non-UTC timestamps | `timestamptz` + `_ensure_utc` (naive→UTC, non-UTC rejected) |
| Bad OHLC (≤0, high<low) | DB CHECK + Pydantic `model_validator` |
| Large row counts | 30-day chunks + compression; S50 ~152k rows/yr ≪ 50M lake threshold (ADR §4) |
| Futures daily | `1d` stored authoritative (settlement); CAGGs derive 1h/4h from 5m only |
| Backward compatibility | New DB/schema; **no change** to `db_csm_set`/`db_gateway`/`db_tfex_*`; `09` untouched |

---

## Success Criteria

- [x] `db_market_data` + `market_data` schema apply on `quant-network` (idempotent re-run = no-op)
- [x] `market_data.ohlcv` is a hypertable, PK `(symbol, timeframe, ts)`, `numeric(18,6)` prices
- [x] OHLCV upsert is idempotent (`ON CONFLICT … DO UPDATE`)
- [x] Constraints reject bad rows (timeframe, ≤0 price, negative volume, high<low)
- [x] `ohlcv_adjusted` view recomputes when a `corporate_actions` row is added
- [x] `cagg_ohlcv_1h` / `cagg_ohlcv_4h` registered as continuous aggregates
- [x] Documented read query is index-backed (Index Scan)
- [x] `uv run ruff check` + `ruff format --check` + `mypy src tests` clean
- [x] `uv run pytest` green, coverage ≥80% (achieved 98.4%); `uv run pytest -m infra` green (19/19)

---

## Completion Notes

### Summary

Implemented in `quant-infra-db` on `feat/market-data-schema-phase1`. The shared `market_data`
store lives in a dedicated `db_market_data` database with `numeric(18,6)` prices (both decisions
confirmed with the user). All four SQL scripts applied cleanly and idempotently against the live
TimescaleDB 2.27.0 / pg16 container; the adjusted view, hypertable, CAGGs, compression policy and
read-path index were all verified. Unit suite: 96 passed, 98.4% coverage. Infra suite: 19/19
passed (transaction-rolled-back, DB left pristine). Gate (ruff + ruff format + mypy strict +
pytest ≥80%) green.

### Issues Encountered

1. **Cross-field `high >= low` validator fired too early.** A `@field_validator("high")` reading
   `info.data["low"]` saw `None` because `high` is declared before `low` (Pydantic v2 validates in
   declaration order). Switched to `@model_validator(mode="after")`, which sees all fields.

### Decisions deferred to later phases

- Exact futures-roll back-adjustment parity → Phase 4 (diff-tested before tfex cutover).
- `contract_specs` table, Parquet snapshot, intraday lake → optional/future per the ADR.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.8)
**Status:** Complete
**Completed:** 2026-06-01
