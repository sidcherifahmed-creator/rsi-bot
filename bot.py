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
RSI_PERIOD = int(os.getenv("RSI_PERIOD", 14))
RSI_OB = float(os.getenv("RSI_OVERBOUGHT", 70))
RSI_OS = float(os.getenv("RSI_OVERSOLD", 30))
TIMEFRAME = os.getenv("TIMEFRAME", "15")  # 15 minutes
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))
SL_BUFFER = float(os.getenv("SL_BUFFER", 0.005))  # 0.5%

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "SOLUSDT", "OPUSDT", "ARBUSDT", "SUIUSDT",
    "AVAXUSDT", "DOTUSDT", "MATICUSDT", "LINKUSDT", "LTCUSDT",
    "UNIUSDT", "ATOMUSDT", "NEARUSDT", "APTUSDT", "FILUSDT",
    "INJUSDT", "STXUSDT", "RUNEUSDT", "SEIUSDT", "TIAUSDT",
    "WLDUSDT", "BLURUSDT", "PENDLEUSDT", "ORDIUSDT", "ACEUSDT",
]

BYBIT_BASE = "https://api.bybit.com"


def fetch_klines(symbol: str, limit: int = 100) -> pd.DataFrame:
    url = f"{BYBIT_BASE}/v5/market/kline"
    params = {"category": "linear", "symbol": symbol, "interval": TIMEFRAME, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    rows = r.json()["result"]["list"]
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "turnover"])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col])
    df = df.iloc[::-1].reset_index(drop=True)
    return df


def calc_rsi(df: pd.DataFrame, period: int) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calc_signal(df: pd.DataFrame, rsi: pd.Series) -> dict | None:
    # آخر شمعة مغلقة = [-2] (الأخيرة [-1] لم تغلق بعد)
    prev_rsi = rsi.iloc[-3]  # الشمعة قبل الأخيرة
    last_rsi = rsi.iloc[-2]  # آخر شمعة مغلقة
    last_close = df["close"].iloc[-2]

    # SHORT: RSI كان فوق 70 ثم أغلق تحته
    if prev_rsi >= RSI_OB and last_rsi < RSI_OB:
        # آخر ذيل قمة في آخر 10 شمعات
        recent = df.iloc[-12:-2]
        last_high_wick = recent["high"].max()

        sl = round(last_high_wick * (1 + SL_BUFFER), 6)
        sl_dist = sl - last_close
        tp1 = round(last_close - sl_dist, 6)
        tp2 = round(last_close - sl_dist * 2, 6)
        entry2 = round((last_close + last_high_wick) / 2, 6)

        return {
            "type": "SHORT",
            "symbol": "",
            "rsi": round(last_rsi, 2),
            "entry1": last_close,
            "entry2": entry2,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
        }

    # LONG: RSI كان تحت 30 ثم أغلق فوقه
    if prev_rsi <= RSI_OS and last_rsi > RSI_OS:
        # آخر ذيل قاع في آخر 10 شمعات
        recent = df.iloc[-12:-2]
        last_low_wick = recent["low"].min()

        sl = round(last_low_wick * (1 - SL_BUFFER), 6)
        sl_dist = last_close - sl
        tp1 = round(last_close + sl_dist, 6)
        tp2 = round(last_close + sl_dist * 2, 6)
        entry2 = round((last_close + last_low_wick) / 2, 6)

        return {
            "type": "LONG",
            "symbol": "",
            "rsi": round(last_rsi, 2),
            "entry1": last_close,
            "entry2": entry2,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
        }

    return None


async def send_tg(bot: Bot, text: str):
    try:
        await bot.send_message(chat_id=TG_CHAT_ID, text=text, parse_mode=ParseMode.HTML)
        log.info("TG sent: %s", text[:80])
    except Exception as e:
        log.error("TG error: %s", e)


async def run_loop():
    bot = Bot(token=TG_BOT_TOKEN)
    last_signals = {s: None for s in SYMBOLS}

    await send_tg(
        bot,
        f"<b>RSI Bot Started ✅</b>\n"
        f"Symbols: <code>{len(SYMBOLS)} pairs</code>\n"
        f"Timeframe: <code>15m</code>\n"
        f"RSI OS: {RSI_OS} | OB: {RSI_OB}\n"
        f"SL Buffer: {SL_BUFFER*100}%\n"
        f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]",
    )

    while True:
        for symbol in SYMBOLS:
            try:
                df = fetch_klines(symbol)
                rsi = calc_rsi(df, RSI_PERIOD)
                signal = calc_signal(df, rsi)

                log.info("%s RSI=%.2f", symbol, rsi.iloc[-2])

                if signal and last_signals[symbol] != signal["type"]:
                    last_signals[symbol] = signal["type"]
                    emoji = "🟢" if signal["type"] == "LONG" else "🔴"
                    await send_tg(
                        bot,
                        f"{emoji} <b>{signal['type']} SIGNAL — {symbol}</b>\n"
                        f"RSI: <code>{signal['rsi']}</code>\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"Entry1 (Market): <code>{signal['entry1']}</code>\n"
                        f"Entry2 (Limit):  <code>{signal['entry2']}</code>\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"TP1: <code>{signal['tp1']}</code>\n"
                        f"TP2: <code>{signal['tp2']}</code>\n"
                        f"SL:  <code>{signal['sl']}</code>\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"TF: 15m | [{datetime.utcnow().strftime('%H:%M')} UTC]",
                    )

                elif signal is None:
                    last_signals[symbol] = None

                await asyncio.sleep(0.5)

            except Exception as e:
                log.error("%s error: %s", symbol, e)

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run_loop())