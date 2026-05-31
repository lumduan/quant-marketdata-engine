# Playbook — development workflow (quant-marketdata-engine)

Service-specific workflow. For the generic 8-step feature loop see
[`feature-development.md`](feature-development.md); for what the service *is* and *why*,
read [`../knowledge/market-data-engine.md`](../knowledge/market-data-engine.md) and
[`../../docs/plans/ROADMAP.md`](../../docs/plans/ROADMAP.md) first.

> **Current state:** scaffold only. The fetch / storage / read-API / Redis modules below
> are the Phase 2 build target and do not exist yet. The local-dev and quality-gate steps
> apply now; the bring-up and tvkit steps apply once Phase 2 lands.

---

## 1. Local setup & quality gates

```bash
uv sync --all-groups
uv run pre-commit install

# Combined gate — must pass before every push (matches CI):
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

- **Always `uv run`** — never bare `python` / `pip`.
- Coverage gate is **≥90%** on core modules (enforced in `pyproject.toml` + CI).
- Any post-format edit (`sed`, manual tweak) invalidates the format check — re-run
  `uv run ruff format --check .` before pushing.

Run the scaffold entrypoint:

```bash
uv run python -m src.quant_marketdata_engine.main
```

---

## 2. Local bring-up order (with infra-db + gateway)

This service depends on `quant-infra-db` (TimescaleDB + the `quant-network`) and is fronted
by `quant-api-gateway`. Bring infra-db up **first**:

```bash
cd ../quant-infra-db          && docker compose up -d   # creates quant-network + DBs
cd ../quant-marketdata-engine && docker compose up -d   # this service + own Redis (host :8300)
cd ../quant-api-gateway       && docker compose up -d   # proxies /api/v2/engines/market-data/*
# strategies (read-only consumers) + quant-openbb after that
```

Health (once the FastAPI app lands in Phase 2):

```bash
curl http://localhost:8300/health
```

Tear down in reverse; only `quant-infra-db` down removes `quant-network`.

> **Public vs owner mode.** `docker compose up` runs **public** mode (read-only, refuses to
> fetch tvkit). Ingest needs **owner** mode with the cookie:
> `docker compose -f docker-compose.yml -f docker-compose.private.yml up`.

---

## 3. Testing tvkit fetches WITHOUT committing the cookie

The cookie is a live session secret and **must never be committed or logged**.

1. **Store it gitignored.** Put the JSON cookie string in `.tmp/tvkit_token.json` (the
   `.tmp/` dir is gitignored) or in `.env` (also gitignored). Shape — `sessionid`
   required, the rest optional:
   ```json
   {"device_t":"…","tv_ecuid":"…","sessionid":"…","sessionid_sign":"…"}
   ```
2. **Inject with command substitution** (preserves the spaces in the JSON):
   ```bash
   env MARKETDATA_ENGINE_PUBLIC_MODE=false \
       TVKIT_AUTH_TOKEN="$(cat .tmp/tvkit_token.json)" \
       uv run python -m src.quant_marketdata_engine.ingest   # (Phase 2 entrypoint)
   ```
   ⚠️ **Do NOT** `set -a; . .tmp/tvkit_token.json` — the JSON has spaces, so dotting
   word-splits it and the cookie parses as `None`, silently falling back to the anonymous
   **5,000-bar cap**. Always use `"$(cat file)"`.
3. **Verify auth actually unlocked depth:** request >5,000 bars and confirm you get >5,000
   back, plus a log line like `authenticated as TradingViewAccount(... tier='premium' ...)`.
   If you're capped at exactly 5,000, the cookie didn't load.
4. **Before any commit:** `git status` + `git diff --cached` to confirm no cookie / `.env`
   / `.tmp/` file is staged. `data/` is gitignored too (DB is the source of truth).
5. Sessions expire (`ProfileFetchError`) → re-login to tradingview.com, re-extract the
   cookie, refresh `.tmp/tvkit_token.json`.

Full reference: umbrella agent memory `reference-tvkit-tradingview-auth`.

---

## 4. PR sequence

This service is one repo in a cross-cutting feature. Coordinate, but each repo ships its
own PR (never reach across repo boundaries):

1. **Phase 0** — this repo's bootstrap PR (scaffold + ROADMAP + CLAUDE.md + `.claude/` +
   README) **and** the umbrella ADR PR (`.claude/knowledge/feature-market-data-engine.md` +,
   once merged, the umbrella registration tables). The ADR gates everything below.
2. **Phase 1** — `quant-infra-db` PR: `10_schema_market_data.sql` +
   `11_market_data_caggs.sql` + `src/db` models/repos.
3. **Phase 2** — **this repo** PR: ingest + read API + own Redis + snapshot exporter +
   compose; **and** a `quant-api-gateway` PR adding the proxy route + flipping the catalog
   `EXTERNAL stub → active`.
4. **Phase 3** — `strategies/csm-set` PR: `CSM_OHLCV_SOURCE = parquet|db`.
5. **Phase 4** — `strategies/tfex-s50-multi-tf-swing` PR: consume the shared store; retire
   the `09` mirror.
6. **Phase 5** — umbrella verification + cutover runbook in `.claude/playbooks/`.

Use Conventional Commits. End AI-authored commits with the
`Co-Authored-By: Claude` trailer. Never commit secrets; keep monetary values `Decimal`;
store UTC, display Asia/Bangkok.

---

## 5. Checklist before pushing

- [ ] `uv run ruff check .` clean
- [ ] `uv run ruff format --check .` clean (re-run after any late edit)
- [ ] `uv run mypy src tests` clean (strict)
- [ ] `uv run pytest` green, coverage ≥90% on core modules
- [ ] No cookie / `.env` / `.tmp/` / `data/` staged (`git diff --cached`)
- [ ] New behaviour has tests; idempotent upserts proven; UTC + `Decimal` honoured
