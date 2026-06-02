# Knowledge — Data Flow

> Executive summary: the engine has an **ingest side** (sole tvkit-cookie owner, writes raw
> bars) and a **read side** (hot/warm resolution: Redis → TimescaleDB → write-through). The
> cold path (auto-fetch-on-miss) is deferred; the single-flight lock primitive is built.
> Authoritative detail: [`../../docs/architecture/overview.md`](../../docs/architecture/overview.md).
> `last_verified: 2026-06-02`

## Write path (ingest, owner mode)

```
tvkit (cookie)  → ingest/tvkit_client.py
                → ingest/service.py     (idempotent upsert)
                → db/repositories.py     ON CONFLICT (symbol,timeframe,ts) DO UPDATE
                → market_data.ohlcv + market_data.corporate_actions
```

Entry: CLI (`python -m src.quant_marketdata_engine.ingest fetch|backfill`) or
`POST /admin/ingest`. Refused in public mode (`require_owner_mode` → `403`).

## Read path (hot / warm)

```
GET /ohlcv[/adjusted]  → api/routes.py::_read
   1. ohlcv_cache.get_cached_bars(redis, key)   ── HIT ─▶ return
   2. fetch_ohlcv[/adjusted](pool, ...)         ── DB  ─▶ write-through Redis ▶ return
```

- Cache key: `ohlcv_cache.make_key(symbol, timeframe, adjusted, start, end, limit)`; TTL
  `MARKETDATA_ENGINE_CACHE_TTL_SECONDS` (default 300s).
- Redis unavailable → reads fall through to the DB (cache optional).
- **Cold path deferred:** no auto-fetch on miss; an absent series returns empty `bars`.

## Single-flight lock (`cache/single_flight.py`)

Dedupes concurrent identical work on `(symbol, timeframe, range)` via Redis
`SET key val NX EX ttl` + compare-and-delete release (Lua). When Redis is `None` it is a no-op
yielding `True` — correctness holds because the upsert is idempotent; the lock is an efficiency
guard. Wired into ingest dedupe; the deferred cold path will consume the same primitive.

## Cache hierarchy

| Tier | Where | TTL / lifetime |
|------|-------|----------------|
| Hot | own Redis sidecar (`marketdata-redis`) | `CACHE_TTL_SECONDS` |
| Warm | TimescaleDB `market_data.*` | durable (compression after 7d; 1d kept forever) |
| Derived | Parquet snapshot (DB→columnar) | regenerated on demand for offline backtests |

See also [`api-contract.md`](api-contract.md), [`deployment.md`](deployment.md),
[`../../docs/data/parquet-snapshot.md`](../../docs/data/parquet-snapshot.md).
