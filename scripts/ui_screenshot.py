"""Screenshot a FinRAG page once a selector exists, via Chrome DevTools (headless).

Chrome's own --screenshot fires before the page's search/answer fetches settle, and
--virtual-time-budget hangs on this page, so this waits for the answer to render instead.
Needs Google Chrome and the `websockets` package (installed with uvicorn[standard]).

    python scripts/ui_screenshot.py "http://localhost:8010/?q=..." out.png 1400 1250 ".answer__text, .answer__abstain"
"""
import asyncio, base64, json, subprocess, sys, time, urllib.request
import websockets

url, out, w, h, sel = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
proc = subprocess.Popen([CH, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=9333",
                         f"--window-size={w},{h}", "--user-data-dir=/tmp/finrag-chrome-shot", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json")); break
        except Exception:
            time.sleep(0.2)
    ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")

    async def main():
        async with websockets.connect(ws_url, max_size=50_000_000) as ws:
            n = 0
            async def call(method, **params):
                nonlocal n; n += 1; my = n
                await ws.send(json.dumps({"id": my, "method": method, "params": params}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == my:
                        return msg.get("result", {})
            await call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=w < 500)
            await call("Page.navigate", url=url)
            for _ in range(240):
                r = await call("Runtime.evaluate", expression=f"!!document.querySelector({json.dumps(sel)})", returnByValue=True)
                if r.get("result", {}).get("value"):
                    break
                await asyncio.sleep(0.5)
            else:
                print("selector never appeared:", sel)
            await asyncio.sleep(1.5)  # let entry animations settle
            shot = await call("Page.captureScreenshot", format="png", captureBeyondViewport=False)
            open(out, "wb").write(base64.b64decode(shot["data"]))
    asyncio.run(main())
finally:
    proc.terminate()
