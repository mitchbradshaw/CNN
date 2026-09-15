"""Smoke test + screenshot capture for prototype B (Panel 1.9.3 + Bokeh 3.9.2).

    "/c/ProgramData/anaconda3/python.exe" smoke.py [--url http://127.0.0.1:8766] [--no-run]

Mirrors A's smoke.py flow: corpus → select → open → zoom → send span → run → block page drag →
re-run shows `cached · 0 s` → history → invalid junction → failed block → running/cancel → ?throw=1.

Fails (non-zero exit) on:
  * any browser console error / page error / failed request (fonts excepted);
  * a Bokeh pane that did not paint — canvas ink sampling (distinct colours > 4, the calibrated
    threshold from tests/ui/browser.py), pierced through shadow DOM;
  * Python-side renderer counts read from GET /b/debug (heatmap rect count, row payload types, glyph rows);
  * unexpected tracebacks in runtime/<stamp>/server.log;
  * a broken Must flow.
Screenshots: screenshots/NN-<frame>.png; result: screenshots/smoke-result.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "screenshots")

DEEP = """
function deepAll(sel, root){ root = root || document; const out = [];
  const walk = (n) => { if (!n) return; if (n.querySelectorAll) out.push(...n.querySelectorAll(sel));
    const kids = n.querySelectorAll ? n.querySelectorAll('*') : []; for (const k of kids) if (k.shadowRoot) walk(k.shadowRoot); };
  walk(root); return out; }
