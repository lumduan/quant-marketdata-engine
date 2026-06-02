# Knowledge — Deployment

> Executive summary: a FastAPI container (`:8000`, host `:8300`) + its own Redis sidecar on
> the external `quant-network`, behind the gateway proxy. Public mode by default (read-only,
> no cookie); owner mode via the `docker-compose.private.yml` overlay. Full bring-up:
> [`../../docs/operations/bring-up.md`](../../docs/operations/bring-up.md); env reference:
> [`../../docs/operations/configuration.md`](../../docs/operations/configuration.md).
> `last_verified: 2026-06-02`

## Compose topology

| Service | Image / build | Ports | Notes |
|---------|---------------|-------|-------|
| `marketdata-engine` | `build: .` | `${MARKETDATA_ENGINE_HOST_PORT:-8300}:8000` | FastAPI app; public-safe defaults |
| `marketdata-redis` | `redis:7-alpine` | none (internal-only) | own sidecar (ADR D8), distinct from gateway Redis |

- Network: `default` → external `quant-network` (created by `quant-infra-db`).
- `marketdata-engine` `depends_on` `marketdata-redis` (healthy).
- Healthcheck: HTTP `GET /health` every 30s.
- Volume: `marketdata_redis_data`.

## Modes

| | Base (`docker-compose.yml`) | + `docker-compose.private.yml` |
|---|---|---|
| `PUBLIC_MODE` | `true` (read-only) | `false` (ingest enabled) |
| Cookie | none | `TVKIT_AUTH_TOKEN` from gitignored `.env` |
| API key | none unless set | `MARKETDATA_ENGINE_API_KEY` from `.env` |

```bash
docker compose up -d                                                   # public
docker compose -f docker-compose.yml -f docker-compose.private.yml up -d  # owner
```

## In-network hostnames

| Hostname | Port | Owner |
|----------|------|-------|
| `quant-marketdata-engine` | `8000` | this service |
| `marketdata-redis` | `6379` | this service (sidecar) |
| `quant-postgres` | `5432` | quant-infra-db (`db_market_data`) |
| `quant-api-gateway` | `8000` | gateway (proxies `/api/v2/engines/market-data/*`) |

Use service hostnames **inside** containers; host ports (`:8300`, …) are for developer access.

See [`data-flow.md`](data-flow.md), [`../../docs/operations/troubleshooting.md`](../../docs/operations/troubleshooting.md).
