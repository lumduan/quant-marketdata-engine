# Phase 5: End-to-End Verification & Cutover

**Feature:** feature-market-data-engine — Phase 5: End-to-end verification & cutover
**Branch (engine, the plan + scripts):** `feat/phase5-end-to-end-verification-cutover` (based on `main`)
**Created:** 2026-06-02
**Status:** In progress
**Depends On:** Phase 0 (ADR) · Phase 1 (schema) · Phase 2 (engine + gateway proxy) · Phase 3 (csm-set reader, flag complete) · Phase 4 (tfex reader, flag complete)

> **Cross-repo note.** This document lives in `quant-marketdata-engine` because that is
> where the verification plan and scripts live, but the cutover (config flips, deprecation
> warnings) lands in the strategy repos (`csm-set`, `tfex-s50-multi-tf-swing`), and the
> roadmap/knowledge updates land in the umbrella. Four repos may be touched; PRs are
> opened together and cross-linked. The engine PR (this one) is primary.

---

## Table of Contents

1. [Overview](#overview)
2. [Originating prompt](#originating-prompt)
3. [Objective, scope, non-goals](#objective-scope-non-goals)
4. [Verification strategy](#verification-strategy)
5. [Verification script design](#verification-script-design)
6. [Tolerance specification](#tolerance-specification)
7. [Edge-case coverage](#edge-case-coverage)
8. [File changes (engine repo)](#file-changes-engine-repo)
9. [File changes (strategy repos — if cutover)](#file-changes-strategy-repos--if-cutover)
10. [File changes (umbrella)](#file-changes-umbrella)
11. [Test plan & coverage](#test-plan--coverage)
12. [Cutover conditions & actions](#cutover-conditions--actions)
13. [Cross-repo PR sequence](#cross-repo-pr-sequence)
14. [Success criteria](#success-criteria)
15. [Completion notes](#completion-notes)

---

## Overview

### Purpose

Phases 0–4 built the Market Data Engine and wired two strategy readers behind feature
flags. The engine is live, both strategies can read from it, but **no end-to-end parity
verification has been run and no cutover decision has been formalised.** Phase 5 closes
this gap: prove the engine path produces output identical to the legacy tvkit-direct
path, then flip the defaults so the engine becomes the unambiguous single source of
truth for OHLCV data.

### Current state (post-Phase 4)

| Reader | Config flag | Modes | Default | Legacy path | Engine path |
|--------|-------------|-------|---------|-------------|-------------|
| `csm-set` | `CSM_OHLCV_SOURCE` | `parquet` / `db` | `parquet` (=tvkit) | tvkit → parquet → `OHLCVLoader` | httpx → gateway → engine → DB (`MarketDataEngineLoader`) |
| `tfex-s50-multi-tf-swing` | `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE` | `mirror` / `engine` | `mirror` (=tvkit) | tvkit → schema-09 mirror (`OhlcvFetcher`) | httpx → gateway → engine → raw dated contracts, back-adjusted locally (`EngineOhlcvFetcher`) |

### Parent plan references

- Umbrella feature roadmap: [`../../../plans/feature-market-data-engine/ROADMAP.md`](../../../plans/feature-market-data-engine/ROADMAP.md) §"Phase 5"
- Per-service roadmap: [`ROADMAP.md`](ROADMAP.md) §"Phase 5"
- ADR (D1–D10, read contract): [`../../../.claude/knowledge/feature-market-data-engine.md`](../../../.claude/knowledge/feature-market-data-engine.md)
- Reader cutover decisions: [`../../../.claude/knowledge/feature-market-data-engine-reader-cutover.md`](../../../.claude/knowledge/feature-market-data-engine-reader-cutover.md)
- Sibling phase plans: [`phase3-csm-set-read-from-store.md`](phase3-csm-set-read-from-store.md), [`phase4-tfex-consume-shared-store.md`](phase4-tfex-consume-shared-store.md)
- Plan format reference: [`../../strategies/csm-set/docs/plans/examples/phase1-sample.md`](../../strategies/csm-set/docs/plans/examples/phase1-sample.md)

### Key deliverables

1. **This plan document** — `quant-marketdata-engine/docs/plans/phase5-end-to-end-verification-cutover.md`
2. **Verification scripts** in `quant-marketdata-engine/tests/verification/`:
   - `verification_utils.py` — shared comparison logic, report generation, CLI helpers
   - `verify_csm_parity.py` — csm-set: engine vs parquet comparison
   - `verify_tfex_parity.py` — tfex: engine vs mirror comparison
3. **Verification reports** as JSON artifacts (committed alongside the scripts)
4. **Cutover commits** (if 100% parity) — config default flips, deprecation warnings, doc updates
5. **Updated CLAUDE.md / .claude files** in engine repo and umbrella
6. **Updated roadmaps** with Phase 5 checkmarks

---

## Originating prompt

The following prompt initiated this work (embedded verbatim):

```
# Phase 5 — End-to-end verification & cutover (feature-market-data-engine)

## Objective

Verify that the two strategy readers (`csm-set` and `tfex-s50-multi-tf-swing`) produce
**output identical to their legacy tvkit-direct counterparts** when sourcing from
`quant-marketdata-engine`, then execute the final cutover — demoting or removing the
legacy paths and making the engine the unambiguous single source of truth for OHLCV data.

## Context

You are implementing **Phase 5** of `feature-market-data-engine`, a cross-cutting
platform feature whose umbrella roadmap lives at
`plans/feature-market-data-engine/ROADMAP.md`. The engine is live (Phase 2 ✓), both
strategies read through it behind feature flags (Phases 3 ✓ + 4 ✓), but no end-to-end
parity verification has been run and no cutover decision has been formalised.

### Current state (post-Phase 4)

| Reader | Config flag | Modes | Default | Legacy path | Engine path |
|--------|-------------|-------|---------|-------------|-------------|
| `csm-set` | `CSM_OHLCV_SOURCE` | `parquet` / `db` | `parquet` (=tvkit direct) | tvkit → parquet → loader | httpx → gateway → engine → DB |
| `tfex-s50-multi-tf-swing` | `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE` | `mirror` / `engine` | `mirror` (=tvkit direct schema-09) | tvkit → standalone schema-09 mirror | httpx → gateway → engine → DB (raw dated contracts, back-adjusted locally) |

### What "verification" means

1. **Data parity** — for a representative date window (≥30 trading days), compare
   OHLCV DataFrames produced by the legacy path and the engine path, symbol-by-symbol,
   timeframe-by-timeframe. Tolerances: price columns (open/high/low/close) within
   ±0.01 absolute, volume within ±1 share, timestamp alignment exact.
2. **Adjustment parity** — where back-adjustment is applied (tfex continuous
   contracts), verify the adjustment methodology produces the same forward-adjusted
   series (within the same tolerances) as the legacy pipeline.
3. **Edge-case coverage** — trading halts, splits/dividends, symbol additions/delistings,
   partial-day data, and cross-timezone boundaries (SET vs TFEX).
4. **Performance comparison** — wall-clock latency for a full universe load (legacy vs
   engine), cold-start (empty Redis cache) vs warm-hit.

### Deliverables

1. **Implementation plan** — a markdown file at
   `quant-marketdata-engine/docs/plans/phase5-end-to-end-verification-cutover.md`
   following the format of `strategies/csm-set/docs/plans/examples/phase1-sample.md`.
   The plan must include this prompt verbatim in a `## Prompt` section at the bottom.

2. **Verification scripts** — one per reader (`csm-set` and `tfex-s50-multi-tf-swing`),
   runnable via `uv run`, that:
   - Load OHLCV data from both the legacy path and the engine path for the same
     (symbols, timeframes, date range).
   - Diff the DataFrames column-by-column with the tolerances above.
   - Produce a JSON report (`verification-report-{reader}.json`) summarising:
     - Symbols checked, timeframes checked, date range
     - Per-symbol pass/fail with mismatch counts
     - Aggregate pass rate (target: 100% for Phase 5 sign-off)
   - Log every mismatch with the exact symbol, date, column, legacy value, and engine
     value.

3. **Cutover PR** — based on verification results, either:
   - **If 100% parity**: flip the default config values from legacy to engine in both
     strategy repos, demote legacy paths to fallback-only (keep code but add deprecation
     warnings), and update all relevant docs/CLAUDE.md files.
   - **If <100% parity**: file a gap-analysis document listing every mismatch category,
     root cause, and fix plan. Do NOT flip defaults until gaps are closed.

4. **Knowledge / memory / playbook updates** — review and update:
   - `quant-marketdata-engine/CLAUDE.md`
   - `quant-marketdata-engine/.claude/*` (knowledge, playbooks, skills as needed)
   - Umbrella `CLAUDE.md` and `.claude/*` (especially the optional-features registry
     and the market-data-engine ADR at `.claude/knowledge/feature-market-data-engine.md`)
   - Any memory files in `.claude/projects/-home-batt-docker-quant-trading-system/memory/`
     that reference the market-data-engine feature

5. **Roadmap checkmarks** — after cutover succeeds, update:
   - `plans/feature-market-data-engine/ROADMAP.md` — mark Phase 5 complete
   - `quant-marketdata-engine/docs/plans/ROADMAP.md` — mark Phase 5 complete

## Requirements

### Process
- **Read first.** Before any code, read all four docs: umbrella `CLAUDE.md`,
  `plans/feature-market-data-engine/ROADMAP.md`,
  `quant-marketdata-engine/docs/plans/ROADMAP.md`, and
  `quant-marketdata-engine/CLAUDE.md`.
- **Branch.** Create a new git branch in `quant-marketdata-engine/` named
  `feat/phase5-end-to-end-verification-cutover` off `main`.
- **Plan before code.** Write the implementation plan at
  `quant-marketdata-engine/docs/plans/phase5-end-to-end-verification-cutover.md`
  and get it approved before writing any implementation code.
- **Commit and PR.** When finished, commit all changes and open a PR to
  `lumduan/quant-marketdata-engine` with the branch.

### Code quality (per-project standards from `quant-marketdata-engine/CLAUDE.md`)
- Python 3.11, FastAPI, `uv` package manager
- **ruff** for linting + formatting, **mypy strict** mode, **pytest ≥90%** coverage
  on new code
- Async correctness throughout (httpx async client, asyncio patterns)
- All monetary/price values as `Decimal`, never `float`
- Timezone-aware: store UTC, display Asia/Bangkok
- Secrets in `.env` (gitignored), never committed

### Verification script design
- Accept CLI args: `--symbols` (comma-separated or "ALL"), `--timeframes` (e.g.
  `1d,1h,4h`), `--start-date`, `--end-date`, `--output` (report path)
- Load legacy data via the existing loader factories (`build_ohlcv_loader` in csm-set,
  the mirror loader in tfex)
- Load engine data via the existing httpx clients that talk to the gateway proxy
- Use `pandas.testing.assert_frame_equal` or equivalent with custom tolerance
  comparators
- Exit code 0 on 100% parity, non-zero on any mismatch

### Tolerance specification
| Column group | Absolute tolerance | Notes |
|-------------|-------------------|-------|
| open, high, low, close | 0.01 | Price rounding differences |
| volume | 1 | Integer rounding |
| timestamp / datetime index | exact | Must match precisely |
| adjusted_close (tfex) | 0.01 | Same as price columns |

### Security & secrets
- The verification scripts must NOT log or persist any tvkit credentials or cookies.
- Engine access uses the gateway's `INTERNAL_API_KEY` from env — never hardcode it.

### Performance
- Benchmark wall-clock time for a full load of both paths; report the ratio.
- If the engine path is >2× slower than legacy, file a performance issue (do not block
  cutover on it, but document it).

### Backward compatibility
- Do NOT delete legacy code paths in this phase. Deprecation warnings only.
- The legacy path must remain functional behind its config flag for at least one
  release cycle after cutover, so operators can roll back if needed.

### Edge cases to verify explicitly
1. Symbols that exist in legacy but not in engine (and vice versa)
2. Symbols delisted mid-window (partial data)
3. Trading halts (gaps in data — both paths should have the same gaps)
4. SET index `.SET` and sector indices (known deferred from Phase 3)
5. TFEX dated-contract symbols vs continuous adjusted symbols
6. 4h timeframe (declined client-side in Phase 4 — confirm engine path handles it
   correctly or explicitly skip with a documented reason)

## Code context

### Repos and paths (project-relative)
- `quant-marketdata-engine/` — the standalone engine service (host `:8300`)
- `strategies/csm-set/` — first reader, reads behind `CSM_OHLCV_SOURCE`
- `strategies/tfex-s50-multi-tf-swing/` — second reader, reads behind
  `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE`
- `quant-api-gateway/` — proxies `/api/v2/engines/market-data/*` to the engine
- `plans/feature-market-data-engine/ROADMAP.md` — umbrella roadmap
- `quant-marketdata-engine/docs/plans/ROADMAP.md` — engine-level roadmap
- `strategies/csm-set/docs/plans/examples/phase1-sample.md` — plan format reference

### Key interfaces
- Engine read API (gateway-proxied): `GET /api/v2/engines/market-data/ohlcv`,
  `GET /api/v2/engines/market-data/ohlcv/adjusted`,
  `GET /api/v2/engines/market-data/universe`
- Legacy csm-set loader: `build_ohlcv_loader(source="parquet"|"db")` at the
  `daily_refresh` seam
- Legacy tfex loader: schema-09 mirror (tvkit → standalone DB table)
- Engine-side httpx clients: `MarketDataEngineLoader` (csm-set),
  tfex engine-mode client (tfex-s50-multi-tf-swing)

### Docker network
- All services on `quant-network` (created by `quant-infra-db`)
- Engine hostname: `quant-marketdata-engine` (internal port 8000, host port 8300)
- Gateway hostname: `quant-api-gateway` (internal port 8000, host port from `.env`)
- Bring-up order: infra-db → marketdata-engine → api-gateway → strategies → openbb
```

---

## Objective, scope, non-goals

### Objective

Verify that both strategy reader paths produce output identical to their legacy
tvkit-direct counterparts within specified tolerances, then execute the final cutover:
flip config defaults from legacy to engine, add deprecation warnings, and update all
documentation.

### In scope

| Item | Description |
|------|-------------|
| Verification scripts | `verify_csm_parity.py`, `verify_tfex_parity.py`, `verification_utils.py` |
| Tier 1 verification | Engine vs strategy Parquet store (primary, deterministic) |
| JSON reports | Structured parity reports with per-symbol status |
| Cutover (if 100%) | Default flips in csm-set + tfex, deprecation warnings, doc updates |
| Gap analysis (if <100%) | Mismatch categories, root causes, fix plan |
| Roadmap updates | Phase 5 checkmarks in both roadmaps |
| Doc/knowledge updates | CLAUDE.md, .claude/knowledge/, memory files |

### Out of scope

| Item | Reason |
|------|--------|
| Deleting legacy code paths | Deprecation warnings only; deletion is a future release cycle |
| Tier 2 live dual-fetch | Supplementary — not a gating condition |
| Engine 4h route | Tracked follow-up, not Phase 5 |
| Schema-09 physical DROP | Separate `quant-infra-db` PR |
| csm-set SET:SET index/sectors fix | Deferred from Phase 3 |
| Engine native back-adjusted S501! | Phase 5+ follow-up |

---

## Verification strategy

### Two-tier approach

**Tier 1: Parquet-to-engine comparison (primary, deterministic).** Compare engine
output against each strategy's durable Parquet store — the ground truth the strategies
were validated on. No tvkit cookie needed; tests the full read pipeline (DB → API →
HTTP → client → DataFrame transform) end-to-end.

**Tier 2: Live dual-fetch (supplementary, future).** For a small subset of symbols,
fetch fresh from tvkit through BOTH paths simultaneously. Requires tvkit cookie.
Not implemented in this phase — tracked as a follow-up enhancement.

### Why Tier 1 is sufficient for cutover

- The engine DB is seeded from the same Parquet files the strategies use as their durable store
- The Parquet store is the ground truth the strategies were validated on
- Tier 1 runs without a tvkit cookie → automatable, reproducible
- Both strategies' engine-mode loaders already pass unit parity tests with synthetic data

### Symbol scope

| Strategy | Timeframes | Source | Notes |
|----------|------------|--------|-------|
| csm-set | `1d` | Parquet files in `data/raw/dividends/` | ~445+ equity symbols; `.SET` index + sectors skipped (deferred) |
| tfex | `5m`, `1h` | Mirror Parquet in `data/raw/` | S50 dated contracts (H/M/U/Z); `4h` skipped (engine unrouted) |

---

## Verification script design

### Package structure

```
quant-marketdata-engine/tests/verification/
├── __init__.py              # Package marker
├── verification_utils.py     # ComparisonResult, compare_ohlcv_frames, report generation, CLI helpers
├── verify_csm_parity.py      # csm-set: engine vs parquet comparison
└── verify_tfex_parity.py     # tfex: engine vs mirror comparison
```

### `verification_utils.py` — shared infrastructure

**`ComparisonResult`** dataclass:
- `status: Literal["match", "tolerance_match", "mismatch", "no_data"]`
- `max_price_diff: float`
- `max_volume_diff: float`
- `mismatch_details: list[MismatchRecord]`
- `missing_in_expected: int`
- `missing_in_actual: int`

**`compare_ohlcv_frames`** function:
1. Align both DataFrames on timestamp index (intersection)
2. For each row pair, compute per-column absolute differences
3. Classify: `match` (all diffs == 0), `tolerance_match` (within tolerance), `mismatch` (exceeds)
4. Rows in only one → flagged as `missing_in_expected` or `missing_in_actual`

**`build_report` / `write_report`**: Generate JSON report with summary, per-symbol status, mismatch details, and skipped symbols.

**CLI helpers**: Shared `argparse.ArgumentParser` factory for `--engine-base-url`, `--api-key`, `--tolerance-price`, `--tolerance-volume`, `--output`, `--verbose`.

### `verify_csm_parity.py`

CLI args: `--parquet-dir`, `--symbols` (comma-separated or "ALL"), `--timeframe` (default `1d`), `--limit` (default 5000), `--concurrency` (default 4), plus shared args.

Flow:
1. Discover symbols from Parquet directory (URL-decode filenames)
2. For each symbol, read Parquet → pandas DataFrame
3. For each symbol, call engine via httpx → transform to csm canonical DataFrame shape
4. Compare with `compare_ohlcv_frames`
5. Handle edge cases: `.SET` index skipped, engine unreachable, empty responses
6. Write JSON report, exit 0 on 100% parity

### `verify_tfex_parity.py`

CLI args: `--mirror-dir`, `--contracts` (comma-separated or "ALL"), `--timeframes` (comma-separated, default `5m,1h`), `--start`, `--end`, plus shared args.

Flow:
1. Discover contracts from mirror Parquet directory
2. For each contract+timeframe, read mirror Parquet → Polars DataFrame
3. For each contract+timeframe, call engine via httpx → transform to tfex raw-frame shape
4. Compare shared columns only: `[time, open, high, low, close, volume]`
5. Handle edge cases: `4h` skipped, contracts missing in engine
6. Write JSON report, exit 0 on 100% parity

### Developer workflow

```bash
# Bring up stack
cd quant-infra-db && docker compose up -d
cd ../quant-marketdata-engine && docker compose -f docker-compose.yml -f docker-compose.private.yml up -d
cd ../quant-api-gateway && docker compose up -d

# Seed engine (csm-set backfill)
uv run python -m src.quant_marketdata_engine.ingest backfill \
  --dir ../strategies/csm-set/data/raw/dividends

# Run verification
uv run python tests/verification/verify_csm_parity.py \
  --engine-base-url http://localhost:8300 \
  --parquet-dir ../strategies/csm-set/data/raw/dividends \
  --output reports/verification-csm.json

uv run python tests/verification/verify_tfex_parity.py \
  --engine-base-url http://localhost:8300 \
  --mirror-dir ../strategies/tfex-s50-multi-tf-swing/data/raw \
  --output reports/verification-tfex.json
```

---

## Tolerance specification

| Column group | Absolute tolerance | Notes |
|-------------|-------------------|-------|
| open, high, low, close | 0.01 | Price rounding differences |
| volume | 1 | Integer rounding |
| timestamp / datetime index | exact | Must match precisely |

---

## Edge-case coverage

| Edge case | Handling |
|-----------|----------|
| `.SET` index + sector indices missing in engine | Skipped with note "Known deferred (Phase 3)" |
| `4h` timeframe for tfex | Skipped with note "engine does not serve 4h (cagg_ohlcv_4h unrouted)" |
| `open_interest` in engine but not mirror | Comparison on shared columns only |
| Symbols delisted mid-window | Report intersection; flag extra rows |
| Trading halts (gaps) | Natural timestamp alignment |
| Empty engine response | `no_actual_data` status |
| Network error on engine | Fail fast with clear message; non-zero exit |
| Volume diff ≤ 1 | `tolerance_match`, not a failure |
| Decimal scale mismatch (18,6 vs 18,4 vs float) | Tolerance absorbs |

---

## File changes (engine repo)

| File | Action | Description |
|------|--------|-------------|
| `docs/plans/phase5-end-to-end-verification-cutover.md` | CREATE | This implementation plan |
| `tests/verification/__init__.py` | CREATE | Package marker |
| `tests/verification/verification_utils.py` | CREATE | ComparisonResult, compare_ohlcv_frames, report generation, CLI helpers |
| `tests/verification/verify_csm_parity.py` | CREATE | csm-set parity verification script |
| `tests/verification/verify_tfex_parity.py` | CREATE | tfex parity verification script |
| `tests/verification/test_verification_utils.py` | CREATE | Unit tests for verification_utils.py |
| `pyproject.toml` | MODIFY | Add `verification` dependency group (pandas, polars) |
| `docs/plans/ROADMAP.md` | MODIFY | Tick Phase 5 boxes, update Current Status |
| `CLAUDE.md` | MODIFY | Update Current state to Phase 5 complete |

---

## File changes (strategy repos — if cutover)

### `strategies/csm-set` (branch: `feat/phase5-cutover`)

| File | Action | Description |
|------|--------|-------------|
| `src/csm/config/settings.py` | MODIFY | Change `ohlcv_source` default from `"parquet"` to `"db"` |
| `src/csm/data/loader.py` | MODIFY | Add `DeprecationWarning` in `OHLCVLoader.__init__` |
| `.env.example` | MODIFY | Update `CSM_OHLCV_SOURCE` default comment |
| `CLAUDE.md` | MODIFY | Update OHLCV source section default to `db` |

### `strategies/tfex-s50-multi-tf-swing` (branch: `feat/phase5-cutover`)

| File | Action | Description |
|------|--------|-------------|
| `src/tfex_s50_multi_tf_swing/config/settings.py` | MODIFY | Change `ohlcv_source` default from `"mirror"` to `"engine"` |
| `src/tfex_s50_multi_tf_swing/data/fetcher.py` | MODIFY | Add `DeprecationWarning` in `OhlcvFetcher.__init__` |
| `.env.example` | MODIFY | Update `_OHLCV_SOURCE` default comment |
| `CLAUDE.md` | MODIFY | Update OHLCV source section default to `engine` |

---

## File changes (umbrella)

| File | Action | Description |
|------|--------|-------------|
| `plans/feature-market-data-engine/ROADMAP.md` | MODIFY | Mark Phase 5 complete |
| `CLAUDE.md` | MODIFY | Update engine catalog status |
| `.claude/knowledge/feature-market-data-engine-reader-cutover.md` | MODIFY | Phase 5 cutover state |
| `.claude/knowledge/feature-market-data-engine.md` | MODIFY | Refresh with cutover decisions |
| `.claude/projects/.../memory/project-marketdata-engine-bootstrap.md` | MODIFY | Phase 5 complete |

---

## Test plan & coverage

### Unit tests for `verification_utils.py`

| Test | Description |
|------|-------------|
| `test_exact_match` | Identical DataFrames → all match |
| `test_tolerance_match` | Within tolerance → tolerance_match |
| `test_mismatch_price` | Price diff > 0.01 → mismatch |
| `test_mismatch_volume` | Volume diff > 1 → mismatch |
| `test_missing_rows` | Different timestamps → missing counts |
| `test_empty_actual` | Engine returns no data → no_actual_data |
| `test_empty_expected` | No parquet data → no_expected_data |
| `test_report_json_schema` | Verify report dict structure |
| `test_discover_csm_symbols` | URL-decode parquet filenames → symbol list |

Coverage target: ≥90% on `verification_utils.py`.

### Quality gate

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

---

## Cutover conditions & actions

### Gate: 100% parity

All symbols present in both stores (except known-deferred), every OHLCV value within
tolerance, timestamps match exactly, no unexplained mismatches.

### If gate passes

1. Flip `CSM_OHLCV_SOURCE` default `"parquet"` → `"db"` in csm-set
2. Flip `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE` default `"mirror"` → `"engine"` in tfex
3. Add `DeprecationWarning` in `OHLCVLoader` and `OhlcvFetcher`
4. Update docs (CLAUDE.md, .env.example, knowledge files)
5. Legacy path remains functional behind flag for ≥1 release cycle

### If gate fails

1. Produce gap analysis document listing every mismatch category, root cause, fix plan
2. File GitHub issues for each discrepancy
3. Do NOT flip defaults
4. Defer cutover to Phase 5.1

---

## Cross-repo PR sequence

1. **quant-marketdata-engine** (primary) — plan + verification scripts + roadmap updates
2. **strategies/csm-set** (if cutover) — config flip + deprecation warning
3. **strategies/tfex-s50-multi-tf-swing** (if cutover) — config flip + deprecation warning
4. **umbrella** — roadmap checkmarks + knowledge/playbook updates

---

## Success criteria

- [ ] Implementation plan written at `docs/plans/phase5-end-to-end-verification-cutover.md`
- [ ] `verification_utils.py` with `compare_ohlcv_frames` and report generation — ≥90% test coverage
- [ ] `verify_csm_parity.py` — CLI args, discovers symbols, loads both paths, diffs, reports
- [ ] `verify_tfex_parity.py` — CLI args, discovers contracts, loads both paths, diffs, reports
- [ ] Scripts exit 0 on 100% parity, non-zero on any mismatch
- [ ] JSON report artifacts well-formed with all required fields
- [ ] Known edge cases handled (deferred symbols, 4h, OI, partial data)
- [ ] No tvkit credentials logged or persisted
- [ ] Engine access uses `X-API-Key` from env — never hardcoded
- [ ] If 100% parity: config defaults flipped, deprecation warnings added, docs updated
- [ ] If <100% parity: gap analysis written, issues filed, cutover deferred
- [ ] Roadmaps updated with Phase 5 checkmarks
- [ ] `CLAUDE.md` and `.claude/` files updated in engine + umbrella repos
- [ ] All Python: ruff check + format + mypy strict + pytest green
- [ ] Legacy path remains functional behind config flag (deprecation warning only)
- [ ] Performance comparison: engine vs legacy wall-clock time documented

---

## Completion notes

*(To be filled after implementation.)*

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.8)
**Status:** In progress
**Created:** 2026-06-02
