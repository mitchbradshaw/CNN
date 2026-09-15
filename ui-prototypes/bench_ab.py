"""Side-by-side load/lag/memory benchmark for prototypes A and B. Starts both servers, measures, stops them."""
import json, subprocess, time, urllib.request, statistics as st, os, sys
import psutil
from playwright.sync_api import sync_playwright

ROOT = "C:/Users/mmebr/Documents/CNN-ui-proto/ui-prototypes"
SERVERS = {
    "A": dict(cmd=[f"{ROOT}/A-react-fastapi/.venv/Scripts/python.exe", f"{ROOT}/A-react-fastapi/run_server.py", "--port", "8775"],
              url="http://127.0.0.1:8775", ready="/api/recordings", hsep="#/"),
    "B": dict(cmd=["C:/ProgramData/anaconda3/python.exe", f"{ROOT}/B-panel/run_app.py", "--port", "8776"],
              url="http://127.0.0.1:8776", ready="/", hsep="#"),
}
RUNS = 3
out = {}


def http_ok(u):
    try:
        return urllib.request.urlopen(u, timeout=2).status == 200
    except Exception:
        return False


def rss_tree(pid):
    try:
        p = psutil.Process(pid)
        return sum(x.memory_info().rss for x in [p] + p.children(recursive=True)) / 2**20
    except Exception:
        return None


def painted_corpus(name, page, s):
    if name == "A":
        return page.evaluate("""() => document.querySelectorAll('[data-testid="heatmap-cell"]').length >= 448""")
    try:
        d = json.load(urllib.request.urlopen(s["url"] + "/b/debug", timeout=2)).get("heatmap", {})
    except Exception:
        return False
    return d.get("rects", 0) == 912 and page.locator("canvas").count() > 0


def painted_signal(name, page):
    if name == "A":
        return page.evaluate("""() => { const o = document.querySelector('[data-testid="signal-overview"]'); return !!o && o.querySelectorAll('path').length > 0 }""")
    return page.get_by_text("back to corpus").count() > 0 and page.locator("canvas").count() >= 2


def timed(page, fn, timeout=60):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        if fn():
            return (time.perf_counter() - t0) * 1000
        page.wait_for_timeout(25)
    return None


procs = {}
try:
    for name, s in SERVERS.items():
        assert not http_ok(s["url"] + s["ready"]), f"port for {name} already in use"
        t0 = time.perf_counter()
        procs[name] = subprocess.Popen(s["cmd"], stdout=open(f"bench_{name}.log", "w"), stderr=subprocess.STDOUT,
                                       cwd=os.path.dirname(s["cmd"][1]))
        while not http_ok(s["url"] + s["ready"]):
            if procs[name].poll() is not None:
                sys.exit(f"{name} server exited")
            time.sleep(0.2)
        out[name] = {"server_start_s": round(time.perf_counter() - t0, 1)}

    time.sleep(3)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for name, s in SERVERS.items():
            r = out[name]
            r["rss_idle_mb"] = round(rss_tree(procs[name].pid) or -1)
            cold, warm, sig, nb, heap = [], [], [], [], []
            for i in range(RUNS):
                ctx = br.new_context(viewport={"width": 1440, "height": 900})
                page = ctx.new_page()
                cdp = ctx.new_cdp_session(page)
                cdp.send("Network.enable")
                tot = {"http": 0, "ws": 0}
                cdp.on("Network.loadingFinished", lambda e: tot.__setitem__("http", tot["http"] + e.get("encodedDataLength", 0)))
                cdp.on("Network.webSocketFrameReceived", lambda e: tot.__setitem__("ws", tot["ws"] + len(e["response"].get("payloadData", ""))))
                t0 = time.perf_counter()
                page.goto(f"{s['url']}/{s['hsep']}explore/corpus", wait_until="commit")
                ms = timed(page, lambda: painted_corpus(name, page, s))
                cold.append(ms)
                page.wait_for_timeout(1500)
                nb.append((tot["http"], tot["ws"]))
                # warm reload (browser cache primed)
                page.reload(wait_until="commit")
                warm.append(timed(page, lambda: painted_corpus(name, page, s)))
                page.wait_for_timeout(1000)
                # in-app navigation corpus -> signal (channel 4, 721 h)
                page.evaluate(f"() => {{ location.hash = '{s['hsep'][1:]}explore/signal/4' }}")
                sig.append(timed(page, lambda: painted_signal(name, page)))
                page.wait_for_timeout(2500)
                heap.append(page.evaluate("() => performance.memory ? performance.memory.usedJSHeapSize/1048576 : null"))
                ctx.close()
            r["rss_after_mb"] = round(rss_tree(procs[name].pid) or -1)
            med = lambda xs: round(st.median([x for x in xs if x is not None])) if any(x is not None for x in xs) else None
            r["corpus_cold_ms"] = [round(x) if x else None for x in cold]; r["corpus_cold_median_ms"] = med(cold)
            r["corpus_warm_ms"] = [round(x) if x else None for x in warm]; r["corpus_warm_median_ms"] = med(warm)
            r["corpus_to_signal_ms"] = [round(x) if x else None for x in sig]; r["corpus_to_signal_median_ms"] = med(sig)
            r["first_load_http_kb"] = round(nb[0][0] / 1024); r["first_load_ws_kb"] = round(nb[0][1] / 1024)
            r["js_heap_mb"] = round(st.median([h for h in heap if h]), 1)
        br.close()
finally:
    for name, p in procs.items():
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    time.sleep(1)
    out["ports_still_open"] = [n for n, s in SERVERS.items() if http_ok(s["url"] + s["ready"])]
    print(json.dumps(out, indent=1))
