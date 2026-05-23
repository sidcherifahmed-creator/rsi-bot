import os
import asyncio
import logging
from datetime import datetime
import requests
import pandas as pd
from dotenv import load_dotenv
from telegram import Bot
from telegram.constants import ParseMode

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "8613977074:AAHgC5gZtmRuZugL8zF1mRiph4YZTWRxC8A")
TG_CHAT_ID = int(os.getenv("TG_CHAT_ID", "-1003959930384"))
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
RSI_PERIOD = int(os.getenv("RSI_PERIOD", 14))
RSI_OB = float(os.getenv("RSI_OVERBOUGHT", 70))
RSI_OS = float(os.getenv("RSI_OVERSOLD", 30))
TIMEFRAME = os.getenv("TIMEFRAME", "60")  # Bybit: 1,3,5,15,30,60,120,240,D
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))

BYBIT_BASE = "https://api.bybit.com"

TIMEFRAME_MAP = {
    "1m": "1", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "4h": "240", "1d": "D",
}


def fetch_klines(symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
    tf = TIMEFRAME_MAP.get(interval, interval)
    url = f"{BYBIT_BASE}/v5/market/kline"
    params = {"category": "linear", "symbol": symbol, "interval": tf, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    rows = data["result"]["list"]
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "turnover"])
    df["close"] = pd.to_numeric(df["close"])
    df = df.iloc[::-1].reset_index(drop=True)
    return df


def get_price(symbol: str) -> float:
    url = f"{BYBIT_BASE}/v5/market/tickers"
    r = requests.get(url, params={"category": "linear", "symbol": symbol}, timeout=10)
    r.raise_for_status()
    return float(r.json()["result"]["list"][0]["lastPrice"])


def calc_rsi(df: pd.DataFrame, period: int) -> float:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


async def send_tg(bot: Bot, text: str):
    try:
        await bot.send_message(chat_id=TG_CHAT_ID, text=text, parse_mode=ParseMode.HTML)
        log.info("TG sent: %s", text[:60])
    except Exception as e:
        log.error("TG error: %s", e)


async def run_loop():
    bot = Bot(token=TG_BOT_TOKEN)

    await send_tg(
        bot,
        f"<b>RSI Bot Started</b>\n"
        f"Symbol: <code>{SYMBOL}</code>  TF: {TIMEFRAME}\n"
        f"RSI OS: {RSI_OS} | OB: {RSI_OB}\n"
        f"Data: Bybit Public API\n"
        f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]",
    )

    last_signal = None

    while True:
        try:
            df = fetch_klines(SYMBOL, TIMEFRAME)
            rsi = calc_rsi(df, RSI_PERIOD)
            price = get_price(SYMBOL)
            log.info("RSI=%.2f  price=%.2f  last_signal=%s", rsi, price, last_signal)

            if rsi <= RSI_OS and last_signal != "LONG":
                last_signal = "LONG"
                await send_tg(
                    bot,
                    f"🟢 <b>LONG SIGNAL — {SYMBOL}</b>\n"
                    f"RSI: <code>{rsi}</code> (Oversold)\n"
                    f"Price: <code>{price:.2f}</code>\n"
                    f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]",
                )

            elif rsi >= RSI_OB and last_signal != "SHORT":
                last_signal = "SHORT"
                await send_tg(
                    bot,
                    f"🔴 <b>SHORT SIGNAL — {SYMBOL}</b>\n"
                    f"RSI: <code>{rsi}</code> (Overbought)\n"
                    f"Price: <code>{price:.2f}</code>\n"
                    f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]",
                )

            elif RSI_OS < rsi < RSI_OB:
                last_signal = None

        except Exception as e:
            log.error("Loop error: %s", e)
            await send_tg(bot, f"<b>Bot Error</b>\n<code>{e}</code>")

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run_loop())