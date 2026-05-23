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

# 1. Delete webhook if any (so getUpdates works)
api("deleteWebhook", drop_pending_updates=False)

# 2. getUpdates with offset=-1 to force fetching latest
print("=== getUpdates offset=-1 ===")
r = api("getUpdates", offset=-1, limit=1, timeout=0,
        allowed_updates=["message","channel_post","my_chat_member","chat_member"])
print(json.dumps(r, indent=2))

# 3. getUpdates with no offset, large limit
print("\n=== getUpdates no offset, limit=100 ===")
r2 = api("getUpdates", limit=100, timeout=0,
         allowed_updates=["message","channel_post","my_chat_member","chat_member"])
updates = r2.get("result", [])
print(f"Total updates: {len(updates)}")
for u in updates:
    for key in ["message","channel_post","my_chat_member","chat_member"]:
        if key in u:
            chat = u[key].get("chat", {})
            user = u[key].get("from", {})
            print(f"  [{key}] chat_id={chat.get('id')}  type={chat.get('type')}  "
                  f"title={chat.get('title') or chat.get('first_name')}  "
                  f"user=@{user.get('username','?')}")
if not updates:
    print("  No updates — bot has never received any message yet.")
    print("  -> Send /start to @capitexcrypto_bot then re-run this script.")
