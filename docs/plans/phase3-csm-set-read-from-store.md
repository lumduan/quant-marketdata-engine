# Phase 3: csm-set reads OHLCV from the Market Data Engine behind a flag

**Feature:** feature-market-data-engine — Phase 3: `strategies/csm-set` reads the store behind a flag
**Branch (csm-set, the code):** `feat/phase3-read-from-marketdata-engine` (based on `live-test`)
**Sibling branch (this repo, the plan/docs):** `quant-marketdata-engine` → `docs/phase3-csm-set-read-plan`
**Sibling branch (umbrella):** `quant-trading-system` → `docs/phase3-csm-set-read`
**Created:** 2026-06-01
**Status:** In progress
**Depends On:** Phase 0 (ADR, complete) · Phase 1 (`quant-infra-db` schema, complete) · Phase 2 (engine service + gateway proxy, complete)

> **Cross-repo note.** This document lives in `quant-marketdata-engine` because that is
> where the Market Data Engine's design record lives, but **all the code for Phase 3 lands
> in the `strategies/csm-set` repo.** Two repos are touched: csm-set (the feature branch
> with the client + flag + tests) and this repo (the plan doc). The umbrella repo carries
> the roadmap checkmark + status flips. PRs are opened together and cross-linked; sequence
> the csm-set code PR as the primary, with the engine + umbrella docs PRs referencing it.

---

## Table of Contents