"""
INK_ALL = "(() => {" + DEEP + """
  return deepAll('canvas').filter(c => c.width > 50 && c.height > 20).map(c => {
    const r = c.getBoundingClientRect(); let d;
    try { d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; } catch (e) { return {err: String(e)}; }
    const counts = {}; let n = 0;
    for (let i = 0; i < d.length; i += 4 * 17) { const k = (d[i] << 16) | (d[i+1] << 8) | d[i+2]; counts[k] = (counts[k]||0) + 1; n++; }
    return {x: r.x, y: r.y, w: r.width, h: r.height, distinct: Object.keys(counts).length};
  });
})()"""
BLANK = 4

# Bokeh view geometry: every plot's frame left/right in page pixels + its x_range id (critique r1: shared-axis drift)
PLOTS = """() => {
 const out=[]; const seen=new Set();
 const walk=(v)=>{ if(!v||seen.has(v))return; seen.add(v);
   if(v.frame && v.frame.bbox && v.el){ const r=v.el.getBoundingClientRect(); const b=v.frame.bbox;
     let xr=null; try{ xr=v.model.x_range.id; }catch(e){}
     out.push({y:r.y,h:r.height,fl:r.x+b.left,fr:r.x+b.right,xr}); }
   try{ for(const c of v.child_views) walk(c);}catch(e){}
   try{ for(const c of (v.children? v.children():[])) walk(c);}catch(e){} };
 const idx = Bokeh.index; const roots = idx && idx.roots ? idx.roots : Object.values(idx||{});
 for(const v of roots) walk(v);
 return out; }"""

# per chain row: the max canvas ink inside the row's band, plus HTML renders (model card, error cards) found there
ROW_PAINT = "(() => {" + DEEP + """
  const heads = deepAll('.row-left').map(e => ({id: e.getAttribute('data-testid'), top: e.getBoundingClientRect().top}))
                 .filter(h => h.id).sort((a, b) => a.top - b.top);
  const canv = deepAll('canvas').filter(c => c.width > 50 && c.height > 20).map(c => {
    const r = c.getBoundingClientRect(); let d; try { d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; } catch (e) { return null; }
    const counts = {}; for (let i = 0; i < d.length; i += 4 * 17) counts[(d[i] << 16) | (d[i+1] << 8) | d[i+2]] = 1;
    return {x: r.x, cy: r.y + r.height / 2, distinct: Object.keys(counts).length}; }).filter(Boolean);
  const html = (sel) => deepAll(sel).map(e => { const r = e.getBoundingClientRect(); return {x: r.x, cy: r.y + Math.min(r.height, 40) / 2}; });
  const kv = html('.kv'), errs = html('[data-testid="render-error"], [data-testid="payload-error"], [data-testid="error-card"]');
  return heads.map((h, k) => {
    const lo = h.top - 14, hi = k + 1 < heads.length ? heads[k + 1].top - 14 : h.top + 150;
    const inb = (o) => o.cy >= lo && o.cy < hi && o.x > 320;
    const ink = canv.filter(inb).reduce((m, c) => Math.max(m, c.distinct), 0);
    return {row: h.id, ink, model_card: kv.some(inb), error_card: errs.some(inb)};
  });
})()"""


class Smoke:
    def __init__(self, url, run_chain):
        self.url = url.rstrip("/")
        self.run_chain = run_chain
        self.errors, self.failures, self.shots, self.evidence, self.n = [], [], [], {}, 0
        self.allow_console = []

    # ------------------------------------------------------------ helpers --
    def debug(self):
        return json.load(urllib.request.urlopen(self.url + "/b/debug", timeout=10))

    def shot(self, page, name):
        self.n += 1
        path = os.path.join(SHOTS, f"{self.n:02d}-{name}.png")
        page.screenshot(path=path, full_page=False)
        self.shots.append(os.path.basename(path))
        return path

    def check(self, cond, msg):
        (self.failures.append(msg), print("  FAIL:", msg)) if not cond else print("  ok:", msg)

    def goto(self, page, h, settle=1500):
        page.goto(f"{self.url}/#{h}", wait_until="networkidle")
        page.wait_for_timeout(settle)

    def ink(self, page):
        return [c for c in page.evaluate(INK_ALL) if "err" not in c]

    def btn(self, page, name, exact=False):
        return page.get_by_role("button", name=name, exact=exact)

    def wait_for(self, fn, timeout_s=30, step_ms=250, page=None):
        t = time.time()
        while time.time() - t < timeout_s:
            try:
                if fn():
                    return True
            except Exception:
                pass
            page.wait_for_timeout(step_ms)
        return False

    # ------------------------------------------------------------ views --
    def corpus(self, page):
        print("[corpus]")
        self.goto(page, "explore/corpus", 2500)
        page.wait_for_selector("canvas", state="attached", timeout=20000)
        page.wait_for_timeout(800)
        d = self.debug().get("heatmap", {})
        self.evidence["heatmap"] = d
        self.check(d.get("rects", 0) == 16 * 57, f"heatmap renderer has {d.get('rects')} rects (16 × 57 = 912, Python-side)")
        self.check(d.get("distinct_colours", 0) >= 3, f"heatmap uses {d.get('distinct_colours')} distinct fills (quantile ramp, not one colour)")
        ink = self.ink(page)
        big = max(ink, key=lambda c: c["w"] * c["h"]) if ink else None
        self.evidence["heatmap_ink"] = big
        self.check(big is not None and big["distinct"] > BLANK, f"heatmap canvas painted ({big and big['distinct']} distinct colours)")
        self.check(page.locator('[data-testid="nav-rail"]').count() == 1 and page.locator('[data-testid="header"]').count() == 1, "rail + header present")
        self.shot(page, "explore-1-corpus")
        seg = page.locator(".seg")
        for label in ("detections", "disagree", "annotations", "both"):
            seg.get_by_role("button", name=label, exact=True).first.click()
            page.wait_for_timeout(500)
            if label == "disagree":
                self.shot(page, "explore-1-corpus-colour-by")
        self.check(self.debug()["heatmap"].get("colour_by") == "both", "colour-by toggle round-trips to the Python side")
        # tap CH2_A1 then CH4_A2 on the heatmap canvas
        box = big
        inner_top, inner_h = box["y"] + 4, box["h"] - 4 - 22
        for k, name in ((1, "CH2_A1"), (3, "CH4_A2")):
            page.mouse.click(box["x"] + box["w"] * 0.55, inner_top + (k + 0.5) * inner_h / 16)
            page.wait_for_timeout(700)
            sel = self.debug()["heatmap"].get("selected")
            self.check(sel == name, f"tapping row {k + 1} selects {name} (got {sel})")
        bar = page.locator('[data-testid="corpus-bottom-bar"]').inner_text()
        self.evidence["bottom_bar"] = bar
        self.check("annotations" in bar and "CH4_A2" in bar, f"bottom bar shows channel counts: {bar!r}")
        self.shot(page, "explore-1-corpus-selected")
        self.btn(page, re.compile(r"^Open CH4_A2")).first.click()
        page.wait_for_timeout(2500)
        self.check("explore/signal/4" in page.url, "Open CH4_A2 → navigates to the signal page")

    def signal(self, page):
        print("[signal]")
        if "explore/signal" not in page.url:
            self.goto(page, "explore/signal/4", 3000)
        page.wait_for_selector("canvas", state="attached", timeout=20000)
        page.wait_for_timeout(1500)
        ink = self.ink(page)
        self.evidence["signal_canvases"] = [(round(c["h"]), c["distinct"]) for c in ink]
        span = max(ink, key=lambda c: c["h"]) if ink else None
        self.check(span is not None and span["distinct"] > BLANK, f"span viewport painted ({span and span['distinct']} colours)")
        over = [c for c in ink if 80 <= c["h"] <= 100]
        self.check(bool(over) and over[0]["distinct"] > BLANK, "channel overview painted")
        self.shot(page, "explore-2-signal")
        # zoom latency over the full 721 h: fit, then 12 wheel steps
        self.btn(page, "fit", exact=True).first.click()
        page.wait_for_timeout(1200)
        n0 = len(page.evaluate("() => window.__zoomStats || []"))
        cx, cy = span["x"] + span["w"] * 0.5, span["y"] + span["h"] * 0.5
        page.mouse.move(cx, cy)
        for _ in range(12):
            page.mouse.wheel(0, -200)
            page.wait_for_timeout(180)
        page.wait_for_timeout(1000)
        stats = page.evaluate("() => window.__zoomStats || []")[n0:]
        srv = self.debug().get("zoom_stats", [])
        self.evidence["zoom_stats_browser"] = stats
        rts = [s["round_trip_ms"] for s in stats if s.get("round_trip_ms") is not None]
        if rts:
            srt = sorted(rts)
            self.evidence["zoom_round_trip_ms"] = {"n": len(rts), "min": round(srt[0], 1), "median": round(srt[len(srt) // 2], 1), "max": round(srt[-1], 1)}
            dm = sorted(s["decimate_ms"] for s in stats)
            self.evidence["zoom_decimate_ms"] = {"min": round(dm[0], 2), "median": round(dm[len(dm) // 2], 2), "max": round(dm[-1], 2)}
            self.evidence["zoom_span_h"] = [round(stats[0]["t1_h"] - stats[0]["t0_h"], 2), round(stats[-1]["t1_h"] - stats[-1]["t0_h"], 3)]
        self.check(len(stats) >= 6, f"per-viewport refetch recorded {len(stats)} fetches over a 12-step wheel sequence from the full channel")
        self.check(len(srv) >= len(stats), f"round trips synced back to Python (/b/debug zoom_stats has {len(srv)})")
        self.shot(page, "explore-2-signal-zoomed")
        # ---- critique r1: wheel zoom must stop at the 30 s minimum (it used to collapse to 0 h and paint blank) ----
        n1 = len(self.debug().get("zoom_stats", []))
        for _ in range(40):
            page.mouse.wheel(0, -300)
            page.wait_for_timeout(50)
        page.wait_for_timeout(1500)
        z = self.debug().get("zoom_stats", [])[n1:]
        widths = [(s["t1_h"] - s["t0_h"]) * 3600 for s in z]
        ink2 = self.ink(page)
        span2 = max(ink2, key=lambda c: c["h"]) if ink2 else None
        self.evidence["min_span"] = {"fetches": len(z), "min_width_s": round(min(widths), 3) if widths else None,
                                     "ink": span2 and span2["distinct"], "send_span_disabled": self.btn(page, re.compile("^Send span to Analyse")).first.is_disabled()}
        self.check(bool(widths) and min(widths) >= 29.99, f"40 more wheel steps: the viewport never went below 30 s (min {self.evidence['min_span']['min_width_s']} s)")
        self.check(span2 is not None and span2["distinct"] > BLANK, f"span viewport still painted at the minimum span ({span2 and span2['distinct']} colours)")
        self.shot(page, "explore-2-signal-min-span")
        self.btn(page, "fit", exact=True).first.click()      # back to the same 12-step view as before (the cancel test doubles it to ~22 h)
        page.wait_for_timeout(1200)
        page.mouse.move(cx, cy)
        for _ in range(12):
            page.mouse.wheel(0, -200)
            page.wait_for_timeout(180)
        page.wait_for_timeout(1200)
        self.btn(page, "›", exact=True).first.click()
        page.wait_for_timeout(1500)
        self.check(page.locator('[data-testid="signal-motif"]').count() == 1, "motif tier shows the selected motif")
        self.shot(page, "explore-2-signal-motif")
        # widen to ~12 h for the later running/cancel test is done in analyse(); send the current span now
        self.btn(page, re.compile("^Send span to Analyse")).first.click()
        page.wait_for_timeout(2500)
        self.check("analyse/chain" in page.url, "Send span to Analyse → navigates to the chain page")
        ev = [e for e in self.debug().get("events", []) if e["msg"] == "send_span"]
        self.evidence["sent_source"] = ev[-1]["source"] if ev else None
        self.check(bool(ev), "the sent span became ctx.source")

    def m4(self, page):
        print("[held-out]")
        self.goto(page, "explore/signal/52", 2000)
        self.check(page.locator('[data-testid="locked-card"]').count() == 1, "M4 channel shows the locked held-out card")
        self.check(self.debug().get("signal", {}).get("channel_id") != 52, "no signal was loaded for the M4 channel")
        self.shot(page, "explore-m4-held-out")

    def wait_job(self, page, before_id, timeout_s=90):
        ok = self.wait_for(lambda: (lambda r: r.get("job") not in (None, before_id) and r.get("job_status") in ("completed", "failed", "cancelled"))(self.debug().get("rows", {})),
                           timeout_s=timeout_s, page=page)
        return self.debug().get("rows", {})

    def badges(self, page):
        return [page.locator(f'[data-testid="row-badge-{i}"]').first.inner_text().strip() for i in range(1, 4)
                if page.locator(f'[data-testid="row-badge-{i}"]').count()]

    def analyse(self, page):
        print("[analyse]")
        self.goto(page, "analyse/chain", 2500)
        page.wait_for_selector('[data-testid="chain-row-0"]', timeout=20000)
        rows = page.locator('[data-testid^="chain-row-"][class="row-left"]').count() or page.locator('.row-left').count()
        self.check(rows >= 4, f"{rows} chain rows (source + 3 steps)")
        self.shot(page, "chain-1-chain-before-run")
        page.locator(".t-insert-1 button").first.click()
        page.wait_for_timeout(1800)
        self.check(page.locator('[data-testid="insert-modal"]').count() == 1, "insert-stage modal opens")
        cards = page.locator(".card-btn button").count()
        disabled = page.locator(".card-btn button[disabled]").count()
        fit = page.locator('[data-testid="modal-fit-count"]').inner_text()
        self.evidence["modal"] = {"cards": cards, "disabled": disabled, "fit": fit}
        self.check(cards >= 20, f"modal lists {cards} adapters")
        self.check(disabled >= 10, f"{disabled} incompatible adapters disabled with reasons ({fit})")
        self.shot(page, "chain-2-insert-stage")
        self.btn(page, "Cancel", exact=True).last.click()
        page.wait_for_timeout(800)
        if not self.run_chain:
            return
        before = self.debug().get("rows", {}).get("job")
        t = time.time()
        page.locator(".t-run button").first.click()
        r = self.wait_job(page, before, 120)
        self.wait_for(lambda: "last run" in page.locator('[data-testid="footer-terminal"]').inner_text(), 20, page=page)
        self.evidence["run_round_trip_s"] = round(time.time() - t, 2)
        page.wait_for_timeout(1200)
        self.evidence["run_rows_debug"] = r.get("rows")
        self.evidence["first_run_timings"] = r.get("step_timings")
        b = self.badges(page)
        self.evidence["badges_after_run"] = b
        st0 = r.get("step_timings") or {}
        honest = len(b) == 3 and all((("cached" in x) == (st0.get(str(i)) == 0.0)) and ("cached" in x or "computed" in x) for i, x in enumerate(b))
        self.check(honest, f"all rows completed and badged honestly (cached only when the core timing is 0.0): {b} · timings {st0}")
        types = [x.get("type") for x in (r.get("rows") or [])]
        self.check(types[:4] == ["signal", "signal", "scores", "spanset"], f"renderer seam drew {types}")
        ink = self.ink(page)
        # Bokeh 3.9 stacks several canvas layers per figure (the upper ones stay transparent): group by position, keep the max
        layers = {}
        for c in ink:
            if 90 <= c["h"] <= 110:
                k = (round(c["x"]), round(c["y"]))
                layers[k] = max(layers.get(k, 0), c["distinct"])
        painted = [layers[k] for k in sorted(layers, key=lambda k: k[1])]
        self.evidence["row_canvas_ink"] = painted
        self.check(len(painted) >= 4 and all(p > BLANK for p in painted), f"every result row canvas painted: {painted}")
        self.shot(page, "chain-1-chain-completed")
        # ---- block page: drag the threshold ----
        page.locator(".t-settings-step-3 button").first.click()
        page.wait_for_timeout(2500)
        self.check(page.locator('[data-testid="block-footer"]').count() == 1, "threshold block page opens")
        dbg = self.debug()
        self.check(dbg.get("block", {}).get("has_handle"), "draggable threshold handle present (PointDrawTool source)")
        self.shot(page, "chain-7b-block-threshold")
        g = dbg.get("block_geometry") or {}
        ink = self.ink(page)
        fig = next((c for c in ink if 270 <= c["h"] <= 290), None)
        thr0 = dbg.get("block", {}).get("threshold")
        if fig and g.get("inner_width") and g.get("inner_height"):
            left = fig["x"] + fig["w"] - g["border_right"] - g["inner_width"]
            top = fig["y"] + g["border_top"]
            hx = left + (g["handle_x"] - g["x_start"]) / (g["x_end"] - g["x_start"]) * g["inner_width"]
            hy = top + (g["y_end"] - g["handle_y"]) / (g["y_end"] - g["y_start"]) * g["inner_height"]
            page.mouse.move(hx, hy)
            page.mouse.down()
            page.mouse.move(hx, hy + 45, steps=10)
            page.mouse.up()
            page.wait_for_timeout(1500)
        b = self.debug().get("block", {})
        self.evidence["threshold_drag"] = {"before": thr0, "after": b.get("threshold"), "stale_from": b.get("stale_from"), "geometry": g}
        self.check(b.get("threshold") is not None and thr0 is not None and b["threshold"] < thr0, f"dragging the cut wrote params.threshold {thr0} → {b.get('threshold')}")
        self.check(b.get("stale_from") == 2 and "stale" in (b.get("statuses") or [""] * 3)[2], f"block 03 marked stale: {b.get('statuses')}")
        un = page.locator('[data-testid="unapplied"]').inner_text()
        self.check("Unapplied changes · 1" in un, f"footer says {un!r}")
        self.shot(page, "chain-7b-block-threshold-dragged")
        before = b.get("job")
        page.locator(".t-rerun2 button").first.click()
        self.wait_for(lambda: (lambda x: x.get("job") != before and x.get("job_status") == "completed")(self.debug().get("block", {})), 60, page=page)
        page.wait_for_timeout(1500)
        b = self.debug().get("block", {})
        self.evidence["suffix_rerun_timings"] = b.get("step_timings")
        st = b.get("step_timings") or {}
        self.check(st.get("0") == 0.0 and st.get("1") == 0.0, f"suffix re-run from the block page hit the prefix cache: step_timings {st}")
        self.check("block/2" in page.url, "Re-run stayed on the block page")
        self.goto(page, "analyse/chain", 2500)
        b = self.badges(page)
        self.evidence["badges_after_rerun"] = b
        self.check(len(b) == 3 and "cached · 0 s" in b[0] and "cached · 0 s" in b[1], f"prefix rows read 'cached · 0 s': {b}")
        self.shot(page, "chain-1-chain-suffix-rerun")
        # ---- export run (Could) ----
        self.btn(page, re.compile("Export run")).first.click()
        page.wait_for_timeout(1200)
        ex = self.debug().get("last_export") or {}
        self.evidence["export"] = dict(ex, bytes=os.path.getsize(ex["path"]) if ex.get("path") and os.path.isfile(ex["path"]) else None)
        self.check(bool(ex.get("path")) and os.path.isfile(ex["path"]) and "runtime" in ex["path"], f"Export run wrote {ex.get('path')}")
        # ---- history ----
        page.locator(".t-history button").first.click()
        page.wait_for_timeout(1500)
        self.check(page.locator('[data-testid="history-popover"]').count() == 1, "history popover opens")
        self.shot(page, "chain-1b-run-history")
        self.btn(page, "close", exact=True).first.click()
        page.wait_for_timeout(600)
        # ---- invalid junction ----
        page.locator(".t-delete-step-2 button").first.click()
        page.wait_for_timeout(1800)
        self.check(page.locator('[data-testid="junction-error"]').count() >= 1, "deleting the Scores producer shows the red junction")
        r = self.debug().get("rows", {})
        self.check(r.get("run_disabled") and r.get("junctions_invalid") == 1, f"Run disabled with 1 invalid junction ({r.get('run_label')})")
        self.shot(page, "chain-1e-invalid-junction")
        self.btn(page, "Undo", exact=True).first.click()
        page.wait_for_timeout(1500)
        self.check(page.locator('[data-testid="junction-error"]').count() == 0, "Undo restores the valid chain")
        # ---- failed block ----
        page.locator(".t-settings-step-2 button").first.click()
        page.wait_for_timeout(2500)
        inp = page.locator(".t-param-window_min input")
        inp.first.fill("500")
        inp.first.press("Enter")
        page.wait_for_timeout(1000)
        self.goto(page, "analyse/chain", 2500)
        before = self.debug().get("rows", {}).get("job")
        page.locator(".t-run button").first.click()
        self.wait_job(page, before, 60)
        page.wait_for_timeout(1500)
        self.check(page.locator('[data-testid="error-card"]').count() >= 1, "failed block shows an error card in place of the plot")
        hdr = page.locator('[data-testid="header"]').inner_text()
        self.evidence["failed_header"] = hdr
        self.check("1 need you" in hdr, f"header counts the failed job: {hdr!r}")
        self.evidence["failed_rows"] = self.debug().get("rows", {}).get("rows")
        self.shot(page, "chain-1f-failed-block")
        page.locator(".t-settings-step-2 button").first.click()
        page.wait_for_timeout(2500)
        inp = page.locator(".t-param-window_min input")
        inp.first.fill("1")
        inp.first.press("Enter")
        page.wait_for_timeout(800)
        # ---- running + cancel: widen the source to ~12 h through Explore ----
        self.goto(page, "explore/signal/4", 3000)
        for _ in range(8):
            z = self.debug().get("zoom_stats", [])
            w = (z[-1]["t1_h"] - z[-1]["t0_h"]) if z else 0
            if 18 <= w <= 22.3:        # MP's local ceiling is 80,527 samples = 22.37 h at 1 Hz
                break
            self.btn(page, "−" if w < 18 else "+", exact=True).first.click()
            page.wait_for_timeout(900)
        self.evidence["cancel_span_h"] = round(w, 2)
        self.btn(page, re.compile("^Send span to Analyse")).first.click()
        page.wait_for_timeout(3000)
        before = self.debug().get("rows", {}).get("job")
        page.locator(".t-run button").first.click()
        page.wait_for_timeout(450)
        r = self.debug().get("rows", {})
        self.evidence["running_rows"] = [(x.get("index"), x.get("status")) for x in r.get("rows", [])]
        page.locator(".t-run button").first.click()   # now ■ Cancel — clicked while 02 Matrix profile is still computing
        self.evidence["cancel_clicked_label"] = r.get("run_label")
        self.shot(page, "chain-1d-running")
        self.check(any(x.get("status") in ("running", "waiting") for x in r.get("rows", [])), "running / waiting row states visible")
        r = self.wait_job(page, before, 90)
        page.wait_for_timeout(1500)
        self.evidence["cancel_result"] = {"status": r.get("job_status"), "rows": [(x.get("index"), x.get("status")) for x in r.get("rows", [])]}
        self.check(r.get("job_status") == "cancelled", f"cancel accepted → job {r.get('job_status')} (cooperative: checked before the next step)")
        self.shot(page, "chain-cancelled")

    # ------------------------------------------------------------ critique round 1 --
    def run_and_wait(self, page, timeout_s=120):
        before = self.debug().get("rows", {}).get("job")
        page.locator(".t-run button").first.click()
        r = self.wait_job(page, before, timeout_s)
        page.wait_for_timeout(2200)
        return self.debug().get("rows", {})

    def import_template(self, page, key):
        page.locator(".t-history").first.wait_for(state="attached")
        self.btn(page, "Import", exact=True).first.click()
        page.wait_for_timeout(1200)
        page.locator(f".t-import-{key} button").first.click()
        page.wait_for_timeout(1800)

    def templates(self, page):
        """Every built-in template on a ≤5000-sample span: each row type paints, zero page errors (gramian blanked the page)."""
        print("[templates]")
        want = {"mp_threshold": ["signal", "signal", "scores", "spanset"], "dsax": ["signal", "signal", "encoding"],
                "windows_model": ["signal", "windowset", "grouping", "model"], "gramian": ["signal", "signal", "encoding"]}
        self.goto(page, "analyse/chain?rid=4&s0=995040&s1=998640", 3000)      # 3,600 samples at 1 Hz
        self.evidence["templates"] = {}
        for key, types in want.items():
            n_err = len(self.errors)
            self.import_template(page, key)
            r = self.run_and_wait(page, 120)
            rows = r.get("rows") or []
            paint = page.evaluate(ROW_PAINT)
            got = [x.get("type") for x in rows]
            ok_rows = []
            for k, (x, pr) in enumerate(zip(rows, paint)):
                t = x.get("type")
                ok_rows.append(bool(pr["model_card"]) if t == "model" else (pr["ink"] > BLANK and not pr["error_card"]))
            ev = {"job_status": r.get("job_status"), "types": got, "paint": paint, "badges": self.badges(page), "errors": self.errors[n_err:],
                  "step_timings": r.get("step_timings")}
            if key == "gramian":
                ev["not_time_aligned_text"] = page.locator("text=not time-aligned").count()
            if key == "mp_threshold":       # shared axis alignment through Bokeh view geometry
                plots = page.evaluate(PLOTS)
                axis = next((p_ for p_ in plots if 20 <= p_["h"] <= 32), None)
                shared = [p_ for p_ in plots if axis and p_["xr"] == axis["xr"] and p_ is not axis]
                ev["axis"] = {"axis": axis and [round(axis["fl"], 1), round(axis["fr"], 1)], "rows": [[round(p_["fl"], 1), round(p_["fr"], 1)] for p_ in shared]}
                self.check(axis is not None and len(shared) >= 4 and all(abs(p_["fl"] - axis["fl"]) <= 1 and abs(p_["fr"] - axis["fr"]) <= 1 for p_ in shared),
                           f"shared axis frame {ev['axis']['axis']} matches every row frame within 1 px: {ev['axis']['rows']}")
            self.evidence["templates"][key] = ev
            self.check(r.get("job_status") == "completed", f"template {key}: job {r.get('job')} {r.get('job_status')}")
            self.check(got == types, f"template {key}: seam drew {got}")
            self.check(len(paint) == len(types) and all(ok_rows), f"template {key}: every row painted {[(p_['row'], p_['ink'], p_['model_card']) for p_ in paint]}")
            self.check(not self.errors[n_err:], f"template {key}: 0 page/console errors ({self.errors[n_err:][:2]})")
            self.shot(page, f"chain-template-{key}")

    def stale_cancel(self, page):
        """A click on a '■ Cancel' that the poll has not repainted after the job finished must not start a run."""
        print("[stale cancel]")
        s0 = 700000 + (int(time.time()) % 997) * 60      # a fresh 20 h span every smoke run → the MP is really computed
        self.goto(page, f"analyse/chain?rid=4&s0={s0}&s1={s0 + 72000}&poll_ms=8000", 3000)
        self.import_template(page, "mp_threshold")
        jobs0 = len(self.debug().get("jobs", []))
        page.locator(".t-run button").first.click()
        t = time.time()
        done = False
        while time.time() - t < 7.0:
            js = self.debug().get("jobs", [])
            if len(js) > jobs0 and js[-1]["status"] in ("completed", "failed", "cancelled"):
                done = True
                break
            page.wait_for_timeout(150)
        label = page.locator(".t-run button").first.inner_text()
        jobs1 = len(self.debug().get("jobs", []))
        if done and "Cancel" in label:
            page.locator(".t-run button").first.click()
            page.wait_for_timeout(1500)
            jobs2 = len(self.debug().get("jobs", []))
            ev = [e["msg"] for e in self.debug().get("events", [])][-3:]
            self.evidence["stale_cancel"] = {"label_at_click": label, "job_done_s": round(time.time() - t, 2), "jobs": [jobs0, jobs1, jobs2], "events": ev}
            self.check(jobs2 == jobs1 and "stale_cancel" in ev, f"stale '■ Cancel' click after the job finished started no run (jobs {jobs1} → {jobs2}, events {ev})")
            self.shot(page, "chain-stale-cancel-refused")
        else:
            self.evidence["stale_cancel"] = {"label": label, "done": done}
            self.check(False, f"could not stage a stale Cancel (job done={done}, label {label!r})")
        # badge honesty on this fresh span: the MP row was computed, never "cached"
        page.wait_for_timeout(8500)
        b = self.badges(page)
        self.evidence["stale_cancel"]["badges"] = b
        self.check(len(b) == 3 and b[1].startswith("✓ computed") and "cached" not in b[1], f"a freshly computed MP row reads computed, not cached: {b}")

    def url_state(self, page, browser):
        """Reload / second tab re-attaches from the hash; an empty span cannot be run."""
        print("[url state]")
        url = page.url
        self.evidence["url_state"] = {"url": url}
        self.check("job=" in url and "rid=" in url, f"the chain page's URL carries the span and job: {url}")
        tab = browser.new_page(viewport={"width": 1440, "height": 900})
        errs = []
        tab.on("pageerror", lambda e: errs.append(str(e)))
        tab.goto(url, wait_until="networkidle")
        tab.wait_for_timeout(4000)
        foot = tab.locator('[data-testid="footer-terminal"]').inner_text()
        src = tab.locator('[data-testid="source-chip"]').inner_text()
        self.evidence["url_state"].update(second_tab_footer=foot, second_tab_source=src, second_tab_badges=[tab.locator(f'[data-testid="row-badge-{i}"]').first.inner_text()
                                                                                                         for i in range(1, 4) if tab.locator(f'[data-testid="row-badge-{i}"]').count()])
        self.check("last run" in foot or "Cancelled" in foot, f"a second tab on the same URL re-attaches to the job: {foot.splitlines()[:2]}")
        tab.screenshot(path=os.path.join(SHOTS, f"{self.n + 1:02d}-chain-second-tab-reattached.png"))
        self.n += 1
        self.shots.append(f"{self.n:02d}-chain-second-tab-reattached.png")
        tab.goto(self.url + "/#analyse/chain?rid=4&s0=995040&s1=995040", wait_until="networkidle")
        tab.wait_for_timeout(3500)
        dis = tab.locator(".t-run button").first.is_disabled()
        why = tab.locator('[data-testid="run-reason"]').inner_text()
        self.evidence["url_state"].update(empty_run_disabled=dis, empty_reason=why, errors=errs)
        self.check(dis and "empty" in why, f"a zero-length span: Run disabled with reason {why!r}")
        tab.close()

    def modal_and_font(self, page):
        print("[modal + font]")
        self.goto(page, "analyse/chain?rid=4&s0=995040&s1=998640", 2500)
        f = page.evaluate("""async()=>{await document.fonts.ready; return {inter: document.fonts.check('12px Inter')}}""")
        f["header"] = page.locator('[data-testid="header"] .ws').evaluate("e=>getComputedStyle(e).fontFamily")
        f["caption"] = page.locator('[data-testid="chain-row-1-caption"]').evaluate("e=>getComputedStyle(e).fontFamily")
        self.evidence["font"] = f
        self.check(f["header"].startswith("Inter") and "Geist Mono" in f["caption"], f"UI text is Inter, mono stays mono: {f}")
        page.locator(".t-insert-1 button").first.click()
        page.wait_for_timeout(2200)
        m = page.evaluate("(() => {" + DEEP + """
          const cards = deepAll('.bk-btn').filter(b => b.getRootNode().host && b.getRootNode().host.classList.contains('card-btn'));
          const over = cards.filter(b => b.scrollHeight > b.clientHeight + 1).length;
          const det = deepAll('[data-testid="modal-detail"]')[0]; let spill = null;
          if (det) { const hr = det.getRootNode().host.getBoundingClientRect(); let mx = 0;
            for (const el of det.querySelectorAll('*')) { const r = el.getBoundingClientRect(); if (r.width) mx = Math.max(mx, r.right); }
            spill = mx - hr.right; }
          return {cards: cards.length, overflowing: over, detail_spill_px: spill}; })()""")
        self.evidence["modal_overflow"] = m
        self.check(m["cards"] >= 20 and m["overflowing"] == 0 and m["detail_spill_px"] is not None and m["detail_spill_px"] <= 0.5,
                   f"insert modal: no clipped card text and the detail panel stays in its column: {m}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(1200)
        vis = page.locator('[data-testid="insert-modal"]').count() and page.locator('[data-testid="insert-modal"]').first.is_visible()
        self.check(not vis, "Escape closes the insert modal")

    def loud_failure(self, page):
        print("[loud failure]")
        n_err = len(self.errors)
        self.goto(page, "analyse/chain?throw=1", 3000)
        self.check(page.locator('[data-testid="render-error"]').count() >= 1, "?throw=1: the thrown renderer error shows as a red card in the row")
        self.evidence["throw_caught_console"] = self.errors[n_err:]
        self.shot(page, "loud-failure-render-error")
        self.goto(page, "analyse/chain?throw=row", 3000)     # critique r1: a STEP row's renderer is caught per row too
        paint = page.evaluate(ROW_PAINT)
        self.evidence["throw_row"] = paint
        self.check(len(paint) >= 3 and paint[2]["error_card"] and paint[0]["ink"] > BLANK, f"?throw=row: row 02 shows its own error card, the Source row still paints: {paint}")
        self.shot(page, "loud-failure-step-row")
        self.goto(page, "explore/corpus", 3000)       # start from a different page so a stale view is unmistakable
        n_err = len(self.errors)
        self.goto(page, "analyse/chain?throw=1&uncaught=1", 3000)
        body = page.locator("body").inner_text()
        self.evidence["throw_uncaught"] = {"render_error_cards": page.locator('[data-testid="render-error"]').count(), "url": page.url,
                                           "corpus_still_shown": page.locator('[data-testid="corpus-bottom-bar"]').count() == 1,
                                           "body_text_head": body[:400], "console": self.errors[n_err:]}
        self.shot(page, "loud-failure-uncaught")
        self.errors = self.errors[:n_err] + [e for e in self.errors[n_err:] if "deliberate" not in e]

    def run(self):
        from playwright.sync_api import sync_playwright
        os.makedirs(SHOTS, exist_ok=True)
        for f in os.listdir(SHOTS):
            if re.match(r"^\d\d-.*\.png$", f):
                os.remove(os.path.join(SHOTS, f))
        rt = self.debug()["runtime"]
        log_path = rt["log_path"]
        log_start = os.path.getsize(log_path) if os.path.isfile(log_path) else 0
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("console", lambda m: self.errors.append(f"console.{m.type}: {m.text[:400]}") if m.type == "error" else None)
            page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
            page.on("requestfailed", lambda r: self.errors.append(f"requestfailed: {r.url}") if "fonts.g" not in r.url else None)
            steps = (self.corpus, self.signal, self.m4, self.analyse, self.templates, self.stale_cancel, lambda pg: self.url_state(pg, browser),
                     self.modal_and_font, self.loud_failure)
            for step in steps:
                try:
                    step(page)
                except Exception as e:
                    nm = getattr(step, "__name__", "step").replace("<lambda>", "url_state")
                    self.failures.append(f"{nm}: {type(e).__name__}: {e}")
                    print("  EXC:", nm, e)
                    try:
                        self.shot(page, f"{nm}-exception")
                    except Exception:
                        pass
            browser.close()
        tail = ""
        if os.path.isfile(log_path):
            with open(log_path, encoding="utf-8", errors="replace") as f:
                f.seek(log_start)
                tail = f.read()
        allowed = ("deliberate", "failed at step", "render error in Source row renderer", "render error in 02 ", "must be shorter")
        err_lines, unexpected, last_err = [], [], ""
        for l in tail.splitlines():
            if " ERROR " in l:
                last_err = l
                err_lines.append(l)
                if not any(a in l for a in allowed):
                    unexpected.append(l)
            elif "Traceback" in l:
                err_lines.append(l)     # a traceback belongs to the nearest ERROR line above it
                if not any(a in last_err for a in allowed):
                    unexpected.append(l)
        self.evidence["server_log_error_lines"] = err_lines[:30]
        self.evidence["server_log_deliberate_block"] = [l for l in tail.splitlines() if "deliberate" in l][:10]
        self.check(not unexpected, f"no unexpected server tracebacks ({len(unexpected)} unexpected of {len(err_lines)} error lines): {unexpected[:3]}")
        self.check(not self.errors, f"no browser console/page errors ({len(self.errors)})")
        for e in self.errors[:20]:
            print("   browser:", e[:300])
        out = {"failures": self.failures, "browser_errors": self.errors, "evidence": self.evidence, "screenshots": self.shots,
               "runtime": rt}
        with open(os.path.join(SHOTS, "smoke-result.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\n{len(self.shots)} screenshots, {len(self.failures)} failures")
        return 0 if not self.failures else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("PROTO_B_URL", "http://127.0.0.1:8766"))
    ap.add_argument("--no-run", action="store_true")
    a = ap.parse_args()
    sys.exit(Smoke(a.url, not a.no_run).run())
