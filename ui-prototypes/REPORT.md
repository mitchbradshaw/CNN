# REPORT.md — UI stack prototypes for issue #12 (overnight, 2026-09-14/15)

> DRAFT SKELETON — filled in at close-out. See DECISIONS.md for the running log.

## 1. Summary table

| Prototype | Stack | Start | URL | 1 Shell | 2 Corpus | 3 Signal | 4 Chain | 5 Block page | 6 History/Save | 7 Export | 8 Cross-channel |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | React 19 + TypeScript + Vite 8 + d3 · FastAPI bridge (venv) | `ui-prototypes/A-react-fastapi/start.ps1` (or `start.sh`) | http://127.0.0.1:8765 | | | | | | | | |
| B | Panel 1.9.3 + Bokeh 3.9.2 (in-process) | `ui-prototypes/B-panel/start.ps1` | http://127.0.0.1:8766 | | | | | | | | |

## 2. Why A ranked first (and what building taught)

## 3. Evidence gathered while building, per stack

### A — React + FastAPI
- zoom latency on the full channel:
- run and progress round trip:
- what a thrown render error looked like:
- install and build friction:
- lines of code — dispatch seam and one renderer:
- where the stack fought the design:

### B — Panel + Bokeh
- (same headings)

## 4. Critique rounds

## 5. Deviations from the pages/spec, and backend gaps wrapped or stubbed

## 6. Screenshot index (screenshot → concept frame)

## 7. Open questions and recommended next step
