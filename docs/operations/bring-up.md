# Operations — Bring-up

How to start the engine locally and in `quant-network`, in public (read-only) or owner
(ingest) mode. Env vars are detailed in [`configuration.md`](configuration.md).

## Prerequisite: the network and DB

`quant-infra-db` creates the external `quant-network` and the `db_market_data` database. It
**must be up first** — every other compose file references the network as `external: true`.

```bash
cd quant-infra-db && docker compose up -d   # creates quant-network + db_market_data
```

## Bring-up order

```bash
cd quant-infra-db            && docker compose up -d   # network + TimescaleDB (first)
cd ../quant-marketdata-engine && docker compose up -d   # this service + own Redis (host :8300)
cd ../quant-api-gateway      && docker compose up -d   # proxies /api/v2/engines/market-data/*
cd ../strategies/csm-set     && docker compose up -d   # read-only consumer
cd ../strategies/tfex-s50-multi-tf-swing && docker compose up -d
cd ../quant-openbb           && docker compose up -d
```

Tear down in reverse; only `quant-infra-db` down removes `quant-network`.

## Public mode (default — read-only, no cookie)

```bash
cd quant-marketdata-engine
docker compose up -d
```

The base `docker-compose.yml` runs `MARKETDATA_ENGINE_PUBLIC_MODE=true` with **no tvkit
cookie**, the asyncpg DSN to `quant-postgres:5432/db_market_data`, and its **own Redis
sidecar** (`marketdata-redis`, internal-only — no host port, to avoid clashing with `:6379`).
Ingest endpoints return `403` in this mode.

## Owner mode (ingest — needs the cookie)

Layer the private overlay, which flips `PUBLIC_MODE=false` and supplies a gitignored `.env`
(holding `TVKIT_AUTH_TOKEN` + `MARKETDATA_ENGINE_API_KEY`):

```bash
docker compose -f docker-compose.yml -f docker-compose.private.yml up -d
```

One-off ingest run without keeping the service up:

```bash
docker compose -f docker-compose.yml -f docker-compose.private.yml run --rm \
  marketdata-engine python -m src.quant_marketdata_engine.ingest fetch \
  --symbol SET:PTT --timeframe 1d --bars 5000
```

> Never commit `.env`. See [`configuration.md`](configuration.md) for safe cookie injection.

## Health checks

```bash
curl http://localhost:8300/health                                   # engine-direct
curl http://localhost:8000/health                                   # gateway (host port configurable)
curl http://localhost:8000/api/v2/engines/market-data/health        # gateway → engine (proxied)
```

A healthy engine returns `{"status":"ok","db":true,"redis":true,"cookie_present":<bool>}`.
`status:"degraded"` means the process is up but the DB is unreachable — see
[`troubleshooting.md`](troubleshooting.md).

## Local (non-Docker) run

```bash
uv sync --all-groups
uv run uvicorn src.quant_marketdata_engine.api.main:app --port 8000
```

Point `MARKETDATA_ENGINE_PG_DSN` / `MARKETDATA_ENGINE_REDIS_URL` at reachable hosts (e.g.
`localhost` ports) for host-local dev.
