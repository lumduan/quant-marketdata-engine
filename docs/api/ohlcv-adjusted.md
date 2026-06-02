# API — `GET /ohlcv/adjusted`

Dividend/split **adjust-on-read** OHLCV bars. Same shape and parameters as
[`/ohlcv`](ohlcv.md), but prices are back-adjusted by the `market_data.ohlcv_adjusted` view
(recomputed on every read, so a newly ingested corporate action is reflected immediately).

| | |
|---|---|
| Method / path | `GET /ohlcv/adjusted` |
| Gateway-proxied | `GET /api/v2/engines/market-data/ohlcv/adjusted` |
| Auth | `X-API-Key` (when configured) |
| Source | `src/quant_marketdata_engine/api/routes.py::get_ohlcv_adjusted` |

## Query parameters

Identical to [`/ohlcv`](ohlcv.md): `symbol` (1–64), `timeframe` (`1d`\|`1h`\|`5m`), `start`,
`end`, `limit` (1–50000, default 5000).

## Request

```bash
curl -H "X-API-Key: <engine-read-key>" \
  "http://localhost:8300/ohlcv/adjusted?symbol=SET:PTT&timeframe=1d&limit=3"
```

## Response `200 OK`

Same fields as `/ohlcv`, but `adjusted` is `true` and the prices carry the cumulative
back-adjustment factor. `volume` / `open_interest` pass through **unadjusted**.

```json
{
  "symbol": "SET:PTT",
  "timeframe": "1d",
  "adjusted": true,
  "bars": [
    {
      "ts": "2026-05-29T00:00:00Z",
      "open": "33.900000",
      "high": "34.146000",
      "low": "33.654000",
      "close": "33.900000",
      "volume": "41250000.0000",
      "open_interest": null
    }
  ]
}
```

## Adjustment semantics

For each bar, the factor is the cumulative product of `corporate_actions.ratio` over all
actions for that symbol whose `ex_date` is strictly **after** the bar's date (back-adjustment).
Bars on or after the most recent action are unchanged (factor `1.0`). The math and the
`corporate_actions` table are detailed in
[`../data/corporate-actions.md`](../data/corporate-actions.md).

## Errors

Same as [`/ohlcv`](ohlcv.md): `401` (auth), `422` (validation), `503` (DB down); gateway maps
transport failures to `504`/`503`/`502`.

## Pending

- The equity **split/dividend** path is proven and testable.
- **Futures-roll back-adjustment of the `S501!` continuous is not yet computed engine-side.**
  tfex builds its back-adjusted continuous locally from raw dated contracts
  (`/ohlcv?...&adjusted` not used for futures); engine-native roll parity is a Phase 5+
  follow-up. Do not assume `S501!` from this endpoint is roll-adjusted.
