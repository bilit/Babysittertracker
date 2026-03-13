# Babysitter Hours Tracker

A Home Assistant add-on (or standalone Docker app) that shows person-detection
snapshots from your Nest doorbell, lets you tag arrivals and departures, and
automatically calculates weekly pay.

| Time window        | Rate        |
|--------------------|-------------|
| 9:00 AM – 3:00 PM  | **$16 / hr** |
| All other hours    | **$10 / hr** |

Hours that straddle the rate boundary are split and calculated correctly.

---

## How It Works

1. Your Nest doorbell detects a person → HA saves a timestamped snapshot.
2. Open the tracker → browse snapshot thumbnails for the week.
3. Click **Arrived** on the photo of the babysitter arriving, **Departed** on the one leaving.
4. Live pay preview appears — click **Save Session**.
5. View the **Weekly Summary** for a full per-day and per-week breakdown.
6. Every session's hours and pay amounts are stored in the database — no recalculation needed at the end of the week.

---

## Deployment Option A — HA Add-on (recommended for HA OS / Supervised)

This is the cleanest option. The app appears as a panel inside your HA sidebar,
uses the automatic Supervisor token (no manual token needed), and survives reboots.

### Step 1 — Find your Nest entity IDs

You need two entity IDs from HA before you configure anything.

1. In HA, go to **Settings → Devices & Services → Integrations → Google Nest**.
2. Click your doorbell device.
3. Note the **camera entity ID** (e.g. `camera.front_door`) and the
   **person binary sensor** (e.g. `binary_sensor.front_door_person`).

You can also find them via **Developer Tools → States** — filter the list by
typing `front_door` or whatever your device is named.

> **Tip:** The person sensor is usually named
> `binary_sensor.<device_name>_person`. If you don't see one, check
> **Settings → Devices & Services → Entities** and search for "person".

### Step 2 — Set up snapshot saving

The app needs a folder of saved images to display. Add the provided automation
to HA so a snapshot is saved every time someone is detected.

1. In HA go to **Settings → Automations → + Create Automation → Edit in YAML**.
2. Paste the contents of `ha_automation.yaml` from this repo.
3. Replace `binary_sensor.front_door_person` and `camera.front_door` with
   **your actual entity IDs**.
4. Save and enable the automation.

From now on, every person detection saves a file to
`/config/www/snapshots/doorbell_YYYYMMDD_HHMMSS.jpg`.

### Step 3 — Install the add-on

#### Method A: Samba / SSH file copy (easiest)

1. Install the **Samba share** add-on from the HA Add-on Store if you haven't.
2. On your computer, connect to `\\<ha-ip>\addons` (Windows) or
   `smb://<ha-ip>/addons` (Mac/Linux).
3. Create a folder called `babysitter_tracker` inside `addons/`.
4. Copy **all files from this repo** into that folder.
   The folder should look like:
   ```
   addons/babysitter_tracker/
   ├── config.yaml
   ├── build.yaml
   ├── Dockerfile
   ├── run.sh
   ├── app.py
   ├── requirements.txt
   ├── templates/
   │   └── index.html
   └── static/
   ```
5. In HA go to **Settings → Add-ons → Add-on Store**.
6. Click the three-dot menu (⋮) in the top right → **Check for updates**.
7. Scroll down to **Local add-ons** — you should see **Babysitter Tracker**.
8. Click it → **Install**. HA will build the Docker image (takes ~2 minutes).

#### Method B: SSH terminal

```bash
# SSH into your HA instance (requires SSH add-on)
mkdir -p /addons/babysitter_tracker
cd /addons/babysitter_tracker

# Copy files here (use scp or the Samba share)
# Then reload add-ons:
ha addons reload
```

### Step 4 — Configure the add-on

1. In HA → **Settings → Add-ons → Babysitter Tracker → Configuration** tab.
2. Fill in:

| Option | Value | Example |
|---|---|---|
| `camera_entity` | Your Nest camera entity ID | `camera.front_door` |
| `person_sensor` | Your person detection binary sensor | `binary_sensor.front_door_person` |
| `snapshot_subdir` | Subfolder inside `/share/` for saved images | `babysitter_snapshots` |
| `timezone` | Your local timezone | `America/New_York` |

3. Click **Save**.

### Step 5 — Start it

