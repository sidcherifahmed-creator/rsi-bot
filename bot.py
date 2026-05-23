import os
import requests
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import schedule
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict

load_dotenv()

TWELVE_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

RISK_REWARD_TP1 = 2.0
RISK_REWARD_TP2 = 3.0
MIN_SIGNAL_GAP_MINUTES = 60
LOOKBACK = 100

# True = وضع الاختبار (يتجاوز Kill Zone والهيكل)
TEST_MODE = True

KILL_ZONES = [
    (7, 0, 10, 0),
    (13, 0, 16, 0),
]

last_signal_time = None

# الصفقة المفتوحة حالياً
active_trade = None
# active_trade = {
#   "direction": "BULLISH" | "BEARISH",
#   "entry": float,
#   "tp1": float, "tp2": float, "sl": float,
#   "tp1_hit": bool, "tp2_hit": bool
# }


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL_ID, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print("[Telegram] تم الإرسال")
    except Exception as e:
        print(f"[Telegram Error] {e}")


def monitor_active_trade():
    global active_trade
    if active_trade is None:
        return

    df = get_data(interval="15min", outputsize=5)
    if df is None:
        return

    price = df["close"].iloc[-1]
    d = active_trade
    direction = d["direction"]

    if direction == "BULLISH":
        # TP1
        if not d["tp1_hit"] and price >= d["tp1"]:
            d["tp1_hit"] = True
            pct = abs(d["tp1"] - d["entry"]) / d["entry"] * 100
            send_telegram(
                f"<b>🎯 TP1 تم!</b>\n"
                f"BTC/USD وصل ${price:,.2f}\n"
                f"ربح: +{pct:.2f}% | انقل SL لنقطة الدخول"
            )
        # TP2
        if not d["tp2_hit"] and price >= d["tp2"]:
            d["tp2_hit"] = True
            pct = abs(d["tp2"] - d["entry"]) / d["entry"] * 100
            send_telegram(
                f"<b>🏆 TP2 تم! صفقة مغلقة</b>\n"
                f"BTC/USD وصل ${price:,.2f}\n"
                f"ربح كامل: +{pct:.2f}%"
            )
            active_trade = None
        # SL
        elif price <= d["sl"]:
            pct = abs(d["sl"] - d["entry"]) / d["entry"] * 100
            send_telegram(
                f"<b>🛑 Stop Loss</b>\n"
                f"BTC/USD وصل ${price:,.2f}\n"
                f"خسارة: -{pct:.2f}% | انتظر الإشارة القادمة"
            )
            active_trade = None

    elif direction == "BEARISH":
        # TP1
        if not d["tp1_hit"] and price <= d["tp1"]:
            d["tp1_hit"] = True
            pct = abs(d["tp1"] - d["entry"]) / d["entry"] * 100
            send_telegram(
                f"<b>🎯 TP1 تم!</b>\n"
                f"BTC/USD وصل ${price:,.2f}\n"
                f"ربح: +{pct:.2f}% | انقل SL لنقطة الدخول"
            )
        # TP2
        if not d["tp2_hit"] and price <= d["tp2"]:
            d["tp2_hit"] = True
            pct = abs(d["tp2"] - d["entry"]) / d["entry"] * 100
            send_telegram(
                f"<b>🏆 TP2 تم! صفقة مغلقة</b>\n"
                f"BTC/USD وصل ${price:,.2f}\n"
                f"ربح كامل: +{pct:.2f}%"
            )
            active_trade = None
        # SL
        elif price >= d["sl"]:
            pct = abs(d["sl"] - d["entry"]) / d["entry"] * 100
            send_telegram(
                f"<b>🛑 Stop Loss</b>\n"
                f"BTC/USD وصل ${price:,.2f}\n"
                f"خسارة: -{pct:.2f}% | انتظر الإشارة القادمة"
            )
            active_trade = None


def get_data(interval="15min", outputsize=200) -> Optional[pd.DataFrame]:
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": "BTC/USD",
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_API_KEY,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
    except Exception as e:
        print(f"[API Error] {e}")
        return None

    if "values" not in data:
        print(f"[Data Error] {data}")
        return None

    df = pd.DataFrame(data["values"])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.iloc[::-1].reset_index(drop=True)
    return df