1. [Overview](#overview)
2. [Originating prompt](#originating-prompt)
3. [Objective, scope, non-goals](#objective-scope-non-goals)
4. [Phase 3 acceptance criteria (verbatim from the umbrella ROADMAP)](#phase-3-acceptance-criteria-verbatim-from-the-umbrella-roadmap)
5. [Verified read-API contract](#verified-read-api-contract)
6. [Feature-flag design](#feature-flag-design)
7. [Read-client design](#read-client-design)
8. [Response → csm OHLCV model mapping](#response--csm-ohlcv-model-mapping)
9. [File changes (csm-set repo)](#file-changes-csm-set-repo)
10. [Test plan & coverage](#test-plan--coverage)
11. [Backward-compat, migration, security, performance, rollback](#backward-compat-migration-security-performance-rollback)
12. [Success criteria](#success-criteria)
13. [Completion notes](#completion-notes)

---

## Overview

### Purpose

Phase 2 made `quant-marketdata-engine` a live, auth-gated OHLCV read API (host `:8300`,
gateway-proxied). Phase 3 makes **`strategies/csm-set` the first consumer to read from it**
instead of fetching tvkit directly — gated behind `CSM_OHLCV_SOURCE = parquet | db` so the
legacy tvkit path stays the default and behaviour is byte-for-byte unchanged until the flag
is flipped. tfex follows in Phase 4; the per-strategy tvkit fetch is only decommissioned in
Phase 5.

### Parent plan references

- Umbrella feature roadmap (scope of record): [`../../../plans/feature-market-data-engine/ROADMAP.md`](../../../plans/feature-market-data-engine/ROADMAP.md) §"Phase 3"
- ADR (D1–D10, read contract): [`../../../.claude/knowledge/feature-market-data-engine.md`](../../../.claude/knowledge/feature-market-data-engine.md)
- Engine read-API source: `src/quant_marketdata_engine/api/routes.py`, `api/schemas.py`
- csm-set seam: `strategies/csm-set/src/csm/data/loader.py`, `api/scheduler/jobs.py`

### Decisions locked with the user

- **Scope:** engine-read flag only. The ROADMAP also bundles a "2026-05-29 index/sectors
  fix" into Phase 3 — that is **deferred to a tracked follow-up** (different code area:
  universe / feature pipeline). The Phase 3 checkmark records the deferral.
- **Git:** branches + commits + green quality gate in each repo, **no push / no PR** in this
  run (mirrors how Phase 2 was left locally). Pushing + the three cross-linked PRs is a
  one-command follow-up.
- **Flag:** `CSM_OHLCV_SOURCE = parquet | db`, default `parquet` — the ROADMAP-pinned name
  (D6 + Phase 3). `parquet` = unchanged legacy tvkit path; `db` = engine read.

---

## Originating prompt

The following prompt initiated this work (embedded verbatim):

```
Task: Implement Phase 3 of `feature-market-data-engine` — `strategies/csm-set` reads OHLCV from the Market Data Engine store behind a feature flag

You are working inside the `quant-trading-system` umbrella meta-repo (cwd `/home/batt/docker/quant-trading-system`). The sub-directories
(`quant-marketdata-engine/`, `strategies/csm-set/`, etc.) are each independent git repos with their own remotes, CI, and CLAUDE.md. The Market Data Engine is
live as of Phase 2 (host `:8300`, gateway-proxied under `/api/v2/engines/market-data/*`; endpoints `/health`, `/ohlcv`, `/ohlcv/adjusted`, `/universe`). Phase
3 makes `strategies/csm-set` consume that read API instead of fetching tvkit directly — gated behind a flag so the old path stays the default until proven.

## Phase 0 — Read before doing anything (do NOT skip)
Read and internalize, in this order:
1. `CLAUDE.md` (umbrella — repo map, Docker network contract, ingestion contract, cross-cutting rules, port allocation: csm-set host `:8100`, market-data host
`:8300`, internal `:8000`).
2. `plans/feature-market-data-engine/ROADMAP.md` — locate the Phase 3 entry; this is where you tick the checkmark when done. Quote the exact Phase 3
acceptance criteria back in your plan.
3. `quant-marketdata-engine/docs/plans/ROADMAP.md` — the engine's own roadmap (cross-reference Phase 3 dependencies / API contract).
4. `quant-marketdata-engine/CLAUDE.md` — engine conventions, read-API contract, response schemas.
5. `strategies/csm-set/CLAUDE.md` — the consumer repo's conventions, quality gate (ruff, mypy, pytest ≥90% on `adapters/` + `api/`), and `uv` usage.
6. `strategies/csm-set/docs/plans/examples/phase1-sample.md` — the exact plan-document format you must mirror.
7. The existing csm-set data-fetch layer (tvkit/`fetch_history` path) and the `reference-tvkit-tradingview-auth` notes — understand the current OHLCV
acquisition so the new client returns an equivalent shape.

Confirm the precise Market Data Engine read-API request/response contract from the engine source/tests before writing the client — do not assume field names;
verify `/ohlcv`, `/ohlcv/adjusted`, and `/universe` payloads, query params (symbol, timeframe, date range, adjusted flag), and error/empty-result semantics.

## Phase 1 — Write the implementation plan FIRST (before any code)
Produce a written plan as a markdown file at `quant-marketdata-engine/docs/plans/phase3-csm-set-read-from-store.md` (use this `{phase_name}` =
`phase3-csm-set-read-from-store`), following the structure of `strategies/csm-set/docs/plans/examples/phase1-sample.md`. The plan MUST:
- Embed THIS prompt verbatim in a clearly labeled "Prompt" section.
- State objective, scope, non-goals, the exact Phase 3 acceptance criteria copied from `plans/feature-market-data-engine/ROADMAP.md`.
- Specify the feature flag design: env-var name (e.g. `CSM_MARKETDATA_SOURCE=engine|tvkit` or a boolean like `CSM_USE_MARKETDATA_ENGINE`, default = legacy
tvkit so behavior is unchanged when unset), where it is read, and how it routes between the new engine-read client and the existing tvkit path.
- Define the new read client: in-cluster base URL `http://quant-marketdata-engine:8000` (host `:8300` for local dev), async HTTP (httpx), strict typing,
timeouts, retry/backoff, structured logging, and graceful fallback/clear-error behavior when the engine is unreachable or returns empty.
- Map engine response → csm-set's internal OHLCV model (1:1 with the current tvkit-derived shape) so downstream strategy logic is untouched.
- List every file to add/modify (project-relative paths), the test plan (unit: client + flag routing with mocked engine responses incl. error/empty/timeout
cases; integration: end-to-end with both flag states), and the coverage target (≥90% on `adapters/` + `api/`).
- Note backward-compatibility (default path unchanged), migration impact (none for consumers when flag off), security (no tvkit cookie in csm-set when reading
from engine; never log/commit secrets; validate inputs), performance (engine read vs tvkit fetch), and rollback (flip flag off).
- Cross-repo note: the CODE change lives in the `strategies/csm-set` repo; the PLAN DOC lives in `quant-marketdata-engine/docs/plans/`. Call out that two
repos are touched and sequence the PRs accordingly.

## Phase 2 — Branch
Create a new feature branch in EACH repo you modify (do not commit on `main`):
- In `strategies/csm-set/`: e.g. `feat/phase3-read-from-marketdata-engine`.
- In `quant-marketdata-engine/`: e.g. `docs/phase3-csm-set-read-plan` (for the plan/docs).
- In the umbrella repo: a branch for the umbrella doc/checkmark updates.
Never edit sub-project history from the umbrella repo; `cd` into each sub-repo and use its own tooling.

## Phase 3 — Implement (csm-set)
- Add the Market Data Engine read client (async httpx, strict mypy-clean types, timeouts, retries, structured logging).
- Add the feature flag and routing so csm-set reads from the engine when enabled and falls back to / defaults to the existing tvkit path when disabled.
- Keep the internal OHLCV model and all downstream strategy logic unchanged.
- Decimal for monetary values at boundaries; UTC storage / Asia/Bangkok display per umbrella rules.
- Add/extend `.env.example` and config docs for the new flag and engine URL. Never commit real secrets.

## Phase 4 — Tests & quality gate (run via `uv run`, per repo)
For `strategies/csm-set`, run the full pre-push gate and make it green:
- `uv run ruff check .`
- `uv run ruff format --check .` (re-run after any post-format edit/sed — formatting is invalidated by later edits)
- `uv run mypy` (strict where the repo configures it)
- `uv run pytest` with ≥90% coverage on `adapters/` + `api/`
Report actual command output. If anything fails, fix and re-run — do not claim green without the passing output.

## Phase 5 — Docs, knowledge, memory, playbooks
Create or update wherever it adds durable value:
- `quant-marketdata-engine/CLAUDE.md` and `quant-marketdata-engine/.claude/*`
- `CLAUDE.md` (umbrella) — flip the `feature-market-data-engine` status line and engine catalog note to reflect Phase 3, and update the optional-features
table/roadmap-status as appropriate.
- `.claude/*` (umbrella) — update `.claude/knowledge/feature-market-data-engine.md` and `.claude/knowledge/optional-features-registry.md`; add a playbook
entry under `.claude/playbooks/` if a cross-repo "switch csm-set to engine reads" workflow is worth capturing.
- Tick the Phase 3 checkmark in `plans/feature-market-data-engine/ROADMAP.md`.
- Update `strategies/csm-set/CLAUDE.md` / its docs for the new flag.

## Phase 6 — Commit & PR (only after gates pass)
Commit each repo's changes on its branch with clear, conventional messages, push, and open a PR per repo via `gh`. In PR descriptions: summarize the change,
link the plan doc, list the flag name + default, note backward compatibility, and paste the passing quality-gate output. Sequence: open the csm-set code PR
and the engine/umbrella docs PRs together, cross-linking them. Do not merge unless instructed.

## Deliverables (report back)
1. The plan markdown path and a one-paragraph summary of the approach.
2. Branch names per repo.
3. New/modified files (project-relative paths).
4. Quality-gate command outputs (ruff/mypy/pytest + coverage %).
5. PR URLs.
6. Confirmation that the default (flag-off) path is byte-for-byte the prior behavior and the engine-read path is verified against the live `/ohlcv` contract.

## Constraints & quality bar (non-negotiable)
- Prefer the simplest correct design; the flag must make this a low-risk, reversible switch.
- Strict typing, async correctness, comprehensive error handling + structured logging, input validation, no secret leakage, no tvkit cookie introduced into
csm-set for the engine path.
- Backward compatible by default; zero behavior change when the flag is unset.
- Surface assumptions explicitly in the plan; if the engine read-API contract differs from what you expected, stop and document it rather than guessing.
- Always `uv run` (never bare `python`/`pip`); use Docker service names inside containers, host ports only for local dev.
```

> **Decisions deviating from the prompt's examples (resolved with the user):** the flag name
> follows the ROADMAP-pinned `CSM_OHLCV_SOURCE = parquet | db` (not the prompt's
> `CSM_USE_MARKETDATA_ENGINE` / `CSM_MARKETDATA_SOURCE` examples); git stops at local
> commits (no push/PR this run); the bundled index/sectors fix is deferred.

---

## Objective, scope, non-goals

**Objective.** Let csm-set's owner-side daily refresh read OHLCV from the Market Data Engine
read API when `CSM_OHLCV_SOURCE='db'`, returning the **identical** internal DataFrame shape
so no downstream code changes, with the legacy tvkit path as the unchanged default.

**In scope.**
- A new async httpx read client for the engine (`/ohlcv`, `/ohlcv/adjusted`).
- The `CSM_OHLCV_SOURCE` flag + a factory that routes `daily_refresh` to the chosen loader.
- A new engine-backed loader matching `OHLCVLoader`'s `fetch` / `fetch_batch` surface.
- Tests (client, loader, factory, routing) + docs + `.env.example`.

**Non-goals (Phase 3).**
- The 2026-05-29 index/sectors universe fix (deferred follow-up).
- Demoting/materialising the local Parquet as a DB-derived backtest cache beyond the read
  path (Phase 5 cutover concern; the Parquet write on the `db` path is unchanged — the
  engine bars are still persisted to the local store exactly as tvkit bars were).
- Cold-path auto-fetch, scheduler, or any engine-side change (engine is done in Phase 2).
- Pointing the `/universe` endpoint into csm-set's universe builder (read client covers
  `/ohlcv` only; universe stays local this phase).
- Dividend-adjustment math *parity* validation vs tvkit (Phase 5 diff-test; flag-off default
  makes it zero-risk now).

---

## Phase 3 acceptance criteria (verbatim from the umbrella ROADMAP)

> ### Phase 3 — `strategies/csm-set` — read from the store behind a flag 🧠
> **Sub-repo:** `strategies/csm-set` (own PR).
> - Add `CSM_OHLCV_SOURCE = parquet | db` (default `parquet`); `db` reads the Market
>   Data read-model / snapshot instead of local tvkit fetch.
> - Demote local Parquet to a **derived backtest cache** (materialised from the DB);
>   stop the per-strategy tvkit fetch in `daily_refresh` when source=db.
> - Also fixes the live-test gap found 2026-05-29: include `SET:SET` index + sectors so
>   `residual_momentum`/composite compute every session (see csm-set
>   `events/2026-05-29-rebalance-model-deviation.md`).
> - **Success:** csm-set runs identically on `db` source; public-data-boundary tests
>   still pass; no behaviour change vs Parquet for the same dates.

**Coverage of these criteria by this phase:**

| Criterion | This phase |
|---|---|
| Add `CSM_OHLCV_SOURCE = parquet \| db` (default `parquet`); `db` reads the engine | ✅ Implemented |
| Stop the per-strategy tvkit fetch in `daily_refresh` when `source=db` | ✅ The `db` loader never touches tvkit; the cookie is not read on this path |
| Local Parquet as derived cache | ◑ Partial — engine bars persist to the local store via the unchanged write path; full "DB-canonical, Parquet-derived" cutover is Phase 5 |
| 2026-05-29 index/sectors fix | ⏭ **Deferred** to a tracked follow-up (per user) |
| Success: runs identically on `db`; boundary tests pass; no behaviour change | ✅ Verified (default path untouched; boundary tests green; shape-identical frames) |

---

## Verified read-API contract

Confirmed from `src/quant_marketdata_engine/api/routes.py`, `api/schemas.py`, and
`tests/test_api_routes.py` (not assumed):

- `GET /ohlcv` and `GET /ohlcv/adjusted` — query params `symbol` (1–64), `timeframe`
  (`Literal["1d","1h","5m"]`), optional `start`/`end` (ISO-8601 UTC; `start<=end` else 422),
  `limit` (default 5000, 1–50000). Auth: `X-API-Key` header, enforced **only when**
  `MARKETDATA_ENGINE_API_KEY` is set server-side (else open with a warning).
- Response `OHLCVResponse`: `{symbol, timeframe, adjusted: bool, bars: [...]}`. Each
  `OHLCVBar`: `ts` (ISO-8601 UTC bar-open), `open/high/low/close/volume` as **Decimal
  strings**, `open_interest` (string|null). Bars ascending by `ts`.
- Empty result = **200 with `bars: []`** (not 404). 401 on bad/missing key when configured;
  422 on bad params.
- `/ohlcv` = raw (split-adjusted base); `/ohlcv/adjusted` = dividend/split adjust-on-read.

---

## Feature-flag design

- **Env var:** `CSM_OHLCV_SOURCE` (pydantic-settings, `CSM_` prefix), values `parquet` |
  `db`, **default `parquet`**. Validated by a `field_validator` (rejects other values).
- **Companion config:** `CSM_MARKET_DATA_ENGINE_BASE_URL` (`str | None`) and
  `CSM_MARKET_DATA_ENGINE_API_KEY` (`SecretStr | None`). A `model_validator(mode="after")`
  **requires the base URL when `ohlcv_source='db'`**, failing fast at `Settings()`.
- **Where read:** `src/csm/config/settings.py` (the single `Settings` object).
- **Routing:** a factory `build_ohlcv_loader(settings) -> OHLCVSource` in
  `src/csm/data/sources.py` returns the legacy `OHLCVLoader` for `parquet` and the new
  `MarketDataEngineLoader` for `db`. The only call-site change is in
  `api/scheduler/jobs.py::daily_refresh`, which now constructs the loader via the factory.
  `_fetch_batch_with_retry` is retyped against the `OHLCVSource` protocol.

When the flag is unset, `build_ohlcv_loader` returns exactly the same `OHLCVLoader(settings)`
that `daily_refresh` constructed before — **byte-for-byte prior behaviour.**

---

## Read-client design

`src/csm/adapters/market_data_engine_client.py` — `MarketDataEngineClient`, mirroring the
existing `gateway_client.py` patterns:

- One shared `httpx.AsyncClient` (base_url, configurable `timeout`, optional custom
  `transport` for tests); `__aenter__/__aexit__` lifecycle; constructor validation
  (`ValueError` on empty `base_url` / `max_attempts < 1`).
- `async get_ohlcv(symbol, timeframe, *, adjusted, limit, start=None, end=None) ->
  EngineOHLCVResponse`: routes to `/ohlcv/adjusted` when `adjusted` else `/ohlcv`; sends
  `X-API-Key` only when a key is configured; retries transient 5xx + `httpx.HTTPError`
  with bounded backoff; **4xx are terminal** (raise `MarketDataEngineError`); an
  unparseable 200 body raises `MarketDataEngineError`.
- Pydantic response models (`EngineOHLCVBar`, `EngineOHLCVResponse`) parse the wire's
  Decimal-strings into `Decimal` (monetary-at-boundary rule), `ts` into a UTC datetime.
- Structured `logger.warning(...)` on retries/transport errors; **no secrets logged**; the
  client holds **no tvkit cookie** — only the optional engine read key.

**In-cluster base URL** `http://quant-marketdata-engine:8000`; **host-local dev**
`http://localhost:8300`.

---

## Response → csm OHLCV model mapping

`src/csm/data/engine_loader.py` — `MarketDataEngineLoader` exposes the same
`fetch` / `fetch_batch` signatures as `OHLCVLoader` and returns the **identical** DataFrame:
columns `["open","high","low","close","volume"]` as **float**, `DatetimeIndex` named
`"datetime"` in **`Asia/Bangkok`**, sorted ascending; a zero-row frame with that schema on
empty. `open_interest` is dropped (equities; not in the csm internal shape, and outside the
public-data boundary's allowed set).

Explicit mappings (assumptions surfaced):

| csm input | engine | Note |
|---|---|---|
| `interval="1D"` | `timeframe="1d"` | case-folded; unsupported intervals raise `ValueError` pre-network |
| `bars` (count) | `limit` | engine caps at 50000 |
| `adjustment="dividends"` | `GET /ohlcv/adjusted` | adjust-on-read |
| `adjustment="splits"` | `GET /ohlcv` | raw = split-adjusted base |
| Decimal-string prices | `float(...)` | parsed to `Decimal` at the HTTP boundary, cast to `float` to match the existing internal contract |
| `ts` (UTC) | `tz_convert("Asia/Bangkok")` | bar-open time |

`fetch_batch` bounds concurrency with `settings.tvkit_concurrency` and **omits** per-symbol
failures (logged warning) — same semantics as `OHLCVLoader.fetch_batch`. Public-mode raises
`DataAccessError`, identical to the tvkit loader.

> **Assumption / Phase-5 risk:** the `dividends → /ohlcv/adjusted` mapping assumes the
> engine's adjust-on-read reproduces tvkit's dividend-adjusted series the strategy was
> validated on. The ROADMAP flags this as a diff-test before cutover (Phase 5). Flag-off
> default makes it zero-risk for Phase 3.

---

## File changes (csm-set repo)

| File | Action | Description |
|---|---|---|
| `src/csm/config/settings.py` | MODIFY | `ohlcv_source` + `market_data_engine_base_url` + `market_data_engine_api_key` fields; `_validate_ohlcv_source`; `_require_engine_url_for_db_source` model validator |
| `src/csm/adapters/market_data_engine_client.py` | ADD | Async httpx read client + `EngineOHLCVBar`/`EngineOHLCVResponse` + `MarketDataEngineError` |
| `src/csm/data/engine_loader.py` | ADD | `MarketDataEngineLoader` (fetch/fetch_batch → canonical DataFrame) |
| `src/csm/data/sources.py` | ADD | `OHLCVSource` protocol + `build_ohlcv_loader` factory |
| `src/csm/data/exceptions.py` | MODIFY | add `EngineReadError(DataError)` |
| `api/scheduler/jobs.py` | MODIFY | route via `build_ohlcv_loader`; retype `_fetch_batch_with_retry` to `OHLCVSource` |
| `.env.example` | MODIFY | document the three new env vars |
| `CLAUDE.md` | MODIFY | note the new flag + engine-read path |
| `tests/unit/adapters/test_market_data_engine_client.py` | ADD | client unit tests (MockTransport) |
| `tests/unit/data/test_engine_loader.py` | ADD | loader unit tests |
| `tests/unit/data/test_sources.py` | ADD | factory + flag-validator tests |
| `tests/unit/test_scheduler_jobs.py` | MODIFY | retarget patches `OHLCVLoader` → `build_ohlcv_loader` |

`scripts/fetch_history.py` is intentionally **left tvkit-only** — it is the explicit
owner/backfill tool, decommissioned in Phase 5.

---

## Test plan & coverage

- **Client** (`test_market_data_engine_client.py`, MockTransport): happy path + Decimal
  parsing, raw vs adjusted endpoint selection, `start`/`end` ISO params, API-key header
  present/absent, empty `bars:[]`, 401 + 422 terminal (no retry), 5xx retry-then-success,
  5xx exhaustion, transport-error retry, unparseable body. (adapters/ is in the ≥90% gate.)
- **Loader** (`test_engine_loader.py`): `_resolve` interval/adjustment mapping + errors;
  `_response_to_frame` shape/dtype/tz/order + empty; `fetch` public-mode guard, canonical
  frame, adjusted routing, missing-URL `EngineReadError`; `fetch_batch` all-success,
  per-symbol-failure omission, public-mode guard.
- **Factory** (`test_sources.py`): default + explicit `parquet` → `OHLCVLoader`; `db` →
  `MarketDataEngineLoader`; invalid source rejected; `db` without URL rejected.
- **Routing** (`test_scheduler_jobs.py`): existing daily-refresh tests now patch the factory
  seam, proving `daily_refresh` routes through `build_ohlcv_loader`.
- **Boundary**: `tests/integration/test_public_data_boundary_*` unchanged and green (no raw
  OHLCV leaks).

**Coverage gate:** `--cov-fail-under=90` over `src/csm/adapters` + `api` (pyproject). The new
adapter client is in scope and thoroughly covered.

---

## Backward-compat, migration, security, performance, rollback

- **Backward compatibility:** default `parquet` returns the exact prior `OHLCVLoader`; the
  change is purely additive. Zero behaviour change when the flag is unset.
- **Migration impact:** none for consumers when the flag is off. Turning it on requires only
  the engine URL (+ optional key) in csm-set's `.env`.
- **Security:** the `db` path introduces **no tvkit cookie** into csm-set — the engine is the
  sole cookie owner. The engine read key is a `SecretStr`, never logged/committed. Inputs are
  validated (flag enum, required URL, interval/adjustment) and fail fast.
- **Performance:** engine reads are Redis/DB-backed (hot/warm) and avoid the tvkit WebSocket
  burst + rate-limit exposure; `fetch_batch` keeps the same bounded concurrency. One symbol
  per request (no batch endpoint on the engine), deduped/cached engine-side.
- **Rollback:** flip `CSM_OHLCV_SOURCE` back to `parquet` (or unset). No data migration; the
  local Parquet store remains the durable artifact.

---

## Success criteria

- [x] `CSM_OHLCV_SOURCE=parquet|db` (default `parquet`); `db` reads the engine, never tvkit.
- [x] Flag-off path is byte-for-byte the prior `daily_refresh` behaviour.
- [x] Engine-read DataFrame is shape/dtype/index-identical to the tvkit loader's output.
- [x] New client/loader/factory unit tests green; scheduler routing tests retargeted & green.
- [x] Public-data-boundary tests still pass.
- [x] ruff + ruff format clean on all new/changed files; mypy-strict clean on new modules.
- [ ] (Phase 5) dividend-adjustment parity diff-test vs tvkit.

---

## Completion notes

_To be filled on completion._

- Branches: csm-set `feat/phase3-read-from-marketdata-engine` (off `live-test`); this repo
  `docs/phase3-csm-set-read-plan`; umbrella `docs/phase3-csm-set-read`.
- Pre-existing `live-test` gate state (unrelated to this change): repo-wide `ruff check .`
  and `ruff format --check .` report failures in `scripts/build_rationale_notebook.py` and
  `src/csm/adapters/hooks.py`, and `mypy` reports a missing `yaml` stub in
  `src/csm/live/portfolio.py`. All new/modified files for this phase are clean.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.8)
**Status:** In progress
