"""Fetch recent updates to find the correct chat ID."""
import asyncio, os
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

async def main():
    bot = Bot(token=os.getenv("TG_BOT_TOKEN"))
    me = await bot.get_me()
    print(f"Bot: @{me.username}  (id={me.id})\n")

    updates = await bot.get_updates(limit=20, timeout=5)
    if not updates:
        print("No updates found.")
        print("Steps to fix:")
        print("  1. Open the channel in Telegram")
        print("  2. Add @" + me.username + " as Admin")
        print("  3. Send any message in the channel (or forward one)")
        print("  4. Run this script again")
        return

    seen = set()
    for u in updates:
        chat = None
        if u.channel_post:
            chat = u.channel_post.chat
        elif u.message:
            chat = u.message.chat
        if chat and chat.id not in seen:
            seen.add(chat.id)
            print(f"Chat found:")
            print(f"  id       = {chat.id}")
            print(f"  type     = {chat.type}")
            print(f"  title    = {getattr(chat, 'title', '-')}")
            print(f"  username = @{getattr(chat, 'username', '-')}")
            print()

asyncio.run(main())
