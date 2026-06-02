# Operations — Troubleshooting

Common failure modes and how to confirm/resolve them. Start every diagnosis with `/health`
(see [`../api/health.md`](../api/health.md)).

## `/health` shows `"status": "degraded"` / `db: false`

The process is up but TimescaleDB is unreachable.

- Confirm `quant-infra-db` is up and healthy (`docker compose ps` in that repo) and that
  `db_market_data` exists.
- Confirm `MARKETDATA_ENGINE_PG_DSN` points at the right host — inside `quant-network` use
  `quant-postgres:5432`, not `localhost`.
- While `db: false`, read endpoints return **`503` "database unavailable"**
  (`get_pool_dep` surfaces the uninitialized pool cleanly).

## `/health` shows `redis: false`

The own Redis sidecar is unreachable. This is **non-fatal** — the cache is optional, reads
fall through to the DB, and the single-flight lock degrades to a no-op (the upsert is
idempotent, so correctness holds). Restart `marketdata-redis`; check
`MARKETDATA_ENGINE_REDIS_URL` (`redis://marketdata-redis:6379/0` in compose).

## Read endpoints return `401`

`MARKETDATA_ENGINE_API_KEY` is set and the request `X-API-Key` is missing or wrong. Send the
matching key. Through the gateway, the header is forwarded verbatim; a `401` from upstream is
forwarded as-is. If the read API should be open (dev only), unset the key — the engine then
logs a warning that the read API is unauthenticated.

## Ingest returns `403` "endpoint disabled in public mode"

The service is in public mode. Ingest (CLI and `/admin/ingest`) requires
`MARKETDATA_ENGINE_PUBLIC_MODE=false` — use the `docker-compose.private.yml` overlay or set the
env var. See [`bring-up.md`](bring-up.md).

## Ingest returns `502` "upstream tvkit fetch failed"

A tvkit fetch failed or the TradingView session expired (`TvkitFetchError`). The cookie is
**never** included in the error.

- The most common cause is an **expired cookie** — refresh `TVKIT_AUTH_TOKEN` from a fresh
  logged-in browser session (it is a JSON cookie string, required key `sessionid`).
- If a fetch silently returns only ~5,000 bars, the cookie was likely injected with
  `set -a; . file` and word-split — re-inject with command substitution
  (`"$(cat file)"`). See [`configuration.md`](configuration.md).

## Ingest returns `400`

An ingest-side validation error (`IngestError`) — e.g. malformed params. Check the request
body against [`../api/admin-ingest.md`](../api/admin-ingest.md).

## Gateway returns `502` / `503` / `504` for `/api/v2/engines/market-data/*`

The gateway proxy classifies upstream transport failures:

| Gateway status | Meaning | Check |
|----------------|---------|-------|
| `504` | engine timed out | engine load / `MARKETDATA_ENGINE_TVKIT_TIMEOUT_SECONDS`; engine `/health` |
| `503` | engine unreachable | engine container up? on `quant-network`? `marketdata_engine_service_url` correct? |
| `502` | engine `5xx` or invalid body | engine logs; engine `/health` `db`/`redis` |

A gateway `4xx` is the engine's own `401`/`422` forwarded verbatim — fix the request, not the
proxy.

## Empty `bars` / empty `symbols`

Not an error. The `(symbol, timeframe, range)` has no rows (the engine read path is hot/warm —
it does **not** auto-fetch on miss; cold-path is deferred). Ingest the symbol first (owner
mode), then re-read. For `/universe`, an empty `symbols` (or `as_of: null`) means no snapshot
exists on or before the requested date.
