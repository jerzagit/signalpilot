import asyncio
import os
import sys

from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")


async def main():
    client = TelegramClient("data/session", API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} ({me.phone})")
    print("--- dialogs matching 'geom' / 'v5' / 'pips' ---")
    async for dialog in client.iter_dialogs():
        name = dialog.name or ""
        low = name.lower()
        if any(k in low for k in ("geom", "v5", "pips", "fighter")):
            print(f"id={dialog.id}  title={name!r}")
    print("--- all dialogs ---")
    async for dialog in client.iter_dialogs():
        print(f"id={dialog.id}  title={(dialog.name or '')!r}")
    await client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
