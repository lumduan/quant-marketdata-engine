# Phase 0: ADR + Repo Bootstrap

**Feature:** feature-market-data-engine — Phase 0: ADR + Repo Bootstrap
**Branch:** `docs/phase0-adr-repo-bootstrap` (this repo) · `docs/feature-market-data-engine-phase0-adr` (umbrella)
**Created:** 2026-06-01
**Status:** Complete
**Completed:** 2026-06-01
**Depends On:** §0.1 Repository & Tooling (Complete), §0.2 Roadmap & Agent Context (Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Implementation Steps](#implementation-steps)
6. [File Changes](#file-changes)
7. [Success Criteria](#success-criteria)
8. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 0 is the **gating milestone** for the whole `feature-market-data-engine` feature.
It ships **no application code** — it authors the architecture-decision record (ADR) the
feature is gated on, pins the contracts every later phase binds to, registers the new
`quant-marketdata-engine` service in the umbrella system map, and ticks the roadmap
checkboxes that are now satisfied. Until the ADR merges, Phase 1 (`quant-infra-db`
schema) and every downstream code phase stay blocked.

§0.1 (repo + tooling) and §0.2 (roadmap + agent context) were completed on the original
bootstrap branch (`feat/bootstrap-marketdata-engine`, merged via PR #1). This phase
completes the two remaining Phase-0 items: **§0.3 the ADR** and **§0.4 umbrella
registration**.

### The two-repo split (critical)

This work spans **two independent git repositories** — `quant-marketdata-engine` (this
repo) and the umbrella `quant-trading-system` (which gitignores this sub-tree). Each repo
gets its **own branch, commit, and PR**; nothing is committed across the boundary.

| Repo | Branch | Deliverables |
|---|---|---|
| **This repo** (`quant-marketdata-engine`) | `docs/phase0-adr-repo-bootstrap` | this phase plan; ROADMAP §0.3/§0.4 ticks + Current Status; `CLAUDE.md` registration-note reconcile; `.claude/knowledge/market-data-engine.md` open-decision reconcile |
| **Umbrella** (`quant-trading-system`) | `docs/feature-market-data-engine-phase0-adr` | the ADR `.claude/knowledge/feature-market-data-engine.md`; `CLAUDE.md` registration; `optional-features-registry.md`; `plans/feature-market-data-engine/ROADMAP.md` ticks + status |

### Parent plan references

- Per-service roadmap: [`docs/plans/ROADMAP.md`](ROADMAP.md) — Phase 0 §0.1–§0.4.
- Umbrella feature roadmap (primary source):
  [`../../../plans/feature-market-data-engine/ROADMAP.md`](../../../plans/feature-market-data-engine/ROADMAP.md).
- Design docs consolidated by the ADR:
  [`request-flow.md`](../../../plans/feature-market-data-engine/request-flow.md),
  [`multi-timeframe-storage.md`](../../../plans/feature-market-data-engine/multi-timeframe-storage.md),
  [`quant-infra-db-changes.md`](../../../plans/feature-market-data-engine/quant-infra-db-changes.md).
- The ADR itself (the gate): umbrella `.claude/knowledge/feature-market-data-engine.md`.

---

## AI Prompt

The following prompt was used to generate this phase:

```
ROLE
  You are a senior platform engineer + technical writer working in the `quant-trading-system` monorepo-of-repos (an umbrella meta-repo whose sub-directories are
  each independent git repos with their own remotes). Execute **Phase 0 — ADR + Repo Bootstrap** of the `feature-market-data-engine` feature end-to-end. This
  is the current gating milestone for the whole feature; nothing downstream may start until it lands.

  CRITICAL FRAMING — THIS IS A DOCS-ONLY PHASE
  Phase 0 ships **zero application code**: no fetch / storage / read-API / Redis logic, no SQL, no gateway route. You are authoring an ADR, defining contracts,
  registering the new service in the umbrella, writing a phase plan, and ticking roadmap checkboxes. If you feel the urge to write Python under `src/`, stop —
  that is Phase 1/2.

  STEP 1 — READ AND GROUND YOURSELF (do this before writing anything)
  Read these in full and reconcile them; quote specifics from them rather than inventing:
  - `CLAUDE.md` (umbrella system map, engine catalog, ingestion contract, Docker network contract, bring-up order, Optional/Independent Features table)
  - `plans/feature-market-data-engine/ROADMAP.md` (cross-cutting roadmap — Phase 0 checkboxes live in its "Phase 0" section AND in the per-service roadmap; you
  will tick the ones that are now done)
  - `plans/feature-market-data-engine/request-flow.md`, `plans/feature-market-data-engine/multi-timeframe-storage.md`,
  `plans/feature-market-data-engine/quant-infra-db-changes.md` (the design detail the ADR must consolidate and pin)
  - `quant-marketdata-engine/docs/plans/ROADMAP.md` (per-service roadmap — read the full "Phase 0 — ADR + Repo Bootstrap" section §0.1–§0.4 and the Decision Log
  D1–D10; note §0.1 and §0.2 are already `[x]`, §0.3 ADR and §0.4 umbrella registration are still `[ ]`)
  - `quant-marketdata-engine/CLAUDE.md` (per-service ownership boundaries, ports, hard rules)
  - `quant-marketdata-engine/.claude/knowledge/market-data-engine.md` and `.claude/playbooks/development-workflow.md` (existing per-service agent context —
  update, don't duplicate)
  - `strategies/csm-set/docs/plans/examples/phase1-sample.md` (the REQUIRED format for the phase-plan markdown you will author — note its "AI Prompt" section
  embeds the originating prompt; replicate that pattern)
  - Existing tfex mirror to reconcile: `quant-infra-db/init-scripts/09_schema_db_tfex_s50_multi_tf_swing_ohlcv.sql`

  STEP 2 — UNDERSTAND THE TWO-REPO BOUNDARY (this governs your git/PR strategy)
  `quant-marketdata-engine/` and the umbrella repo are **separate git repos** (the sub-tree is in the umbrella's `.gitignore`). Phase 0 work therefore splits
  into two independent branches + two PRs:
    A. **Umbrella repo** (cwd `quant-trading-system/`): the ADR knowledge doc + umbrella `CLAUDE.md` registration + umbrella roadmap checkbox ticks + umbrella
  registry status flip + any umbrella `.claude/` playbook/knowledge updates.
    B. **Engine repo** (cwd `quant-marketdata-engine/`): the phase-plan markdown + per-service roadmap checkbox ticks + any `quant-marketdata-engine/CLAUDE.md`
  / `.claude/` updates.
  Never commit one repo's changes from the other. `cd` into each repo and use that repo's own git. Confirm each repo's remote with `git remote -v` before
  pushing.

  STEP 3 — CREATE BRANCHES
  In the engine repo, the scaffold already lives on `feat/bootstrap-marketdata-engine` (per its roadmap). Continue Phase-0 doc work on a clearly-named branch —
  if that branch still exists and is unmerged, extend it; otherwise create `docs/phase0-adr-repo-bootstrap`. In the umbrella repo, create
  `docs/feature-market-data-engine-phase0-adr` off `main`. State which branch you used for each repo.

  STEP 4 — WRITE THE PLAN BEFORE ANY CONTENT
  Author the phase plan at `quant-marketdata-engine/docs/plans/phase0-adr-repo-bootstrap.md`, following the structure of
  `strategies/csm-set/docs/plans/examples/phase1-sample.md` exactly (header block with Feature/Branch/Created=2026-06-01/Status/Depends-On; Table of Contents;
  Overview; **AI Prompt** section containing this very prompt verbatim inside a fenced block; Scope in/out; Design Decisions; Implementation Steps; File Changes
  table spanning BOTH repos; Success Criteria as a checkbox list; Completion Notes). The plan must make the two-repo split explicit and enumerate every file
  you touch in each repo.

  STEP 5 — AUTHOR THE ADR (the actual gate) — umbrella repo
  Create `.claude/knowledge/feature-market-data-engine.md` in the **umbrella** repo. It is the architecture-decision record the whole feature is gated on. It
  must:
  - State architecture rationale + the target topology (single standalone `quant-marketdata-engine`, host `:8300` / container `:8000`, sole tvkit-cookie owner,
  gateway-proxied under `/api/v2/engines/market-data/*`, own Redis sidecar, writes `market_data.*` in TimescaleDB).
  - **Confirm Decision Log D1–D10** — restate each decision and its rationale, and mark it ACCEPTED (or, if you find a genuine conflict in the design docs, flag
  it explicitly rather than silently changing it). Do NOT invent new D-decisions.
  - **Pin the intraday lake-first threshold as a concrete number** (rows/sym/yr or bars/day, with the arithmetic), and conclude that S50 stays in TimescaleDB
  (cite the ~13k rows/sym/yr figure from `multi-timeframe-storage.md`). The threshold must be a number, not "TBD".
  - **Define the Market Data read contract**: the request shape (`symbol`, `timeframe` enum, `range`) and response shape for raw OHLCV, adjusted OHLCV, and
  universe; `Decimal`-as-string on the wire; UTC `ts` = bar-open; daily + adjusted variants. This is the contract strategies bind to (never a table name).
  - **Pin the `S501!` continuous question** from D10: decide which series the read API serves under `S501!` — (a) TradingView-native non-back-adjusted vs (b)
  system-derived roll-adjusted — and whether dated contracts (e.g. `S50M2026`) are independently addressable. Justify the choice against what the strategies
  were validated on. Confirm `5m` is base grain (stored raw, not CAGG-derived).
  - **Decide seed-vs-retire for the existing tfex `09` TimescaleDB mirror** (`quant-infra-db/init-scripts/09_schema_db_tfex_s50_multi_tf_swing_ohlcv.sql`): does
  it seed the shared `market_data` schema or get retired? Record the decision and its migration implication for Phase 4.
  Reflect the same conclusions back into `quant-marketdata-engine/.claude/knowledge/market-data-engine.md` only where that per-service doc currently leaves them
  open (link to the umbrella ADR as the source of truth; do not fork the decisions).

  STEP 6 — UMBRELLA REGISTRATION (§0.4) — umbrella `CLAUDE.md`
  Now that the ADR exists, register the service in the umbrella `CLAUDE.md`:
  - Add `quant-marketdata-engine` to the **repo/remote table** (path `quant-marketdata-engine/`, remote `github.com/lumduan/quant-marketdata-engine`, role =
  canonical OHLCV producer / sole tvkit-cookie owner).
  - Add to the **Docker network contract** table: hostname `quant-marketdata-engine`, container `:8000`, host `:8300`.
  - Add to the **Engine catalog**: Market Data engine — note it is being realised by this service (keep status accurate to reality — code is not built yet, so
  do NOT claim `active`; reflect that the service is registered/bootstrapped, ingestion lands in Phase 2).
  - Add to the **local bring-up order** (after `quant-infra-db`, before/with the gateway) and the **health checks** list (`curl http://localhost:8300/health`,
  noting it goes live in Phase 2).
  - Add to the **Per-service quick reference** table (FastAPI / Python 3.11, `uv`, ruff + mypy strict + pytest ≥90% on core modules, docs →
  `quant-marketdata-engine/CLAUDE.md`).
  - Flip the `feature-market-data-engine` row in the **Optional / Independent Features** table from "Proposed — design phase, gated on Phase 0 ADR" to reflect
  Phase 0 complete / Phase 1 next.
  - Update the bullet under "Per-feature companion docs" that currently says the service is "not built yet … added here in Phase 0" to reflect that registration
  is now done.

  STEP 7 — KNOWLEDGE / MEMORY / PLAYBOOK UPDATES (only where warranted, both repos)
  - Umbrella `.claude/knowledge/optional-features-registry.md`: update the `feature-market-data-engine` entry to Phase-0-complete.
  - If a cross-repo bring-up/PR-sequencing note belongs in umbrella `.claude/playbooks/`, add or update it; otherwise leave playbooks alone.
  - In the engine repo, update `quant-marketdata-engine/CLAUDE.md` "Network & ports" / registration note that currently says "registered in the umbrella … once
  the Phase 0 ADR merges" to point at the now-authored registration.
  - Update the agent memory note `project-marketdata-engine-bootstrap` (the persistent memory index entry) to record Phase-0 ADR authored + umbrella
  registration done (absolute date 2026-06-01), keeping the existing facts. Do not duplicate facts already in the repos.
  Do not create memory/knowledge/playbook files speculatively — only what these specific Phase-0 deliverables justify.

  STEP 8 — TICK ROADMAP CHECKBOXES (both roadmaps)
  - In `quant-marketdata-engine/docs/plans/ROADMAP.md`: flip §0.3 and §0.4 items from `[ ]` to `[x]`; update the "Current Status" block (active phase → Phase 0
  complete, unblock Phase 1; remove the "Blocked on the Phase 0 ADR" note).
  - In `plans/feature-market-data-engine/ROADMAP.md`: tick the Phase 0 deliverables in its "Phase 0 — Design & ADR" section and update its Status line.
  Keep ticks faithful — only mark what you actually delivered.

  QUALITY BAR (enforce, even though this is docs-only)
  - The engine repo's existing scaffold gates must stay green: run `cd quant-marketdata-engine && uv run ruff check . && uv run ruff format --check . && uv run
  mypy src tests && uv run pytest` and confirm nothing you touched broke them (docs changes shouldn't, but verify). Report the actual output; if anything fails,
  fix or surface it — do not claim green falsely.
  - Markdown must be internally consistent: every relative link you add must resolve; tables must render; ports/hostnames must match across umbrella
  `CLAUDE.md`, engine `CLAUDE.md`, and both roadmaps (`:8300` host / `:8000` container everywhere).
  - Secret hygiene: never write the tvkit cookie value anywhere; reference `TVKIT_AUTH_TOKEN` as a gitignored-`.env` concept only.
  - No D-decision invented beyond D1–D10; no contract field left "TBD"; the intraday threshold is a real number; the `S501!` (a)/(b) choice and the tfex-`09`
  seed-vs-retire choice are both decided, not deferred.
  - Backward-compatibility check: confirm your umbrella `CLAUDE.md` edits don't contradict existing engine-catalog wording or the ingestion-contract section;
  reconcile if they do.

  DELIVERABLES / EXPECTED OUTPUT
  1. Engine-repo branch with: `quant-marketdata-engine/docs/plans/phase0-adr-repo-bootstrap.md` (new, sample-format, prompt embedded), per-service roadmap
  checkboxes + Current Status updated, any `CLAUDE.md`/`.claude/` reconciliations.
  2. Umbrella-repo branch with: `.claude/knowledge/feature-market-data-engine.md` (new ADR), `CLAUDE.md` registration edits,
  `plans/feature-market-data-engine/ROADMAP.md` checkbox + status updates, `optional-features-registry.md` update, any playbook update.
  3. Commit each repo separately using Conventional Commits (e.g. umbrella: `docs(adr): author feature-market-data-engine ADR + register service`; engine:
  `docs(plans): Phase 0 ADR + repo-bootstrap plan, tick roadmap`). End each commit body with the Co-Authored-By trailer.
  4. Open a PR per repo via `gh pr create` against each repo's `main`, with a body that summarises the ADR decisions (D1–D10 accepted, intraday threshold =
  <number>, `S501!` = option <a|b>, tfex-`09` = <seed|retire>), lists the registration changes, and states "docs-only, no application code". End each PR body
  with the "🤖 Generated with Claude Code" line.
  5. A final summary message to me listing: the two branch names, the two PR URLs, the key ADR decisions you pinned (with the actual chosen values), and the
  exact `ruff/mypy/pytest` result on the engine scaffold.

  If — and only if — you hit a genuinely blocking ambiguity that the design docs do not resolve (e.g. the `S501!` (a)/(b) choice has no signal in
  `multi-timeframe-storage.md`), state the options and your recommended default in your summary and proceed with that default rather than stalling; record it as
  a decision in the ADR with the rationale.
```

---

## Scope

### In Scope (Phase 0)

| Component | Repo | Description | Status |
|---|---|---|---|
| Phase plan (this doc) | engine | Sample-format plan with prompt embedded | Complete |
| ROADMAP §0.3 / §0.4 ticks + Current Status | engine | Flip 10 checkboxes; unblock Phase 1 | Complete |
| `CLAUDE.md` registration-note reconcile | engine | "once the ADR merges" → "registered" | Complete |
| `.claude/knowledge/market-data-engine.md` reconcile | engine | Resolve the two open decisions; link to ADR | Complete |
| ADR `feature-market-data-engine.md` | umbrella | Architecture + D1–D10 + threshold + read contract + `S501!` + `09` | Complete |
| `CLAUDE.md` registration (7 edits) | umbrella | Repo table, network contract, engine catalog, bring-up, health, quick-ref, features flip, companion bullet | Complete |
| `optional-features-registry.md` | umbrella | Phase-0-complete entry | Complete |
| `plans/feature-market-data-engine/ROADMAP.md` | umbrella | Phase 0 ticks + Status line | Complete |
| Agent memory `project-marketdata-engine-bootstrap` | (memory) | Record ADR + registration done 2026-06-01 | Complete |

### Out of Scope (Phase 0 — explicitly deferred)

- Any application code under `src/` — fetch, storage, read-API, Redis, single-flight (Phase 2).
- Any SQL: `10_schema_market_data.sql`, `11_market_data_caggs.sql`, `src/db` models/repos (Phase 1, `quant-infra-db` PR).
- The gateway proxy route `/api/v2/engines/market-data/*` and the `EXTERNAL stub → active` flip (Phase 2, `quant-api-gateway` PR).
- Strategy cutover — `CSM_OHLCV_SOURCE` (Phase 3), tfex shared-store read + `09` retirement execution (Phase 4).
- The intraday lake (DuckDB/object store) — reserved, not built (D5).
- A cross-repo cutover runbook in umbrella `.claude/playbooks/` — due at Phase 5, not Phase 0.

---

## Design Decisions

The ADR consolidates and *pins* the design docs. It introduces **no D-decision beyond
D1–D10**. The full rationale lives in the umbrella ADR
(`.claude/knowledge/feature-market-data-engine.md`); summarised here:

### 1. Decision Log D1–D10 — ACCEPTED

All ten decisions in the ROADMAP Decision Log are restated and marked ACCEPTED in the
ADR with their rationale. No conflict was found in the design docs.

### 2. Intraday lake-first threshold = a concrete number

**Trigger to go lake-first = ~50M new rows/year ingested** (≈250–500M rows resident),
**or any sustained sub-1-minute / tick capture.** Arithmetic in the docs' own units
(5m ≈ 13k rows/sym/yr, from `multi-timeframe-storage.md`):

- S50 multi-TF, ~10 syms × (5m 13k + 1h ~2k + 1d ~250) ≈ **~152k rows/yr** → ~0.3% of
  the threshold → **stays in TimescaleDB**.
- All-SET 5m, ~700 syms × 13k ≈ **~9M rows/yr** → ~18% of threshold → still TimescaleDB.
- All-SET 1-minute or tick → exceeds the threshold → **lake-first (DuckDB + object store, D5)**.

**Conclusion: S50 stays in TimescaleDB; the lake is reserved, not used now.**

### 3. `S501!` continuous (D10 refinement) → Option (b)

The read API serves the **system-derived back-adjusted continuous** as the default
series under `S501!`. Rationale: the strategy was validated on the back-adjusted series
(the existing `09` mirror builds its *own* `ohlcv_continuous` via a volume-crossover roll;
TradingView's native `S501!` is fetched there only as a Parquet cross-check), and
back-adjustment removes the artificial roll gaps that corrupt returns/indicators/backtests.

Served through the **adjust-on-read** contract (D2/D10): the native non-back-adjusted (a)
series remains available via `adjusted=false`; **default = roll-adjusted**. **Dated
contracts** (`S50M2026`, `S50H2026`, `S50U2026`, `S50Z2026`) are **independently
addressable** as their own symbols. **`5m` is base grain — stored raw, never CAGG-derived.**

### 4. tfex `09` mirror → RETIRE (build fresh + migrate), not seed

`09`'s shape is incompatible with the shared schema: it uses a per-contract `contract`
column (`S50H2026`) + a *separate* `ohlcv_continuous` table, has **no `1d` timeframe**, is
Parquet-sourced (DB = mirror), and lives in `db_tfex_s50_multi_tf_swing`. The shared
schema is unified `(symbol, timeframe, ts)`, DB-canonical, adjust-on-read, with `1d`.
Seeding would lock in the wrong shape.

**Phase-4 migration implication:** port `09`'s roll logic (volume-crossover,
`roll_offset_days=5`, `adjustment_factor`) into the engine's adjust-on-read + stored roll
dates; one-time backfill the data into `market_data.ohlcv` + `corporate_actions`; demote
tfex `db_writer.py` to a reader; then drop `ohlcv_raw` / `ohlcv_continuous`.

### 5. Market Data read contract (what strategies bind to)

A contract, never a table name:

- **Request:** `symbol` (`S501!`, `SET:PTT`, `S50M2026`, `SET:SET50`); `timeframe` enum
  (`1d|1h|5m`, extensible via CAGG); `range` (`start`/`end` UTC, or a relative window);
  `adjusted` (bool, default `true`).
- **Response:** bar series `{ ts (UTC, bar-open), open, high, low, close, volume,
  open_interest? }` with **`Decimal`-as-string on the wire**; a parallel adjusted variant;
  and a `/universe` (as-of point-in-time membership) shape. Daily + adjusted both defined.

---

## Implementation Steps

### Step 1 — Branches (both repos)

Engine: `git checkout -b docs/phase0-adr-repo-bootstrap` (off `main`; the original
`feat/bootstrap-marketdata-engine` is already merged via PR #1). Umbrella:
`git checkout -b docs/feature-market-data-engine-phase0-adr` off `main`.

### Step 2 — Engine repo docs

1. Author this plan (`docs/plans/phase0-adr-repo-bootstrap.md`).
2. Tick ROADMAP §0.3 (5 items) + §0.4 (5 items); rewrite Current Status (Phase 0 complete,
   Phase 1 unblocked).
3. Reconcile `CLAUDE.md` "Network & ports" registration note → registered in umbrella.
4. Reconcile `.claude/knowledge/market-data-engine.md` — resolve the `S501!` and `09`
   open decisions inline, linking the umbrella ADR as the source of truth.

### Step 3 — Umbrella repo docs

1. Author the ADR `.claude/knowledge/feature-market-data-engine.md`.
2. Register the service in `CLAUDE.md` (7 edits per STEP 6 above).
3. Update `optional-features-registry.md` to Phase-0-complete.
4. Tick `plans/feature-market-data-engine/ROADMAP.md` Phase 0 + Status line.

### Step 4 — Verify, commit, PR

Run the engine scaffold gate; consistency-check ports/links/secrets; commit each repo
separately with Conventional Commits + Co-Authored-By; `gh pr create` against each `main`.

---

## File Changes

Spanning **both repos** — committed separately.

### Engine repo (`quant-marketdata-engine`, branch `docs/phase0-adr-repo-bootstrap`)

| File | Action | Description |
|---|---|---|
| `docs/plans/phase0-adr-repo-bootstrap.md` | CREATE | This phase plan (prompt embedded) |
| `docs/plans/ROADMAP.md` | MODIFY | Tick §0.3 + §0.4; rewrite Current Status |
| `CLAUDE.md` | MODIFY | "Network & ports" registration note → registered in umbrella |
| `.claude/knowledge/market-data-engine.md` | MODIFY | Resolve `S501!` + `09` open decisions; link ADR |

### Umbrella repo (`quant-trading-system`, branch `docs/feature-market-data-engine-phase0-adr`)

| File | Action | Description |
|---|---|---|
| `.claude/knowledge/feature-market-data-engine.md` | CREATE | The ADR (the gate) |
| `CLAUDE.md` | MODIFY | Repo table, network contract, engine catalog, bring-up, health, quick-ref, features flip, companion bullet |
| `.claude/knowledge/optional-features-registry.md` | MODIFY | Add `feature-market-data-engine` row, Phase-0-complete |
| `plans/feature-market-data-engine/ROADMAP.md` | MODIFY | Tick Phase 0 deliverables; update Status line |

### Agent memory (persistent, not a repo)

| File | Action | Description |
|---|---|---|
| `project-marketdata-engine-bootstrap.md` + `MEMORY.md` pointer | MODIFY | Record ADR authored + registration done 2026-06-01; pinned decisions |

---

## Success Criteria

- [x] Two branches created on the correct repos (`docs/phase0-adr-repo-bootstrap` engine; `docs/feature-market-data-engine-phase0-adr` umbrella)
- [x] This phase plan authored in sample format with the originating prompt embedded verbatim
- [x] ADR `.claude/knowledge/feature-market-data-engine.md` authored in the umbrella
- [x] D1–D10 restated and marked ACCEPTED (no new D-decision invented)
- [x] Intraday lake-first threshold pinned as a number (~50M rows/yr) with arithmetic; S50 concluded to stay in TimescaleDB
- [x] Market Data read contract defined (request + response, Decimal-as-string, UTC bar-open ts, daily + adjusted + universe)
- [x] `S501!` decided = option (b) back-adjusted default (adjust-on-read), dated contracts independently addressable, `5m` base grain
- [x] tfex `09` decided = RETIRE (build fresh + migrate), Phase-4 migration implication recorded
- [x] Service registered in umbrella `CLAUDE.md` (repo table, network contract, engine catalog, bring-up, health, quick-ref) without claiming `active`
- [x] `feature-market-data-engine` flipped to Phase-0-complete in the umbrella CLAUDE.md Optional Features table + `optional-features-registry.md`
- [x] Both roadmaps' Phase 0 checkboxes ticked + status lines updated
- [x] Engine scaffold gate green (`ruff check` + `ruff format --check` + `mypy src tests` + `pytest`) — unbroken by docs edits
- [x] Ports/hostnames consistent (`:8300` host / `:8000` container) across umbrella + engine `CLAUDE.md` + both roadmaps + ADR
- [x] No tvkit cookie value written anywhere (`TVKIT_AUTH_TOKEN` referenced as gitignored-`.env` concept only)
- [x] Two PRs opened against each repo's `main`

---

## Completion Notes

### Summary

Phase 0 closed both remaining items — §0.3 (the ADR) and §0.4 (umbrella registration) —
across two repos and two PRs, with zero application code. The ADR pins every contract the
later phases bind to: D1–D10 accepted, intraday threshold ~50M rows/yr (S50 stays in
TimescaleDB), the Market Data read contract, `S501!` = option (b) back-adjusted default,
and tfex `09` = retire. The engine scaffold quality gate stayed green throughout.

### Decisions resolved without escalation

The `S501!` (a)/(b) choice and the `09` seed-vs-retire choice both had clear signal in the
design docs (`multi-timeframe-storage.md` + `quant-infra-db-changes.md` + the `09` SQL),
so they were decided directly rather than flagged as blocking ambiguities. Both are
recorded in the ADR with rationale.

### What unblocks next

Phase 1 (`quant-infra-db` shared `market_data` schema) is now unblocked. It lands in
`quant-infra-db`'s own PR — `10_schema_market_data.sql` + `11_market_data_caggs.sql` +
`src/db` models/repos — per [`ROADMAP.md`](ROADMAP.md) Phase 1.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.8)
**Status:** Complete
**Completed:** 2026-06-01
