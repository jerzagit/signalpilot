import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

from core.config import RECONNECT_ATTEMPTS, RECONNECT_BACKOFF_SECS  # noqa: E402
from core.listener import start_listener  # noqa: E402

Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

PID_FILE = Path("data/bot.pid")


def _pid_alive(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def acquire_lock() -> bool:
    PID_FILE.parent.mkdir(exist_ok=True)
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            if _pid_alive(old_pid):
                print(f"\nSignalPilot is already running (PID {old_pid}).")
                return False
            print(f"\nStale lock file found (PID {old_pid}), replacing.")
            PID_FILE.unlink()
        except Exception:
            try:
                PID_FILE.unlink()
            except Exception:
                pass
    try:
        fd = os.open(str(PID_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        print(f"\nSignalPilot lock exists ({PID_FILE}).")
        return False


def release_lock() -> None:
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception as exc:
        log.warning("Could not remove PID file: %s", exc)


async def main_async() -> int:
    log.info("SignalPilotV1 starting...")
    if not acquire_lock():
        return 1
    try:
        await start_listener()
        return 0
    finally:
        release_lock()


def _run():  # pragma: no cover - thin wiring
    attempt = 0
    while True:
        try:
            code = asyncio.run(main_async())
            log.info("SignalPilot stopped cleanly (code=%s).", code)
            return code
        except KeyboardInterrupt:
            log.info("SignalPilot stopped by user.")
            release_lock()
            return 0
        except Exception as exc:
            attempt += 1
            delay = min(RECONNECT_BACKOFF_SECS * (2 ** (attempt - 1)), 300)
            log.error(
                "SignalPilot crashed: %s — restarting in %ss (attempt %d/%d).",
                exc, delay, attempt, RECONNECT_ATTEMPTS,
            )
            release_lock()
            if attempt >= RECONNECT_ATTEMPTS:
                log.critical("Giving up after %d attempts.", attempt)
                return 1
            time.sleep(delay)


if __name__ == "__main__":
    sys.exit(_run())