1. Go to the **Info** tab → **Start**.
2. Enable **Start on boot** and **Watchdog** (auto-restart if it crashes).
3. Click **Open Web UI** — or look for **Babysitter Tracker** in your HA sidebar.

> **Note on snapshots folder:** The add-on saves images to `/share/babysitter_snapshots/`.
> Your HA automation must also save to that path. Update `ha_automation.yaml`
> line:
> ```yaml
> filename: "/share/babysitter_snapshots/doorbell_{{ now().strftime('%Y%m%d_%H%M%S') }}.jpg"
> ```

---

## Deployment Option B — Standalone Docker Compose

Use this if you run **HA Container** (plain Docker, no Supervisor) or want to
run the tracker on a separate machine on your network.

### Step 1 — Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Your HA URL and a long-lived access token
HA_URL=http://192.168.1.100:8123
HA_TOKEN=your_long_lived_token_here   # see below for how to get this

# Your entity IDs
CAMERA_ENTITY=camera.front_door
PERSON_SENSOR=binary_sensor.front_door_person

# Path on the HOST where HA saves snapshots (mounted into the container)
SNAPSHOT_DIR=/config/www/snapshots

TIMEZONE=America/New_York
PORT=5050
```

**Getting a long-lived token:**
1. In HA, click your username at the bottom-left.
2. Scroll to **Long-Lived Access Tokens** → **Create Token**.
3. Name it `babysitter-tracker` and copy the value into `.env` as `HA_TOKEN`.

### Step 2 — Set the snapshot volume

Edit `docker-compose.yml` and replace the host path for the snapshots volume:

```yaml
volumes:
  - /YOUR/HA/CONFIG/www/snapshots:/config/www/snapshots:ro
```

Common paths:
| HA install type | Host path |
|---|---|
| HA OS (default) | `/mnt/data/supervisor/homeassistant/www/snapshots` |
| Docker (`-v /config:/config`) | `/config/www/snapshots` |
| Manual | Wherever your `configuration.yaml` lives, then `/www/snapshots` |

### Step 3 — Run

```bash
docker compose up -d
```

Open **http://your-host:5050**.

---

## Connecting to the Nest Camera

The app uses HA's existing Google Nest integration — you don't need a separate
Nest API key. It reads camera snapshots and person-detection events directly
from HA.

### Verify the Nest integration is working

1. In HA → **Settings → Devices & Services → Google Nest**.
2. Your doorbell should be listed. Click it and confirm you see:
   - A **Camera** entity (live feed)
   - A **Person** binary sensor

### If person detection isn't showing up

- Make sure your Nest device supports person detection (Nest Doorbell, Nest
  Hello, or Nest Cam with a Nest Aware subscription).
- In the Google Home app, confirm motion/person alerts are enabled for the device.
- In HA, go to **Settings → Devices & Services → Google Nest → Configure** and
  check that event subscriptions are enabled.

### Automation snapshot path

The automation in `ha_automation.yaml` saves images to a path inside HA's
config directory. **The app must point to the same directory.**

| Deployment | Automation `filename` | App `SNAPSHOT_DIR` or add-on `snapshot_subdir` |
|---|---|---|
| HA Add-on | `/share/babysitter_snapshots/doorbell_...jpg` | `babysitter_snapshots` |
| Docker | `/config/www/snapshots/doorbell_...jpg` | `/config/www/snapshots` (host path mapped to container) |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| No snapshots appear | Check the automation ran: go to **Developer Tools → Events**, listen for `automation_triggered` then walk in front of the camera |
| "Could not fetch camera snapshot" | Check `CAMERA_ENTITY` matches exactly what HA shows in Developer Tools → States |
| Add-on won't install | Make sure `config.yaml`, `Dockerfile`, and `run.sh` are all in the add-on folder |
| Wrong time on sessions | Set `timezone` in add-on config or `.env` to your local timezone (e.g. `America/Chicago`) |
| HA API errors (401) | For Docker mode, regenerate your long-lived token |

---

## Pay Rate Reference

```
Example: babysitter arrives 8:00 AM, leaves 5:00 PM

  8:00 AM →  9:00 AM  =  1 hr  × $10  =  $10.00   (off-peak)
  9:00 AM →  3:00 PM  =  6 hrs × $16  =  $96.00   (peak)
  3:00 PM →  5:00 PM  =  2 hrs × $10  =  $20.00   (off-peak)
                                        ─────────
  Total:  9 hours                       $126.00
```
