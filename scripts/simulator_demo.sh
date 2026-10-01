#!/usr/bin/env bash
# A scripted conversation with the simulator host around ONE event (Phase 12 acceptance).
# Usage, after `make up && make migrate && make seed`:  scripts/simulator_demo.sh
# Each run uses a new listener, so remembered history never hides the flow.
# To act as a demo user with a bearer token instead of the dev header:
#   GREEO_TOKEN=greeo_... scripts/simulator_demo.sh
set -euo pipefail

BASE="${SIMULATOR_URL:-http://127.0.0.1:8000/api/simulator}"
if [ -n "${GREEO_TOKEN:-}" ]; then
  IDENTITY="Authorization: Bearer $GREEO_TOKEN"
else
  IDENTITY="X-Greeo-User: demo-$(date +%s)"
fi

say() {
  local session="$1" text="$2"
  echo
  echo "YOU   ($session): $text"
  curl -sS -X POST "$BASE/turn" \
    -H "Content-Type: application/json" -H "$IDENTITY" \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"session_id": sys.argv[1], "text": sys.argv[2]}))' "$session" "$text")" |
    python3 -c '
import json, sys
reply = json.load(sys.stdin)
print("GREEO:", reply["spoken"])
calls = ", ".join("{}({}) {}ms {}".format(
    step["tool"],
    ", ".join("{}={}".format(k, v) for k, v in step["args"].items()),
    step["ms"],
    "ok" if step["ok"] else "error",
) for step in reply["tool_trace"])
print("       tools: [{}]  host_mode: {}  card: {}".format(
    calls, reply["host_mode"], reply["display"].get("resource_uri")))
'
}

say one "tell me about the footbridge"
say one "go on"
say one "go on"
say one "what's the lesson?"
say one "what does that proverb mean?"
say one "make it serious"
say one "what actually happened?"
say one "what are the sides?"
say one "show me the evidence"
say one "save it"

echo
echo "--- a fresh session, same listener ---"
say two "what was I listening to?"
say two "continue"
