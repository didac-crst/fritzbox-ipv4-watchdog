#!/usr/bin/env python3
"""
fritz_ipv4_watchdog.py
======================

Poll a FRITZ!Box via TR-064 every *N* seconds.
If the **public IPv4** reported by the chosen WAN service object becomes
`0.0.0.0` (or an empty string) for longer than a configurable grace period,
the script automatically heals the line by either

* **reconnecting** the PPP session (`ForceTermination`), **or**
* performing a **full reboot** (`DeviceConfig:Reboot`).

It also writes time-stamped logs with rotation and can mirror them to stdout
so `docker logs` works.

Environment variables (with sensible defaults)
----------------------------------------------
| Variable              | Default               | Purpose                              |
| --------------------- | --------------------- | ------------------------------------ |
| `FRITZ_HOST`          | `fritz.box`           | Router host or LAN IP                |
| `FRITZ_USER`          | `svc-rebooter`        | User with TR-064 rights              |
| `FRITZ_PASSWORD`      | _(none)_              | **Required** - the user’s password   |
| `TARGET_SVC`          | `WANPPPConnection1`   | TR-064 service to poll & heal        |
| `CHECK_EVERY_SEC`     | `60`                  | Polling interval in seconds          |
| `MAX_BAD_CYCLES`      | `5`                   | # polls without IPv4 before healing  |
| `DEFAULT_REBOOT_DELAY`| `150`                 | seconds to wait after reboot command |
| `TZ`                  | _unset_               | Time-zone for log timestamps         |
| `LOG_DIR`             | `/logs`               | Folder inside container / volume     |
| `LOG_FILE`            | `watchdog.log`        | Base filename (rotates)              |
| `LOG_LEVEL`           | `INFO`                | `DEBUG` \| `INFO` \| `WARNING`…      |
| `LOG_STDOUT`          | `true`                | Also mirror logs to stdout           |
| `LOG_JSON`            | `false`               | Emit JSON lines instead of text      |
| `LOG_ON_CYCLE`        | `60`                  | Log on every Nth cycle (0=off)       |
| `LOG_ROTATE_WHEN`     | `midnight`            | Rotation unit (`S`, `M`, `H`, `D`)   |
| `LOG_ROTATE_INTERVAL` | `1`                   | How many units between rotations     |
| `LOG_BACKUP_COUNT`    | `30`                  | Files to keep before pruning         |

All settings can be placed in a **`.env` file** in the working directory; the
script loads it automatically when run bare-metal *and* inside Docker.

---------------------------------------------------------------------------
"""

from __future__ import annotations

import logging
import os
import sys
import time
from logging.handlers import TimedRotatingFileHandler

from dotenv import load_dotenv
from fritzconnection import FritzConnection

# ───────────────────────── Load configuration ───────────────────────── #

load_dotenv(".env", override=False)  # read .env if present

BOX_HOST = os.getenv("FRITZ_HOST", "fritz.box")
USER = os.getenv("FRITZ_USER", "svc-rebooter")
PWD = os.getenv("FRITZ_PASSWORD")

SERVICE = os.getenv("TARGET_SVC", "WANPPPConnection1")  # ← check with fc.services

CHECK_EVERY = int(os.getenv("CHECK_EVERY_SEC", 60))  # seconds
MAX_BAD = int(os.getenv("MAX_BAD_CYCLES", 5))  # grace period (cycles)
DEFAULT_REBOOT_DELAY = int(os.getenv("DEFAULT_REBOOT_DELAY", "150"))  # seconds to wait after reboot command

