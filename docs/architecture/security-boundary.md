# Architecture — Security Boundary

Three boundaries define this service's security posture: **who holds the tvkit cookie**, **who
may read raw OHLCV**, and **who may ingest**. They are enforced in
`src/quant_marketdata_engine/api/deps.py` and `config/settings.py`.

## 1. Sole tvkit-cookie owner

`TVKIT_AUTH_TOKEN` — a JSON cookie string (NOT a JWT; required key `sessionid`) — lives in
**this service only**, read from a gitignored `.env` (or a gitignored `.tmp/` file). No
strategy, no gateway, and no host holds the cookie or calls TradingView.

- It is **never logged.** `Settings` reads it but only parses/validates it when ingest runs
  (`Settings.tvkit_cookies()`); `/health` reports **presence only** (`cookie_present: true`),
  never the value.
- Safe injection uses command substitution; do **not** `set -a; . file` — the JSON has spaces
  and would word-split into the anonymous 5,000-bar cap. See
  [`../operations/configuration.md`](../operations/configuration.md).

Blast radius: a cookie compromise is limited to one service's `.env`, not every host.

## 2. Read API is private/auth-gated

Raw OHLCV is private-side data and must not cross the public-data boundary (it preserves the
strategies' `test_public_data_boundary_*` guarantees). Every read endpoint (`/ohlcv`,
`/ohlcv/adjusted`, `/universe`) and `/admin/ingest` depends on `require_api_key`:

- When `MARKETDATA_ENGINE_API_KEY` is **set**, the request `X-API-Key` header is compared
  constant-time (`hmac.compare_digest`); a missing/incorrect key → **`401`**.
- When the key is **unset**, the endpoint is open but logs a startup/per-call **warning** —
  acceptable for single-host dev, not for any shared deployment.

`/health` is **not** auth-gated (it is a liveness probe and leaks nothing sensitive).

The gateway forwards the caller's `X-API-Key` verbatim to the engine; the gateway itself
holds no engine key and no tvkit cookie.

## 3. Public vs owner mode

`MARKETDATA_ENGINE_PUBLIC_MODE` (default `true`) gates the ingest side:

| Mode | `PUBLIC_MODE` | Read API | Ingest (`/admin/ingest`, CLI) | Cookie expected |
|------|---------------|----------|-------------------------------|-----------------|
| **Public** (default) | `true` | available (auth-gated) | **refused** → `403` (`require_owner_mode`) | no |
| **Owner** | `false` | available (auth-gated) | enabled | yes (`TVKIT_AUTH_TOKEN`) |

The base `docker-compose.yml` runs public mode with no cookie; the
`docker-compose.private.yml` overlay flips `PUBLIC_MODE=false` and supplies `.env`. See
[`../operations/bring-up.md`](../operations/bring-up.md).

## Summary table

| Asset | Who can access | Mechanism |
|-------|----------------|-----------|
| tvkit cookie | this service only | gitignored `.env`; never logged; presence-only in `/health` |
| raw OHLCV reads | callers with `X-API-Key` (when set) | `require_api_key`, constant-time compare |
| ingest / writes | owner mode + `X-API-Key` | `require_owner_mode` + `require_api_key` |
| liveness | anyone | `/health` (no secrets) |
