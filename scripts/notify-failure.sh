#!/usr/bin/env bash
# Sends a Telegram message when invoked via systemd OnFailure=.
# Silently no-ops if TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set.

set -u

cd "$(dirname "$0")/.."

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    exit 0
fi

UNIT="${MONITOR_UNIT:-yt-instrumental.service}"
RESULT="${MONITOR_SERVICE_RESULT:-unknown}"
EXIT_STATUS="${MONITOR_EXIT_STATUS:-?}"

# `journalctl --user-unit` reads user-unit logs from whichever journal storage
# the system has (system or runtime), unlike `journalctl --user -u` which
# requires a persistent per-user journal.
LAST_LOG=$(journalctl --user-unit "$UNIT" -n 20 --no-pager 2>/dev/null || echo "(journal unavailable)")

# Detect the most common recoverable failure: an expired OAuth refresh token.
# When seen, append actionable instructions so the alert is one-touch from a phone.
HINT=""
if grep -qE 'invalid_grant|Token has been expired or revoked|RefreshError' <<<"$LAST_LOG"; then
    HINT=$'\n\n🔐 OAuth refresh token is expired/revoked. To re-link, SSH in and run:\n  ssh -L 8080:localhost:8080 pi@'"$(hostname)"$'\n  cd /home/pi/code/yt-song-to-instrumental\n  mv token.json token.json.bak\n  uv run yt-instrumental --sync-channel\nCopy the printed URL into a browser, approve, and the run will re-link.'
fi

MESSAGE="[FAIL] ${UNIT}
Result: ${RESULT} (exit ${EXIT_STATUS})
Host: $(hostname)
Time: $(date -Iseconds)

Last 20 log lines:
${LAST_LOG}${HINT}"

export MESSAGE
python3 - <<'PYEOF'
import json, os, sys, urllib.request

token = os.environ["TELEGRAM_BOT_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]
text = os.environ["MESSAGE"][:4000]

url = f"https://api.telegram.org/bot{token}/sendMessage"
data = json.dumps({"chat_id": chat_id, "text": text}).encode()
req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=10).read()
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", errors="replace")
    print(f"telegram notify failed: {e} — {body}", file=sys.stderr)
except Exception as e:
    print(f"telegram notify failed: {e}", file=sys.stderr)
PYEOF
