import os
import asyncio
import logging
from datetime import datetime, timezone
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
TIMEFRAME = os.getenv("TIMEFRAME", "15m")  # OKX: 1m,3m,5m,15m,30m,1H,4H,1D
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))
SL_BUFFER = float(os.getenv("SL_BUFFER", 0.005))
REPORT_HOUR = int(os.getenv("REPORT_HOUR", 20))

# OKX يستخدم تنسيق BTC-USDT-SWAP للعقود الدائمة
SYMBOLS_RAW = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "SOLUSDT", "OPUSDT", "ARBUSDT", "SUIUSDT",
    "AVAXUSDT", "DOTUSDT", "POLUSDT", "LINKUSDT", "LTCUSDT",
    "UNIUSDT", "ATOMUSDT", "NEARUSDT", "APTUSDT", "FILUSDT",
    "INJUSDT", "STXUSDT", "RUNEUSDT", "SEIUSDT", "TIAUSDT",
    "WLDUSDT", "BLURUSDT", "PENDLEUSDT", "ORDIUSDT", "ACEUSDT",
]


def to_okx_symbol(s: str) -> str:
    # BTCUSDT → BTC-USDT-SWAP
    base = s.replace("USDT", "")
    return f"{base}-USDT-SWAP"


SYMBOLS = SYMBOLS_RAW  # نحتفظ بالأسماء الأصلية للعرض

OKX_BASE = "https://www.okx.com"

active_trades = {}

daily_stats = {
    "wins": [],
    "losses": [],
    "opened": [],
}

last_report_date = None


def fetch_klines(symbol: str, limit: int = 100) -> pd.DataFrame:
    okx_sym = to_okx_symbol(symbol)
    url = f"{OKX_BASE}/api/v5/market/candles"
    params = {"instId": okx_sym, "bar": TIMEFRAME, "limit": str(limit)}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    rows = data.get("data", [])
    if not rows:
        raise ValueError(f"No data for {symbol}")
    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "volume_ccy", "volume_quote", "confirm"
    ])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col])
    df = df.iloc[::-1].reset_index(drop=True)  # OKX يرسل الأحدث أولاً
    return df


def get_price(symbol: str) -> float:
    okx_sym = to_okx_symbol(symbol)
    url = f"{OKX_BASE}/api/v5/market/ticker"
    r = requests.get(url, params={"instId": okx_sym}, timeout=10)
    r.raise_for_status()
    data = r.json()["data"]
    if not data:
        raise ValueError(f"No price for {symbol}")
    return float(data[0]["last"])


def calc_rsi(df: pd.DataFrame, period: int) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calc_pct(entry, target, direction):
    if direction == "LONG":
        return round((target - entry) / entry * 100, 2)
    else:
        return round((entry - target) / entry * 100, 2)


def calc_signal(df: pd.DataFrame, rsi: pd.Series) -> dict | None:
    prev_rsi = rsi.iloc[-3]
    last_rsi = rsi.iloc[-2]
    last_close = df["close"].iloc[-2]

    if prev_rsi >= RSI_OB and last_rsi < RSI_OB:
        recent = df.iloc[-12:-2]
        last_high_wick = recent["high"].max()
        sl = round(last_high_wick * (1 + SL_BUFFER), 6)
        sl_dist = sl - last_close
        tp1 = round(last_close - sl_dist, 6)
        tp2 = round(last_close - sl_dist * 2, 6)
        entry2 = round((last_close + last_high_wick) / 2, 6)
        pct_tp1 = calc_pct(last_close, tp1, "SHORT")
        pct_tp2 = calc_pct(last_close, tp2, "SHORT")
        pct_sl = calc_pct(last_close, sl, "SHORT")
        return {"type": "SHORT", "entry1": last_close, "entry2": entry2,
                "sl": sl, "tp1": tp1, "tp2": tp2, "tp1_hit": False,
                "pct_tp1": pct_tp1, "pct_tp2": pct_tp2, "pct_sl": pct_sl}

    if prev_rsi <= RSI_OS and last_rsi > RSI_OS:
        recent = df.iloc[-12:-2]
        last_low_wick = recent["low"].min()
        sl = round(last_low_wick * (1 - SL_BUFFER), 6)
        sl_dist = last_close - sl
        tp1 = round(last_close + sl_dist, 6)
        tp2 = round(last_close + sl_dist * 2, 6)
        entry2 = round((last_close + last_low_wick) / 2, 6)
        pct_tp1 = calc_pct(last_close, tp1, "LONG")
        pct_tp2 = calc_pct(last_close, tp2, "LONG")
        pct_sl = calc_pct(last_close, sl, "LONG")
        return {"type": "LONG", "entry1": last_close, "entry2": entry2,
                "sl": sl, "tp1": tp1, "tp2": tp2, "tp1_hit": False,
                "pct_tp1": pct_tp1, "pct_tp2": pct_tp2, "pct_sl": pct_sl}

    return None


