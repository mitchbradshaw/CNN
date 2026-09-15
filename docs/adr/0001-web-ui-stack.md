---
status: accepted
---

# The rebuilt interface is React + TypeScript over a FastAPI bridge, with plots drawn in SVG on d3 scales

The rebuilt Pipeline GUI is a **React 19 + TypeScript** single-page app built with **Vite**, talking over
HTTP (JSON, plus server-sent events for run progress) to a thin **FastAPI/uvicorn bridge** that imports the
untouched Python core (`Working/`, `Adapters/`). It lives at `webui/`. We chose it over staying on
**Panel + Bokeh** after building the same vertical slice in both, overnight 2026-09-14 → 15
(`ui-prototypes/REPORT.md`, scorecard §8), because the two properties this project has paid for repeatedly —
**failures that are loud rather than a silently blank pane**, and **fidelity to a bespoke designed interface**
(`prototyping/imgs/`) — separated the candidates decisively, while large-signal rendering and interaction
latency did not.

## Considered Options

- **A — React + TypeScript + Vite, d3 scales + hand-written SVG, FastAPI bridge (chosen).** A thrown render
  error becomes a red card in place of the row plus a browser console error, and a server exception is a
  500 carrying the traceback; the Playwright gate sees both without extra wiring. Every designed component
  (chips, badges, modal card grid, drag handles, draggable threshold, crosshair on one shared time axis) was
  drawn directly. Faster on every load/navigation/memory measure (first paint 0.62 s vs 0.90 s, page switch
  0.11 s vs 0.54 s, JS heap 9.5 MB vs 31.6 MB).
- **B — Panel 1.9.3 + Bokeh 3.9.2 in-process (runner-up).** Real advantages: no bridge to write, in-process
  cancel, no build step, one language, a shared axis that is one `Range1d`, canvas/WebGL headroom for very
  dense plots, and it fits the existing repo. **It lost on loud failure:** an exception in any Panel callback
  leaves the previous page on screen with a clean browser console and only a line in `server.log`, so every
  callback must be wrapped by hand and a test gate must read the server log; its critic hit the silent-pane
  class by accident through an ordinary template. It also approximated designed components with widgets
  (cards, grips, popovers, fonts) and kept state in the server session, so a reload lost the page. If this
  choice is ever refuted, B is the real alternative to start from.
- Dash/NiceGUI (same family as B, not built), Qt/PySide6 + pyqtgraph (no web output path; every renderer
  custom) and webview wrappers (answer no open question) were ranked out before building.

## Plotting approach

Charts are React components drawing **SVG on d3 scales** (`d3-scale`, `d3-shape`; no chart library), with one
x scale shared by every row of a chain. Bulk arrays never cross the wire: the bridge ships **server-side
bucketed min/max envelopes** of about twice the plot width, capped span lists, symbol strips, and PNG
thumbnails for image stacks. The seam is **one serialiser per interchange type on the server**
(`webui/server/serialize.py`) and **one renderer switch on the client** (`Renderer.tsx`), covering all seven
types. **Escape hatch:** SVG degrades past roughly 10–20k marks, so a page that must draw tens of thousands of
marks at once (every detection across a recording, a large recurrence matrix) draws that renderer to
`<canvas>` — hand-written, as the image rows already are, or a small canvas library such as uPlot — behind the
same per-type seam (REPORT §8). Publication-quality static export was out of the slice and is still open; SVG
is exportable, matplotlib parity is untested.

## Inherited

**No code or component is inherited** from an existing open-source project. Ideas are: the step cache keyed
by recipe prefix hash (the core's own, DVC-like), per-type widget dispatch (the old `render_value` contract,
NWB-widgets-like), zoom-triggered re-aggregation (`plotly-resampler`'s idea, implemented as the bridge's
viewport envelope endpoint), and the bucketed min/max decimation from `UI/plots.py`, re-implemented in the
bridge with identical per-bucket semantics.

## Consequences

- **A second toolchain:** Node 25 + npm, TypeScript and a Vite build step for `webui/client` (project-local
  `node_modules`, ~97 MB, development only), plus FastAPI + uvicorn in a project-local `webui/.venv` created
  with `--system-site-packages` over the conda environment (~20 MB). The researcher's choice of A on
  2026-09-15 is the sign-off for this toolchain; nothing is installed into the shared conda environment.
- **The bridge is a maintained layer** (~1,700 lines of Python: runtime isolation, SSE with a polling
  fallback, cancel between steps, reload re-attach, a meta sidecar for cache-restored steps, the held-out
  guard on every route). It must keep redirecting every writable path into a throwaway runtime.
- **New gates:** `webui/smoke.py` (Playwright, fails on console errors, unpainted panes and server
  tracebacks), a TypeScript type-check and a production build. The old Panel tree `UI/` and its pytest gates
  remain until retired.
