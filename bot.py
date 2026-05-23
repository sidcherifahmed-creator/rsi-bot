import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd
from binance.client import Client
from binance.enums import *
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
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
BINANCE_BASE_URL = os.getenv("BINANCE_BASE_URL", "")
TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() == "true" or "testnet" in BINANCE_BASE_URL

SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
RSI_PERIOD = int(os.getenv("RSI_PERIOD", 14))
RSI_OB = float(os.getenv("RSI_OVERBOUGHT", 70))
RSI_OS = float(os.getenv("RSI_OVERSOLD", 30))
TIMEFRAME = os.getenv("TIMEFRAME", "1h")
LEVERAGE = int(os.getenv("LEVERAGE", 5))
TRADE_USDT = float(os.getenv("TRADE_USDT", 10))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))

BINANCE_TF_MAP = {
    "1m": Client.KLINE_INTERVAL_1MINUTE,
    "5m": Client.KLINE_INTERVAL_5MINUTE,
    "15m": Client.KLINE_INTERVAL_15MINUTE,
    "1h": Client.KLINE_INTERVAL_1HOUR,
    "4h": Client.KLINE_INTERVAL_4HOUR,
    "1d": Client.KLINE_INTERVAL_1DAY,
}


def get_binance_client() -> Client:
    client = Client(BINANCE_API_KEY, BINANCE_API_SECRET, testnet=TESTNET)
    futures_url = BINANCE_BASE_URL.rstrip("/") + "/fapi" if BINANCE_BASE_URL else "https://testnet.binancefuture.com/fapi"
    if TESTNET:
        client.FUTURES_URL = futures_url
    return client


def fetch_klines(client: Client, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
    klines = client.futures_klines(
        symbol=symbol,
        interval=BINANCE_TF_MAP.get(interval, Client.KLINE_INTERVAL_1HOUR),
        limit=limit,
    )
    df = pd.DataFrame(klines, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    df["close"] = pd.to_numeric(df["close"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df


def calc_rsi(df: pd.DataFrame, period: int) -> float:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


def get_position(client: Client, symbol: str) -> dict | None:
    positions = client.futures_position_information(symbol=symbol)
    for p in positions:
        if float(p["positionAmt"]) != 0:
            return p
    return None


def open_position(client: Client, symbol: str, side: str, usdt: float, leverage: int):
    client.futures_change_leverage(symbol=symbol, leverage=leverage)
    price = float(client.futures_mark_price(symbol=symbol)["markPrice"])
    qty_raw = (usdt * leverage) / price
    info = client.futures_exchange_info()
    step = next(
        float(f["stepSize"])
        for s in info["symbols"] if s["symbol"] == symbol
        for f in s["filters"] if f["filterType"] == "LOT_SIZE"
    )
    qty = round(qty_raw - (qty_raw % step), 8)
    order = client.futures_create_order(
        symbol=symbol,
        side=SIDE_BUY if side == "LONG" else SIDE_SELL,
        type=ORDER_TYPE_MARKET,
        quantity=qty,
    )
    return order, price, qty


def close_position(client: Client, symbol: str, position: dict):
    amt = float(position["positionAmt"])
    side = SIDE_SELL if amt > 0 else SIDE_BUY
    order = client.futures_create_order(
        symbol=symbol,
        side=side,
        type=ORDER_TYPE_MARKET,
        quantity=abs(amt),
        reduceOnly=True,
    )
    return order


async def send_tg(bot: Bot, text: str):
    try:
        await bot.send_message(chat_id=TG_CHAT_ID, text=text, parse_mode=ParseMode.HTML)
        log.info("TG sent: %s", text[:60])
    except Exception as e:
        log.error("TG error: %s", e)


async def run_loop():
    bot = Bot(token=TG_BOT_TOKEN)
    client = get_binance_client()

    mode = "Testnet" if TESTNET else "Production"
    await send_tg(
        bot,
        f"<b>RSI Bot Started</b>\n"
        f"Symbol: <code>{SYMBOL}</code>  TF: {TIMEFRAME}\n"
        f"RSI: {RSI_OS}/{RSI_OB}  Leverage: {LEVERAGE}x\n"
        f"Mode: {mode}  [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]",
    )

    last_signal = None

    while True:
        try:
            df = fetch_klines(client, SYMBOL, TIMEFRAME)
            rsi = calc_rsi(df, RSI_PERIOD)
            price = float(client.futures_mark_price(symbol=SYMBOL)["markPrice"])
            position = get_position(client, SYMBOL)
            log.info("RSI=%.2f  price=%.2f  pos=%s", rsi, price, bool(position))

            if rsi <= RSI_OS and last_signal != "LONG" and position is None:
                order, ep, qty = open_position(client, SYMBOL, "LONG", TRADE_USDT, LEVERAGE)
                last_signal = "LONG"
                await send_tg(
                    bot,
                    f"<b>LONG Opened</b>\n"
                    f"RSI: {rsi}  Price: <code>{ep:.2f}</code>\n"
                    f"Qty: {qty}  Lev: {LEVERAGE}x",
                )

            elif rsi >= RSI_OB and last_signal != "SHORT" and position is None:
                order, ep, qty = open_position(client, SYMBOL, "SHORT", TRADE_USDT, LEVERAGE)
                last_signal = "SHORT"
                await send_tg(
                    bot,
                    f"<b>SHORT Opened</b>\n"
                    f"RSI: {rsi}  Price: <code>{ep:.2f}</code>\n"
                    f"Qty: {qty}  Lev: {LEVERAGE}x",
                )

            elif position is not None:
                amt = float(position["positionAmt"])
                pnl = float(position["unRealizedProfit"])
                ep = float(position["entryPrice"])
                dir_ = "LONG" if amt > 0 else "SHORT"

                should_close = (dir_ == "LONG" and rsi >= RSI_OB) or \
                               (dir_ == "SHORT" and rsi <= RSI_OS)

                if should_close:
                    close_position(client, SYMBOL, position)
                    last_signal = None
                    await send_tg(
                        bot,
                        f"<b>{dir_} Closed</b>\n"
                        f"RSI: {rsi}  Entry: <code>{ep:.2f}</code>\n"
                        f"PnL: <code>{pnl:+.4f} USDT</code>",
                    )
                else:
                    log.info("Holding %s  PnL=%.4f", dir_, pnl)

        except Exception as e:
            log.error("Loop error: %s", e)
            await send_tg(bot, f"<b>Bot Error</b>\n<code>{e}</code>")

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run_loop())
