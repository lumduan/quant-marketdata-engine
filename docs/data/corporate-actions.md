# Data — Corporate Actions & Adjust-on-Read

`market_data.corporate_actions` holds equity splits/dividends **and** futures roll dates. The
`ohlcv_adjusted` view consumes it to back-adjust prices on read (D2/D10), so no adjusted bar is
ever cached and stale. SQL: `quant-infra-db/init-scripts/10_schema_market_data.sql`.

## `market_data.corporate_actions`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `symbol` | `text` | PK | |
| `ex_date` | `date` | PK | |
| `action_type` | `text` | PK, CHECK ∈ `{split, dividend, roll}` | |
| `ratio` | `numeric(18,8)` | CHECK NULL or `> 0` | multiplicative **back-adjustment** factor |
| `amount` | `numeric(18,6)` | | raw human-readable magnitude (cash dividend, split label, roll gap) — audit only |
| `note` | `text` | | free-form |
| `ingested_at` | `timestamptz` | default `now()` | |

PK `(symbol, ex_date, action_type)`; index `idx_corporate_actions_symbol_exdate` on
`(symbol, ex_date DESC)`. Low-cardinality point-lookup table — a plain table, not a hypertable.

### What `ratio` means

`ratio` is the price factor applied to bars dated **strictly before** `ex_date`. The engine
computes it at ingest:

- **split:** `1 / split_factor`
- **dividend:** `(close − dividend) / close`
- **roll:** the roll-gap multiplier (`far_close / near_close` at the roll boundary)

`amount` records the raw magnitude for a human to audit any re-derivation.

## The `ohlcv_adjusted` view

```sql
-- adjustment_factor for a bar = product of ratio over all actions with ex_date > bar date
-- (Postgres has no product aggregate → exp(sum(ln(ratio))), ratio > 0)
SELECT o.symbol, o.timeframe, o.ts,
       (o.open  * f.adjustment_factor)::numeric(18,6) AS open,
       ...,
       o.volume, o.open_interest, f.adjustment_factor
FROM market_data.ohlcv o
CROSS JOIN LATERAL (
  SELECT COALESCE(
    (SELECT exp(sum(ln(ca.ratio)))
       FROM market_data.corporate_actions ca
      WHERE ca.symbol = o.symbol AND ca.ratio IS NOT NULL
        AND ca.ex_date > (o.ts AT TIME ZONE 'UTC')::date),
    1.0) AS adjustment_factor
) f;
```

- It is a **view, not a continuous aggregate** — it recomputes on every read, so inserting a
  new action row is reflected on the next `/ohlcv/adjusted` read with **nothing to
  invalidate**.
- Bars on/after the most recent action have factor `1.0` (unchanged).
- **Volume and open_interest pass through unadjusted.**

Exposed via [`../api/ohlcv-adjusted.md`](../api/ohlcv-adjusted.md).

## Status

- **Done:** equity split/dividend back-adjustment (ratio-driven), proven and testable.
- **Pending:** **futures-roll back-adjustment of `S501!`** is not yet computed engine-side. The
  schema supports it (`action_type='roll'`), but tfex currently back-adjusts its continuous
  **locally** from raw dated contracts; engine-native roll parity is a Phase 5+ follow-up. Do
  not treat `S501!` from `/ohlcv/adjusted` as roll-adjusted.
