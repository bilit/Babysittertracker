# Babysitter Hours Tracker

Tracks babysitter hours using video clips your Nest doorbell already saves
automatically in Home Assistant. Select the arrival and departure clip each
day — the app calculates and stores the pay split.

| Time window       | Rate        |
|-------------------|-------------|
| 9:00 AM – 3:00 PM | **$16 / hr** |
| All other hours   | **$10 / hr** |

---

## Prerequisites

Before you start, confirm you have:

- **Home Assistant OS** or **Home Assistant Supervised** running on your
  network (Raspberry Pi, NUC, etc.). This is the version with the
  **Add-on Store** in Settings.
- **Google Nest integration** already set up in HA with your doorbell linked.
  If your doorbell shows a live feed in HA, you're good.
- A way to copy files to your HA machine — either the **Samba share** add-on
  (easiest) or the **SSH & Web Terminal** add-on.

> **Note:** The app reads video clips directly from disk — it does **not**
> query the HA API or require any entity IDs. As long as HA is saving Nest
> clips to `/config/nest/event_media/`, the app will work.

---

## Part 1 — Verify clips are already being saved (2 minutes)

The Nest integration in HA saves video clips automatically to:
```
/config/nest/event_media/
```
You do **not** need to set up any automation. Let's confirm this is working:

