# Scheduled ingest

How the canonical OHLCV store stays current: the **`daily` bulk refresh**, how it is
scheduled, what it guarantees, and how to tell when it has stopped.

## Why this exists

Before 2026-07-31 the engine had **no scheduled driver at all**. The ingest machinery was
complete and working — `POST /admin/ingest`, the `fetch` CLI, idempotent upserts, the
single-flight lock — but three things combined to leave it inert:

1. The CLI could only ingest **one symbol per invocation** (`fetch --symbol …`).
2. The long-running service runs in **public mode**, so `POST /admin/ingest` returns `403`.
3. Nothing — no host cron, no systemd timer, no in-app scheduler — ever called either.

The result was a store that froze silently. The `1d` table was bulk-loaded during the Phase 5
cutover verification and its last bar was **2026-05-29** for 652 of 692 symbols, while
`/health` continued to return `{"status":"ok","db":true,"redis":true}` — the health check
reports process liveness, **not** data freshness. Two months of staleness produced no signal
anywhere. See [Monitoring freshness](#monitoring-freshness) for the query that does catch it.

## The `daily` command

```bash
docker compose -f docker-compose.yml -f docker-compose.private.yml run --rm --no-deps \
  marketdata-engine python -m src.quant_marketdata_engine.ingest daily \
  --timeframe 1d --bars 30
```

It re-fetches a recent window for **every symbol already in the store** at that timeframe
(`SELECT DISTINCT symbol FROM market_data.ohlcv WHERE timeframe = $1`). The store therefore
defines its own coverage: a symbol ingested once keeps being refreshed, with no separate
universe registration step.

| Flag | Default | Meaning |
|---|---|---|
| `--timeframe` | `1d` | `1d` / `1h` / `5m` |
| `--bars` | `30` | Recent bar depth per symbol — the refresh window |
| `--symbols` | — | Comma-separated override (`SET:PTT,SET:AOT`) |
| `--symbols-file` | — | Newline-delimited file; `#` comments and blanks ignored |
| `--concurrency` | `2` | Max simultaneous tvkit fetches |
| `--min-interval` | `1.0` | Min seconds between fetch **starts** — the upstream rate ceiling (`0` disables) |
| `--retries` | `2` | Retries per symbol after the first attempt |
| `--limit` | — | Cap the symbol count (smoke tests) |

**Owner mode is required** (`MARKETDATA_ENGINE_PUBLIC_MODE=false` + a valid
`TVKIT_AUTH_TOKEN`), which the `docker-compose.private.yml` overlay supplies. The overlay is
layered only for the one-off `run --rm` container; **the long-running service stays in public
mode**, so no ingest surface is persistently exposed.

### Why `--bars 30` and not `1`

The window is deliberately wider than the number of new bars. Re-fetching the trailing month
every night means a missed run, a late-corrected bar, or a public-holiday gap self-heals on
the next run instead of leaving a permanent hole. Upserts are
`ON CONFLICT (symbol, timeframe, ts) DO UPDATE`, so re-writing 29 unchanged bars costs a row
comparison and nothing else — `ingested_at` is DB-defaulted and does not churn.

For a larger gap, widen the window rather than inventing a backfill path:
`--bars 90` covers roughly a quarter.

### The TradingView rate ceiling — why pacing, not just concurrency

Every fetch opens a fresh tvkit client, and each client bootstraps its auth token with an
HTTP `GET https://www.tradingview.com/`. A full-universe run therefore issues one bootstrap
**per symbol**, and that is what the upstream limits.

Measured on **2026-07-31**, running all 692 symbols at `--concurrency 4` with no pacing:

| | |
|---|---|
| Fetches completed before the first block | **449** |
| Elapsed to the first block | **4 min 41 s** |
| Sustained rate | **~96 requests/min** |
| Failure mode | `GET https://www.tradingview.com/ → 403 Forbidden`, for every subsequent symbol |

Concurrency alone does not bound this: with a semaphore of N, fast responses simply let the
request rate spike. `--min-interval` bounds the **rate** directly by spacing fetch *starts*,
which is the quantity the upstream actually meters. The default (`1.0 s`, i.e. ~60 req/min)
sits comfortably under the observed ~96 req/min ceiling and puts a 692-symbol run at roughly
12 minutes.

If a run does get blocked, it fails cleanly — every remaining symbol records a per-symbol
failure, and the run exits non-zero only if *nothing* succeeded. Wait for the window to clear
(tens of minutes) rather than immediately retrying, then re-run: the upsert is idempotent, so
the symbols that already landed cost nothing the second time.

## Guarantees

- **Idempotent.** Re-running is safe and converges; there is no "already ingested" state to
  reset. A crashed run is repaired by running it again.
- **Per-symbol isolation.** An upstream tvkit failure or an upsert failure on one symbol is
  retried, recorded, and never aborts the run. Delisted or renamed tickers fail individually
  and are listed in full in the log — never truncated, because a silent cap reads as
  "everything succeeded".
- **Fail-fast on configuration.** Public mode and a missing/malformed cookie are checked
  **once** before any fetch, so a misconfigured run raises immediately instead of producing N
  identical per-symbol failures.
- **Single-flight.** The existing Redis lock still applies, so a scheduled run overlapping a
  manual one hits TradingView once per `(symbol, timeframe, range)`.
- **Cache coherent.** Each symbol's hot-window cache is invalidated after its upsert.

## Exit codes

`__main__` maps a negative return to exit `1`. The run reports **failure** when:

- **zero symbols resolved** — a misconfiguration (empty store, bad `--symbols-file`), not a
  benign no-op; or
- **every attempted symbol failed** — a systemic fault such as an expired cookie or an
  upstream outage.

A *partial* failure exits `0`. At ~692 symbols some names always fail (delisted, renamed,
suspended), and treating that as a red run would train the operator to ignore the alert.
Inspect the `daily ingest failed symbols (N): …` warning line for the list.

## Scheduling

Installed in the **`batt` user crontab** (tagged `# MD_INGEST`), run **after** the SET close
and after `csm-set`'s own 18:00 BKK refresh so the two do not contend for TradingView:

```cron
15 12 * * 1-5 cd /home/batt/docker/quant-trading-system/quant-marketdata-engine && /usr/bin/docker compose -f docker-compose.yml -f docker-compose.private.yml run --rm --no-deps marketdata-engine python -m src.quant_marketdata_engine.ingest daily --timeframe 1d --bars 30 --concurrency 2 --min-interval 1.0 >> /home/batt/.config/quant-pm/marketdata-ingest.log 2>&1 # MD_INGEST
```

The user crontab rather than `/etc/cron.d` because it needs no root, and `batt` is already in
the `docker` group. Find it with `crontab -l | grep MD_INGEST`.

**Cron runs in UTC on this host** (`Etc/UTC`) — `12:15 UTC` is `19:15 Asia/Bangkok`. Getting
this backwards is the single most common scheduling mistake in this platform.

**The `cd` is load-bearing.** Cron runs from `$HOME`, where `-f docker-compose.yml` resolves
to `/home/batt/docker-compose.yml` and fails with `no such file or directory`. Validate any
change to this line under a cron-like environment before trusting it:

```bash
cd /home/batt && env -i HOME=/home/batt PATH=/usr/bin:/bin /bin/sh -c \
  'cd /home/batt/docker/quant-trading-system/quant-marketdata-engine && \
   /usr/bin/docker compose -f docker-compose.yml -f docker-compose.private.yml config --services'
```

At ~692 symbols with the default pacing a full run takes roughly **12 minutes**.

Weekends are skipped (`1-5`); SET holidays are **not** — the engine holds no market calendar,
so a holiday run simply re-fetches unchanged bars and upserts nothing new. That is harmless
here precisely because the write is idempotent, unlike the gateway write-back paths that
fabricate carry-forward rows on closures.

## Monitoring freshness

`/health` reports process liveness, not data freshness — it returned `ok` throughout the
two-month stall. Check the data instead:

```bash
docker exec quant-postgres psql -U postgres -d db_market_data -c \
  "SELECT max(ts)::date AS last_bar, count(*) AS symbols
     FROM (SELECT symbol, max(ts) ts FROM market_data.ohlcv
            WHERE timeframe='1d' GROUP BY symbol) s
    GROUP BY 1 ORDER BY 1 DESC LIMIT 5;"
```

The top row should be the most recent trading day and should carry the large majority of
symbols. A `last_bar` more than a few sessions old means the scheduled run has stopped —
check `/home/batt/.config/quant-pm/marketdata-ingest.log` first, then the cookie.

## When it breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| Every symbol fails, exit `1` | tvkit cookie expired | Refresh `TVKIT_AUTH_TOKEN` in the gitignored `.env` — see [`configuration.md`](configuration.md) |
| Symbols succeed then all fail with `403` | Upstream rate limit tripped | Lower the rate (raise `--min-interval`); wait for the window to clear before re-running |
| `IngestDisabledError` immediately | Private overlay not layered | Include `-f docker-compose.private.yml` |
| `CookieConfigError` immediately | `.env` missing or cookie malformed | Cookie is a JSON string with a `sessionid` key, not a JWT |
| Exit `1` with `resolved 0 symbols` | Empty store or bad `--symbols-file` | Seed with `fetch`, or check the file path |
| A handful of symbols fail every run | Delisted / renamed tickers | Expected; confirm against the failed-symbol list in the log |
| Runs succeed but `last_bar` never advances | Job scheduled in the wrong timezone | Cron is UTC — see the note above |

## Related

- [`bring-up.md`](bring-up.md) — public vs owner mode, one-off ingest
- [`configuration.md`](configuration.md) — every env var, safe cookie injection
- [`troubleshooting.md`](troubleshooting.md) — cookie expiry, DB/Redis down, gateway 5xx
- [`../api/admin-ingest.md`](../api/admin-ingest.md) — the single-symbol HTTP path
