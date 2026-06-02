# Data — Universe Membership

`market_data.universe_membership` records **as-of dated** index constituents so backtests get
point-in-time membership and avoid survivorship / look-ahead bias. SQL:
`quant-infra-db/init-scripts/10_schema_market_data.sql`. Exposed via
[`../api/universe.md`](../api/universe.md).

## Schema

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `as_of` | `date` | PK | snapshot date |
| `symbol` | `text` | PK | constituent |
| `index_name` | `text` | PK, default `SET` | which index |
| `ingested_at` | `timestamptz` | default `now()` | |

PK `(as_of, symbol, index_name)`; index `idx_universe_membership_asof` on
`(index_name, as_of DESC)`.

## Point-in-time semantics

A read for `as_of = D` resolves to the **latest snapshot on or before `D`** — not an exact
match. The API returns the resolved date in the response, which may be earlier than requested:

```
request as_of=2026-05-31  →  response as_of=2026-05-30 (the latest snapshot ≤ request)
```

This is what makes membership look-ahead-free: a backtest at date `D` only ever sees the
constituents known on or before `D`.

## Seeding

Schema ships in Phase 1; seeding is from the existing **monthly universe snapshots**. When no
snapshot exists on or before the requested date, the API returns `as_of: null` and an empty
`symbols` list.

## Pending

The **`SET:SET` index + sector indices** are a known csm-set carve-out (deferred from Phase 3):
they are not yet seeded/fixed for csm-set's `residual_momentum`/composite feature pipeline.
That is a tracked csm-set follow-up; equity-constituent membership reads here are unaffected.
