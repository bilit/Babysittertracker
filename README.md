# Babysitter Hours Tracker

A web app that integrates with Home Assistant to help you track babysitter hours
using person-detection snapshots from your Nest doorbell camera.

## Pay Rates

| Time window     | Rate      |
|-----------------|-----------|
| 9:00 AM – 3:00 PM | **$16 / hr** |
| All other hours | **$10 / hr** |

Hours that span both windows are automatically split and calculated correctly.

---

## How It Works

1. Your Nest doorbell detects a person → HA saves a snapshot image.
2. You open the tracker → browse the snapshot grid for your week.
3. Click **Arrived** on the photo of the babysitter arriving, **Departed** on the photo of them leaving.
4. The app calculates the pay split across the rate windows and shows a preview.
5. Click **Save Session** — done. Repeat for each day.
6. View the **Weekly Summary** tab for a full breakdown.

---

## Setup

### 1. Configure HA to save snapshots

Add `ha_automation.yaml` to your HA automations (or import via the UI).
Adjust the entity IDs to match your doorbell camera and person sensor.

Snapshots will be saved to `/config/www/snapshots/` inside your HA instance.

### 2. Configure the tracker

```bash
cp .env.example .env
# Edit .env with your HA URL, long-lived token, entity IDs, and snapshot path
```

### 3a. Run with Docker Compose (recommended)

```bash
# Edit the snapshot volume path in docker-compose.yml first
docker compose up -d
```

### 3b. Run with Python directly

```bash
pip install -r requirements.txt
python app.py
```

Open **http://your-host:5050** in your browser.

---

## Environment Variables

| Variable        | Default                      | Description                                      |
|-----------------|------------------------------|--------------------------------------------------|
| `HA_URL`        | `http://homeassistant.local:8123` | URL of your HA instance                    |
| `HA_TOKEN`      | _(required)_                 | HA long-lived access token                       |
| `CAMERA_ENTITY` | `camera.doorbell`            | Entity ID of your Nest doorbell camera           |
| `PERSON_SENSOR` | `binary_sensor.doorbell_person` | Entity ID of the person detection sensor      |
| `SNAPSHOT_DIR`  | `/config/www/snapshots`      | Directory containing saved snapshot images       |
| `DB_PATH`       | `babysitter.db`              | Path to the SQLite database                      |
| `TIMEZONE`      | `America/New_York`           | Your local timezone                              |
| `PORT`          | `5050`                       | Port the web app listens on                      |

---

## Getting Your HA Long-Lived Token

1. In HA, click your username (bottom-left).
2. Scroll to **Long-Lived Access Tokens**.
3. Click **Create Token**, give it a name (e.g. `babysitter-tracker`).
4. Copy the token into your `.env` as `HA_TOKEN`.

---

## Features

- **Snapshot grid** — browse person-detection images for any day or week
- **One-click tagging** — mark arrival and departure directly on photos
- **Live pay preview** — see estimated pay before saving
- **Manual entry** — add sessions by typing times (no photo required)
- **Weekly summary** — full hour and pay breakdown per day and week
- **Session management** — delete or review past sessions
- **Automatic HA sync** — pulls person-detection events directly from HA history as a fallback when no local snapshots exist
