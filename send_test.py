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

targets = ["@capitexgoldsignal", "@capitexgold", -1003959930384]

for target in targets:
    gc = api("getChat", chat_id=target)
    if gc.get("ok"):
        cid = gc["result"]["id"]
        title = gc["result"].get("title", "")
        print(f"getChat OK   {target}  =>  id={cid}  title={title}")
        sm = api("sendMessage", chat_id=cid, text="RSI Bot - Test Message")
        if sm.get("ok"):
            mid = sm["result"]["message_id"]
            print(f"  sendMessage SUCCESS  message_id={mid}")
        else:
            print(f"  sendMessage FAIL  =>  {sm.get('description')}")
    else:
        print(f"getChat FAIL {target}  =>  {gc.get('description')}")
    print()