def in_kill_zone() -> bool:
    if TEST_MODE:
        return True
    now = datetime.now(timezone.utc)
    for h_start, m_start, h_end, m_end in KILL_ZONES:
        start = now.replace(hour=h_start, minute=m_start, second=0, microsecond=0)
        end = now.replace(hour=h_end, minute=m_end, second=0, microsecond=0)
        if start <= now <= end:
            return True
    return False


def detect_structure(df: pd.DataFrame) -> str:
    highs = df["high"].values
    lows = df["low"].values
    n = len(highs)
    if n < 20:
        return "NEUTRAL"

    pivot_highs = []
    pivot_lows = []
    for i in range(2, n - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            pivot_highs.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            pivot_lows.append(lows[i])

    if len(pivot_highs) >= 2 and len(pivot_lows) >= 2:
        hh = pivot_highs[-1] > pivot_highs[-2]
        hl = pivot_lows[-1] > pivot_lows[-2]
        ll = pivot_lows[-1] < pivot_lows[-2]
        lh = pivot_highs[-1] < pivot_highs[-2]
        if hh and hl:
            return "BULLISH"
        if ll and lh:
            return "BEARISH"

    return "NEUTRAL"


def detect_liquidity_sweep(df: pd.DataFrame, direction: str) -> bool:
    n = len(df)
    if n < 10:
        return False
    recent = df.iloc[-10:-1]
    if direction == "BULLISH":
        recent_low = recent["low"].min()
        last_low = df["low"].iloc[-1]
        last_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        return last_low < recent_low and last_close > prev_close
    elif direction == "BEARISH":
        recent_high = recent["high"].max()
        last_high = df["high"].iloc[-1]
        last_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        return last_high > recent_high and last_close < prev_close
    return False


def find_order_block(df: pd.DataFrame, direction: str) -> Optional[Dict]:
    n = len(df)
    if n < 5:
        return None
    for i in range(n - 2, max(n - 20, 1), -1):
        candle = df.iloc[i]
        body = abs(candle["close"] - candle["open"])
        avg_body = df["close"].iloc[max(0, i-10):i].sub(df["open"].iloc[max(0, i-10):i]).abs().mean()
        if direction == "BULLISH":
            if candle["close"] < candle["open"] and i+1 < n and df["close"].iloc[i+1] > candle["high"] and body > avg_body * 0.5:
                if df["close"].iloc[i+1:].min() > candle["low"] * 0.998:
                    return {"high": candle["high"], "low": candle["low"], "mid": (candle["high"] + candle["low"]) / 2}
        elif direction == "BEARISH":
            if candle["close"] > candle["open"] and i+1 < n and df["close"].iloc[i+1] < candle["low"] and body > avg_body * 0.5:
                if df["close"].iloc[i+1:].max() < candle["high"] * 1.002:
                    return {"high": candle["high"], "low": candle["low"], "mid": (candle["high"] + candle["low"]) / 2}
    return None


def find_fvg(df: pd.DataFrame, direction: str) -> Optional[Dict]:
    n = len(df)
    for i in range(n - 3, max(n - 15, 1), -1):
        c1 = df.iloc[i - 1]
        c3 = df.iloc[i + 1]
        if direction == "BULLISH":
            if c3["low"] > c1["high"]:
                if df["low"].iloc[i+1:].min() > c1["high"]:
                    return {"top": c3["low"], "bottom": c1["high"], "mid": (c3["low"] + c1["high"]) / 2}
        elif direction == "BEARISH":
            if c3["high"] < c1["low"]:
                if df["high"].iloc[i+1:].max() < c1["low"]:
                    return {"top": c1["low"], "bottom": c3["high"], "mid": (c1["low"] + c3["high"]) / 2}
    return None


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def detect_rsi_divergence(df: pd.DataFrame, direction: str, lookback: int = 14) -> bool:
    closes = df["close"].values
    rsi = calc_rsi(df["close"]).values
    n = len(closes)
    if n < lookback + 5:
        return False
    recent_closes = closes[-lookback:]
    recent_rsi = rsi[-lookback:]
    if direction == "BULLISH":
        price_lower = recent_closes[-1] < recent_closes[:-1].min()
        rsi_higher = recent_rsi[-1] > recent_rsi[np.argmin(recent_closes[:-1])]
        return price_lower and rsi_higher
    elif direction == "BEARISH":
        price_higher = recent_closes[-1] > recent_closes[:-1].max()
        rsi_lower = recent_rsi[-1] < recent_rsi[np.argmax(recent_closes[:-1])]
        return price_higher and rsi_lower
    return False


def get_5min_confirmation(direction: str) -> bool:
    if TEST_MODE:
        return True
    df5 = get_data(interval="5min", outputsize=20)
    if df5 is None or len(df5) < 4:
        return False
    last = df5.iloc[-1]
    prev = df5.iloc[-2]
    body_last = abs(last["close"] - last["open"])
    range_last = last["high"] - last["low"]
    if direction == "BULLISH":
        engulfing = (last["close"] > last["open"] and prev["close"] < prev["open"] and
                     last["close"] > prev["open"] and last["open"] < prev["close"])
        lower_wick = last["open"] - last["low"] if last["close"] > last["open"] else last["close"] - last["low"]
        pin_bar = lower_wick > body_last * 2 and range_last > 0
        return engulfing or pin_bar
    elif direction == "BEARISH":
        engulfing = (last["close"] < last["open"] and prev["close"] > prev["open"] and
                     last["close"] < prev["open"] and last["open"] > prev["close"])
        upper_wick = last["high"] - last["open"] if last["close"] < last["open"] else last["high"] - last["close"]
        pin_bar = upper_wick > body_last * 2 and range_last > 0
        return engulfing or pin_bar
    return False


def build_signal_message(direction: str, market_price: float, limit_price: float,
                          sl: float, tp1: float, tp2: float,
                          ob: Optional[Dict], fvg: Optional[Dict],
                          sweep: bool, rsi_div: bool) -> str:
    emoji_dir = "🟢" if direction == "BULLISH" else "🔴"
    signal_ar = "شراء" if direction == "BULLISH" else "بيع"
    rr1 = abs(tp1 - limit_price) / abs(limit_price - sl)
    rr2 = abs(tp2 - limit_price) / abs(limit_price - sl)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    limit_src = "Order Block" if ob else ("FVG" if fvg else "السعر")

    confluence = []
    if sweep:
        confluence.append("⚡ Liquidity Sweep")
    if ob:
        confluence.append("📦 Order Block")
    if fvg:
        confluence.append("🌀 Fair Value Gap")
    if rsi_div:
        confluence.append("📊 RSI Divergence")

    msg = (
        f"<b>⚡ Capitex BTC Signal</b>\n"
        f"<b>BTC/USD -- {signal_ar} {emoji_dir}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💹 <b>السعر الحالي:</b> ${market_price:,.2f}\n"
        f"📌 <b>Limit Order:</b> ${limit_price:,.2f}  <i>({limit_src})</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>TP1:</b> ${tp1:,.2f}  (RR {rr1:.1f})\n"
        f"🏆 <b>TP2:</b> ${tp2:,.2f}  (RR {rr2:.1f})\n"
        f"🛑 <b>SL:</b>  ${sl:,.2f}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>التقاطع:</b>\n"
        + "\n".join(f"  {c}" for c in confluence) + "\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {now}\n"
        f"<i>ضع Limit Order عند ${limit_price:,.2f}</i>"
    )
    return msg


def run():
    try:
        monitor_active_trade()
        _run_logic()
    except Exception as e:
        print(f"[CRASH] {e}")
        traceback.print_exc()


def _run_logic():
    global last_signal_time

    now_str = datetime.now().strftime("%H:%M:%S")
    mode = "[TEST]" if TEST_MODE else ""
    print(f"\n[{now_str}] {mode} فحص السوق...")

    if not in_kill_zone():
        print("خارج Kill Zone -- انتظار")
        return

    # لا صفقة جديدة أثناء صفقة مفتوحة
    if active_trade is not None:
        print("صفقة مفتوحة -- انتظار الإغلاق")
        return

    if last_signal_time:
        elapsed = (datetime.now() - last_signal_time).seconds / 60
        if elapsed < MIN_SIGNAL_GAP_MINUTES:
            print(f"آخر اشارة منذ {elapsed:.0f} دقيقة -- انتظار")
            return

    df = get_data(interval="15min", outputsize=LOOKBACK)
    if df is None or len(df) < 50:
        print("فشل جلب البيانات")
        return

    current_price = df["close"].iloc[-1]
    print(f"السعر: ${current_price:,.2f}")

    structure = detect_structure(df)
    print(f"الهيكل: {structure}")

    if structure == "NEUTRAL":
        if TEST_MODE:
            structure = "BULLISH"
            print("[TEST] السوق محايد -- نفرض BULLISH للاختبار")
        else:
            print("السوق محايد -- لا اشارة")
            return

    direction = structure

    sweep = detect_liquidity_sweep(df, direction)
    print(f"Sweep: {sweep}")

    ob = find_order_block(df, direction)
    print(f"OB: {ob is not None}")

    fvg = find_fvg(df, direction)
    print(f"FVG: {fvg is not None}")

    rsi_div = detect_rsi_divergence(df, direction)
    print(f"RSI Div: {rsi_div}")

    confluence_score = sum([sweep, ob is not None, fvg is not None, rsi_div])
    print(f"التقاطع: {confluence_score}/4")

    if not TEST_MODE:
        if confluence_score < 2:
            print("تقاطع ضعيف -- لا اشارة")
            return
        if not sweep and ob is None:
            print("لا Sweep ولا OB -- رفض")
            return

    confirmed = get_5min_confirmation(direction)
    print(f"تاكيد M5: {confirmed}")

    if not confirmed:
        print("لا تاكيد على M5 -- انتظار")
        return

    entry = current_price

    if direction == "BULLISH":
        sl_base = ob["low"] if ob else df["low"].iloc[-3:].min()
        sl = sl_base - (current_price * 0.0005)
        # Limit أفضل: عند OB أو FVG أو 0.1% تحت السعر
        if ob:
            limit_price = round(ob["mid"], 2)
        elif fvg:
            limit_price = round(fvg["mid"], 2)
        else:
            limit_price = round(current_price * 0.999, 2)
        # أعد حساب risk من Limit لا من السعر الحالي
        risk = limit_price - sl
        tp1 = limit_price + risk * RISK_REWARD_TP1
        tp2 = limit_price + risk * RISK_REWARD_TP2
    else:
        sl_base = ob["high"] if ob else df["high"].iloc[-3:].max()
        sl = sl_base + (current_price * 0.0005)
        if ob:
            limit_price = round(ob["mid"], 2)
        elif fvg:
            limit_price = round(fvg["mid"], 2)
        else:
            limit_price = round(current_price * 1.001, 2)
        risk = sl - limit_price
        tp1 = limit_price - risk * RISK_REWARD_TP1
        tp2 = limit_price - risk * RISK_REWARD_TP2

    if risk / entry < 0.0015 and not TEST_MODE:
        print(f"مخاطرة صغيرة جدا ({risk/entry*100:.3f}%) -- رفض")
        return
    print(f"المخاطرة: {risk/limit_price*100:.3f}%")

    msg = build_signal_message(direction, current_price, limit_price, sl, tp1, tp2, ob, fvg, sweep, rsi_div)
    send_telegram(msg)
    last_signal_time = datetime.now()

    # تسجيل الصفقة للمراقبة — نتابع من سعر الـ Limit
    active_trade = {
        "direction": direction,
        "entry": limit_price,
        "tp1": tp1, "tp2": tp2, "sl": sl,
        "tp1_hit": False, "tp2_hit": False,
    }

    print(f"--- الاشارة ---")
    print(f"الاتجاه : {direction}")
    print(f"الدخول  : ${entry:,.2f}")
    print(f"TP1     : ${tp1:,.2f}")
    print(f"TP2     : ${tp2:,.2f}")
    print(f"SL      : ${sl:,.2f}")
    print(f"---------------")


if __name__ == "__main__":
    print("Capitex SMC Bot -- النسخة 2.0")
    print("TEST_MODE:", TEST_MODE)
    print("-" * 40)

    run()

    schedule.every(15).minutes.do(run)

    while True:
        schedule.run_pending()
        time.sleep(30)
