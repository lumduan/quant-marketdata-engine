# Phase 4: tfex-s50-multi-tf-swing consumes the shared Market Data store

**Feature:** feature-market-data-engine — Phase 4: `strategies/tfex-s50-multi-tf-swing` reads the store behind a flag
**Branch (tfex, the code):** `feat/phase4-consume-marketdata-engine` (based on `main`)
**Sibling branch (this repo, the plan/docs):** `quant-marketdata-engine` → `docs/phase4-tfex-consume-plan`
**Sibling branch (umbrella):** `quant-trading-system` → `docs/market-data-phase4`
**Created:** 2026-06-02
**Status:** Complete
**Depends On:** Phase 0 (ADR) · Phase 1 (schema) · Phase 2 (engine + gateway proxy) · Phase 3 (csm-set reader, flag complete 2026-06-01)

> **Cross-repo note.** This document lives in `quant-marketdata-engine` because that is
> where the Market Data Engine's design record lives, but **all the Phase 4 code lands in
> the `strategies/tfex-s50-multi-tf-swing` repo.** Three repos are touched: tfex (the
> feature branch with the client + flag + tests), this repo (the plan doc + roadmap ticks),
> and the umbrella (roadmap/registry/catalog status). No `quant-infra-db` change this run —
> the schema-09 retirement is a documented follow-up. PRs are cross-linked; the tfex code PR
> is primary.

---

## Table of Contents

