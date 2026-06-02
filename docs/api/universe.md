# API — `GET /universe`

As-of dated, point-in-time index constituents. Returns the latest snapshot **on or before**
the requested date, so backtests get survivorship-/look-ahead-free membership. Auth-gated.

| | |
|---|---|
| Method / path | `GET /universe` |
| Gateway-proxied | `GET /api/v2/engines/market-data/universe` |
| Auth | `X-API-Key` (when configured) |
| Source | `src/quant_marketdata_engine/api/routes.py::get_universe` |

## Query parameters

| Param | Type | Required | Default | Allowed | Effect |
|-------|------|----------|---------|---------|--------|
| `as_of` | date | yes | — | ISO date `YYYY-MM-DD` | resolves the latest snapshot ≤ this date |
| `index_name` | string | no | `SET` | length 1–32 | which index's membership |

## Request

```bash
curl -H "X-API-Key: <engine-read-key>" \
  "http://localhost:8300/universe?as_of=2026-05-31&index_name=SET"
```

## Response `200 OK`

```json
{
  "as_of": "2026-05-30",
  "index_name": "SET",
  "symbols": ["SET:PTT", "SET:AOT", "SET:CPALL"]
}
```

| Field | Type | Notes |
|-------|------|-------|
| `as_of` | date \| null | the **resolved** snapshot date (≤ requested); `null` if no snapshot exists on/before the request |
| `index_name` | string | echoes the request |
| `symbols` | string[] | constituents in that snapshot |

## Errors

| Status | When |
|--------|------|
| `401` | API key set and `X-API-Key` missing/incorrect |
| `422` | malformed `as_of` date |
| `503` | DB pool unavailable |

## Notes

- The resolved `as_of` may be **earlier** than the requested date (it is the most recent
  snapshot on or before it); always read it from the response rather than assuming it equals
  the request.
- `market_data.universe_membership` is seeded from the monthly universe snapshots; see
  [`../data/universe-membership.md`](../data/universe-membership.md).
- **Pending (Phase 3 carve-out):** the `SET:SET` index + sector indices are not yet seeded /
  fixed for csm-set's feature pipeline; that fix is a tracked csm-set follow-up and does not
  affect equity-constituent reads here.
