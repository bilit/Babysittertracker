#!/bin/sh
set -e

# Set timezone from add-on config (falls back to env var for Docker Compose mode)
if [ -f /data/options.json ]; then
    TZ=$(python3 -c 'import json; print(json.load(open("/data/options.json")).get("timezone","America/New_York"))')
else
    TZ="${TIMEZONE:-America/New_York}"
fi
export TZ
ln -snf /usr/share/zoneinfo/"$TZ" /etc/localtime 2>/dev/null || true

echo "[babysitter-tracker] Starting on port 8099 (TZ=$TZ)"

mkdir -p /data/thumbs

exec python3 /app/app.py
