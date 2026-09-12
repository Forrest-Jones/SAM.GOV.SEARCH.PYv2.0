#!/bin/bash
# ---------------------------------------------------------------------
# Double-click this file to start Contract Finder.
#
# It exists because every step before this one has a way to fail that
# looks identical from a browser: a wrong directory, a missing Flask, a
# port already held by something else. All three end in
# ERR_CONNECTION_REFUSED with nothing on screen to say which.
#
# This script cds to its own folder (so there is no path to get wrong),
# installs what is missing, finds a free port, opens the browser, and
# keeps the window open if anything fails so the reason is readable.
# ---------------------------------------------------------------------

cd "$(dirname "$0")" || exit 1

say() { printf '\n  %s\n' "$1"; }
die() {
  printf '\n  ---- Could not start ----\n  %s\n\n' "$1"
  printf '  Press any key to close this window.\n'
  read -r -n 1 -s
  exit 1
}

clear
printf '  Contract Finder\n  %s\n' "$(pwd)"

command -v python3 >/dev/null 2>&1 || die \
  "python3 is not installed. Install it from python.org, then double-click this again."

say "Getting the latest version..."
git pull --quiet 2>/dev/null || say "(could not reach GitHub — starting with what is already here)"

say "Using $(python3 -V 2>&1) at $(command -v python3)"

# Every module the app imports at startup, not just Flask. Checking only
# Flask meant that on a Python with Flask already installed the install
# step was skipped entirely — and the app then died on a missing tomllib,
# which is standard library only from Python 3.11 and comes from the
# "tomli" package below that.
missing=""
for mod in flask requests; do
  python3 -c "import $mod" >/dev/null 2>&1 || missing="$missing $mod"
done
python3 -c "import tomllib" >/dev/null 2>&1 \
  || python3 -c "import tomli" >/dev/null 2>&1 \
  || missing="$missing tomli"

if [ -n "$missing" ]; then
  say "Installing what is missing:$missing"
  python3 -m pip install --quiet --user -r requirements.txt -r webapp/requirements.txt 2>/dev/null \
    || python3 -m pip install --quiet -r requirements.txt -r webapp/requirements.txt 2>/dev/null \
    || python3 -m pip install --quiet --break-system-packages -r requirements.txt -r webapp/requirements.txt \
    || die "Could not install:$missing

  Try this in Terminal, then double-click again:
      python3 -m pip install$missing"
fi

# Re-check, and name whichever one is still absent rather than failing
# later inside the app with a bare traceback.
for mod in flask requests; do
  python3 -c "import $mod" >/dev/null 2>&1 || die "$mod is still not importable.
  Try: python3 -m pip install $mod"
done
python3 -c "import tomllib" >/dev/null 2>&1 || python3 -c "import tomli" >/dev/null 2>&1 \
  || die "No TOML parser for $(python3 -V 2>&1).
  Try: python3 -m pip install tomli"

# Port 5000 is held by AirPlay Receiver on macOS, which answers with a 403
# that looks like a broken app. 8000 is the default; step along if taken.
PORT=8000
for candidate in 8000 8001 8002 8003 8010; do
  if ! (exec 3<>"/dev/tcp/127.0.0.1/$candidate") 2>/dev/null; then
    PORT=$candidate
    break
  fi
  say "Port $candidate is already in use, trying the next one..."
done

say "Starting on http://localhost:$PORT"
export PORT
export FLASK_RUN_FROM_CLI=false

# Open the browser once the server is actually answering, rather than
# immediately — an early open is what produces ERR_CONNECTION_REFUSED even
# when the server is seconds from being ready.
(
  for _ in $(seq 1 40); do
    sleep 0.25
    if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
      open "http://localhost:$PORT" 2>/dev/null || true
      exit 0
    fi
  done
) &

printf '\n  Leave this window open while you use it. Press Ctrl+C to stop.\n\n'
python3 webapp/app.py
status=$?
[ $status -ne 0 ] && die "The app stopped with error code $status. The message above says why."