async def send_tg(bot: Bot, text: str):
    try:
        await bot.send_message(chat_id=TG_CHAT_ID, text=text, parse_mode=ParseMode.HTML)
        log.info("TG sent: %s", text[:80])
    except Exception as e:
        log.error("TG error: %s", e)


async def send_daily_report(bot: Bot):
    now = datetime.now(timezone.utc)
    wins = daily_stats["wins"]
    losses = daily_stats["losses"]
    opened = daily_stats["opened"]
    open_now = list(active_trades.keys())

    total = len(wins) + len(losses)
    win_rate = round(len(wins) / total * 100, 1) if total > 0 else 0

    wins_text = ""
    for w in wins:
        wins_text += f"  ✅ {w['symbol']} ({w['type']}) → TP2 <b>+{w['pct_tp2']}%</b>\n"
    if not wins_text:
        wins_text = "  —\n"

    losses_text = ""
    for l in losses:
        losses_text += f"  ❌ {l['symbol']} ({l['type']}) → SL <b>-{abs(l['pct_sl'])}%</b>\n"
    if not losses_text:
        losses_text = "  —\n"

    open_text = ""
    for s in open_now:
        t = active_trades[s]
        open_text += f"  🔄 {s} ({t['type']}) | TP1: {t['pct_tp1']}% | TP2: {t['pct_tp2']}% | SL: -{abs(t['pct_sl'])}%\n"
    if not open_text:
        open_text = "  —\n"

    report = (
        f"📊 <b>التقرير اليومي — Capitex RSI Bot</b>\n"
        f"📅 {now.strftime('%Y-%m-%d')}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📈 إجمالي الإشارات: <b>{len(opened)}</b>\n"
        f"✅ رابحة: <b>{len(wins)}</b> | ❌ خاسرة: <b>{len(losses)}</b>\n"
        f"🔄 مفتوحة الآن: <b>{len(open_now)}</b>\n"
        f"🎯 Win Rate: <b>{win_rate}%</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<b>الرابحة:</b>\n{wins_text}\n"
        f"<b>الخاسرة:</b>\n{losses_text}\n"
        f"<b>المفتوحة:</b>\n{open_text}"
        f"━━━━━━━━━━━━━━━\n"
        f"[{now.strftime('%H:%M')} UTC]"
    )

    await send_tg(bot, report)

    daily_stats["wins"].clear()
    daily_stats["losses"].clear()
    daily_stats["opened"].clear()


