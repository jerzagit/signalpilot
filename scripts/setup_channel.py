"""
scripts/setup_channel.py
Create the public SignalPilot channel (or verify an existing one), set its
@username, invite BOT_TOKEN's bot as admin, and post a welcome message.

Usage (run from the repo root):
    python scripts/setup_channel.py                 # create @SignalPilot
    python scripts/setup_channel.py --username ""   # keep it private
    python scripts/setup_channel.py --no-bot        # skip bot invitation

First run will ask for your Telegram login code (like the bot does).
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telethon import TelegramClient, functions  # noqa: E402
from telethon.errors import UserBotError  # noqa: E402
from telethon.tl.types import ChatAdminRights, InputChannelEmpty  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("setup_channel")


async def main() -> int:
    from core.config import BOT_TOKEN, CHANNEL_HEADER, TG_API_HASH, TG_API_ID, TG_PHONE
    from core.forwarder import send_message

    parser = argparse.ArgumentParser(description="Create / verify the SignalPilot channel.")
    parser.add_argument("--title", default=CHANNEL_HEADER, help="channel title")
    parser.add_argument(
        "--username",
        default="SignalPilot",
        help='public @username to claim ("" keeps the channel private)',
    )
    parser.add_argument(
        "--about",
        default="M15-focused signal feed. Educational only — not financial advice.",
    )
    parser.add_argument("--no-bot", action="store_true", help="do not invite bot as admin")
    parser.add_argument(
        "--channel-id",
        default="",
        help="reuse an existing channel (numeric -100… id) instead of creating one",
    )
    args = parser.parse_args()

    client = TelegramClient("data/session", TG_API_ID, TG_API_HASH)
    if TG_PHONE:
        await client.start(phone=TG_PHONE)
    else:
        await client.start()

    try:
        me = await client.get_me()
        log.info("Logged in as %s", me.first_name)

        if args.username:
            log.info("Checking if @%s is available...", args.username)
            available = await client(functions.channels.CheckUsernameRequest(InputChannelEmpty(), args.username))
            if available:
                log.info("@%s is available 🎉", args.username)
            else:
                log.warning(
                    "@%s is TAKEN — leaving channel private so it does not fail.",
                    args.username,
                )

        if args.channel_id:
            channel = await client.get_entity(int(args.channel_id))
            log.info("Reusing channel: %s (id %s)", getattr(channel, "title", ""), channel.id)
            target = f"@{args.username}" if args.username and available else f"-100{channel.id}"
        else:
            created = await client(functions.channels.CreateChannelRequest(
                title=args.title,
                about=args.about,
                broadcast=True,
                megagroup=False,
            ))
            channel = created.chats[0]
            log.info("Channel created: %s (id %s)", getattr(channel, "title", ""), channel.id)

            if args.username and available:
                await client(functions.channels.UpdateUsernameRequest(channel, args.username))
                log.info("Public username set: https://t.me/%s", args.username)

            target = f"@{args.username}" if args.username and available else f"-100{channel.id}"

        if args.no_bot:
            log.info("Skipping bot invitation (--no-bot).")
        elif not BOT_TOKEN:
            log.warning("BOT_TOKEN missing — add it to .env and run: python scripts/setup_channel.py again")
        else:
            bot_id = int(BOT_TOKEN.split(":")[0])
            bot = await client.get_entity(bot_id)
            bot_name = getattr(bot, "username", None) or f"bot@{bot_id}"
            try:
                await client(functions.channels.InviteToChannelRequest(channel, [bot]))
            except UserBotError:
                log.info("Bot can only join as admin — promoting directly.")
            await client(functions.channels.EditAdminRequest(
                channel,
                bot,
                ChatAdminRights(
                    post_messages=True,
                    edit_messages=True,
                    delete_messages=True,
                    invite_users=True,
                ),
                rank="poster",
            ))
            log.info("Bot @%s added as admin (post permission).", bot_name)

        welcome = (
            f"Welcome to {CHANNEL_HEADER} 🎯\n\n"
            f"Signals forwarded here were captured from configured provider channels, "
            f"parsed automatically, and republished in a clean format.\n\n"
            f"Educational content only — trade at your own risk."
        )
        ok = await asyncio.to_thread(send_message, welcome, chat_id=target)
        log.info("Welcome message posted to %s: %s", target, "OK" if ok else "FAILED")

        print("\n" + "=" * 46)
        print("NEXT STEPS")
        print("=" * 46)
        print(f"Channel target: {target}")
        print(f"Add to .env: FORWARD_CHAT_ID={target}")
        print("Run the bot:")
        print("    python bot.py")
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))