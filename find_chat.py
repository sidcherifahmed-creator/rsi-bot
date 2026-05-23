"""
Try every possible interpretation of the channel ID from the web URL.
Also attempts to get the real chat_id via a forwarded message trick.
"""
import urllib.request, json, os
from dotenv import load_dotenv
load_dotenv()

token = os.getenv("TG_BOT_TOKEN")

def api(method, **params):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(params).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())

raw = 1003959930384  # digits from URL (without minus)

print("=== Trying all chat_id interpretations ===")
candidates = [
    ("url-as-is",          -1003959930384),
    ("-raw",               -1003959930384),
    ("-raw/10",            -100395993038),
    ("drop-leading-100",   -3959930384),
    ("pure-positive",       3959930384),
]

found_id = None
for label, cid in candidates:
    r = api("getChat", chat_id=cid)
    if r.get("ok"):
        ch = r["result"]
        print(f"  OK   [{label}]  id={ch['id']}  title={ch.get('title')}  type={ch['type']}")
        found_id = ch["id"]
    else:
        print(f"  FAIL [{label}]  id={cid}  -> {r.get('description')}")

if found_id:
    print(f"\n=== Sending message to {found_id} ===")
    sm = api("sendMessage", chat_id=found_id, text="RSI Bot — connected!")
    print(json.dumps(sm, indent=2))
else:
    print("\n=== No valid chat_id found ===")
    print("Action needed — ONE of these will fix it:")
    print()
    print("  Option A: If channel has a @username")
    print("    -> Edit .env: TG_CHAT_ID=@your_channel_username")
    print("    -> Re-run test_telegram.py")
    print()
    print("  Option B: Get real chat_id automatically")
    print("    1. Open Telegram -> search @capitexcrypto_bot -> send /start")
    print("    2. Re-run this script — your personal chat_id will appear in updates")
