#!/usr/bin/env bash
# The SERVICE half of TK-0655's regression guard.
#
# WHY IT EXISTS. TK-0655: an unknown TFEX series returned 503 instead of 404 because the handler
# caught the WRONG package's exception. It survived review because THE UNIT TESTS PASSED -- they
# hand-constructed status_code=404, so they could not see a handler keyed to a package that never
# raises. A unit test is therefore the wrong guard for this defect class. Only the deployed service
# can answer it.
#
# THE SPLIT (agreed with session:settfex, 2026-11-14):
#   LIBRARY half (theirs, done): settfex PR #185, a live integration test -- TFEX still answers an
#     unknown series with 404 and settfex raises SeriesNotFoundError. Runs only with -m integration.
#   SERVICE half (this script):  marketdata's route maps that to HTTP 404.
# The halves fail independently: if TFEX changes, theirs reds; if our handler regresses, this does.
#
# EXIT CODES -- the finding is in the code, so a caller can act on it:
#   0  OK        both as expected
#   2  REGRESSED the control is healthy but the unknown series no longer 404s  <- the real finding
#   3  UNKNOWN   the control itself failed, so the 404 result is uninterpretable
# 3 is deliberately NOT 2: "we are blind" must stay distinguishable from "the behaviour changed".
#
# Slack only on 2 or 3 (a daily "nothing wrong" is the alert fatigue DC-0007 is about).
# Reads PM_SLACK_WEBHOOK by NAME at call time; never embeds a URL.
#
#   bash scripts/check_settlement_404.sh --no-slack     # safe anywhere, makes 2 local requests
#
# Armed from the host crontab; see docs/operations/settlement-404-guard.md
set -uo pipefail

BASE="${MDE_BASE:-http://127.0.0.1:8300}"
UNKNOWN_SERIES="${MDE_UNKNOWN_SERIES:-ZZZZ99}"
CONTROL_SERIES="${MDE_CONTROL_SERIES:-S50Z26}"
NOSLACK=0; [ "${1:-}" = "--no-slack" ] && NOSLACK=1

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$BASE$1" 2>/dev/null; }

C_UNKNOWN=$(code "/settlements/$UNKNOWN_SERIES")
C_CONTROL=$(code "/settlements/$CONTROL_SERIES")

printf 'ts=%s base=%s unknown=%s->%s control=%s->%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$BASE" "$UNKNOWN_SERIES" "$C_UNKNOWN" "$CONTROL_SERIES" "$C_CONTROL"

# The CONTROL is evaluated FIRST. Without it a 404 on everything also "passes".
if [ "$C_CONTROL" != "200" ]; then
  STATE=UNKNOWN; RC=3
  MSG="marketdata 404-guard UNKNOWN: the control series $CONTROL_SERIES returned $C_CONTROL, not 200. The unknown-series result ($C_UNKNOWN) cannot be interpreted -- this says the SERVICE is unhealthy, NOT that the 404 mapping regressed."
elif [ "$C_UNKNOWN" = "404" ]; then
  STATE=OK; RC=0
  MSG="marketdata 404-guard OK: $UNKNOWN_SERIES -> 404, control $CONTROL_SERIES -> 200."
else
  STATE=REGRESSED; RC=2
  MSG="marketdata 404-guard REGRESSED: $UNKNOWN_SERIES returned $C_UNKNOWN, expected 404, while the control $CONTROL_SERIES correctly returned 200. TK-0655's defect is back: an unknown TFEX series is not mapping to 404."
fi
echo "verdict=$STATE rc=$RC"
echo "$MSG"

if [ "$RC" != "0" ] && [ "$NOSLACK" = "0" ]; then
  if [ -n "${PM_SLACK_WEBHOOK:-}" ]; then
    OUT=$(curl -sS -X POST -H 'Content-type: application/json' --max-time 20 \
          -d "$(printf '{"text":"%s"}' "$(printf '%s' "$MSG" | sed 's/"/\\"/g')")" \
          "$PM_SLACK_WEBHOOK" 2>&1)
    [ "$OUT" = "ok" ] && echo "slack: ok" || echo "slack: FAILED -- NOT DELIVERED"
  else
    echo "slack: PM_SLACK_WEBHOOK unset -- NOT DELIVERED"
  fi
fi
exit "$RC"
