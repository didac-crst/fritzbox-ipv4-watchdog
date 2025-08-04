# FRITZ IPv4 Watchdog
**_“One more dawn, one more IP lease ghosted by the ISP, one more reboot to restore order…”_**

> It began like all good tech mysteries:  
> subtle, quiet, and with that unmistakable scent of something just slightly broken.
>
> **Tuesday morning, 10:46 AM.**  
> I’m at work, minding my own packets.  
> Then — *ding* — an email from Synology: *“Connection lost.”*  
> That’s always the first hint something’s off.
>
> I try to SSH into my LAN. Nothing.  
> I check the house cameras — offline.  
> VPN? Dead both ways.  
> Bots? Ignoring me on Telegram.  
> Cloudflare tunnel? Gone.
>
> I call home.  
> Wife says, *“Internet works fine.”*  
> Told her to reboot the router.  
> *Voilà.* Everything back.  
> We moved on. We always do. Until we can’t.
>
> **Twelve days later. Sunday. 06:30.**  
> Kids asleep. Peace in the kingdom.  
> *Ding.* Another Synology email.  
> This time, I’m home.
>
> I log into the FRITZ!Box 7560.  
> IPv6? Shining with a fresh `/56` from Wilhelm.tel.  
> But WAN-IPv4? **`0.0.0.0`**. Again.
>
> Every service stuck in the past with A-records was choking.  
> Clicked *“Neu verbinden”*. IPv4 popped back in.  
> Crisis postponed.
>
> But now the pattern was clear:  
> **Mr. Fritz — or maybe the ISP — was letting the IPv4 lease quietly expire, and doing nothing about it.**
>
> And that’s when it hit me:  
> *What if this happens while I’m away?*
>
> No cameras. No VPN.  
> No Synology. No Cloudflare.  
> No bots, no alerts, no control.
>
> So I did what any slightly neurotic engineer would do:  
> I deputized a Raspberry Pi.
>
> This watchdog now polls Fritz’s TR-064 API.  
> If IPv4 disappears too long, it tells Fritz to reconnect.  
> If Fritz ignores that, the Pi orders a full reboot.  
> Logs everything. No drama. No excuses.
>
> Since then?  
> Fritz gets out of line, the Pi puts him back in place.  
> IPv4 stays alive.  
> And I stay in bed.

---  

## What the script does 🩹  

1. Polls the router’s **TR-064** API every `CHECK_EVERY_SEC` seconds.  
2. If `GetExternalIPAddress` returns `0.0.0.0` for `MAX_BAD_CYCLES` polls:  
   * first two times → **PPP reconnect** (`ForceTermination`)  
   * third time onward → **full reboot** (`DeviceConfig:Reboot`)  
3. Logs to `/logs/watchdog.log` with rotation and optionally mirrors to stdout.  

Result: outages drop from *hours* to *≈30 s* and everything auto-recovers.  

---  

## Repository layout 📂  

```
fritzbox-ipv4-watchdog/
├── .env.example          # copy → .env and fill in the password
├── fritzbox_ipv4_watchdog.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── start_watchdog.sh     # helper → docker compose up -d
├── README.md             # ← you’re reading it
└── LICENCE
```  

---  

## Configuration via `.env` 🔧  

