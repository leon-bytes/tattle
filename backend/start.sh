#!/usr/bin/env bash
# One command to start the VM side of the demo: the backend on port 8000, reachable from the host.
# It serves the show screen (the plain files in frontend/, no build step) at /, the operator console at
# /debug and the fallback view at /present. Files are read at each request: after an edit, reload the page.
#
# Usage, from anywhere:  bash backend/start.sh        Stop with Ctrl+C (that also forgets everything captured).

set -euo pipefail                                   # stop at the first failing command or unset variable
cd "$(dirname "$0")/.."                             # the repo root, wherever this was called from

if [ ! -x backend/.venv/bin/python ]; then          # first run on this machine: see backend/README.md
  echo "backend/.venv is missing. Create it once (needs internet):" >&2
  echo "  python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt" >&2
  exit 1
fi

if [ -f .env ]; then                                # optional settings (database, AI)
  while IFS='=' read -r key value; do               # read KEY=value lines as plain text: nothing in .env is executed
    case "$key" in ''|\#*) continue ;; esac         # skip blank lines and comments
    case "$value" in *'<'*) continue ;; esac        # skip placeholders nobody filled in, like <db-password>
    export "$key=$value"
  done < .env
fi

if [ -f frontend/index.html ]; then page="the show screen (frontend/)"; else page="the debug page (frontend/index.html is missing)"; fi
echo "Tattle backend starting. / shows $page."
for address in $(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1); do
  echo "  http://$address:8000/   also /debug and /present"   # one line per address of this machine
done
echo "The host reaches this VM at its 192.168.122.x address. Give the sensor: --backend http://<that address>:8000"

# --host 0.0.0.0: listen on all interfaces, so the host can connect. --no-access-log: no line per request.
exec backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --no-access-log
