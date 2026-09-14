"""Smoke test + screenshot capture for prototype A.

    "/c/ProgramData/anaconda3/python.exe" smoke.py [--url http://127.0.0.1:8765] [--no-run]

Fails (non-zero exit) if:
  * any browser console error or page error occurs on any view (a render error that
    reaches the console is loud by design — the ErrorBoundary logs it);
  * a pane that must paint did not: the corpus heatmap has < 800 filled cells, an
    envelope path has an empty `d`, the chain rows have no plot path/rects/canvas;
  * the server log contains a traceback that was not deliberately provoked;
  * a Must-view flow (open channel → send span → run chain → suffix re-run) breaks.

Screenshots land in screenshots/<nn>-<name>.png, paired to concept frames in REPORT.md.
Uses the repo's Playwright (conda python), not a Node harness.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "screenshots")


class Smoke:
    def __init__(self, url: str, run_chain: bool):
        self.url = url.rstrip("/")
        self.run_chain = run_chain
        self.errors: list[str] = []
        self.failures: list[str] = []
        self.shots: list[str] = []
        self.evidence: dict = {}
        self.n = 0

    # ------------------------------------------------------------ helpers --
    def shot(self, page, name: str):
        self.n += 1
        path = os.path.join(SHOTS, f"{self.n:02d}-{name}.png")
        page.screenshot(path=path, full_page=False)
        if os.path.getsize(path) > 1_000_000:          # gitignore rule: *.big.png
            big = path.replace(".png", ".big.png"); os.replace(path, big); path = big
        self.shots.append(path)
        return path

    def check(self, cond: bool, msg: str):
        if not cond:
            self.failures.append(msg)
            print("  FAIL:", msg)
        else:
            print("  ok:", msg)

    def goto(self, page, hash_: str, settle_ms=600):
        page.goto(f"{self.url}/#/{hash_}", wait_until="networkidle")
        page.wait_for_timeout(settle_ms)

    # --------------------------------------------------------------- views --
    def corpus(self, page):
        print("[corpus]")
        self.goto(page, "explore/corpus", 1200)
        page.wait_for_selector('[data-testid="corpus-heatmap"]', timeout=20000)
        cells = page.locator('[data-testid="heatmap-cell"]')
        n = cells.count()
        filled = page.evaluate("""() => Array.from(document.querySelectorAll('[data-testid="heatmap-cell"]')).filter(r => { const f = getComputedStyle(r).fill || r.getAttribute('fill'); return f && f !== 'none' }).length""")
        distinct = page.evaluate("""() => new Set(Array.from(document.querySelectorAll('[data-testid="heatmap-cell"]')).map(r => r.getAttribute('fill') || getComputedStyle(r).fill)).size""")
        self.evidence["heatmap_cells"] = n; self.evidence["heatmap_distinct_fills"] = distinct
        self.check(n >= 16 * 28, f"heatmap has {n} cells (>= 448)")
        self.check(filled >= 800, f"heatmap painted {filled} cells (>= 800)")
        self.check(distinct >= 3, f"heatmap uses {distinct} distinct fills (>= 3, i.e. real counts, not one colour)")
        self.check(page.locator('[data-testid="nav-rail"]').count() == 1, "nav rail present")
        self.check(page.locator('[data-testid="header"]').count() == 1, "header present")
        self.shot(page, "explore-1-corpus")
        # colour-by toggle
        for label in ("detections", "disagree", "both"):
            b = page.get_by_role("button", name=re.compile(rf"^{label}$", re.I))
            if b.count():
                b.first.click(); page.wait_for_timeout(500)
        self.shot(page, "explore-1-corpus-colour-by")
        # select a channel row
        row = page.locator('[data-testid="heatmap-row-CH4_A2"]')
        if row.count():
            row.first.locator('[data-testid="heatmap-cell"]').first.click(); page.wait_for_timeout(400)
        bar = page.locator('[data-testid="corpus-bottom-bar"]')
        self.check(bar.count() == 1 and "annotations" in bar.inner_text().lower(), "bottom bar shows channel counts")
        self.shot(page, "explore-1-corpus-selected")
        open_btn = page.locator('[data-testid="open-channel"]')
        self.check(open_btn.count() == 1, "Open channel button present")
        open_btn.first.click()
        page.wait_for_timeout(1500)

    def signal(self, page):
        print("[signal]")
        if "explore/signal" not in page.url:
            self.goto(page, "explore/signal/4", 1500)
        page.wait_for_selector('[data-testid="signal-overview"]', timeout=20000)
        page.wait_for_timeout(1200)
        d_len = page.evaluate("""() => [document.querySelector('[data-testid="signal-overview"] path[d]'), document.querySelector('[data-testid="signal-span"] path[d], [data-testid="envelope-path"]')].map(p => p ? (p.getAttribute('d')||'').length : 0)""")
        self.evidence["envelope_path_lengths"] = d_len
        self.check(len(d_len) == 2 and all(l > 500 for l in d_len), f"overview + span envelope paths painted (d lengths {d_len})")
        bands = page.locator('[data-testid="span-bands"] rect').count()
        self.evidence["span_bands"] = bands
        self.check(bands >= 1, f"{bands} tinted span bands drawn in the viewport")
        self.shot(page, "explore-2-signal")
        # zoom in with the wheel over the span plot, measuring the latency instrumentation
        box = page.locator('[data-testid="signal-span"]').bounding_box()
        if box:
            cx, cy = box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.5
            page.mouse.move(cx, cy)
            for _ in range(8):
                page.mouse.wheel(0, -240); page.wait_for_timeout(120)
            page.wait_for_timeout(700)
            # pan
            page.mouse.move(cx, cy); page.mouse.down(); page.mouse.move(cx - 200, cy, steps=8); page.mouse.up()
            page.wait_for_timeout(700)
        stats = page.evaluate("() => window.__zoomStats || []")
        self.evidence["zoom_stats"] = stats[-12:]
        self.check(len(stats) >= 2, f"viewport refetch instrumentation recorded {len(stats)} fetches")
        if stats:
            rts = [s.get("round_trip_ms", 0) for s in stats]
            self.evidence["zoom_round_trip_ms"] = {"min": min(rts), "max": max(rts), "median": sorted(rts)[len(rts) // 2]}
        self.shot(page, "explore-2-signal-zoomed")
        # select a motif via next-motif button
        nxt = page.locator('[data-testid="motif-next"]')
        if nxt.count():
            nxt.first.click(); page.wait_for_timeout(900)
        self.check(page.locator('[data-testid="signal-motif"]').count() == 1, "motif tier present")
        self.shot(page, "explore-2-signal-motif")
        # send span to analyse
        send = page.locator('[data-testid="send-span"]')
        self.check(send.count() == 1, "Send span to Analyse present")
        send.first.click(); page.wait_for_timeout(1200)
        self.check("analyse" in page.url, "sending a span navigates to Analyse")

    def m4(self, page):
        print("[held-out]")
        self.goto(page, "explore/signal/52", 1200)
        txt = page.locator("body").inner_text()
        self.check("held out" in txt.lower(), "M4 channel shows a held-out / locked state")
        self.shot(page, "explore-m4-held-out")

    def analyse(self, page):
        print("[analyse]")
        self.goto(page, "analyse/chain", 1500)
        page.wait_for_selector('[data-testid="chain-page"]', timeout=20000)
        page.wait_for_timeout(800)
        rows = page.locator('[data-testid^="chain-row-"]').count()
        self.check(rows >= 4, f"{rows} chain rows (source + 3 steps)")
        self.shot(page, "chain-1-chain-before-run")
        # insert modal
        ins = page.locator('[data-testid="insert-2"]')
        if ins.count():
            ins.first.click(); page.wait_for_timeout(700)
            self.check(page.locator('[data-testid="insert-modal"]').count() == 1, "insert-stage modal opens")
            cards = page.locator('[data-testid^="modal-card-"]').count()
            self.check(cards >= 20, f"modal lists {cards} adapters")
            disabled = page.evaluate("""() => Array.from(document.querySelectorAll('[data-testid^="modal-card-"]')).filter(c => c.disabled || c.getAttribute('aria-disabled') === 'true' || /nofit|disabled|unfit/.test(c.className)).length""")
            self.check(disabled >= 10, f"{disabled} incompatible adapters shown disabled with reasons")
            self.shot(page, "chain-2-insert-stage")
            page.keyboard.press("Escape"); page.wait_for_timeout(300)
            if page.locator('[data-testid="insert-modal"]').count():
                page.get_by_role("button", name=re.compile("cancel", re.I)).first.click(); page.wait_for_timeout(300)
        if not self.run_chain:
            return
        run = page.locator('[data-testid="run-button"]')
        self.check(run.count() == 1 and run.first.is_enabled(), "run button present and enabled")
        t = time.time(); run.first.click()
        # wait for completion: the terminal footer says "last run" or a failure
        for _ in range(120):
            page.wait_for_timeout(250)
            ft = page.locator('[data-testid="footer-terminal"]').inner_text().lower() if page.locator('[data-testid="footer-terminal"]').count() else ""
            if "last run" in ft or "no result" in ft or "failed" in ft:
                break
        self.evidence["run_wall_s"] = round(time.time() - t, 2)
        badges = [page.locator(f'[data-testid="row-badge-{i}"]').inner_text().strip() for i in range(1, 4) if page.locator(f'[data-testid="row-badge-{i}"]').count()]
        self.evidence["badges_after_run"] = badges
        self.check(all(("cached" in b.lower() or "done" in b.lower()) for b in badges) and len(badges) == 3, f"all rows completed: {badges}")
        painted = page.evaluate("""() => [1,2,3].map(i => { const el = document.querySelector('[data-testid="row-plot-'+i+'"]'); if (!el) return 'missing'; const p = el.querySelector('path[d]'); const r = el.querySelectorAll('rect').length; const c = el.querySelector('canvas'); return (p && p.getAttribute('d').length > 200) ? 'path' : r > 2 ? 'rects' : c ? 'canvas' : 'blank' })""")
        self.evidence["row_plots"] = painted
        self.check(all(p != "blank" and p != "missing" for p in painted), f"every result row painted something: {painted}")
        self.shot(page, "chain-1-chain-completed")
        # block page for the threshold (step index 2) with a draggable line
        page.locator('[data-testid="settings-step-3"]').first.click() if page.locator('[data-testid="settings-step-3"]').count() else self.goto(page, "analyse/block/2", 800)
        page.wait_for_timeout(900)
        self.check(page.locator('[data-testid="block-page"]').count() == 1, "block page opens")
        line = page.locator('[data-testid="threshold-line"]')
        self.check(line.count() >= 1, "draggable threshold line present")
        self.shot(page, "chain-7b-block-threshold")
        if line.count():
            b = line.first.bounding_box()
            if b:
                page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2); page.mouse.down()
                page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2 - 30, steps=6); page.mouse.up()
                page.wait_for_timeout(600)
        self.shot(page, "chain-7b-block-threshold-dragged")
        # back to chain: rows 1,2 should be cached, 3 stale; re-run → suffix cache hit
        self.goto(page, "analyse/chain", 900)
        badges = [page.locator(f'[data-testid="row-badge-{i}"]').inner_text().strip().lower() for i in range(1, 4) if page.locator(f'[data-testid="row-badge-{i}"]').count()]
        self.evidence["badges_after_edit"] = badges
        self.check(len(badges) == 3 and "stale" in badges[2], f"editing the threshold marked row 3 stale: {badges}")
        run = page.locator('[data-testid="run-button"]')
        run.first.click()
        for _ in range(80):
            page.wait_for_timeout(250)
            ft = page.locator('[data-testid="footer-terminal"]').inner_text().lower() if page.locator('[data-testid="footer-terminal"]').count() else ""
            if "last run" in ft or "no result" in ft:
                break
        page.wait_for_timeout(400)
        badges = [page.locator(f'[data-testid="row-badge-{i}"]').inner_text().strip().lower() for i in range(1, 4)]
        titles = [page.locator(f'[data-testid="row-badge-{i}"]').get_attribute("title") or "" for i in range(1, 4)]
        self.evidence["badges_after_rerun"] = badges; self.evidence["badge_titles_after_rerun"] = titles
        self.check("cached" in badges[0] and "cached" in badges[1], f"prefix rows cached after suffix re-run: {badges}")
        self.check(any("0.0" in (b + t) or "0 s" in (b + t) for b, t in zip(badges[:2], titles[:2])), f"prefix rows report 0 s core timings: {list(zip(badges[:2], titles[:2]))}")
        self.shot(page, "chain-1-chain-suffix-rerun")
        # history popover
        h = page.locator('[data-testid="history-button"]')
        if h.count():
            h.first.click(); page.wait_for_timeout(700)
            self.check(page.locator('[data-testid="history-popover"]').count() == 1, "history popover opens")
            self.shot(page, "chain-1b-run-history")
            page.keyboard.press("Escape"); page.wait_for_timeout(300)
        # invalid junction: delete step 2 (matrix profile)
        d = page.locator('[data-testid="delete-step-2"]')
        if d.count():
            d.first.click(); page.wait_for_timeout(900)
            self.check(page.locator('[data-testid="junction-error"]').count() >= 1, "deleting the Scores producer shows the red junction")
            self.shot(page, "chain-1e-invalid-junction")
            undo = page.get_by_role("button", name=re.compile("undo", re.I))
            if undo.count():
                undo.first.click(); page.wait_for_timeout(700)
        # failed block: window_min too long, via the block page param
        self.goto(page, "analyse/block/1", 900)
        p = page.locator('input[data-testid="param-window_min"], [data-testid="param-window_min"] input[type=number]')
        if p.count():
            p.first.fill("500"); p.first.press("Enter"); page.wait_for_timeout(500)
            self.goto(page, "analyse/chain", 800)
            page.locator('[data-testid="run-button"]').first.click()
            for _ in range(80):
                page.wait_for_timeout(250)
                if page.locator('[data-testid="error-card"]').count():
                    break
            page.wait_for_timeout(300)
            self.check(page.locator('[data-testid="error-card"]').count() >= 1, "failed block shows an error card in place of the plot")
            self.shot(page, "chain-1f-failed-block")
            # restore
            self.goto(page, "analyse/block/1", 900)
            p = page.locator('input[data-testid="param-window_min"], [data-testid="param-window_min"] input[type=number]')
            p.first.fill("1"); p.first.press("Enter"); page.wait_for_timeout(400)
        # running state: seed a 20 h source span (72,000 samples, under MP's 80,527 ceiling; MP takes ~3 s)
        page.evaluate("""() => sessionStorage.setItem('ub-proto-a:source', JSON.stringify({recording_id: 4, channel_name: 'CH4_A2', source_file: 'M2_aug_concat_fs1.mat', fs: 1, start_idx: 995040, end_idx: 1067040, label: 'smoke 20 h span'}))""")
        page.reload(wait_until="networkidle"); page.wait_for_timeout(1200)
        run = page.locator('[data-testid="run-button"]')
        if run.count() and run.first.is_enabled():
            run.first.click(); page.wait_for_timeout(700)
            self.shot(page, "chain-1d-running")
            c = page.locator('[data-testid="cancel-button"]')
            if c.count():
                c.first.click(); page.wait_for_timeout(1500)
                self.shot(page, "chain-cancelled")
            for _ in range(120):
                page.wait_for_timeout(250)
                if not page.locator('[data-testid="cancel-button"]').count():
                    break
        # restore the example span for anyone using the page after the smoke test
        page.evaluate("""() => sessionStorage.setItem('ub-proto-a:source', JSON.stringify({recording_id: 4, channel_name: 'CH4_A2', source_file: 'M2_aug_concat_fs1.mat', fs: 1, start_idx: 995040, end_idx: 1002240, label: 'example span'}))""")

    def loud_failure(self, page):
        print("[loud failure]")
        self.goto(page, "analyse/chain?throw=1", 1200)
        self.check(page.locator('[data-testid="render-error"]').count() >= 1, "a thrown render error is shown as a red card (not a blank pane)")
        self.check(any("deliberate render failure" in e for e in self.errors), "the thrown render error reached the browser console")
        self.shot(page, "loud-failure-render-error")
        self.errors = [e for e in self.errors if "deliberate render failure" not in e]

    # ------------------------------------------------------------ driver --
    def run(self):
        from playwright.sync_api import sync_playwright
        os.makedirs(SHOTS, exist_ok=True)
        for f in os.listdir(SHOTS):
            if re.match(r"^\d\d-.*\.(big\.)?png$", f):
                os.remove(os.path.join(SHOTS, f))
        rt = json.load(__import__("urllib.request").request.urlopen(self.url + "/api/runtime"))
        log_path = rt["log_path"]
        log_start = os.path.getsize(log_path) if os.path.isfile(log_path) else 0
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("console", lambda m: self.errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
            page.on("requestfailed", lambda r: self.errors.append(f"requestfailed: {r.url}") if "fonts.g" not in r.url else None)
            for step in (self.corpus, self.signal, self.m4, self.analyse, self.loud_failure):
                try:
                    step(page)
                except Exception as e:  # keep going, report everything
                    self.failures.append(f"{step.__name__}: {type(e).__name__}: {e}")
                    print("  EXC:", step.__name__, e)
                    try: self.shot(page, f"{step.__name__}-exception")
                    except Exception: pass
            browser.close()
        # server log check
        tail = ""
        if os.path.isfile(log_path):
            with open(log_path, encoding="utf-8", errors="replace") as f:
                f.seek(log_start); tail = f.read()
        tb = [l for l in tail.splitlines() if "Traceback" in l or "ERROR" in l]
        allowed = ("/api/boom", "deliberate", "must be shorter than the span", "RecipeExecutionError", "run", "window (m=")
        unexpected = [l for l in tb if not any(a in l for a in allowed)]
        self.evidence["server_log_error_lines"] = tb[:20]
        self.check(not unexpected, f"no unexpected server tracebacks ({len(unexpected)} unexpected of {len(tb)} error lines)")
        self.check(not self.errors, f"no browser console/page errors ({len(self.errors)})")
        for e in self.errors[:20]:
            print("   browser:", e[:300])
        out = {"failures": self.failures, "browser_errors": self.errors, "evidence": self.evidence, "screenshots": self.shots}
        with open(os.path.join(SHOTS, "smoke-result.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"\n{len(self.shots)} screenshots, {len(self.failures)} failures")
        return 0 if not self.failures else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("PROTO_A_URL", "http://127.0.0.1:8765"))
    ap.add_argument("--no-run", action="store_true", help="skip the run/cancel/fail flows")
    a = ap.parse_args()
    sys.exit(Smoke(a.url, not a.no_run).run())
