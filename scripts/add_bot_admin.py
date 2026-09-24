"""
scripts/add_bot_admin.py
Make BOT_TOKEN's bot an admin (post rights) of the FORWARD_CHAT_ID channel,
using the existing user session. Run with the bot STOPPED (they share
data/session).

Usage (from the repo root):
    python scripts/add_bot_admin.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telethon import TelegramClient, functions  # noqa: E402
from telethon.errors import ChatAdminRequiredError  # noqa: E402
from telethon.tl.types import Channel, ChatAdminRights  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("add_bot_admin")


async def main() -> int:
    from core.config import BOT_TOKEN, FORWARD_CHAT_ID, TG_API_HASH, TG_API_ID, TG_PHONE

    if not BOT_TOKEN:
        log.error("BOT_TOKEN missing in .env")
        return 1

    bot_id = int(BOT_TOKEN.split(":")[0])

    client = TelegramClient("data/session", TG_API_ID, TG_API_HASH)
    if TG_PHONE:
        await client.start(phone=TG_PHONE)
    else:
        await client.start()

    try:
        me = await client.get_me()
        log.info("Logged in as %s", me.first_name)

        entity = await client.get_entity(FORWARD_CHAT_ID)
        if not isinstance(entity, Channel) or not entity.megagroup and not entity.broadcast:
            log.error("Target is not a channel: %s", FORWARD_CHAT_ID)
            return 1

        log.info("Channel: %s (id %s)", getattr(entity, "title", ""), entity.id)

        bot = await client.get_entity(bot_id)
        bot_name = getattr(bot, "username", None) or f"bot@{bot_id}"
        log.info("Target bot: @%s", bot_name)

        await client(functions.channels.InviteToChannelRequest(entity, [bot]))
        log.info("Bot @%s invited to channel.", bot_name)

        await client(functions.channels.EditAdminRequest(
            entity,
            bot,
            ChatAdminRights(
                post_messages=True,
                edit_messages=True,
                delete_messages=True,
                invite_users=True,
            ),
            rank="poster",
        ))
        log.info("Bot @%s granted admin (post) rights.", bot_name)

        print("\n" + "=" * 46)
        print("DONE — @%s can now post to %s" % (bot_name, FORWARD_CHAT_ID))
        print("=" * 46)
        return 0
    except ChatAdminRequiredError:
        log.error(
            "Your account (%s) is not an admin of %s — promote it to admin first.",
            me.first_name if "me" in dir() else "?",
            FORWARD_CHAT_ID,
        )
        return 1
    finally:
        await client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))