1. Open the **File editor** add-on (install it from the Add-on Store if you
   don't have it, or use Samba/SSH to browse files).
2. Navigate to `config/nest/event_media/`.
3. You should see subdirectories named after your device ID(s), and inside
   them `.mp4` clip files — one per detected event.

If the folder is empty or missing, trigger a test:
- Wave your hand in front of the doorbell, or press the doorbell button.
- Wait 10 seconds and refresh. A new `.mp4` file should appear.

If nothing appears after triggering, check **Settings → Devices & Services →
Google Nest → Configure** and make sure event subscriptions are enabled.

---

## Part 2 — Copy the add-on files to HA (5 minutes)

### Using Samba share (recommended)

1. Install **Samba share** from the HA Add-on Store if you haven't already.
   Configure it with a username and password, then start it.

2. On your computer, open your file manager and connect to your HA machine:
   - **Windows**: Open File Explorer → type `\\<your-ha-ip>` in the address
     bar (e.g. `\\192.168.1.100`) → press Enter → log in with your Samba
     credentials.
   - **Mac**: Finder → Go → Connect to Server → type
     `smb://<your-ha-ip>` → Connect → log in.
   - **Linux**: File manager → Connect to Server →
     `smb://<your-ha-ip>/addons`

3. Open the `addons` share. Create a new folder called `babysitter_tracker`.

4. Copy **all files from this repository** into that folder. When done it
   should look exactly like this:
   ```
   addons/
   └── babysitter_tracker/
       ├── config.yaml          ← required (add-on manifest)
       ├── build.yaml           ← required (build config)
       ├── Dockerfile           ← required
       ├── run.sh               ← required
       ├── app.py               ← required
       ├── requirements.txt     ← required
       ├── templates/
       │   └── index.html       ← required
       ├── static/              ← required (can be empty folder)
       ├── .env.example
       ├── docker-compose.yml
       └── README.md
       ```

### Using SSH instead

If you prefer the SSH & Web Terminal add-on:

```bash
# In the SSH terminal inside HA:
mkdir -p /addons/babysitter_tracker

# Then use scp from your computer to copy the files:
# (run this on your computer, not in the HA terminal)
scp -r /path/to/Babysittertracker/* root@<ha-ip>:/addons/babysitter_tracker/
```

---

## Part 3 — Install the add-on (3 minutes)

1. In HA go to **Settings → Add-ons**.
2. Click **Add-on Store** (bottom right).
3. Click the **⋮ (three-dot menu)** in the top-right corner of the store page.
4. Click **Check for updates**.
5. Scroll to the very bottom of the page. You should see a section called
   **Local add-ons** containing **Babysitter Tracker**.
6. Click **Babysitter Tracker** → **Install**.

HA will now build the Docker image. This takes **1–3 minutes** depending on
your hardware. A progress bar will appear — wait for it to complete.

> **Don't see it in Local add-ons?**
> The `config.yaml` file must be directly inside the `babysitter_tracker`
> folder (not in a subfolder). Double-check the folder structure from Part 3.

---

## Part 4 — Configure the add-on (2 minutes)

Once installed, **do not start it yet** — configure it first.

1. Click the **Configuration** tab on the add-on page.
2. The only values you need to change are `timezone` and, if your clips are
   stored in a non-default path, `snapshot_subdir`:

```yaml
camera_entity: "camera.front_door"              # stored for future use, not queried
person_sensor: "event.front_door_bell_motion"   # stored for future use, not queried
snapshot_subdir: "nest/event_media"             # ← leave as-is unless clips are elsewhere
timezone: "America/New_York"                    # ← change this to your timezone
```

**Common US timezones:**
```
America/New_York       Eastern
America/Chicago        Central
America/Denver         Mountain
America/Los_Angeles    Pacific
America/Phoenix        Arizona (no DST)
America/Anchorage      Alaska
Pacific/Honolulu       Hawaii
```

3. Click **Save**.

---

## Part 5 — Start the add-on

1. Click the **Info** tab.
2. Click **Start**.
3. Toggle on **Start on boot** — this makes the add-on start automatically
   when HA restarts.
4. Toggle on **Watchdog** — this restarts the add-on automatically if it
   crashes.
5. Click **Open Web UI**.

The app should open. If it doesn't, wait 10 seconds and try again — it takes
a moment on first launch to scan the clips directory.

You should also see **Babysitter Tracker** appear in your HA sidebar as a
panel. Click it any time to open the app without leaving HA.

---

## Part 6 — Using the app

The app has four tabs across the top.

### Clips tab

Shows video thumbnails from your Nest doorbell, newest first, filtered to the
current week.

- Use the **Week** dropdown to navigate to a different week.
- Use the **Date** filter to narrow to a single day.
- Click a thumbnail to play the clip inline. Click again to stop.

**To record a session:**
1. Find the clip where the babysitter arrived. Click **Arrived** — the card
   turns green and a banner appears at the top.
2. Find the clip where the babysitter departed. Click **Departed** — the card
   turns orange.
3. The banner shows the calculated pay preview instantly.
4. Click **Save Session**. The session is stored with all hours and pay amounts.
5. Click **Clear** in the banner to deselect and start over.

### Sessions tab

Lists every saved session for the selected week, with per-rate hour breakdown
and a delete button on each row.

### Weekly Summary tab

Four stat cards at the top show total pay, total hours, peak hours, and
off-peak hours for the week. Below is a by-date table with one row per session.

### Manual Entry tab

Add a session without a clip (e.g. for a past week or if clips are missing):

1. Enter the date, arrival time, and departure time.
2. The pay preview updates instantly.
3. Click **Save Session**.

---

## Troubleshooting

### "No clips found for this period"

The clips directory is empty or the path is wrong.

1. In the add-on **Log** tab, look for:
   ```
   [babysitter-tracker] Clips folder: /config/nest/event_media
   ```
2. Check that `/config/nest/event_media/` actually exists and contains `.mp4`
   files (see Part 1).
3. If your clips are somewhere else, update `snapshot_subdir` in the add-on
   configuration to match. For example, if they're at
   `/config/nest/media/`, set `snapshot_subdir: "nest/media"`.

### Add-on won't appear in Local add-ons

- Make sure the folder is named `babysitter_tracker` (no spaces).
- Make sure `config.yaml` is directly inside that folder.
- After copying files, go to Add-on Store → ⋮ → **Check for updates** again.

### Add-on fails to build / install

Check the **Log** tab for the error. Common causes:

| Error message | Fix |
|---|---|
| `no such file: run.sh` | `run.sh` wasn't copied into the folder |
| `invalid config.yaml` | Make sure you copied `config.yaml`, not just `README.md` |
| Build hangs for >5 minutes | Restart HA and try again |

### Wrong timezone / pay calculation is off

The timezone must match your local timezone exactly. Check
[this list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)
for the exact string. Update it in **Configuration → timezone → Save →
Restart**.

### Clips show but times look wrong

The timestamp comes from the file modification time that HA sets when it saves
the clip. If clips are old backups that were copied, their modification times
may be wrong. The app will show whatever time the file was last written.

---

## Standalone Docker (alternative to the add-on)

Use this only if you're running **HA Container** (no Supervisor/add-on system)
or want to run the tracker on a separate machine.

```bash
# 1. Clone the repo
cp .env.example .env
```

Edit `.env` — the only required setting is pointing to your HA config directory:
```env
TIMEZONE=America/New_York
PORT=5050
```

Edit `docker-compose.yml` — update the volume host path to your HA config directory:
```yaml
volumes:
  - /YOUR/HA/CONFIG/DIR:/config:ro   # ← change this line
  - babysitter_data:/data
```

```bash
# 2. Start
docker compose up -d

# 3. Open
http://<your-machine-ip>:5050
```

**How to find your HA config path:**
- HA OS on Raspberry Pi / NUC: typically under
  `/mnt/data/supervisor/homeassistant`
- HA Docker with `-v /ha-config:/config`: use `/ha-config`
- Check: `docker inspect homeassistant | grep Mounts` on your Docker host

---

## Pay Rate Reference

```
Example: babysitter arrives 8:00 AM, leaves 5:00 PM

  8:00 AM →  9:00 AM  =  1 hr  × $10  =  $10.00   (off-peak, before 9am)
  9:00 AM →  3:00 PM  =  6 hrs × $16  =  $96.00   (peak)
  3:00 PM →  5:00 PM  =  2 hrs × $10  =  $20.00   (off-peak, after 3pm)
                                        ─────────
  Total:  9 hours                       $126.00
```
