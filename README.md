# FRITZBOX IPv4 Watchdog  
  
> *“One more dawn, one more day, one more forced router reboot …”*  
  
I finally snapped at 05:46 one August morning.  
  
* • My bots stopped scraping Binance prices.*  
* • The Cloudflare tunnel went dark.*  
* • Telegram refused to send a single byte.*  
  
When I logged into the FRITZ!Box UI, the story was always the same:  
IPv6 happily showed a shiny /56, yet **WAN-IPv4 read `0.0.0.0`**.  
Every dual-stack service that still publishes **A-records only** was dead in the water.  
The cure? Manually click “Neu verbinden” or, on bad days, power-cycle the router.  
  
After the third pre-dawn crawl under my desk I wrote this watchdog.  
Now the box heals itself while I stay in bed.  
  
---

## What the script does 🩹  
  
1. Polls the router’s **TR-064** API every `CHECK_EVERY_SEC` seconds.  
2. As soon as `GetExternalIPAddress` returns `0.0.0.0` for `MAX_BAD_CYCLES` polls:  
   * First → forces a **PPP reconnect** (`ForceTermination`).  
   * If that fails twice in a row → performs a **full reboot**.  
3. Writes rotating logs to `/logs/watchdog.log` and (optionally) mirrors them to stdout, so `docker logs` works.  
  
The result: dual-stack outages shrink from *hours* to *≈30 seconds* and my bots never notice.  
  
---

## Repository layout 📂  
  
```
fritz-ipv4-watchdog/
├── .env                  # all tunables & secrets (never commit the real PW!)
├── fritz_ipv4_watchdog.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md             # ← you’re reading it
```  
  
---

## Configuration via `.env` 🔧  
  
| Variable          | Default             | Purpose                                          |
| ----------------- | ------------------- | ------------------------------------------------ |
| `FRITZ_HOST`      | `fritz.box`         | Router hostname / LAN-IP                         |
| `FRITZ_USER`      | `svc-rebooter`      | User with TR-064 rights                          |
| `FRITZ_PASSWORD`  | _(none)_            | **Required** – user’s password                   |
| `TARGET_SVC`      | `WANPPPConnection1` | TR-064 service to poll (check via `fc.services`) |
| `CHECK_EVERY_SEC` | `60`                | Polling interval (seconds)                       |
| `MAX_BAD_CYCLES`  | `10`                | Polls without IPv4 before healing                |
| `MODE`            | *unused*            | Escalation is automatic → reconnect, then reboot |
| `TZ`              | _(unset)_           | Time-zone for log timestamps                     |
| `LOG_*`           | see file            | Directory, rotation, level, JSON vs text, etc.   |
  
Example `.env` (verbose for the first week):  
  
```
FRITZ_HOST=fritz.box
FRITZ_USER=svc-rebooter
FRITZ_PASSWORD=SuperSecret123!
TARGET_SVC=WANPPPConnection1
CHECK_EVERY_SEC=60
MAX_BAD_CYCLES=10
LOG_LEVEL=DEBUG
LOG_EVERY_CYCLE=true
TZ=Europe/Berlin
```  
  
---

## Quick-start with Docker Compose 🐳  
  
```bash
git clone https://github.com/you/fritz-ipv4-watchdog.git
cd fritz-ipv4-watchdog
cp .env.example .env        # edit your real password
mkdir logs                  # bind-mounted log dir
docker compose up -d
docker compose logs -f watchdog
```  
  
*Bind mount* → `./logs/watchdog.log` on the host rotates nightly; keep the last 14 files.  
  
---

## Running bare-metal 🖥️  
  
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python fritz_ipv4_watchdog.py        # reads .env automatically
```  
  
Stop with **Ctrl-C** – the script exits gracefully.  
  
---

## Listing available TR-064 services 🔍  
  
If your WAN object is not `WANPPPConnection1` (e.g. a fallback LTE stick):  
  
```python
python - <<'PY'
from fritzconnection import FritzConnection
fc = FritzConnection(user="svc-rebooter", password="…")
print([s for s in fc.services if s.startswith(("WANIP","WANPPP"))])
PY
```  
  
Pick the entry whose `GetExternalIPAddress` matches the public IPv4 shown in the FRITZ!Box UI and put it into `TARGET_SVC`.  
  
---

## Known limitations ⚠️  
  
* Relies on **TR-064** being enabled (`Heimnetz ▸ Netzwerk ▸ Netzwerkeinstellungen ▸ Heimnetzfreigaben`).  
* FRITZ!OS below 7.0 sometimes stalls TR-064 replies; upgrade if polls throw repeated exceptions.  
* Escalation ladder is simple: 2 failed reconnects → reboot. Tweak the `healing_attempts` logic inside the script if you want a different policy.  
  
---

## Credits & Licence 📝  
  
Built with 🩵 after too many 5 a.m. reconnects.  
Released under the MIT Licence – do whatever you want, just don’t blame me if your ISP’s DHCP server goes completely rogue.