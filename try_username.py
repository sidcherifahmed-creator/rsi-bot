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

usernames = [
    "@capitexgoldsignal",
    "@capitexgoldsignals",
    "@capitex_gold_signal",
    "@capitexgold",
    "@capitexcrypto",
    "@capitexcryptosignal",
    "@capitexcryptosignals",
]

found = None
for u in usernames:
    r = api("getChat", chat_id=u)
    if r.get("ok"):
        ch = r["result"]
        title = ch.get("title", "")
        cid = ch["id"]
        print(f"FOUND  {u}  ->  id={cid}  title={title}")
        found = cid
    else:
        print(f"FAIL   {u}  ->  {r.get('description')}")

if found:
    print(f"\nSending test message to {found} ...")
    sm = api("sendMessage", chat_id=found, text="RSI Bot -- Test OK")
    if sm.get("ok"):
        print(f"SUCCESS  message_id={sm['result']['message_id']}")
        print(f"\nUpdate .env: TG_CHAT_ID={found}")
    else:
        print("sendMessage failed:", sm.get("description"))
else:
    print("\nChannel not found via any username.")
    print("The channel is likely PRIVATE — share the invite link so we can get the real ID.")
