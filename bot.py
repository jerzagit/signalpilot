import asyncio
import logging
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
from core.singleton import acquire as singleton_acquire  # noqa: E402
from core.singleton import release as singleton_release  # noqa: E402

Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

APP_NAME = "bot"


def acquire_lock() -> bool:
    if not singleton_acquire(APP_NAME):
        print("\nSignalPilot is already running. Only one bot instance allowed.")
        return False
    return True


def release_lock() -> None:
    singleton_release(APP_NAME)


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