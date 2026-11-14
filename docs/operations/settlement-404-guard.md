# The settlement 404 guard

`scripts/check_settlement_404.sh` asks the **deployed** service whether an unknown TFEX series still
maps to HTTP 404.

## Why it is not a unit test

[[TK-0655]]: an unknown series returned **503** instead of 404 because the handler caught
`httpx.HTTPStatusError`, and settfex does not use httpx — so the handler could never fire.

🔑 **It survived review because the unit tests passed.** They hand-constructed `status_code=404`, so
they could not see a handler keyed to a package that never raises. **A unit test is structurally
unable to catch this defect class.** Only the running service can answer it.

## The two halves

| half | owner | guards |
| --- | --- | --- |
| library | `session:settfex` (their PR #185, `-m integration`) | TFEX still answers 404, and settfex raises `SeriesNotFoundError` |
| **service** | **this script** | our route maps that to HTTP 404 |

They fail independently: a TFEX change reds theirs; a handler regression reds this one.

## Exit codes

| rc | state | meaning |
| --- | --- | --- |
| 0 | `OK` | unknown → 404 **and** control → 200 |
| 2 | `REGRESSED` | the control is healthy but the unknown series no longer 404s |
| 3 | `UNKNOWN` | **the control itself failed, so the 404 result is uninterpretable** |

**3 is deliberately not 2.** A 404 on *everything* would pass a naive check, and a dead service must
not be reported as a behaviour change — blindness stays distinguishable from regression.

## Overrides (for testing only)

`MDE_BASE`, `MDE_UNKNOWN_SERIES`, `MDE_CONTROL_SERIES`. Pointing `MDE_UNKNOWN_SERIES` at a real
series must produce `rc=2`; pointing `MDE_CONTROL_SERIES` at a bogus one must produce `rc=3`. Those
two are the mutants that prove the check is not vacuous.

## Slack

Posts **only** on rc 2 or 3, reading `PM_SLACK_WEBHOOK` by name at call time. It embeds no URL and
never prints the value. `--no-slack` suppresses the post entirely.