# Logging
LOG_DIR = os.getenv("LOG_DIR", "/logs")
LOG_FILE = os.getenv("LOG_FILE", "watchdog.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_STDOUT = os.getenv("LOG_STDOUT", "true").lower() == "true"
LOG_JSON = os.getenv("LOG_JSON", "false").lower() == "true"
LOG_ON_CYCLE = int(os.getenv("LOG_ON_CYCLE", 60))

ROTATE_WHEN = os.getenv("LOG_ROTATE_WHEN", "midnight")  # TimedRotatingFileHandler arg
ROTATE_INTERVAL = int(os.getenv("LOG_ROTATE_INTERVAL", 1))
ROTATE_BACKUPS = int(os.getenv("LOG_BACKUP_COUNT", 30))  # how many files to keep

# Optional timezone override so timestamps match your locale
TZ = os.getenv("TZ")
if TZ:
    os.environ["TZ"] = TZ
    try:
        import time as _t

        _t.tzset()  # POSIX only - harmless on Windows
    except Exception:
        pass  # ignore if not supported


# ───────────────────────── Configure the logger ─────────────────────── #

logger = logging.getLogger("watchdog")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

text_fmt = "%(asctime)s %(levelname)s %(message)s"
formatter: logging.Formatter

if LOG_JSON:
    try:
        from pythonjsonlogger import jsonlogger

        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    except ImportError:
        # Fallback gracefully to plain text if library missing
        formatter = logging.Formatter(text_fmt)
        logger.warning("python-json-logger not installed - falling back to text")
else:
    formatter = logging.Formatter(text_fmt)

handlers: list[logging.Handler] = []

# File handler with rotation
os.makedirs(LOG_DIR, exist_ok=True)
file_path = os.path.join(LOG_DIR, LOG_FILE)
fh = TimedRotatingFileHandler(
    file_path,
    when=ROTATE_WHEN,
    interval=ROTATE_INTERVAL,
    backupCount=ROTATE_BACKUPS,
    utc=False,
)
fh.setFormatter(formatter)
fh.setLevel(logger.level)
handlers.append(fh)

# Optional stdout mirror so `docker logs` shows live output
if LOG_STDOUT:
    sh = logging.StreamHandler(stream=sys.stdout)
    sh.setFormatter(formatter)
    sh.setLevel(logger.level)
    handlers.append(sh)

for h in handlers:
    logger.addHandler(h)


# ───────────────────────── Core functionality ───────────────────────── #

def init_connection() -> FritzConnection:
    """
    Initialize the FritzConnection instance.

    This is useful if the connection was lost or needs to be re-established.
    """
    if not PWD:
        logger.critical("FRITZ_PASSWORD not set! Exiting.")
        sys.exit(1)
    logger.info(f"Initializing FritzConnection to {BOX_HOST} as user {USER}")
    while True:
        try:
            # Attempt to create a FritzConnection instance
            fc = FritzConnection(address=BOX_HOST, user=USER, password=PWD)
            return fc
        except Exception as e:
            logger.warning(f"Cannot reach FRITZ!Box ({e})")
            logger.info("Retrying in 30 seconds …")
            time.sleep(30)  # Wait before retrying

def external_ipv4(connection: FritzConnection) -> str:
    """Return the router’s *public* IPv4 reported by the given TR-064 service."""
    return connection.call_action(SERVICE, "GetExternalIPAddress")[
        "NewExternalIPAddress"
    ]


def heal(connection: FritzConnection, heal_by_reboot: bool = False) -> bool:
    """
    Take corrective action once the grace period has elapsed:

    * If `heal_by_reboot` is `True`, reboot the FRITZ!Box.
    * Otherwise, force a PPP reconnect by calling `ForceTermination` on the service.

    !!! Returns `True` if a re-initialization is needed after the action !!!

    If the reboot is successful, we need to re-initialize the connection.
    If we only force a PPP reconnect, we can continue using the existing connection.
    """
    need_to_reinitialize = False  # flag to re-initialize connection if needed
    if heal_by_reboot:
        logger.warning("Healing action: Rebooting FRITZ!Box …")
        try:
            connection.reboot()
            logger.info(f"Reboot command sent - waiting {DEFAULT_REBOOT_DELAY} seconds…")
            # Wait a bit to allow the reboot to start
            time.sleep(DEFAULT_REBOOT_DELAY)
            need_to_reinitialize = True  # we need to re-initialize after reboot
        except Exception as e:
            logger.error(f"Failed to reboot Router: {e}")
    else:
        logger.warning("Healing action: Forcing PPP reconnect …")
        try:
            connection.call_action(SERVICE, "ForceTermination")
        except Exception as e:
            logger.error(f"Failed to force PPP reconnection: {e}")
    return need_to_reinitialize

def increment_cycle_counter(counter: int, log_on_cycle: int) -> int:
    """
    Increment the cycle counter and reset it if it reaches the log_on_cycle threshold.

    This is used to control how often we log the current state.
    """
    if log_on_cycle > 0:
        counter = (counter + 1) % log_on_cycle
    return counter

def is_time_to_log(cycle_counter: int, log_on_cycle: int) -> bool:
    """
    Check if it's time to log based on the cycle counter and log_on_cycle setting.

    Returns True if we should log the current state.
    """
    # If log_on_cycle is 0 we don't log at all
    log_enabled = log_on_cycle > 0
    if not log_enabled:
        return False  # No logging requested
    else:
        # If cycle_counter is 0, it's time to log
        # Otherwise, this is a cycle where we don't log
        return cycle_counter == 0



def main() -> None:
    """Entry point - sets up the FritzConnection and runs the watchdog loop."""

    logger.info(
        f"Watchdog started • service={SERVICE} • poll={CHECK_EVERY}s • grace={CHECK_EVERY * MAX_BAD}s • log={file_path}",
    )
    # Initialize the FritzConnection
    fc = init_connection()

    bad = 0  # consecutive polls without IPv4
    healing_attempts = 0  # reconnect attempts before we escalate
    last_state_present: bool | None = None  # tri-state: None/True/False
    last_ip = ""  # last known IPv4 address
    cycle_counter = 0  # for logging every N cycles

    while True:
        try:
            ip = external_ipv4(fc)
        except Exception as e:
            logger.exception("TR-064 query failed") # Log the exception with traceback
            ip = ""
            healing_attempts = 0  # reset the escalation ladder to avoid hard reboot every grace period.
            # To be sure we re-initialize the connection if it was lost
            fc = init_connection()

        # Determine if the IPv4 is present
        present = ip not in ("0.0.0.0", "")

        # Check if the IP has changed since the last poll
        ip_change = (ip != last_ip)
        last_ip = ip  # update last known IP

        # Only log when state changes (or if verbose logging requested)
        if present != last_state_present:
            if present:
                logger.info("IPv4 present: %s", ip)
            else:
                logger.warning("IPv4 missing (0.0.0.0)")
            last_state_present = present
        elif ip_change:
            logger.info(f"IPv4 changed: {last_ip} → {ip}")

        if is_time_to_log(cycle_counter, LOG_ON_CYCLE) or (bad > 0) or (healing_attempts > 0):
            # Log every cycle if requested, or if we have bad cycles or healing attempts
            logger.info("Poll: ipv4=%s bad=%s/%s heal attempts=%s", ip or "0.0.0.0", bad, MAX_BAD, healing_attempts)

        # Update grace-period counter & heal if necessary
        if present:
            bad = 0
            healing_attempts = 0  # reset escalation ladder
        else:
            bad += 1
            if bad >= MAX_BAD:
                # First attempts to heal by reconnecting
                if healing_attempts <= 1:
                    heal_by_reboot = False
                    logger.warning(
                        "Grace period exceeded (%d/%d) - attempting to heal by reconnecting …",
                        bad,
                        MAX_BAD,
                    )
                # After 2 failed reconnects, try a full reboot
                else:
                    heal_by_reboot = True
                    logger.warning(
                        "Grace period exceeded (%d/%d) - attempting to heal by rebooting …",
                        bad,
                        MAX_BAD,
                    )
                # PERFORM THE HEALING ACTION !!!
                need_to_reinitialize = heal(fc, heal_by_reboot)
                if need_to_reinitialize:
                    logger.info("Re-initializing FritzConnection after healing action …")
                    fc = init_connection()  # re-initialize connection after reboot
                healing_attempts += 1
                bad = 0  # reset after healing attempt
                
        # Count cycles for logging on modular basis
        cycle_counter = increment_cycle_counter(cycle_counter, LOG_ON_CYCLE)
        time.sleep(CHECK_EVERY)  # wait before next poll


# ───────────────────────── Script bootstrap ─────────────────────────── #

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Watchdog interrupted by user - exiting.")
