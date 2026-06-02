# Operations — Configuration

All runtime config is read from the environment (or a gitignored `.env` for local dev) via
`pydantic-settings`. Engine knobs use the `MARKETDATA_ENGINE_` prefix; the **unprefixed**
`TVKIT_AUTH_TOKEN` is the shared cookie this service alone owns. Source:
`src/quant_marketdata_engine/config/settings.py`.

## Engine settings (`MARKETDATA_ENGINE_*`)

| Env var | Default | Allowed / type | Effect |
|---------|---------|----------------|--------|
| `MARKETDATA_ENGINE_PUBLIC_MODE` | `true` | bool | `true` = read-only (ingest → `403`); `false` = owner mode (ingest enabled) |
| `MARKETDATA_ENGINE_HOST_PORT` | `8300` | int | host port mapping (container always listens on `:8000`) |
| `MARKETDATA_ENGINE_PG_DSN` | `postgresql://quant:quant@quant-postgres:5432/db_market_data` | DSN | asyncpg DSN for the canonical store |
| `MARKETDATA_ENGINE_REDIS_URL` | `redis://localhost:6379/0` | URL | own Redis sidecar (in compose: `redis://marketdata-redis:6379/0`) |
| `MARKETDATA_ENGINE_API_KEY` | `null` | string | `X-API-Key` for the read API; when **unset** the read API is open + logs a warning |
| `MARKETDATA_ENGINE_PG_POOL_MIN_SIZE` | `1` | int ≥ 0 | asyncpg pool min |
| `MARKETDATA_ENGINE_PG_POOL_MAX_SIZE` | `10` | int ≥ 1 | asyncpg pool max |
| `MARKETDATA_ENGINE_CACHE_TTL_SECONDS` | `300` | int ≥ 0 | hot-window cache TTL |
| `MARKETDATA_ENGINE_TVKIT_TIMEOUT_SECONDS` | `30.0` | float > 0 | upper bound on a single tvkit fetch |
| `MARKETDATA_ENGINE_APP_ENV` | `development` | string | environment label |
| `MARKETDATA_ENGINE_LOG_LEVEL` | `INFO` | string | root log level |

## The tvkit credential (`TVKIT_AUTH_TOKEN`)

| Env var | Default | Type | Effect |
|---------|---------|------|--------|
| `TVKIT_AUTH_TOKEN` | `null` | JSON cookie string | required for ingest; **this service is the sole owner** |

- It is a **JSON cookie string, NOT a JWT**. Required key `sessionid`; optional
  `sessionid_sign`, `device_t`, `tv_ecuid`:
  ```
  {"device_t":"<...>","tv_ecuid":"<...>","sessionid":"<...>","sessionid_sign":"<...>"}
  ```
- Source it from a logged-in tradingview.com browser session. **Never commit it; never log
  it.** Keep it in a gitignored `.env` or a gitignored `.tmp/` file.
- **Safe injection — use command substitution, never `set -a`:**
  ```bash
  # GOOD: the JSON (which contains spaces) is passed as one value
  TVKIT_AUTH_TOKEN="$(cat .tmp/tvkit_cookie.json)" \
    uv run python -m src.quant_marketdata_engine.ingest fetch --symbol SET:PTT --timeframe 1d --bars 5000
  ```
  Do **not** `set -a; . file` — the spaces word-split and the fetch silently falls back to the
  anonymous 5,000-bar cap. The engine validates the JSON only when ingest runs
  (`Settings.tvkit_cookies()`); a missing `sessionid` raises `CookieConfigError`.

## Strategy reader flags (consumer side — not this repo)

Strategies select the engine vs their legacy path with their own env var. Documented here so
operators see the full cutover picture; the flag lives in each strategy repo.

| Strategy | Env var | Values | Default | Notes |
|----------|---------|--------|---------|-------|
| `csm-set` | `CSM_OHLCV_SOURCE` | `db` \| `parquet` | **`db`** | `db` = read engine (no cookie); `parquet` = legacy tvkit (deprecated). **Cut over** (Phase 5). |
| `tfex-s50-multi-tf-swing` | `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE` | `engine` \| `mirror` | **`mirror`** | `engine` = read engine; `mirror` = legacy tvkit + schema-09. **Cutover pending Phase 5.x.** |

Each strategy also needs `..._MARKET_DATA_ENGINE_BASE_URL` (and optional
`..._MARKET_DATA_ENGINE_API_KEY`) on the engine path. csm-set targets the engine read API
directly; tfex targets the **gateway proxy** prefix (`/api/v2/engines/market-data`). See the
[cutover runbook](../../../.claude/playbooks/marketdata-engine-cutover.md).

## Reference

A copyable template lives at `.env.example` in the repo root. The full machine-readable
settings list is in `src/quant_marketdata_engine/config/settings.py`.
