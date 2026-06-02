# Knowledge — API Contract

> Executive summary: a uniform read contract (`/health`, `/ohlcv`, `/ohlcv/adjusted`,
> `/universe`) + owner-mode `/admin/ingest`; money is `Decimal`-as-string, `ts` is UTC
> bar-open. Read endpoints are gateway-proxied under `/api/v2/engines/market-data/*`;
> `/admin/ingest` is engine-direct. Per-endpoint detail with curl examples lives in
> [`../../docs/api/`](../../docs/api/). `last_verified: 2026-06-02`

## Endpoints

| Endpoint | Auth | Proxied | Doc |
|----------|------|---------|-----|
| `GET /health` | none | yes | [`../../docs/api/health.md`](../../docs/api/health.md) |
| `GET /ohlcv` | `X-API-Key` | yes | [`../../docs/api/ohlcv.md`](../../docs/api/ohlcv.md) |
| `GET /ohlcv/adjusted` | `X-API-Key` | yes | [`../../docs/api/ohlcv-adjusted.md`](../../docs/api/ohlcv-adjusted.md) |
| `GET /universe` | `X-API-Key` | yes | [`../../docs/api/universe.md`](../../docs/api/universe.md) |
| `POST /admin/ingest` | `X-API-Key` + owner mode | **no** | [`../../docs/api/admin-ingest.md`](../../docs/api/admin-ingest.md) |

## Response models (`api/schemas.py`)

- `OHLCVResponse`: `symbol`, `timeframe` (`1d`\|`1h`\|`5m`), `adjusted` (bool), `bars[]`.
- `OHLCVBar`: `ts` (UTC), `open/high/low/close` (decimal string), `volume` (decimal string),
  `open_interest` (decimal string | null).
- `UniverseResponse`: `as_of` (resolved date | null), `index_name`, `symbols[]`.
- `HealthResponse`: `status`, `db`, `redis`, `cookie_present`.
- `IngestResponse`: `symbol`, `timeframe`, `rows_written`.

## Status codes

| Code | Source | Meaning |
|------|--------|---------|
| `200` | route | success |
| `401` | `require_api_key` | API key set + `X-API-Key` missing/wrong (constant-time compare) |
| `403` | `require_owner_mode` | ingest attempted in public mode |
| `400` | `admin_ingest` | `IngestError` (validation) |
| `422` | route | invalid `timeframe`/`limit`, or `start > end` |
| `502` | `admin_ingest` / gateway | `TvkitFetchError`; or gateway sees upstream `5xx`/invalid body |
| `503` | `get_pool_dep` / gateway | DB pool unavailable; or gateway sees engine unreachable |
| `504` | gateway | engine timed out |

## Invariants

- **Decimal-as-string** on the wire (never float); prices `numeric(18,6)`, volume/OI
  `numeric(20,4)`.
- **`ts` = bar-open, UTC**; display Asia/Bangkok at the edge.
- The gateway forwards `X-API-Key` verbatim and forwards upstream `4xx` bodies unchanged.
- **`4h` is not served** (cagg exists, route deferred); cold-path auto-fetch is deferred.
