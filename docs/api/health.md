# API — `GET /health`

Liveness/readiness probe. Reports dependency reachability and tvkit-cookie **presence**
(never the value). **Not auth-gated.**

| | |
|---|---|
| Method / path | `GET /health` |
| Gateway-proxied | `GET /api/v2/engines/market-data/health` |
| Auth | none |
| Source | `src/quant_marketdata_engine/api/routes.py::health` |

## Request

```bash
# Engine-direct (host)
curl http://localhost:8300/health

# Via the gateway proxy (in-cluster service name; host port is configurable)
curl http://quant-api-gateway:8000/api/v2/engines/market-data/health
```

## Response `200 OK`

```json
{
  "status": "ok",
  "db": true,
  "redis": true,
  "cookie_present": false
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `status` | string | `"ok"` when the DB is reachable, else `"degraded"` |
| `db` | bool | TimescaleDB (`db_market_data`) pool reachable |
| `redis` | bool | own Redis sidecar reachable (cache is optional — `false` is non-fatal) |
| `cookie_present` | bool | whether `TVKIT_AUTH_TOKEN` is configured — **presence only**, never the value |

## Notes

- `status` is `"degraded"` (not an error code) when the DB is unreachable — the endpoint
  still returns `200` so the probe can distinguish "process up, dependency down" from "process
  down". See [`../operations/troubleshooting.md`](../operations/troubleshooting.md).
- 🔴 **A probe must therefore read the BODY, not the status code.** The container healthcheck
  asserted only `status == 200` until 2026-09-11, and consequently reported `healthy` for 33 h
  while every `/ohlcv` request returned `503`. It now requires `db == true`. Any external
  monitor of this endpoint must do the same, or it is grading liveness, not readiness.
- `db` reflects the **serving** pool — the same pool the read routes use — and probing it also
  re-opens a pool that a failed startup left closed.
- In public mode `cookie_present` is normally `false` (no cookie is mounted); in owner mode it
  is `true`.