1. [Overview](#overview)
2. [Originating prompt](#originating-prompt)
3. [Objective, scope, non-goals](#objective-scope-non-goals)
4. [Phase 4 acceptance criteria (verbatim from the umbrella ROADMAP)](#phase-4-acceptance-criteria-verbatim-from-the-umbrella-roadmap)
5. [Locked decisions](#locked-decisions)
6. [Verified read-API contract](#verified-read-api-contract)
7. [Feature-flag design](#feature-flag-design)
8. [Read-client design](#read-client-design)
9. [Response → tfex raw-frame mapping](#response--tfex-raw-frame-mapping)
10. [Continuous build & the 09-mirror disposition](#continuous-build--the-09-mirror-disposition)
11. [File changes (tfex repo)](#file-changes-tfex-repo)
12. [Test plan & coverage](#test-plan--coverage)
13. [Backward-compat, migration, security, performance, rollback](#backward-compat-migration-security-performance-rollback)
14. [Cross-repo PR sequence & checkmark edits](#cross-repo-pr-sequence--checkmark-edits)
15. [Success criteria](#success-criteria)
16. [Completion notes](#completion-notes)

---

## Overview

### Purpose

Phase 3 made `strategies/csm-set` the first engine reader (flag `CSM_OHLCV_SOURCE`,
committed 2026-06-01). **Phase 4 makes `strategies/tfex-s50-multi-tf-swing` read OHLCV from
the same engine** (gateway-proxied at `/api/v2/engines/market-data/*`) instead of fetching
tvkit itself, behind `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE = mirror | engine` — default
`mirror` keeps the Phase-1 tvkit path byte-for-byte. It also reconciles tfex's standalone
TimescaleDB OHLCV mirror (init-script `09`) against the canonical `market_data.*` schema by
demoting it to a derived cache, so there is one canonical store.

### Parent plan references

- Umbrella feature roadmap (scope of record): [`../../../plans/feature-market-data-engine/ROADMAP.md`](../../../plans/feature-market-data-engine/ROADMAP.md) §"Phase 4"
- ADR (D1–D10, read contract, S501! decision): [`../../../.claude/knowledge/feature-market-data-engine.md`](../../../.claude/knowledge/feature-market-data-engine.md)
- Engine read-API source: `src/quant_marketdata_engine/api/routes.py`, `api/schemas.py`
- Sibling phase plan (the pattern this mirrors): [`phase3-csm-set-read-from-store.md`](phase3-csm-set-read-from-store.md)
- tfex seam: `strategies/tfex-s50-multi-tf-swing/src/.../data/{refresh.py,fetcher.py,continuous.py,store.py}`

### Decisions locked with the user

- **4h:** **deferred** — the engine serves only `1d|1h|5m`; `4h` (the `cagg_ohlcv_4h`
  aggregate is unrouted) is declined with a typed error, no local rollup (D10). Engine 4h
  route is a tracked follow-up.
- **Phase 3 box #3** (SET:SET index/sectors gap fix): **not done** in `1de4d65` — left
  unticked with a deferral note; only boxes #1/#2 ticked.
- **Schema 09 drop:** documented as a follow-up `quant-infra-db` PR; not in this run (the
  default `mirror` path still writes 09).

---

## Originating prompt

The following prompt initiated this work (embedded verbatim):

```
ROLE: You are Claude Code working inside the `quant-trading-system` umbrella workspace at
  `/home/batt/docker/quant-trading-system`. Each sub-directory is its own independent git repo
  with its own remote, CI, and history. NEVER edit a sub-project's history from the umbrella repo.
  For per-service work, `cd` into the sub-directory and use that repo's own tooling.

  OBJECTIVE
  Implement **Phase 4 — `strategies/tfex-s50-multi-tf-swing`: consume the shared Market Data store**
  of the `feature-market-data-engine` roadmap, AND retroactively fix the missing Phase 3 checkmarks
  the previous pass forgot. Phase 4 makes the tfex strategy read OHLCV from the canonical
  `quant-marketdata-engine` (host `:8300`, gateway-proxied under `/api/v2/engines/market-data/*`)
  instead of fetching tvkit itself, and reconciles/retires tfex's standalone TimescaleDB mirror so
  there is one canonical store.

  STEP 0 — READ FIRST (do not skip; quote what governs your choices back in the plan)
  Read and internalise:
    - `CLAUDE.md` (umbrella system map, engine catalog, network/port contract, cross-cutting rules)
    - `plans/feature-market-data-engine/ROADMAP.md` (umbrella feature roadmap — Phase 3 §, Phase 4 §;
      this is where the cross-cutting checkmarks live)
    - `quant-marketdata-engine/docs/plans/ROADMAP.md` (per-service roadmap — Phase 3 §, Phase 4 §,
      Decision Log D1–D10, the `S501!` continuous (a)/(b) question, the Current Status block)
    - `quant-marketdata-engine/CLAUDE.md` (ownership boundaries, hard rules, conventions)
    - `quant-marketdata-engine/.claude/knowledge/market-data-engine.md` and
      `quant-marketdata-engine/.claude/playbooks/development-workflow.md` (read contract, cookie rules)
    - `strategies/tfex-s50-multi-tf-swing/CLAUDE.md` and that repo's
      `docs/plans/ROADMAP.md` (the strategy's own quality gate, data layer, current architecture)
    - `quant-infra-db/init-scripts/09_schema_db_tfex_s50_multi_tf_swing_ohlcv.sql` (the existing
      standalone mirror: `db_tfex_s50_multi_tf_swing.ohlcv_raw` / `.ohlcv_continuous`) and the new
      canonical schema `quant-infra-db/init-scripts/10_schema_market_data.sql` +
      `11_market_data_caggs.sql` — you must reconcile/retire `09` against `market_data.*`
    - `strategies/csm-set/docs/plans/examples/phase1-sample.md` (the REQUIRED format for the plan doc)
    - How csm-set implemented Phase 3 as your reference pattern (the reader-side seam): its
      `CSM_OHLCV_SOURCE = parquet | db` flag, the httpx Market Data Engine client, the
      `MarketDataEngineLoader` + `build_ohlcv_loader` factory at the `daily_refresh` seam, and the
      `test_public_data_boundary_*` tests. Mirror this design for tfex; do not reinvent it.

  KEY DECISIONS THE PLAN MUST PIN (carry them from the ADR / Decision Log, do not invent new ones)
    - D4/D7: tfex reads ONLY via the gateway proxy `/api/v2/engines/market-data/*` (or the Parquet
      snapshot for offline backtests). tfex must NOT hold the tvkit cookie and must NOT call tvkit.
    - D2/D10: store raw; adjust on read. Futures `1d` close = **settlement**, never rolled up from
      intraday. Carry `open_interest`. Coarser TFs the strategy didn't fetch come from continuous
      aggregates, not local rollups.
    - D5: for S50 the lake is NOT needed (~13k rows/sym/yr) — multi-TF (5m / 1h / 4h / 1d) stays in
      TimescaleDB hot window. State this explicitly as the resolved intraday decision.
    - D10 `S501!` continuous: state which series tfex consumes ((a) TradingView-native non-back-adjusted
      vs (b) system roll-adjusted) per the ADR; if the ADR left it open, surface it as a blocker in the
      plan and choose the option that matches what the tfex strategy was validated on (back-adjusted
      continuity), documenting the assumption.
    - `09` mirror disposition: the ADR decided **RETIRE** (build fresh + migrate). Decide concretely
      whether to (i) drop/retire the `09` schema, (ii) demote it to a derived local cache, and how
      in-flight readers cut over. Any actual schema drop/migration in `quant-infra-db` is that repo's
      OWN PR — do not couple it into the tfex code PR.

  SCOPE — WHERE EACH CHANGE LANDS (this is multi-repo; keep PRs per-repo)
    1) `strategies/tfex-s50-multi-tf-swing` (its OWN repo, its OWN PR — the Phase 4 code):
       - Introduce a source flag mirroring csm-set, e.g. `TFEX_OHLCV_SOURCE = mirror | engine`
         (default = current behaviour so nothing breaks by default; `engine` = read the shared store).
       - Add an async httpx client to the gateway's `/api/v2/engines/market-data/*` (ohlcv, adjusted,
         universe), forwarding `X-API-Key`; a loader implementation behind the same factory seam tfex
         already uses for its data layer; map the multi-TF (5m/1h/4h/1d) + `open_interest` fields.
       - Stop the per-strategy tvkit fetch when `source=engine`; remove the cookie requirement on that
         path. Demote the local TimescaleDB mirror / any local store to a derived cache (materialised
         from the engine), not a parallel source of truth.
       - Reconcile the `09` mirror schema usage in code: point reads at `market_data.*` via the engine
         contract; leave a clear migration note for the infra-db drop.
    2) `quant-infra-db` (its OWN repo/PR) — ONLY if an actual SQL migration to retire/demote `09` is
       required this phase. If so, do it as a separate branch+PR in that repo; otherwise record it as a
       documented follow-up in the plan and DO NOT touch that repo now.
    3) `quant-marketdata-engine` repo — the plan markdown (below) + the Phase 4 checkmarks + Current
       Status update in `docs/plans/ROADMAP.md`, plus the Phase 3 checkmark fix.
    4) umbrella repo — Phase 3 + Phase 4 checkmarks in `plans/feature-market-data-engine/ROADMAP.md`,
       the engine-catalog/feature-registry status lines, and any knowledge/playbook updates.

  RETROACTIVE FIX — PHASE 3 CHECKMARKS (the previous pass forgot these; Phase 3 IS complete)
    - In `quant-marketdata-engine/docs/plans/ROADMAP.md` Phase 3 §: flip the three `[ ]` boxes to `[x]`
      (CSM_OHLCV_SOURCE flag; Parquet demoted to derived cache + tvkit fetch stopped on db source;
      SET:SET index + sectors gap fix), append the completion date (2026-06-01) and the
      "Exit criteria MET" note consistent with how Phases 1–2 are annotated.
    - In `plans/feature-market-data-engine/ROADMAP.md` Phase 3 §: mark the phase ✅ COMPLETE with the
      same evidence, and advance the top-of-file Status line + Current Status from "Phase 3 next" to
      "Phase 3 complete; Phase 4 in progress".
    - Verify against reality before ticking: Phase 3 shipped on branch
      `feat/phase3-read-from-marketdata-engine` off `live-test` (csm-set repo), built locally, not
      pushed. If you cannot confirm the work exists in that repo, DO NOT tick — report the discrepancy
      instead.

  PROCESS (in order)
    1) Create a feature branch in the tfex repo for the code work, e.g.
       `cd strategies/tfex-s50-multi-tf-swing && git checkout -b feat/phase4-consume-marketdata-engine`.
       (Check whether tfex's convention is to branch off `main` or a `live-test` integration branch, as
       csm-set did; follow the tfex repo's own convention and state which base you chose and why.) Use
       separate branches for the doc/roadmap PRs in the umbrella and engine repos.
    2) WRITE THE PLAN BEFORE ANY CODE. Create the implementation plan as a markdown file at
       `quant-marketdata-engine/docs/plans/phase4-tfex-consume-shared-store.md`, following the structure
       of `strategies/csm-set/docs/plans/examples/phase1-sample.md`. The plan MUST:
         - embed THIS ENTIRE PROMPT verbatim in a "Prompt" section (the sample shows where);
         - enumerate the design (flag, client, loader/factory seam, field mapping, `09` disposition,
           `S501!` (a)/(b) choice, intraday decision), file-by-file change list with project-relative
           paths, the test plan, the migration/rollback note, and the exit criteria;
         - list the cross-repo PR sequence and the checkmark edits.
       Do not start coding until the plan file is written.
    3) Implement the tfex changes per the plan.
    4) Update the checkmarks and status lines (Phase 3 fix + Phase 4) in both roadmaps.
    5) Create/update agent context where warranted (only if genuinely useful, not noise):
         - `quant-marketdata-engine/CLAUDE.md` and `quant-marketdata-engine/.claude/*`
         - umbrella `CLAUDE.md` (engine catalog / feature-registry status; tfex row in per-service impact)
         - umbrella `.claude/*` (knowledge note on the tfex reader cutover + the resolved `S501!` /
           intraday decisions; playbook step if bring-up order changes)
         - the tfex repo's own `CLAUDE.md`/`.claude/*` if its data-layer contract changed.

  QUALITY BAR (enforce; this is a strict-typed async Python 3.11 / FastAPI / uv codebase)
    - All commands via `uv run` (never bare python/pip). Respect each repo's gate; tfex's gate is
      ruff + mypy **strict** + pytest ≥90% on `adapters/` + `risk/`. Engine repo gate is ≥90% on core.
    - `mypy --strict` clean; full annotations, no bare `Any`; Pydantic models at every boundary, never
      raw dicts. `from __future__ import annotations` at module tops.
    - Async correctness: all HTTP via `httpx.AsyncClient`; `requests` forbidden in `src/`. No blocking
      calls on the event loop; single-flight / dedupe where the engine contract expects it.
    - Comprehensive error handling: upstream engine 5xx / gateway-down / auth failure → typed,
      module-local exceptions in `errors.py` inheriting a shared base; never `except Exception: pass`;
      never leak the tvkit cookie or API key in logs. Structured logging via
      `logging.getLogger(__name__)`, `%`-formatting; never `print`.
    - Security: `X-API-Key` constant-time handling; secrets only via gitignored `.env` +
      `pydantic-settings`; raw OHLCV stays private-side (do not breach the public-data boundary).
    - Money & time: `Decimal` for OHLC (string on the wire), never `float`; `ts` = bar-open UTC,
      display Asia/Bangkok.
    - Backward compatibility: the new source flag defaults to current behaviour; the `engine` path must
      be byte-for-byte equivalent to the old data for the same dates/timeframes — add a diff/parity test.
    - Idempotency & migration impact: document the `09` retire/demote migration and a rollback path;
      keep the Parquet snapshot usable offline so backtests don't hard-require infra-db being up.
    - Edge cases to cover explicitly: gateway/engine unavailable (clean degraded error, fall back to
      snapshot for backtests); partial range / missing tail; `S501!` roll boundary; equities vs futures
      (`open_interest` NULL for equities); timeframe enum rejection (`1d|1h|5m` + derived 4h); empty
      universe / missing index.

  TESTS (unit + integration; meet each repo's coverage gate)
    - Source-flag selection (mirror vs engine) resolves the right loader.
    - Engine client: success, auth-forwarding, upstream-down, malformed payload, partial range.
    - Parity test: `engine` source produces identical bars to the prior path for the same dates/TFs.
    - tfex's existing data-boundary / public-data tests still pass (the analogue of csm-set's
      `test_public_data_boundary_*`).
    - Multi-TF + `open_interest` + `S501!` continuity handling.

  VERIFY BEFORE COMMIT (run the FULL gate in each repo you touched; matches CI)
    `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest`
    Re-run `ruff format --check` AFTER any post-format edit/sed — late edits invalidate formatting.
    Report real results: if a gate fails or a step is skipped, say so with the output; do not claim
    green if it isn't. Note any PRE-EXISTING failures on the base branch that are unrelated to this
    change, and keep them out of your diff.

  COMMIT & PR (per-repo; Conventional Commits; do NOT edit sub-repo history from the umbrella)
    - tfex repo: `feat(data): read OHLCV from quant-marketdata-engine behind TFEX_OHLCV_SOURCE flag …`
    - engine repo: `docs(plans): add Phase 4 tfex-consume plan + tick Phase 3/4 roadmap`
    - umbrella repo: `docs(feature-market-data-engine): mark Phase 3 done, Phase 4 in progress`
    - quant-infra-db (only if a real `09` migration is in scope): its own branch + PR.
    Push each branch and open a PR on GitHub via `gh` for each repo touched. End every commit message
    with the required co-author trailer:
        Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
    End every PR body with:
        🤖 Generated with [Claude Code](https://claude.com/claude-code)

  FINAL REPORT (mandatory format)
    After all commit/push/PR operations, output an ASCII box-drawing table (characters
    ┌ ─ ┬ ┐ │ ├ ┼ ┤ └ ┴ ┘ — NOT a markdown pipe table), one row per repo, columns:
    Repo | Branch | Commit | GitHub. Repo = `owner/name` plus a short role note in parens
    (e.g. `(code)`, `(plan doc)`, `(umbrella docs)`). Commit = short SHA. GitHub = `PR #N → <url>`,
    or push status, or `local only`. Then summarise: what changed, the resolved `S501!`/intraday/`09`
    decisions, gate results per repo, and any deferred follow-ups (e.g. the infra-db `09` drop,
    Phase-5 adjustment-parity, end-to-end cutover).

  CONSTRAINTS / DO-NOT
    - Do not put the tvkit cookie anywhere in tfex; tfex never calls tvkit.
    - Do not add strategy-specific columns to shared tables; use the engine read contract as-is.
    - Do not cache adjusted bars as a source of truth; do not roll futures `1d` up from intraday.
    - Do not couple unrelated repos into one PR; keep code, plan-doc, and umbrella-doc changes separate.
    - Do not tick any checkmark you cannot verify against the actual repo state.
```

> **Decisions deviating from the prompt's instructions (resolved with the user):** (1) the
> Phase 3 retroactive fix ticks **only boxes #1/#2** — box #3 (SET:SET index/sectors) is
> **not** present in the Phase 3 commit `1de4d65` (verified: the commit touches no
> universe/index/sector code and its message doesn't mention it), so per the prompt's own
> "do not tick what you cannot verify" rule it stays `[ ]` with a deferral note. (2) The
> stale memory said Phase 3 was "not pushed"; it is in fact on `origin/live-test`. (3) The
> `4h` timeframe is deferred (the engine has no 4h route) rather than rolled up locally.
> (4) No `quant-infra-db` change this run — the schema-09 drop is a documented follow-up.

---

## Objective, scope, non-goals

**Objective.** Let tfex's owner-side refresh read RAW OHLCV from the Market Data Engine read
API when `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE='engine'`, returning the **identical** raw
Polars frame so the store → continuous → validator → db_writer chain is unchanged, with the
legacy tvkit path as the unchanged default. The back-adjusted continuous is built **locally**
from engine-served raw dated contracts.

**In scope.**
- A new async httpx read client for the engine (`/ohlcv`, raw only on this path).
- The `OHLCV_SOURCE` flag + a factory that routes `refresh_all` to the chosen fetcher.
- A new engine-backed `FetcherProtocol` adapter returning tfex's raw-frame shape (+OI).
- Demoting the 09 mirror to a derived cache (code + docs); local continuous build unchanged.
- Tests (client, fetcher, factory, parity, boundary) + docs + `.env.example`.

**Non-goals (Phase 4).**
- The engine **4h** read route (`cagg_ohlcv_4h`) — deferred; `4h` is declined client-side.
- The engine **native back-adjusted `S501!`** (futures-roll adjust-on-read) — Phase-5
  adjustment-parity; tfex builds the continuous locally meanwhile.
- The physical **schema-09 drop/migration** in `quant-infra-db` — separate follow-up PR.
- Adding **`1d`** to tfex's `Timeframe` domain (the strategy trades 5m/1h/4h; engine `1d`
  settlement is available but tfex consuming it is future work).
- Pointing tfex at the engine `/universe` endpoint (single-instrument strategy; not needed).

---

## Phase 4 acceptance criteria (verbatim from the umbrella ROADMAP)

> ### Phase 4 — `strategies/tfex-s50-multi-tf-swing` — consume shared store 📉
> **Sub-repo:** `strategies/tfex-s50-multi-tf-swing` (own PR).
> - Point tfex's data layer at the shared Market Data store; **reconcile or retire its
>   Phase-1 standalone TimescaleDB OHLCV mirror** so there is one canonical store.
> - Decide intraday handling per Phase 0 (Timescale hot window vs lake) for multi-TF.
> - **Success:** tfex backtests/live read the shared store; duplicate mirror removed or
>   demoted to cache; no per-host tvkit credential needed.

**Coverage of these criteria by this phase:**

| Criterion | This phase |
|---|---|
| Point tfex's data layer at the shared store | ✅ `engine` source reads `/ohlcv` via the gateway proxy; selected at the `refresh_all` seam |
| Reconcile/retire the 09 mirror | ✅ Demoted to a **derived local cache** in code + docs; physical DROP is a tracked `quant-infra-db` follow-up |
| Multi-TF via Option A; `1d` = settlement (never rolled up) | ◑ 5m/1h served from the engine as-stored; `1d` settlement available engine-side (tfex consumes it later); **4h deferred** (engine route pending) — no local rollup, per D10 |
| Consume `S501!` per (a)/(b); carry `open_interest` | ✅ Option **(b)** back-adjusted, **built locally** from raw dated contracts; `open_interest` carried (NULL for equities) |
| Intraday handling (Timescale hot window; no lake for S50) | ✅ Resolved per D5 — multi-TF stays in the Timescale hot window |
| Success: read the shared store; mirror demoted; no per-host tvkit credential | ✅ Verified — `engine` path holds no cookie; default `mirror` unchanged |

---

## Locked decisions

| Topic | Decision | Rationale |
|---|---|---|
| **S501! continuous** (D10 a/b) | **(b) back-adjusted**, but **built locally** by tfex from engine-served **raw dated-contract** bars (`/ohlcv?adjusted=false`) via existing `data/continuous.py`. Engine = raw-bar source only. | The engine's native futures-roll back-adjustment is unbuilt (`routes.py` "futures-roll parity is Phase 4"); tfex was validated on its own back-adjusted continuity. Honors D2/D10 (store raw, adjust on read). |
| **Intraday** (D5) | Multi-TF stays in the Timescale hot window; **no lake** for S50 (~13k rows/sym/yr). | Per ADR D5. |
| **4h** | **Deferred.** `engine` source serves `5m/1h`; `4h` raises `EngineTimeframeUnavailableError` before any I/O — no local rollup (D10). Engine 4h route over `cagg_ohlcv_4h` is a follow-up; enabling tfex is then a one-line map change. | Prompt scopes the engine repo to docs-only; `mirror` (default) still covers 4h; reversible. |
| **Schema 09** | **Demote to derived cache** in code/docs; physical DROP = separate future `quant-infra-db` PR. | Default `mirror` path still writes 09; dropping now would break it. Prompt forbids coupling infra-db DDL into the tfex PR. |
| **Phase 3 box #3** | **Leave `[ ]`** + annotate "deferred — not in `1de4d65`". | Ticking unverified work violates the prompt's own rule; it's a separate csm-set concern. |

---

## Verified read-API contract

Confirmed from `src/quant_marketdata_engine/api/{routes.py,schemas.py,deps.py}` (not assumed):

- `GET /ohlcv` and `GET /ohlcv/adjusted` — query params `symbol` (1–64), `timeframe`
  (`Literal["1d","1h","5m"]` — **no `4h`**), optional `start`/`end` (ISO-8601 UTC), `limit`
  (default 5000, 1–50000). Auth: `X-API-Key`, enforced only when `MARKETDATA_ENGINE_API_KEY`
  is set server-side (else open with a warning; `hmac.compare_digest`).
- Response `OHLCVResponse`: `{symbol, timeframe, adjusted, bars:[...]}`. Each `OHLCVBar`:
  `ts` (UTC bar-open), `open/high/low/close/volume` as **Decimal strings**, `open_interest`
  (string|null). OHLC are `numeric(18,6)` in the DB.
- Empty result = **200 with `bars: []`**. 401 on bad/missing key when configured; 422 on bad
  params. `/ohlcv/adjusted` does dividend/split adjust-on-read; **futures-roll parity is
  Phase 4** (i.e. it does not yet back-adjust futures — the reason tfex builds its continuous
  locally and reads `/ohlcv` raw).
- Gateway proxy: `quant-api-gateway` forwards `/api/v2/engines/market-data/{health,ohlcv,
  ohlcv/adjusted,universe}` to `:8300`, passing `X-API-Key` and mapping upstream failures to
  502/503/504.

---

## Feature-flag design

- **Env var:** `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE` (pydantic-settings), values
  `mirror | engine`, **default `mirror`**. Validated by a `field_validator`.
- **Companion config:** `..._MARKET_DATA_ENGINE_BASE_URL` (`str | None`, **include the
  gateway proxy prefix** `/api/v2/engines/market-data`) and `..._MARKET_DATA_ENGINE_API_KEY`
  (`SecretStr | None`). A `model_validator(mode="after")` **requires the base URL when
  `ohlcv_source='engine'`**, failing fast at `Settings()`.
- **Where read:** `src/.../config/settings.py`.
- **Routing:** `build_ohlcv_fetcher(settings) -> FetcherProtocol` in `src/.../data/sources.py`
  returns the legacy `OhlcvFetcher` for `mirror` and the new `EngineOhlcvFetcher` for
  `engine`. The only call-site change is `data/refresh.py::refresh_all`, which builds the
  fetcher via the factory when none is injected (`scripts/refresh_ohlcv.py` likewise). When
  the flag is `mirror`, the factory returns exactly the prior `OhlcvFetcher` — **byte-for-byte
  prior behaviour.**

> Note: tfex's data seam is `FetcherProtocol` (`fetch_contract` /
> `fetch_continuous_reference`), **not** csm's `OHLCVSource` — the factory therefore returns a
> fetcher, the natural tfex analogue of csm's loader.

---

## Read-client design

`src/.../adapters/market_data_engine_client.py` — `MarketDataEngineClient`, mirroring the
existing `gateway_client.py` manual-retry patterns:

- One shared `httpx.AsyncClient` (base_url, configurable `timeout`, optional `transport` for
  tests); `__aenter__/__aexit__`; constructor validation (`ValueError` on empty `base_url` /
  `max_attempts < 1`).
- `async get_ohlcv(symbol, timeframe, *, adjusted, limit, start=None, end=None) ->
  EngineOHLCVResponse`: routes to `/ohlcv/adjusted` when `adjusted` else `/ohlcv` (tfex's
  engine path always passes `adjusted=False`); sends `X-API-Key` only when configured;
  retries transient 5xx + `httpx.HTTPError` with bounded backoff; **4xx terminal** (raise
  `adapters.errors.MarketDataEngineError`); unparseable 200 body raises it too.
- Pydantic `EngineOHLCVBar` / `EngineOHLCVResponse` parse Decimal-strings → `Decimal`, `ts` →
  UTC datetime. The client holds **no tvkit cookie** — only the optional read key; never
  logs it.

---

## Response → tfex raw-frame mapping

`src/.../data/engine_fetcher.py` — `EngineOhlcvFetcher` implements `FetcherProtocol` and
returns the **identical** raw Polars frame the tvkit `OhlcvFetcher` produces, plus
`open_interest`: columns `time, open, high, low, close, volume, open_interest`, Decimal-typed
`(18,4)`, tz-aware UTC, sorted ascending, **window-filtered to `[start, end)`**; a zero-row
frame on empty.

| tfex input | engine | Note |
|---|---|---|
| `contract_code` (e.g. `S50M2026`) | `symbol` via `engine_symbol_for_contract` | bare TradingView code (localized choice; verify vs seed data) |
| `timeframe` `5m`/`1h` | `timeframe` `5m`/`1h` | `4h` → `EngineTimeframeUnavailableError` **before any I/O** |
| (always) | `adjusted=false` | raw bars; tfex back-adjusts locally |
| `ts` (UTC) | `time` | bar-open |
| `open/high/low/close/volume` `Decimal(18,6)` | quantize half-even → `Decimal(18,4)` | matches the 09/Parquet store scale; **no float round-trip** |
| `open_interest` `Decimal\|null` | `open_interest` `Decimal(18,4)\|null` | futures carry OI; NULL for equities |

`fetch_continuous_reference` returns an **empty frame** (interim) — `refresh_all`'s
`if ref_frame.height > 0` guard skips the S501! cross-check cleanly, pending the engine's
native back-adjusted continuous.

---

## Continuous build & the 09-mirror disposition

- **Continuous build is local and unchanged.** `refresh_all` already builds the back-adjusted
  continuous from the per-contract raw frames via `ContinuousBuilder`. Because
  `EngineOhlcvFetcher.fetch_contract` returns the identical raw shape, the continuous is built
  identically whether bars came from tvkit or the engine — the engine is purely the raw-bar
  source; the back-adjusted continuous stays a tfex-side derived artifact (the series the
  strategy was validated on). No change to `continuous.py`.
- **09 mirror demotion.** On the `engine` source the engine (`market_data.*`) is the source of
  truth; the 09 tables (`db_tfex_s50_multi_tf_swing.ohlcv_raw` / `.ohlcv_continuous`) become a
  **derived local cache** materialised from engine-sourced bars — never a parallel ingest.
  Code change is documentation-only (`db_writer.py` docstring + `CLAUDE.md`); the write path
  is unchanged so the default `mirror` path is untouched. **Migration/rollback:** the physical
  DROP/migration of the 09 tables is a separate `quant-infra-db` PR, deferred until `engine`
  is the validated default and no reader touches 09. The Parquet snapshot remains usable
  offline, so backtests don't hard-require infra-db.

---

## File changes (tfex repo)

| File | Action | Description |
|---|---|---|
| `src/.../config/settings.py` | MODIFY | `ohlcv_source` + `market_data_engine_base_url` + `market_data_engine_api_key`; `_validate_ohlcv_source`; `_require_engine_url_for_engine_source` |
| `src/.../adapters/market_data_engine_client.py` | ADD | Async httpx read client + `EngineOHLCVBar`/`EngineOHLCVResponse` |
| `src/.../adapters/errors.py` | MODIFY | add `MarketDataEngineError(AdapterError)` |
| `src/.../data/engine_fetcher.py` | ADD | `EngineOhlcvFetcher` (FetcherProtocol adapter) + `engine_timeframe` + `_TF_TO_ENGINE` |
| `src/.../data/sources.py` | ADD | `build_ohlcv_fetcher` factory |
| `src/.../data/errors.py` | MODIFY | add `EngineTimeframeUnavailableError(DataError)` |
| `src/.../data/contracts.py` | MODIFY | add `engine_symbol_for_contract` + `ENGINE_CONTINUOUS_SYMBOL` |
| `src/.../data/refresh.py` | MODIFY | build fetcher via the factory when none injected |
| `src/.../data/db_writer.py` | MODIFY | docstring: 09 is a derived cache on the engine source |
| `src/.../data/__init__.py` | MODIFY | re-export the new symbols |
| `scripts/refresh_ohlcv.py` | MODIFY | construct the fetcher via `build_ohlcv_fetcher` |
| `.env.example` | MODIFY | document the three new env vars |
| `CLAUDE.md` | MODIFY | new "OHLCV source" subsection; 09 demotion; 4h/S501! interim notes |
| `tests/unit/adapters/test_market_data_engine_client.py` | ADD | client unit tests (MockTransport) |
| `tests/unit/data/test_engine_fetcher.py` | ADD | fetcher unit tests (fake client) |
| `tests/unit/data/test_sources.py` | ADD | factory + flag-validator tests |
| `tests/unit/data/test_engine_parity.py` | ADD | mirror↔engine frame + continuous parity |
| `tests/integration/test_public_data_boundary_files.py` | ADD | public-data boundary (tfex's first) |
| `tests/unit/data/test_refresh.py` | MODIFY | flag-selection case (factory seam) |

**Separate repo PR (out of scope, follow-up only):** `quant-infra-db` init-script `09` —
eventual drop/migration of `ohlcv_raw`/`ohlcv_continuous`; and the future engine `4h` route
over `cagg_ohlcv_4h` + native back-adjusted `S501!` route.

---

## Test plan & coverage

- **Client** (`test_market_data_engine_client.py`, MockTransport): happy path + Decimal/ts
  parsing, raw vs adjusted endpoint, `start`/`end` ISO params, API-key header present/absent,
  empty `bars:[]`, 401/422 terminal (no retry), 5xx retry-then-success + exhaustion,
  transport-error retry, unparseable/malformed body, OI null.
- **Fetcher** (`test_engine_fetcher.py`): raw-frame shape, **18,6→18,4 cast**, OI null/present,
  **4h raises before any I/O**, window filter, symbol/param mapping, empty→empty frame,
  upstream error propagation, empty continuous reference; `engine_timeframe` mapping.
- **Factory** (`test_sources.py`): default + explicit `mirror` → `OhlcvFetcher`; `engine` →
  `EngineOhlcvFetcher`; invalid source rejected; `engine` without URL rejected; env-driven via
  `get_settings.cache_clear()`.
- **Parity** (`test_engine_parity.py`): engine vs mirror produce identical `time/OHLCV` for
  5m/1h on the same bars; `ContinuousBuilder` over both yields the identical continuous.
- **Boundary** (`test_public_data_boundary_files.py`): no raw OHLCV keys / long numeric arrays
  in `results/static/` + negative self-tests.
- **Refresh** (`test_refresh.py`): `fetcher=None` routes through `build_ohlcv_fetcher`.

**Coverage gate:** `--cov-fail-under=90` over `adapters/`+`data/`+`features/`+`regime/`.

---

## Backward-compat, migration, security, performance, rollback

- **Backward compatibility:** default `mirror` returns the exact prior `OhlcvFetcher`; purely
  additive. Zero behaviour change when the flag is unset.
- **Migration impact:** none for consumers when off. Turning it on requires only the engine
  base URL (+ optional key) in tfex's `.env`. The 09 mirror is re-documented as a cache; no
  data migration this run.
- **Security:** the `engine` path introduces **no tvkit cookie** into tfex — the engine is the
  sole cookie owner. The engine read key is a `SecretStr`, never logged/committed; raw OHLCV
  stays private-side (boundary test added).
- **Performance:** engine reads are Redis/DB-backed (hot/warm), avoiding the tvkit WebSocket
  burst + rate-limit exposure; one symbol per request, deduped/cached engine-side.
- **Rollback:** flip `OHLCV_SOURCE` back to `mirror` (or unset). No data migration; the local
  Parquet store remains the durable artifact and is usable offline for backtests.

---

## Cross-repo PR sequence & checkmark edits

1. **tfex** (code) — `feat/phase4-consume-marketdata-engine` off `main` → PR (primary).
2. **quant-marketdata-engine** (this doc + roadmap ticks) — `docs/phase4-tfex-consume-plan` → PR.
3. **umbrella** (roadmap/registry/catalog + knowledge note) — `docs/market-data-phase4` → PR.

**Checkmark edits this run:**
- Engine `docs/plans/ROADMAP.md`: Phase 3 § tick #1/#2, leave #3 with deferral note; Phase 4 §
  tick the satisfied boxes (data layer → engine; 09 reconciled→demoted; S501! (b)-built-locally
  + OI; intraday=Timescale) with 4h + native-S501! follow-up notes; advance Current Status to
  "Phase 3 (flag) complete; Phase 4 in progress".
- Umbrella `plans/feature-market-data-engine/ROADMAP.md`: same Phase 3/4 status + top Status +
  Current Status flip.

---

## Success criteria

- [x] `OHLCV_SOURCE=mirror|engine` (default `mirror`); `engine` reads the shared store, never tvkit.
- [x] Flag-off path is byte-for-byte the prior `refresh_all` behaviour.
- [x] Engine-read raw frame is shape/dtype/tz-identical to the tvkit fetcher's output (+OI).
- [x] Back-adjusted continuous built locally; identical from either source (parity test).
- [x] 4h declined with a typed error before I/O (no local rollup, D10).
- [x] 09 mirror demoted to a derived cache (code docstring + CLAUDE.md); DROP deferred.
- [x] New client/fetcher/factory/parity tests green; refresh retargeted to the factory seam.
- [x] Public-data-boundary test added and green.
- [x] ruff + ruff format clean; mypy-strict clean; pytest ≥90% (96% total).
- [ ] (follow-up) engine 4h route; engine native back-adjusted S501! (Phase-5); infra-db 09 drop.

---

## Completion notes

- **Branches:** tfex `feat/phase4-consume-marketdata-engine` (off `main`); this repo
  `docs/phase4-tfex-consume-plan`; umbrella `docs/market-data-phase4`.
- **tfex gate (green):** `ruff check` ✓ · `ruff format --check` ✓ · `mypy src tests` (strict)
  ✓ · `pytest` **306 passed, 5 skipped, 96.36% coverage**.
- **Phase 3 verification:** the Phase 3 reader shipped as `1de4d65` on `origin/live-test`
  (flag + client + `engine_loader.py` + `sources.py` + boundary tests). Box #3 (SET:SET
  index/sectors) is **absent** from that commit → left unticked with a deferral note.
- **Base-branch note:** tfex `main` gate is clean; all Phase 4 files pass.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.8)
**Status:** Complete
**Completed:** 2026-06-02
