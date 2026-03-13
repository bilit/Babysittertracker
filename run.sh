#!/usr/bin/env bash
set -e

# ── HA Add-on mode ──────────────────────────────────────────────────────────
# When running inside HA Supervisor, /data/options.json is written by the
# add-on framework and SUPERVISOR_TOKEN is injected automatically.
if [ -f /data/options.json ]; then
    echo "[babysitter-tracker] Detected HA add-on environment"

    # Use the Supervisor-provided token — no manual long-lived token needed
    export HA_TOKEN="${SUPERVISOR_TOKEN}"
    export HA_URL="http://supervisor/core"

    # Read user options set in the HA add-on UI
    CAMERA_ENTITY=$(jq --raw-output '.camera_entity // "camera.front_door"'       /data/options.json)
    PERSON_SENSOR=$(jq --raw-output '.person_sensor // "event.front_door_bell_motion"' /data/options.json)
    SNAPSHOT_SUBDIR=$(jq --raw-output '.snapshot_subdir // "nest/event_media"'         /data/options.json)
    TIMEZONE=$(jq --raw-output '.timezone // "America/New_York"'                       /data/options.json)

    export CAMERA_ENTITY
    export PERSON_SENSOR
    # Nest saves clips to /config/nest/event_media — accessible via config:ro mount
    export SNAPSHOT_DIR="/config/${SNAPSHOT_SUBDIR}"
    export TIMEZONE
    export DB_PATH="/data/babysitter.db"
    export PORT=5050

    echo "[babysitter-tracker] Clips folder: ${SNAPSHOT_DIR}"
    echo "[babysitter-tracker] Camera entity:     ${CAMERA_ENTITY}"
    echo "[babysitter-tracker] Person sensor:     ${PERSON_SENSOR}"
fi

# ── Standalone / Docker Compose mode ────────────────────────────────────────
# If no /data/options.json, all config comes from environment variables
# (set via .env file or docker-compose.yml). Nothing extra to do here.

echo "[babysitter-tracker] Starting on port ${PORT:-5050}"
exec python /app/app.py
