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

# 1. getMe
me = api("getMe")
print("=== getMe ===")
print(f'username: @{me["result"]["username"]}  id: {me["result"]["id"]}')

# 2. getUpdates — find real chat IDs
print("\n=== getUpdates (last 20) ===")
upd = api("getUpdates", limit=20, timeout=3)
if upd.get("result"):
    for u in upd["result"]:
        for key in ["channel_post", "message", "my_chat_member"]:
            if key in u:
                chat = u[key].get("chat", {})
                print(f"  type={key}  chat_id={chat.get('id')}  title={chat.get('title')}  chat_type={chat.get('type')}")
else:
    print("  no updates found")

# 3. getChat
print("\n=== getChat(-1003959930384) ===")
gc = api("getChat", chat_id=-1003959930384)
print(json.dumps(gc, indent=2))

# 4. sendMessage
print("\n=== sendMessage(-1003959930384) ===")
sm = api("sendMessage", chat_id=-1003959930384, text="RSI Bot — Test ping")
print(json.dumps(sm, indent=2))
