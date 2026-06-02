# Phase 6: Documentation — tvkit-ref style, AI-agent-first

**Feature:** feature-market-data-engine — Phase 6: Documentation
**Branch (engine, docs):** `docs/phase6-documentation` (based on `main`)
**Created:** 2026-06-02
**Status:** In progress
**Depends On:** Phase 0 (ADR) · Phase 1 (schema) · Phase 2 (engine + gateway proxy) ·
Phase 3 (csm-set reader ✓) · Phase 4 (tfex reader ✓) · Phase 5 (verification & cutover —
**partial**, see Preconditions)

> **Cross-repo note.** The docs land in `quant-marketdata-engine`. The umbrella repo
> separately gets the consolidated cutover runbook, roadmap checkmarks, and `.claude/*`
> cross-references on its own branch (`docs/phase6-marketdata-engine`). The two repos'
> commits and PRs stay independent; no sub-repo history is rewritten from the umbrella.

---

## Table of Contents

1. [Overview](#overview)
2. [Originating prompt](#originating-prompt)
3. [Preconditions / open Phase 5 gaps](#preconditions--open-phase-5-gaps)
4. [Scope](#scope)
5. [The "tvkit-ref style, AI-agent-first" deliverable](#the-tvkit-ref-style-ai-agent-first-deliverable)
6. [Design decisions](#design-decisions)
7. [File changes](#file-changes)
8. [Docs that must stay in sync](#docs-that-must-stay-in-sync)
9. [Implementation steps](#implementation-steps)
10. [Quality gate](#quality-gate)
11. [Success criteria / acceptance checklist](#success-criteria--acceptance-checklist)
12. [Completion notes](#completion-notes)

---

## Overview

### Purpose

Phases 0–5 built the Market Data Engine and wired both strategy readers. Phase 6 is the
**documentation milestone**: produce AI-agent-first reference documentation — structured,
navigable, example-driven, with explicit contracts and cross-links — mirroring the
documented structure and voice of the [`tvkit`](https://github.com/lumduan/tvkit) reference
docs, so an AI agent (or human) can operate, extend, and reason about the engine without
reading the source.

Because Phase 6 *describes the finished system*, its accuracy is gated on Phase 5 being
truly complete. This plan therefore **rechecks Phase 5 first** (see Preconditions), then
documents **only what the code does today** and flags every deferred item as explicitly
pending — never as done.

### Parent plan references

- Umbrella feature roadmap: [`../../../plans/feature-market-data-engine/ROADMAP.md`](../../../plans/feature-market-data-engine/ROADMAP.md) §"Phase 6"
- Per-service roadmap: [`ROADMAP.md`](ROADMAP.md) §"Phase 6"
- Phase 5 plan: [`phase5-end-to-end-verification-cutover.md`](phase5-end-to-end-verification-cutover.md)
- ADR (D1–D10, read contract): [`../../../.claude/knowledge/feature-market-data-engine.md`](../../../.claude/knowledge/feature-market-data-engine.md)
- Plan format reference: [`../../../strategies/csm-set/docs/plans/examples/phase1-sample.md`](../../../strategies/csm-set/docs/plans/examples/phase1-sample.md)
- Style exemplar: tvkit `docs/` (7-category hierarchy) — https://github.com/lumduan/tvkit/tree/main/docs

### Key deliverables

1. **This plan document.**
2. **Focused-core `docs/` set** (16 files + `docs/README.md` hub) — architecture, API,
   operations, data.
3. **Three new `.claude/knowledge/` files** (data-flow, deployment, api-contract) closing the
   AI-agent context TODOs.
4. **Refreshed `CLAUDE.md` + `docs/plans/ROADMAP.md`** — index live docs, correct Phase 5
   wording.
5. **Umbrella updates** (separate branch/PR): consolidated cutover runbook, roadmap
   checkmarks, knowledge cross-refs, agent memory.

---

## Originating prompt

The following prompt initiated this work (embedded verbatim):

```
# Task: Implement Phase 6 — Documentation (tvkit-ref style, AI-agent-first) for
`quant-marketdata-engine`

You are working in the `quant-trading-system` umbrella meta-repo. The sub-directory
`quant-marketdata-engine/` is its OWN independent git repository (remote
`github.com/lumduan/quant-marketdata-engine`). Phase 6 documentation work lands in THAT
sub-repo; only umbrella-level roadmap checkmarks and cross-cutting `.claude/*` notes land
in the umbrella repo. Never rewrite a sub-repo's history from the umbrella, and never
commit secrets (the tvkit cookie in particular).

## Step 0 — Read and reconcile context BEFORE writing anything

Read these in full and reconcile them against each other:
- `CLAUDE.md` (umbrella system map)
- `plans/feature-market-data-engine/ROADMAP.md` (umbrella roadmap — where Phase 5 / Phase 6
  checkmarks are tracked)
- `quant-marketdata-engine/docs/plans/ROADMAP.md` (the engine repo's own main roadmap —
  the Phase 6 plan source of truth)
- `quant-marketdata-engine/CLAUDE.md` (engine repo instructions, quality gates)
- `strategies/csm-set/docs/plans/examples/phase1-sample.md` (the REQUIRED format reference
  for the plan file you will author — match its structure, headings, and the convention of
  embedding the originating prompt inside the plan)
- Any existing `quant-marketdata-engine/docs/plans/phase5-end-to-end-verification-cutover.md`
  and the verification assets under `quant-marketdata-engine/tests/verification/`
  (`verify_csm_parity.py`, `verify_tfex_parity.py`, `verification_utils.py`).

## Step 1 — Recheck Phase 5 status (gate Phase 6 on it)

Phase 6 (documentation) describes the finished system, so its accuracy depends on Phase 5
being truly complete. Audit the Phase 5 — End-to-end verification & cutover checklist
against the actual repo state and report the true status of EACH item (done / partial /
not done), citing the file or command that proves it:
1. Verification plan authored (`phase5-end-to-end-verification-cutover.md`)
2. Verification scripts built (`tests/verification/verify_csm_parity.py`,
   `verify_tfex_parity.py`, `verification_utils.py`)
3. Verification unit tests (target: 21 tests, all green) — actually run them with the
   repo's gate command (`uv run pytest …`) and report the real count/result
4. Tier 1 verification (engine vs Parquet) run for csm-set AND tfex
5. If 100% parity: strategy defaults flipped + deprecation warnings added + docs updated
6. If <100% parity: gap-analysis document written, issues filed, cutover deferred to 5.1
7. Confirm NO strategy fetches tvkit directly anymore (grep both strategy repos for the
   tvkit fetch path / cookie usage and show the evidence)
8. Confirm backtest read performance: the Parquet snapshot path is at least as fast as
   today's local Parquet, and the DB path does not become a backtest bottleneck
9. Cutover runbook authored in the umbrella `.claude/playbooks/`

Exit criteria to confirm for Phase 5: single daily ingest; both strategies consistent on
the same closes; per-strategy tvkit fetch decommissioned; cutover runbook exists.

If any Phase 5 item is genuinely incomplete, DO NOT silently fix it under the Phase 6
branch and DO NOT mark it done. Surface the gap explicitly in your status report and in the
Phase 6 plan's "Preconditions / open Phase 5 gaps" section, then proceed with documentation
for the parts that ARE complete, clearly flagging anything documented as "pending Phase 5.x".
Treat the umbrella CLAUDE.md note that Phase 3 deferred the "SET:SET index/sectors fix" and
that 4h is declined client-side as known, already-documented carve-outs — reflect them, do
not re-litigate them.

## Step 2 — Create a branch

In `quant-marketdata-engine/`, create a feature branch off the repo's correct base branch
(check what Phase 4/5 work branched from — likely `live-test`, NOT `main`; confirm before
branching and state your choice). Suggested name: `docs/phase6-documentation`. If umbrella
changes are also needed, branch the umbrella repo separately (e.g.
`docs/phase6-marketdata-engine`) — keep the two repos' commits independent.

## Step 3 — Write the plan FIRST (plan before code)

Author `quant-marketdata-engine/docs/plans/phase6-documentation.md` matching the format of
`strategies/csm-set/docs/plans/examples/phase1-sample.md`. The plan MUST:
- Embed this originating prompt verbatim (in a clearly marked "Originating prompt" section).
- State the Phase 5 recheck findings as preconditions.
- Define the "tvkit-ref style, AI-agent-first" documentation deliverable concretely:
  documentation optimized for an AI agent (and human) to operate, extend, and reason about
  the engine — structured, navigable, with explicit contracts, examples, and cross-links —
  mirroring the structure/voice of the existing `tvkit` reference docs in the workspace
  (locate and match that style; cite the file(s) you used as the style exemplar).
- Enumerate every doc to create/update with its exact project-relative path, audience, and
  the sections it will contain. At minimum cover, under `quant-marketdata-engine/docs/`:
  architecture (request flow, multi-timeframe storage, schema ownership), the read API
  surface (`/health`, `/ohlcv`, `/ohlcv/adjusted`, `/universe`) with request/response
  examples and the gateway proxy path `/api/v2/engines/market-data/*`, owner-mode ingest +
  the single-credential/sole-tvkit-cookie-owner model, ops/runbook (bring-up order, env
  vars incl. `CSM_OHLCV_SOURCE` and `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE`, health checks),
  and the data contract strategies read against.
- Include an explicit acceptance checklist and a "docs that must stay in sync" map (which
  umbrella docs must be updated when the engine docs change).
- List the exact commands the doc work must pass before push (the engine repo's quality
  gate: `ruff check`, `ruff format --check`, `mypy` strict where configured, `pytest` at
  the repo's coverage target — even doc-only branches should leave the gate green; if any
  code/docstrings change, re-run the formatter and re-check after every post-format edit).

Stop after the plan is written only if you uncover a genuine blocker; otherwise continue to

## Step 4 — Execute the documentation

Write the docs exactly as planned. Requirements:
- AI-agent-first: precise, self-contained, example-driven; every endpoint shows a real
  request and response; every env var states default + allowed values + effect; every
  cross-repo dependency is linked by project-relative path.
- Accuracy over aspiration: document only what the code actually does today; mark deferred
  items (SET:SET index/sectors fix, engine 4h route, any open Phase 5 gap) as explicitly
  pending, not done.
- Keep monetary/timezone conventions correct in examples (Decimal at boundaries; store UTC,
  display Asia/Bangkok).
- No secrets in any example — use placeholders for the tvkit cookie / API keys.
- Match the surrounding docs' tone, heading depth, and Markdown conventions.

## Step 5 — Update knowledge / memory / playbooks (create or update, do not duplicate)

Where warranted, update or create:
- `quant-marketdata-engine/CLAUDE.md` and `quant-marketdata-engine/.claude/*` — point to the
  new docs; record any conventions discovered.
- Umbrella `CLAUDE.md` — flip the `feature-market-data-engine` row / roadmap status to mark
  Phase 6 documentation complete (and correct the Phase 5 status to match your recheck);
  add the cutover runbook reference if it now exists.
- Umbrella `.claude/knowledge/feature-market-data-engine*.md` and
  `.claude/playbooks/` — ensure the Phase 5 cutover runbook is present/linked and the
  knowledge files cross-reference the new Phase 6 docs.
- `plans/feature-market-data-engine/ROADMAP.md` — tick the Phase 6 checkboxes that are
  genuinely done; leave unfinished items unticked.
Before creating any new note, check for an existing file covering the same ground and update
it instead of duplicating.

## Step 6 — Verify the gate, then commit & PR

- Run the engine repo's full quality gate and paste the real output. Doc-only branches must
  still leave the gate green; fix anything your edits broke.
- Commit with clear conventional-commit messages (`docs(...)`/`chore(...)`), end each commit
  message body with the required `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
  trailer, and open a PR per repo touched against that repo's correct base branch. End PR
  bodies with the required Claude Code generation footer.
- Do NOT push or open PRs until the gate is green and I can see the results.

## Final report — REQUIRED format

After all commit/push/PR operations, report the result as an ASCII box-drawing table (NOT a
markdown pipe table), one row per repo touched, using the characters
`┌ ─ ┬ ┐ │ ├ ┼ ┤ └ ┴ ┘`, with columns: Repo | Branch | Commit | GitHub. In the Repo column
use `owner/name` plus a short role note in parens (e.g. `(engine docs)`, `(umbrella docs)`);
Commit = short SHA; GitHub = `PR #N → <url>`, or push status, or `local only`.

Deliverables summary to include alongside the table:
- Phase 5 recheck verdict (item-by-item) with evidence.
- List of doc files created/updated (project-relative paths).
- Confirmation of which roadmaps/checkmarks were updated.
- Any deferred/blocked items and why.
```

---

## Preconditions / open Phase 5 gaps

Phase 5 was rechecked against the actual repo state on 2026-06-02. Verdict: **PARTIAL but
legitimately so** — csm-set is fully cut over and verified; tfex verification + cutover are
deferred for a documented reason (no mirror Parquet / no TFEX contract data in the engine
yet). These are pre-existing, already-documented carve-outs. Phase 6 documents them as
**pending**, and does **not** fix them under the Phase 6 branch.

| # | Phase 5 item | Status | Evidence |
|---|---|---|---|
| 1 | Verification plan authored | **DONE** | [`phase5-end-to-end-verification-cutover.md`](phase5-end-to-end-verification-cutover.md) (merged PR #8, `ad7eff3`) |
| 2 | Verification scripts built | **DONE** | `tests/verification/{verification_utils,verify_csm_parity,verify_tfex_parity}.py` |
| 3 | Verification unit tests (21, green) | **DONE — 21 passed** | `uv run pytest tests/verification/` → `21 passed` (sub-dir-only coverage-fail is expected; the full-suite gate is the real one) |
| 4a | Tier 1 csm-set verification | **DONE** | `reports/verification-csm.json`: 691 symbols, 325 exact + 366 tolerance, 0 mismatch, 1 skip (`SET:SET`), `overall_parity: true` |
| 4b | Tier 1 tfex verification | **DEFERRED (legit)** | No `reports/verification-tfex.json`; no mirror Parquet / TFEX data in the engine |
| 5a | csm cutover (default + deprecation + docs) | **DONE** | `strategies/csm-set/src/csm/config/settings.py` `ohlcv_source` default `"db"`; csm-set CLAUDE.md updated; PR `lumduan/csm-set#15` |
| 5b | tfex cutover | **NOT DONE (deferred)** | `strategies/tfex-s50-multi-tf-swing/.../config/settings.py` default still `"mirror"` (tvkit-direct) |
| 6 | Gap analysis (if <100%) | **N/A** | csm = 100% parity; tfex deferred is no-data, not a parity gap |
| 7 | No strategy fetches tvkit directly | **PARTIAL** | csm: default `db` ⇒ no tvkit on default path ✓; tfex: default `mirror` ⇒ **still tvkit-direct by default** ✗ |
| 8 | Backtest read performance documented | **NOT DONE** | No perf-comparison artifact in the repo; documented as pending |
| 9 | Cutover runbook in umbrella `.claude/playbooks/` | **PARTIAL → addressed in Phase 6** | Only `switch-csm-set-to-engine-reads.md` (Phase-3-era, csm-only) existed; Phase 6 authors a consolidated `marketdata-engine-cutover.md` (umbrella) |

**Already-documented carve-outs (reflected, not re-litigated):** `SET:SET` index/sectors fix
deferred from Phase 3; engine `4h` route unbuilt (`cagg_ohlcv_4h` unrouted, declined
client-side in tfex); engine-native back-adjusted `S501!` deferred (tfex back-adjusts
locally). All are documented as **pending**, not done.

---

## Scope

### In scope

- The focused-core `docs/` set (architecture ×3, API ×5, operations ×3, data ×4) + a
  `docs/README.md` hub; refresh the stale `docs/overview.md`.
- Three `.claude/knowledge/` files (data-flow, deployment, api-contract); refresh
  `market-data-engine.md`.
- Engine `CLAUDE.md` Documentation index + Current-state correction.
- Engine `docs/plans/ROADMAP.md` Phase 6 checkmarks + Phase 5 wording correction.
- Umbrella (separate branch): consolidated cutover runbook + roadmap checkmarks + knowledge
  cross-refs + agent memory.

### Out of scope (tracked as `(TODO: Phase 6.x)`)

- `docs/getting-started/`, `docs/concepts/`, `docs/reference/`, `docs/guides/` subtrees.
- Additional `.claude/playbooks/` (docs-workflow, data-refresh, troubleshooting) and
  `.claude/memory/cookie-management.md`.
- Any code change, tfex cutover, engine 4h route, or `09` physical DROP (other phases).

---

## The "tvkit-ref style, AI-agent-first" deliverable

**Style exemplar.** tvkit is not checked out in this workspace; the style is matched from
its **documented structure** (the 7-category `docs/` hierarchy referenced in this repo's
[`ROADMAP.md`](ROADMAP.md) §6.2 and indexed in [`../../CLAUDE.md`](../../CLAUDE.md)) and the
voice of this repo's existing plans/knowledge. The exemplar repo:
https://github.com/lumduan/tvkit/tree/main/docs.

**What "AI-agent-first" means here, concretely:**

- **A hub-and-spoke layout.** `docs/README.md` is a hub that one-line-describes and links
  every sub-doc, so an agent can navigate by reading one file.
- **Explicit contracts, not prose.** Every endpoint documents method, path, the
  gateway-proxied path, every query/body parameter (type, default, allowed values), the exact
  response shape, and every status code it can return.
- **Example-driven.** Every endpoint shows a **real** `curl` request and a **real** JSON
  response. Money is `Decimal`-as-string on the wire; `ts` is UTC bar-open (display
  Asia/Bangkok noted).
- **Self-contained + cross-linked.** Every cross-repo dependency is a project-relative link;
  deferred behaviour is labelled **pending**, never implied done.
- **No secrets.** The tvkit cookie and API keys appear only as placeholders.

---

## Design decisions

1. **Branch base = `main` (engine repo).** Unlike the strategy repos (csm-set uses
   `live-test`), the engine repo's integration branch is `main`; Phase 2 and Phase 5 both
   branched off `main`, and `main` is current with origin. Docs branch off `main`.
2. **Focused core now, full tree later.** The full ~40-file tvkit tree pre-listed in
   `CLAUDE.md` is valuable but large; Phase 6 ships the high-value core the originating
   prompt names as the minimum and leaves the rest as `(TODO: Phase 6.x)` so no link breaks.
3. **`/admin/ingest` documented as engine-direct, not gateway-proxied.** The gateway proxy
   (`quant-api-gateway/src/api/v2/engines/market_data.py`) forwards only `/health`,
   `/ohlcv`, `/ohlcv/adjusted`, `/universe` (+ static `/providers`). Owner-mode ingest is
   reached on the engine host (`:8300`) directly — the docs reflect this.
4. **Knowledge files point to `docs/`, not duplicate it.** The 3 new `.claude/knowledge`
   files are concise and link into `docs/` to avoid drift.

---

## File changes

### Engine repo — `docs/` (focused core)

| File | Action | Audience | Sections |
|------|--------|----------|----------|
| `docs/plans/phase6-documentation.md` | CREATE | maintainer | This plan |
| `docs/README.md` | CREATE | all | Hub: one-line links to every sub-doc |
| `docs/overview.md` | MODIFY | all | Remove "Scaffold only"; point to the hub; reflect live state |
| `docs/architecture/overview.md` | CREATE | agent/dev | Topology, ingest vs read sides, hot/warm path, gateway position, cookie-owner invariant |
| `docs/architecture/data-model.md` | CREATE | agent/dev | `market_data.*`, PK `(symbol,timeframe,ts)`, CAGGs (1h/4h), compression, numeric scales |
| `docs/architecture/security-boundary.md` | CREATE | agent/dev | `X-API-Key` gate, sole-cookie-owner, public-data boundary, public vs owner mode |
| `docs/api/health.md` | CREATE | consumer | `GET /health` shape + curl + gateway path |
| `docs/api/ohlcv.md` | CREATE | consumer | `GET /ohlcv` params, 200 example, 401/422 errors, proxy path |
| `docs/api/ohlcv-adjusted.md` | CREATE | consumer | `GET /ohlcv/adjusted`; futures-roll parity **pending** |
| `docs/api/universe.md` | CREATE | consumer | `GET /universe` `as_of`/`index_name`, resolved-snapshot semantics |
| `docs/api/admin-ingest.md` | CREATE | owner | `POST /admin/ingest` (engine-direct, owner mode + key); 400/502; never logs cookie |
| `docs/operations/bring-up.md` | CREATE | operator | Bring-up order, compose (public vs private overlay), network prereq, health checks |
| `docs/operations/configuration.md` | CREATE | operator | Every `MARKETDATA_ENGINE_*` + `TVKIT_AUTH_TOKEN`: default/allowed/effect; reader flags; safe cookie injection |
| `docs/operations/troubleshooting.md` | CREATE | operator | Cookie expiry, DB/Redis down (`degraded`), gateway 502/503/504, public-mode ingest refusal |
| `docs/data/ohlcv-schema.md` | CREATE | agent/dev | OHLCV table columns, constraints, compression, idempotent upsert |
| `docs/data/corporate-actions.md` | CREATE | agent/dev | `corporate_actions`, roll dates, adjust-on-read math; native S501! **pending** |
| `docs/data/universe-membership.md` | CREATE | agent/dev | As-of dated constituents, point-in-time correctness |
| `docs/data/parquet-snapshot.md` | CREATE | agent/dev | DB→Parquet exporter, decimal128-exact, offline backtest usage |

### Engine repo — `.claude/` + agent context

| File | Action | Description |
|------|--------|-------------|
| `.claude/knowledge/data-flow.md` | CREATE | Read/write paths, cache hierarchy, single-flight lock → links `docs/` |
| `.claude/knowledge/deployment.md` | CREATE | Compose topology, host ports, env reference → links `docs/operations/configuration.md` |
| `.claude/knowledge/api-contract.md` | CREATE | Full request/response + error codes → links `docs/api/` |
| `.claude/knowledge/market-data-engine.md` | MODIFY | Cross-ref the new Phase 6 docs |
| `CLAUDE.md` | MODIFY | Flip focused-core files to live links; Current state Phase 6 partial |
| `docs/plans/ROADMAP.md` | MODIFY | Tick §6.1/§6.2 boxes done; correct Phase 5 wording |

### Umbrella repo (branch `docs/phase6-marketdata-engine`)

| File | Action | Description |
|------|--------|-------------|
| `.claude/playbooks/marketdata-engine-cutover.md` | CREATE | Consolidated cutover runbook (csm done; tfex **pending Phase 5.x**) |
| `plans/feature-market-data-engine/ROADMAP.md` | MODIFY | Phase 6 checkmarks; correct Phase 5 item status |
| `CLAUDE.md` | MODIFY | feature row: Phase 6 docs (core) complete; Phase 5 corrected; runbook ref |
| `.claude/knowledge/feature-market-data-engine.md` | MODIFY | Cross-ref Phase 6 docs |
| `.claude/knowledge/feature-market-data-engine-reader-cutover.md` | MODIFY | Cross-ref runbook + Phase 6 docs |

---

## Docs that must stay in sync

| When an engine doc changes… | Update in the umbrella |
|---|---|
| `docs/api/*` (endpoint surface) | `CLAUDE.md` engine catalog `/api/v2/engines/market-data/*` row |
| `docs/operations/configuration.md` (env vars / reader flags) | `marketdata-engine-cutover.md` + `switch-csm-set-to-engine-reads.md` |
| `docs/architecture/*` (decisions) | `.claude/knowledge/feature-market-data-engine.md` (ADR) |
| Phase status in `docs/plans/ROADMAP.md` | `plans/feature-market-data-engine/ROADMAP.md` + `CLAUDE.md` |

---

## Implementation steps

1. Branch `docs/phase6-documentation` off `main` (engine). ✓
2. Write this plan. ✓
3. Write the focused-core `docs/` set (hub → architecture → api → operations → data).
4. Refresh `docs/overview.md`; create the 3 `.claude/knowledge` files; refresh
   `market-data-engine.md`.
5. Update engine `CLAUDE.md` + `docs/plans/ROADMAP.md`.
6. Switch to the umbrella branch; author the cutover runbook + roadmap/CLAUDE/knowledge
   updates + agent memory.
7. Run the engine quality gate; verify cross-refs + no secrets.
8. Commit each repo (conventional + `Co-Authored-By` trailer); open one PR per repo.

---

## Quality gate

Run in the engine repo before any push (doc-only must still leave it green):

```bash
cd quant-marketdata-engine
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

Docs are Markdown only (no `src/` change), so mypy/pytest/coverage are unaffected from the
current green `main`. If any post-format edit touches code/docstrings, re-run
`ruff format --check` before push.

---

## Success criteria / acceptance checklist

- [ ] This plan written in phase1-sample format with the originating prompt verbatim
- [ ] 16 focused-core docs + `docs/README.md` hub created; stale `docs/overview.md` updated
- [ ] Every engine endpoint has a real `curl` request + response example
- [ ] Every env var documents default + allowed values + effect; no real secrets (placeholders only)
- [ ] 3 `.claude/knowledge` TODOs (data-flow, deployment, api-contract) created
- [ ] Engine `CLAUDE.md` + `docs/plans/ROADMAP.md` updated; Phase 5 wording corrected
- [ ] Umbrella consolidated cutover runbook authored (tfex flagged pending Phase 5.x)
- [ ] Umbrella `CLAUDE.md` + feature ROADMAP + knowledge + agent memory updated
- [ ] Deferred items (tfex cutover/verification, engine 4h route, `SET:SET` index/sectors,
      native S501! back-adjust, backtest perf) documented as **pending**, not done
- [ ] No broken cross-references: every project-relative path resolves or is `(TODO: Phase 6.x)`
- [ ] Engine quality gate green; two PRs opened against `main`; result table reported

---

## Completion notes

*(To be filled after implementation.)*

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.8)
**Status:** In progress
**Created:** 2026-06-02
