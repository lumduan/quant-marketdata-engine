# quant-marketdata-engine

> The platform's **Market Data Engine** — the single canonical producer of OHLCV and the
> **sole owner of the TradingView (tvkit) auth cookie**. Gateway-proxied; strategies read,
> they never fetch.

[![CI](https://github.com/lumduan/quant-marketdata-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/lumduan/quant-marketdata-engine/actions/workflows/ci.yml)
[![Docker Publish](https://github.com/lumduan/quant-marketdata-engine/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/lumduan/quant-marketdata-engine/actions/workflows/docker-publish.yml)
[![Security Scan](https://github.com/lumduan/quant-marketdata-engine/actions/workflows/security.yml/badge.svg)](https://github.com/lumduan/quant-marketdata-engine/actions/workflows/security.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A FastAPI service (Python 3.11, `uv`-managed) that fetches market data **once**,
idempotently upserts canonical OHLCV into `quant-infra-db` (TimescaleDB), and serves it
back through `quant-api-gateway`. It is the only component that holds the tvkit cookie, so
every strategy reads pre-fetched data from one shared store instead of re-pulling it.

> ⚠️ **Scaffold only.** This repo currently contains the bootstrap (tooling + planning +
> agent context). There is **no** fetch / storage / read-API / Redis logic yet — that
> build-out is sequenced in [`docs/plans/ROADMAP.md`](docs/plans/ROADMAP.md) (Phase 2+) and
> is gated on the Phase 0 ADR.

## Why this exists

- **One credential owner** — only this service holds `TVKIT_AUTH_TOKEN`; no strategy, no
  gateway, no host needs it.
- **Fetch once, read everywhere** — `csm-set` and `tfex` overlap heavily on SET symbols;
  one ingest serves both, halving premium-account / rate-limit load.
- **Single source of truth** — one canonical store instead of N per-strategy Parquet
  copies; no more stale / mixed-date data from skip-existing fetch scripts.

## Architecture position

Part of the **quant-trading-system** umbrella (see [`../CLAUDE.md`](../CLAUDE.md)). It is the
`Market Data` **EXTERNAL** engine in the gateway's engine catalog — the same pattern as
`csm-set` behind the Backtest engine.

```
tvkit (premium cookie) + settfex      ← owned ONLY by this service
            │
            ▼
   quant-marketdata-engine (host :8300 / container :8000)  ── writes ──▶ quant-infra-db
     fetch + idempotent upsert                                          (TimescaleDB
     own Redis sidecar (hot window + single-flight lock)                 market_data.*)
            ▲
            │  GET /api/v2/engines/market-data/*   (PROXY, no cookie)
   quant-api-gateway
            │
            ▼
   strategies (csm-set, tfex…) + quant-openbb   ── read, never fetch tvkit
```

## Ports & `quant-network`

| Item | Value |
|---|---|
| Service hostname (in-container) | `quant-marketdata-engine` |
| Container port | `:8000` |
| Host port | `:8300` |
| Health check | `curl http://localhost:8300/health` *(Phase 2)* |
| Canonical DB | `quant-postgres:5432` (TimescaleDB, `market_data.*`) |
| Own Redis sidecar | distinct from the gateway's Redis |

All services join the external **`quant-network`** created by `quant-infra-db`. Use service
hostnames inside containers; host ports are for developer access only.

## Prerequisites

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

## Local setup

```bash
git clone https://github.com/lumduan/quant-marketdata-engine.git
cd quant-marketdata-engine

uv sync --all-groups        # install deps (dev group included)
uv run pre-commit install   # ruff-check / ruff-format / mypy on commit

# Run the scaffold entrypoint
uv run python -m src.quant_marketdata_engine.main
```

## Quality gates

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

`ruff` (E, F, I, UP, B, SIM) · `mypy --strict` · `pytest` with **≥90% coverage on core
modules** (`--cov-fail-under=90`), enforced in CI. Weekly `bandit` + `pip-audit` security
scans.

## Environment variables

Copy [`.env.example`](.env.example) to `.env` (gitignored) and fill in real values.

| Variable | Purpose |
|---|---|
| `TVKIT_AUTH_TOKEN` | **Sole tvkit credential.** JSON cookie string (NOT a JWT), required key `sessionid`. **Never committed; never logged.** |
| `MARKETDATA_ENGINE_PUBLIC_MODE` | `true` (default) = read-only, refuses to fetch tvkit; `false` = owner/ingest mode |
| `MARKETDATA_ENGINE_HOST_PORT` | host port mapping (default `8300`; container is always `:8000`) |
| `MARKETDATA_ENGINE_PG_DSN` | TimescaleDB DSN (`quant-postgres:5432`, `db_market_data`) |
| `MARKETDATA_ENGINE_REDIS_URL` | own Redis sidecar (hot-window cache + single-flight lock) |
| `MARKETDATA_ENGINE_API_KEY` | read-API auth (raw OHLCV is private-side only) |

> **Never commit the cookie.** Keep it in the gitignored `.env` / `.tmp/`; inject with
> `"$(cat file)"`, never `set -a`. See
> [`.claude/playbooks/development-workflow.md`](.claude/playbooks/development-workflow.md).

## Documentation

- **Roadmap (what to build, phase by phase):** [`docs/plans/ROADMAP.md`](docs/plans/ROADMAP.md)
- **Agent guide / conventions:** [`CLAUDE.md`](CLAUDE.md)
- **Domain knowledge:** [`.claude/knowledge/market-data-engine.md`](.claude/knowledge/market-data-engine.md)
- **Dev playbook:** [`.claude/playbooks/development-workflow.md`](.claude/playbooks/development-workflow.md)
- **Umbrella feature design:** [`../plans/feature-market-data-engine/`](../plans/feature-market-data-engine/)
- **Umbrella system map:** [`../CLAUDE.md`](../CLAUDE.md)

## Contributing & security

See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow and quality-gate expectations. Report
vulnerabilities privately to **bad.sonsuk@gmail.com** — see [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