| Variable                     | Default / Example | Purpose                                                              |
| ---------------------------- | ----------------- | -------------------------------------------------------------------- |
| **FRITZ_HOST**               | `192.168.1.1`     | Router hostname or LAN-IP                                            |
| **FRITZ_USER**               | `svc-rebooter`    | User that owns the TR-064 session                                    |
| **FRITZ_PASSWORD**           | —                 | **Required** – password for the user above                           |
| **TARGET_SVC**               | `WANPPPConnection1` | TR-064 service to poll/heal (list with the snippet below)          |
| **CHECK_EVERY_SEC**          | `60`              | Seconds between polls                                                |
| **MAX_BAD_CYCLES**           | `5`               | Polls without IPv4 before a heal attempt                             |
| **DEFAULT_REBOOT_DELAY**     | `150`             | Seconds to wait after issuing a reboot                               |
| **TZ**                       | `Europe/Berlin`   | Time-zone for log timestamps                                         |
| **LOG_LEVEL**                | `INFO`            | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`                            |
| **LOG_DIR**                  | `/logs`           | Directory inside the container that is bind-mounted on the host      |
| **LOG_FILE**                 | `watchdog.log`    | Base filename (rotates)                                              |
| **LOG_ROTATE_WHEN**          | `midnight`        | Rotation unit (`S`, `M`, `H`, `D`, `midnight`, `W0`…`W6`)            |
| **LOG_ROTATE_INTERVAL**      | `1`               | How many units between rotations                                     |
| **LOG_BACKUP_COUNT**         | `30`              | How many rotated files to keep                                       |
| **LOG_STDOUT**               | `true`            | Also mirror logs to container stdout (`docker logs …`)               |
| **LOG_JSON**                 | `false`           | Emit JSON log lines instead of plain text                            |
| **LOG_ON_CYCLE**             | `60`              | Log on every Nth cycle (0=off)                                       |

**Example `.env.example`:**

```
# --- FRITZ!Box creds / host ---------------------------------
FRITZ_HOST=192.168.1.1
FRITZ_USER=svc-rebooter
FRITZ_PASSWORD=REPLACE_ME

# --- Behaviour ----------------------------------------------
TARGET_SVC=WANPPPConnection1
CHECK_EVERY_SEC=60
MAX_BAD_CYCLES=5
DEFAULT_REBOOT_DELAY=150

# --- Logging -------------------------------------------------
LOG_LEVEL=INFO
LOG_DIR=/logs
LOG_FILE=watchdog.log
LOG_ROTATE_WHEN=midnight
LOG_ROTATE_INTERVAL=1
LOG_BACKUP_COUNT=30
LOG_STDOUT=true
LOG_JSON=false
LOG_ON_CYCLE=60

# --- Timezone -----------------------------------------------
TZ=Europe/Berlin
```  

---  

## Create the `svc-rebooter` user (FRITZ!Box 7560) 👤  

1. **System ▸ FRITZ!Box-Benutzer** → *Benutzer hinzufügen*  
   * Benutzername `svc-rebooter`  
   * Strong password  
2. **Rights** → tick **“Zugang aus dem Heimnetz”** only.  
3. **Heimnetz ▸ Netzwerk ▸ Netzwerkeinstellungen**  
   * Enable **“Zugriff für Anwendungen zulassen”**  
   * Enable **“Statusinformationen über UPnP übertragen”**  
4. Save — TR-064 is now accessible for that user.  

---  

## Quick-start with Docker 🐳  

```bash
git clone https://github.com/didac-crst/fritzbox-ipv4-watchdog.git
cd fritzbox-ipv4-watchdog
cp .env.example .env        # fill in FRITZ_PASSWORD
mkdir logs                  # host directory for rotated logs
sh start_watchdog.sh         # wrapper → docker compose up -d
```

*Bind mount* `./logs/watchdog.log` rotates nightly; 30 files kept.  

---  

## Running bare-metal 🖥️  

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in creds
python fritzbox_ipv4_watchdog.py
```  

Ctrl-C stops it gracefully.  

---  

## List available TR-064 services 🔍  

```bash
python - <<'PY'
from fritzconnection import FritzConnection
fc = FritzConnection(user="svc-rebooter", password="…")
print([s for s in fc.services if s.startswith(("WANIP","WANPPP"))])
PY
```  

Choose the one whose `GetExternalIPAddress` matches the IPv4 in the UI and set it as `TARGET_SVC`.  

---  

## Known limitations ⚠️  

* TR-064 must be enabled (see steps above).  
* FRITZ!OS < 7.0 had TR-064 stalls — upgrade if you see frequent timeouts.  
* Escalation ladder: **2 reconnects → reboot**. Edit `healing_attempts` in the script to change that.  


---  

## Credits & Licence 📝  

Built with 🩵 after too many dawn reboots.  
Released under the MIT [Licence](LICENSE) — hack away, but don’t blame me if your ISP’s DHCP server goes rogue.