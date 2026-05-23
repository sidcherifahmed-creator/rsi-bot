"""Quick test: sends a single message to Telegram then exits."""
import asyncio
import os
from dotenv import load_dotenv
from telegram import Bot
from telegram.constants import ParseMode

load_dotenv()

TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = int(os.getenv("TG_CHAT_ID"))


async def main():
    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("ERROR: Set TG_BOT_TOKEN in .env first")
        return

    bot = Bot(token=TOKEN)
    me = await bot.get_me()
    print(f"Bot: @{me.username}")

    msg = await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "<b>RSI Bot — Test Message</b>\n"
            "Connection to Telegram: <code>OK</code>\n"
            "Chat ID: <code>{}</code>".format(CHAT_ID)
        ),
        parse_mode=ParseMode.HTML,
    )
    print(f"Message sent! message_id={msg.message_id}")


if __name__ == "__main__":
    asyncio.run(main())
