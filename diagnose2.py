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

# 1. Check webhook — if set, getUpdates returns nothing
print("=== getWebhookInfo ===")
wh = api("getWebhookInfo")
print(json.dumps(wh.get("result", wh), indent=2))

# 2. Try different chat ID variants
print("\n=== getChat — all ID variants ===")
variants = {
    "as-given":        -1003959930384,
    "positive":         1003959930384,
    "minus-100-style": -100_3959930384,   # same as above
    "raw-channel-id":  -3959930384,
}
for label, cid in variants.items():
    r = api("getChat", chat_id=cid)
    status = "OK  " if r.get("ok") else "FAIL"
    desc = r["result"].get("title", "") if r.get("ok") else r.get("description", "")
    print(f"  [{status}]  {label:20s}  id={cid}  -> {desc}")

# 3. getUpdates with allowed_updates to catch channel posts
print("\n=== getUpdates (channel_post + my_chat_member) ===")
upd = api("getUpdates", limit=20, timeout=3,
          allowed_updates=["channel_post", "message", "my_chat_member", "chat_member"])
if upd.get("result"):
    for u in upd["result"]:
        for key in ["channel_post", "message", "my_chat_member", "chat_member"]:
            if key in u:
                chat = u[key].get("chat", {})
                print(f"  {key}: chat_id={chat.get('id')}  title={chat.get('title')}  type={chat.get('type')}")
else:
    print("  still no updates —", upd.get("description", "empty"))
