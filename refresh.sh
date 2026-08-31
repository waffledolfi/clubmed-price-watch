#!/bin/bash
# Refresh the Kiroro price data and rebuild the shareable page.
#   ./refresh.sh          full refresh (re-scans the season, ~3 min)
#   ./refresh.sh quick    just the watched week (~2 s)
set -e
cd "$(dirname "$0")"

echo "==> Checking the watched week"
python3 watch.py check

if [ "$1" != "quick" ]; then
  echo
  echo "==> Re-scanning the season (4, 5, 6 nights) - takes about 3 minutes"
  python3 watch.py scan KIPC_WINTER 2026-12-01 2027-04-27 4,5,6 7
fi

echo
echo "==> Rebuilding the shareable page"
python3 publish.py

cat <<'MSG'

Local data is up to date.

The shared link still shows the PREVIOUS version until the page is republished,
which only Claude can do. Either wait for the automatic run (every 2 days), or
ask Claude in any session:

    Republish the Kiroro price watch page

MSG