async def check_trade(bot: Bot, symbol: str, trade: dict, price: float):
    t = trade["type"]

    if t == "LONG":
        if not trade["tp1_hit"] and price >= trade["tp1"]:
            trade["tp1_hit"] = True
            await send_tg(bot,
                f"✅ <b>TP1 HIT — {symbol}</b>\n"
                f"Price: <code>{price}</code> | TP1: <code>{trade['tp1']}</code> (+{trade['pct_tp1']}%)\n"
                f"نقل SL للدخول ✅")

        elif trade["tp1_hit"] and price >= trade["tp2"]:
            await send_tg(bot,
                f"🎯 <b>TP2 HIT — {symbol}</b>\n"
                f"Price: <code>{price}</code> | TP2: <code>{trade['tp2']}</code> (+{trade['pct_tp2']}%)\n"
                f"إغلاق الصفقة كاملاً 🏆")
            daily_stats["wins"].append({**trade, "symbol": symbol})
            del active_trades[symbol]

        elif price <= trade["sl"]:
            await send_tg(bot,
                f"❌ <b>SL HIT — {symbol}</b>\n"
                f"Price: <code>{price}</code> | SL: <code>{trade['sl']}</code> (-{abs(trade['pct_sl'])}%)")
            daily_stats["losses"].append({**trade, "symbol": symbol})
            del active_trades[symbol]

    elif t == "SHORT":
        if not trade["tp1_hit"] and price <= trade["tp1"]:
            trade["tp1_hit"] = True
            await send_tg(bot,
                f"✅ <b>TP1 HIT — {symbol}</b>\n"
                f"Price: <code>{price}</code> | TP1: <code>{trade['tp1']}</code> (+{trade['pct_tp1']}%)\n"
                f"نقل SL للدخول ✅")

        elif trade["tp1_hit"] and price <= trade["tp2"]:
            await send_tg(bot,
                f"🎯 <b>TP2 HIT — {symbol}</b>\n"
                f"Price: <code>{price}</code> | TP2: <code>{trade['tp2']}</code> (+{trade['pct_tp2']}%)\n"
                f"إغلاق الصفقة كاملاً 🏆")
            daily_stats["wins"].append({**trade, "symbol": symbol})
            del active_trades[symbol]

        elif price >= trade["sl"]:
            await send_tg(bot,
                f"❌ <b>SL HIT — {symbol}</b>\n"
                f"Price: <code>{price}</code> | SL: <code>{trade['sl']}</code> (-{abs(trade['pct_sl'])}%)")
            daily_stats["losses"].append({**trade, "symbol": symbol})
            del active_trades[symbol]


async def run_loop():
    global last_report_date
    bot = Bot(token=TG_BOT_TOKEN)

    await send_tg(bot,
        f"<b>RSI Bot Started ✅</b>\n"
        f"Symbols: <code>{len(SYMBOLS)} pairs</code>\n"
        f"Timeframe: <code>{TIMEFRAME}</code>\n"
        f"RSI OS: {RSI_OS} | OB: {RSI_OB}\n"
        f"Data: OKX Public API\n"
        f"تقرير يومي: {REPORT_HOUR}:00 UTC\n"
        f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC]")

    while True:
        now = datetime.now(timezone.utc)

        if now.hour == REPORT_HOUR and now.date() != last_report_date:
            last_report_date = now.date()
            await send_daily_report(bot)

        for symbol in SYMBOLS:
            try:
                price = get_price(symbol)

                if symbol in active_trades:
                    await check_trade(bot, symbol, active_trades[symbol], price)
                    if symbol not in active_trades:
                        await asyncio.sleep(0.3)
                        continue

                if symbol not in active_trades:
                    df = fetch_klines(symbol)
                    rsi = calc_rsi(df, RSI_PERIOD)
                    signal = calc_signal(df, rsi)
                    log.info("%s RSI=%.2f price=%.4f", symbol, rsi.iloc[-2], price)

                    if signal:
                        active_trades[symbol] = signal
                        daily_stats["opened"].append((symbol, signal["type"]))
                        emoji = "🟢" if signal["type"] == "LONG" else "🔴"
                        await send_tg(bot,
                            f"{emoji} <b>{signal['type']} SIGNAL — {symbol}</b>\n"
                            f"RSI: <code>{round(rsi.iloc[-2], 2)}</code>\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"Entry1 (Market): <code>{signal['entry1']}</code>\n"
                            f"Entry2 (Limit):  <code>{signal['entry2']}</code>\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"TP1: <code>{signal['tp1']}</code> (+{signal['pct_tp1']}%)\n"
                            f"TP2: <code>{signal['tp2']}</code> (+{signal['pct_tp2']}%)\n"
                            f"SL:  <code>{signal['sl']}</code> (-{abs(signal['pct_sl'])}%)\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"TF: {TIMEFRAME} | [{now.strftime('%H:%M')} UTC]")

                await asyncio.sleep(0.5)

            except Exception as e:
                log.error("%s error: %s", symbol, e)

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run_loop())