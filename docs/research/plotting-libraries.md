# Plotting libraries for multi-day signals — research (issue #7)

Ticket: [mitchbradshaw/CNN#7](https://github.com/mitchbradshaw/CNN/issues/7), blocking issue #12,
child of the map issue #4. Method: `research` skill substance — primary sources only, findings
here, nothing on secondary write-ups taken at face value.

## The question this file actually answers

Per the ticket, this is **not** "can it draw a million points." `UI/plots.py:311`
(`_minmax_decimate`) already reduces any span to ≤`MAX_RENDER_POINTS` = 40,000
(`UI/plots.py:156`) in 12.1 ms on 2.6M samples, preserving both extremes per bucket so spikes
survive. That problem is solved, portable (pure numpy), and not in question.

What's actually being scored, per the ticket's three numbered questions:

1. Can the library draw ~40k points as a polyline at interactive framerate and redraw on every
   viewport change?
2. **Can it report the visible x-range back to application code on pan/zoom**, so the decimator
   can re-run for the new span? A library that can't expose its viewport is disqualified
   regardless of how well it draws. **This is the decisive axis.**
3. Does the redraw path fail loudly, or silently (the failure mode this codebase has hit twice —
   see `UI/plots.py:43-63` and `CLAUDE.md` > Panel surfaces)?

Secondary: native large-N handling that could make the external decimator optional; fit for
small-multiples/filmstrip layouts across the pipeline's seven heterogeneous interchange types;
publication-quality static export (vector, fonts, DPI) and whether it shares code with the
interactive path.

---

## Comparison table

Legend: ✅ confirmed from a primary source · ⚠️ confirmed but with a real caveat · ❌ confirmed
absent/disqualifying · ❔ could not confirm from documentation in this session (see
[Verification gaps](#verification-gaps))

| Library | Family | Q1 draw 40k + redraw | Q2 viewport→Python/JS callback | Q3 fails loudly | Native big-N / own resampling | Small multiples | Static vector export |
|---|---|---|---|---|---|---|---|
| **HoloViews/Bokeh** (incumbent) | Python→browser | ✅ proven in this repo | ✅ `hv.streams.RangeX`, in production now | ⚠️ proven *fragile* — the exact type-consistency trap already hit once | n/a (decimator already owns this) | ✅ used today for ribbon panes | ⚠️ SVG via headless browser, no native PDF, perf caveat |
| **Plotly (Python) via Panel** | Python→browser | ✅ | ✅ Panel's own `viewport` param, confirmed first-party | ❔ not proven safe, not proven fragile | ⚠️ only via Plotly-Resampler, which needs Dash or Jupyter, not Panel | ✅ `make_subplots` | ✅ kaleido, shared Figure object, SVG/PDF — avoid Scattergl |
| **Matplotlib** | Python, GUI/Jupyter | ✅ | ⚠️ `xlim_changed` real, but needs `ipympl` (Jupyter-widget bridge), awkward in Panel | ❔ | n/a | ✅ best-in-class (`subplots`/`gridspec`) | ✅✅ gold standard, native |
| **VisPy** | Python, GPU | ✅ (over-engineered for 40k) | ❌ no documented public range-change event | ❔ | ✅ GPU, moot here | ❔ | ❌ raster only, no vector export |
| **Datashader** | Python, raster | ✅ but wrong tool now | ⚠️ only via HoloViews (same trap) or an unverified raw-Bokeh path | ❌ this is the exact failure already diagnosed and removed | ✅ but the bottleneck it solves no longer exists | ❔ | n/a (raster) |
| **PyQtGraph** | Python, native Qt (leaves the browser) | ✅ | ✅ `sigRangeChanged`/`sigXRangeChanged`/`sigYRangeChanged` | ❔ no scenegraph type trap by design | ✅ built for exactly this | ✅ | ✅✅ `SVGExporter`, docs call it "the preferred method for publication graphics" |
| **Vega-Altair** | Python↔JS, Jupyter-shaped | ✅ | ⚠️ `JupyterChart` selections round-trip to Python, but requires Jupyter-widget host, not confirmed in Panel | ❔ | ❌ | ✅ facet/concat | ⚠️ SVG/PNG via vl-convert; PDF needs older `altair_saver` |
| **uPlot** | JS, canvas | ✅✅ built for this exact shape | ✅ `hooks.setScale` fires `(u, key)` on every scale change | ❔ plain JS callback, no framework type trap | ❌ explicitly — "do it in advance," a clean fit for this project's own decimator | ⚠️ multiple instances, manual sync | ❌ canvas-only, no vector export found |
| **Plotly.js** | JS | ✅ | ✅ `plotly_relayout` (same engine Panel's pane consumes) | ❔ | ⚠️ same Resampler caveat as Python | ✅ `make_subplots` (JS API) | ❔ not independently re-checked against JS-specific docs |
| **ECharts** | JS, canvas/SVG | ✅ | ✅ `chart.on('dataZoom', …)`, with a documented `startValue`/`endValue` reliability wrinkle | ❔ | ⚠️ `large`-series mode, not benchmarked here | ✅ multiple instances | ✅ native `renderer:'svg'` mode (separate init from the canvas mode used for interactivity) |
| **D3 / d3-zoom** | JS, SVG, framework | ✅ (you build it) | ✅✅ textbook — `event.transform`, `.rescaleX()` | ✅ no scenegraph, nothing to fail silently | ❌ none, by design | ✅ (you build it) | ✅✅ the live SVG *is* the export — no separate step |
| **Observable Plot** | JS, SVG, built on D3 | ✅ | ❌ pan/zoom **not shipped** — GitHub issue open since 2024-11-01 | n/a | ❌ | ✅✅ best facet system reviewed (`fx`/`fy`) | ✅ same as D3 |
| **Lightweight Charts** | JS, canvas | ✅ | ✅✅ best-documented API of any candidate — `subscribeVisibleLogicalRangeChange` returns `{from,to}` sample-index bounds directly | ❔ | ⚠️ not designed for it; not the point | ❔ multi-pane since v4, not verified this session | ❌ canvas-only, no vector export found |
| **WebGL-generic** (deck.gl/regl/raw WebGL) | JS, GPU | ✅ (over-engineered for 40k) | ❔ no universal event — whatever the specific library provides | ❔ | ✅ GPU, moot here | ❔ | ❔ |
| **Canvas-direct (hand-rolled)** | JS | ✅ (you build it) | ✅ trivially — your own event handler sets the range | ✅ nothing to fail silently | ❌ you build it | ❌ you build it | ❌ you build it |

---

## Per-candidate notes and sources

### Incumbent: HoloViews + Bokeh (`hv.streams.RangeX`)

This is already running in `UI/plots.py`. `build_channel_dmap` (`UI/plots.py:445`) drives an
`hv.DynamicMap` off `hv.streams.RangeX(x_range=...)`; `range_stream.x_range` is the live visible
span, read by `UI/app.py` for ribbons, the cross-channel peek, and `scale_viewed`
(`UI/plots.py:492`). This is question 2, solved, in production, today — the primary source for
"does this mechanism work" is the codebase's own operating history, which the ticket explicitly
instructs to treat as evidence.

Bokeh's Python callback docs confirm the underlying primitive requires a running Bokeh server
(not static HTML) for Python-side range callbacks
([docs.bokeh.org/interaction/python_callbacks](https://docs.bokeh.org/en/latest/docs/user_guide/interaction/python_callbacks.html)):
"You can only use these callbacks in Bokeh server apps." Panel *is* a Bokeh server app, which is
why this already works.

**Static export** (`docs.bokeh.org/output/export.html`): `output_backend="svg"` plus
`export_svg()`/`export_svgs()` produces vector SVG. Real caveats confirmed in the same page: "The
SVG output isn't as performant as the default Canvas backend when it comes to rendering a large
number of glyphs or handling lots of user interactions such as panning"; no native PDF (convert
externally, e.g. via Illustrator); export requires a headless-browser dependency (Playwright or
Selenium) beyond what interactive serving needs. So Bokeh's interactive and static paths already
*diverge* today — the static path needs an extra toolchain component.

### Q3, precisely: whose fault was the blank pane?

The ticket asks to check whether the diagnosed failure (`UI/plots.py:43-63`) was Datashader's or
Panel's. Neither, precisely — it's **HoloViews'**. The constraint is `hv.DynamicMap` requiring
every frame a callback returns to be the same element type, enforced in HoloViews' own core. This
is confirmed independent of Datashader: a GitHub issue on a completely different type pairing,
`NdOverlay`/`Overlay`, hits the identical `AssertionError: DynamicMap must only contain one type
of object`
([holoviz/holoviews#2359](https://github.com/holoviz/holoviews/issues/2359)) — proving the rule is
general to `DynamicMap`, not specific to `Curve`/`Image` or to Datashader. Panel's role was solely
that it caught the resulting exception and logged it as a `WARNING` instead of surfacing it —
the silent-failure *aggravator*, not the root cause.

Could Datashader be driven without ever hitting this — i.e., wired directly to Bokeh's own
`x_range.on_change`, bypassing `hv.DynamicMap` entirely? Datashader's own docs describe this as
possible but don't demonstrate it:
[datashader.org/getting_started/Interactivity.html](https://datashader.org/getting_started/Interactivity.html)
states "HoloViews encapsulates the Datashader pipeline in a way that lets you combine interactive
datashaded plots easily... without having to write explicit callbacks," implying the raw-Bokeh
path exists but needs "more programming" — no code sample was found to confirm it in this
session (see [Verification gaps](#verification-gaps)). Regardless: the bottleneck Datashader
solves (rendering millions of on-screen points) no longer exists in this pipeline now that
`_minmax_decimate` caps every redraw at 40,000 — so even a working raw-Bokeh Datashader
integration would be solving a problem this project doesn't have anymore. Not recommended.

### Plotly (Python), via Panel's own pane — the strongest non-incumbent Python candidate

The decisive finding: **Panel's own `Plotly` pane already exposes a `viewport` parameter** —
"Current viewport state, i.e. the x- and y-axis limits of the displayed plot. Updated on
`plotly_relayout`, `plotly_relayouting` and `plotly_restyle` events," watchable via
`pn.bind(fn, plotly_pane.param.viewport, watch=True)`, with a `viewport_update_policy` (default
`'mouseup'`) controlling update cadence
([panel.holoviz.org/reference/panes/Plotly](https://panel.holoviz.org/reference/panes/Plotly.html)).
This is first-party evidence in the *exact* framework this project already runs on, arguably
stronger than checking Plotly's own docs in isolation. Corroborated by Plotly's documented
Python-side `FigureWidget` pattern (`fig.layout.on_change(callback, 'xaxis.range')`,
[plotly.com/python/figurewidget](https://plotly.com/python/figurewidget/), via search — direct
fetch of this page returned HTTP 403 in this session) sitting on top of plotly.js's
`plotly_relayout` event.

**Plotly-Resampler as the "bonus" native-resampling answer**: its default algorithm is
`MinMaxLTTB` (1000 points by default), a real analogue to this project's own decimator
([predict-idlab/plotly-resampler README](https://github.com/predict-idlab/plotly-resampler)). But
it explicitly **requires** either a Dash app (`FigureResampler`, server-side callbacks) or an
IPython/Jupyter kernel (`FigureWidgetResampler`) — the README states plainly that `show()`
"*always* generates a static HTML view... prohibiting dynamic aggregation." Panel is neither Dash
nor a Jupyter kernel, so plotly-resampler's own engine does not plug into this project's actual
host without a bigger swap. Practical read: adopting Plotly buys the `viewport` callback (via
Panel's pane, no new dependency needed beyond `plotly` itself), not the resampling — this
project's own `_minmax_decimate` would still do the work, fed by decimated data into a plain
`go.Scatter(mode="lines")`.

**Static export**: `write_image()` via Kaleido, same `Figure` object used interactively — a
genuinely shared code path
([plotly.com/python/static-image-export](https://plotly.com/python/static-image-export/)). One
real caveat: "Figures containing WebGL traces... that are exported in a vector format will
include encapsulated rasters, instead of vectors, for some parts of the image. This is a
fundamental limitation of WebGL," and Plotly Express auto-switches to WebGL above 1,000 scatter
points. At this project's numbers (≤40k points, drawn as an explicit `Scatter`/line trace, not
opted into `Scattergl`) this is avoidable — but it's a trap to name, since the WebGL switch is
automatic in some Plotly Express code paths.

### Matplotlib

`Axes.callbacks.connect('xlim_changed', callback)` is real and stable across matplotlib's history
(confirmed via the API docs and the `viewlims` gallery example,
[matplotlib.org/stable/gallery/event_handling/viewlims.html](https://matplotlib.org/stable/gallery/event_handling/viewlims.html)
— direct fetch returned HTTP 403 in this session, confirmed instead via search excerpt quoting
the same page). The catch: this fires inside an interactive event loop, and matplotlib's default
web-facing path (a static Agg render embedded in a page) has none. The documented way to get a
live, browser-hosted, interactive matplotlib figure is the `ipympl` backend (`%matplotlib widget`)
— "uses the ipywidget framework," designed for "the classic notebook or Jupyter lab" (search
excerpts from matplotlib.org and community sources). Panel does support embedding ipywidgets, but
this means bolting a second interactivity system (Jupyter-widget comms) onto a Bokeh-server app
that already has its own — a real seam, not a clean swap. Static export remains matplotlib's
strongest asset by a wide margin: native SVG/PDF/EPS/PGF via `savefig`, explicit `dpi=`, full font
control via rcParams (confirmed via `matplotlib.pyplot.savefig` API docs).

### VisPy — eliminated

No public range/viewport-changed event was found in VisPy's own API docs for `PanZoomCamera` or
`BaseCamera` ([vispy.org/api/vispy.scene.cameras.panzoom](https://vispy.org/api/vispy.scene.cameras.panzoom.html),
[vispy.org/api/vispy.scene.cameras.base_camera](https://vispy.org/api/vispy.scene.cameras.base_camera.html)):
only internal handler methods (`viewbox_mouse_event`, `view_changed()`) are documented, with no
stated public callback contract — getting the current range would mean polling `camera.rect` or
subclassing, not using a documented API. Independently disqualifying: VisPy has **no vector
export** — screenshots only, via `vispy.io.write_png`; "Output scene to vector graphics" is a
still-open VisPy GitHub issue (#1260). A GPU scenegraph library is also the wrong tool for a
40,000-point 2-D polyline in the first place.

### PyQtGraph — technically the strongest candidate, at the cost of leaving the browser

`ViewBox` documents `sigRangeChanged` (emits `(viewbox, [[xmin,xmax],[ymin,ymax]],
[x_changed, y_changed])`) plus separate `sigXRangeChanged`/`sigYRangeChanged` — confirmed via
pyqtgraph's own readthedocs API reference and source
(`pyqtgraph.readthedocs.io/en/latest/api_reference/graphicsItems/viewbox.html` plus the
`ViewBox.py` source on GitHub, cross-checked via search since the specific signal list wasn't on
the first page fetched). Static export is native and explicitly endorsed for this purpose:
`pyqtgraph.exporters.SVGExporter`, whose docs state SVG export "is the preferred method for
generating publication graphics from PyQtGraph," targeted at Inkscape/Illustrator compatibility
([pyqtgraph.readthedocs.io/en/latest/user_guide/exporting.html](https://pyqtgraph.readthedocs.io/en/latest/user_guide/exporting.html)).

This scores best of every candidate reviewed on both of the ticket's decisive axes. The cost is
architectural, not qualitative: PyQtGraph is a native Qt widget — it does not render in a browser
tab at all. Adopting it means the interface stops being a browser app and becomes a native
PyQt/PySide desktop window. The map issue (#4) keeps this door open ("a non-Python toolchain is
admissible... so is staying on Panel") but a browser-served app is clearly the default assumption
elsewhere in that issue. This is a bigger decision than a plotting-library swap, so this ticket
surfaces it rather than recommending it — it belongs with #12 (the ticket this one blocks).

### Vega-Altair

`JupyterChart` (built on AnyWidget) can report point/index/interval selections back into Python —
confirmed: `jchart.selections.interval.value` reads a live selection after browser-side
interaction
([altair-viz.github.io/user_guide/interactions/jupyter_chart](https://altair-viz.github.io/user_guide/interactions/jupyter_chart.html)).
But the same page is explicit that this requires "environments that support third party Jupyter
Widgets" — Classic Notebook, JupyterLab, VS Code, Colab, Voila are named; **Panel is not**, and no
evidence was found either way for whether Panel's own widget bridge can host an AnyWidget
component outside an actual Jupyter kernel. Treat this as an open risk, not a confirmed fit.
Static export: `chart.save('chart.svg'/'chart.png')` via `vl-convert` needs no extra binary
dependency, but PDF requires the older, less-maintained `altair_saver`
([altair-viz.github.io/user_guide/saving_charts](https://altair-viz.github.io/user_guide/saving_charts.html)).

### uPlot — the JS candidate purpose-built for this shape of data

`opts.hooks.setScale` is an array of callbacks that fire `(u, scaleKey)` after *any* scale change
— including the scale change uPlot itself performs internally after a user drag-zoom — letting
application code read `u.scales[key].min`/`.max` immediately after
(confirmed via uPlot's own GitHub issues/docs excerpts, e.g. issue #82 "Any way to do event
callbacks?" and the hooks examples therein; the canonical `docs/API.md` returned 404 both via
raw.githubusercontent.com and the GitHub blob URL in this session — see
[Verification gaps](#verification-gaps)). uPlot's own README is explicit that it does **not**
decimate for you: under "Non-Features," "No data parsing, aggregation, summation or statistical
processing - just do it in advance"
([raw README fetch](https://raw.githubusercontent.com/leeoniya/uPlot/master/README.md)) — which
is exactly this project's existing architecture (decimate in Python/numpy, hand uPlot the
already-reduced series). Community-reported performance (treated as secondary, not vendor-primary,
evidence, but consistent across multiple independent sources) puts ~166k points at ~25ms initial
render and comfortable 60fps live updates at thousands of points — well inside this project's
40k-point ceiling. No SVG/vector export path is documented anywhere in uPlot's README or docs —
canvas-only, confirmed by the same README fetch ("uPlot is a Canvas 2D-based chart" with no export
section beyond that). A JS-frontend choice built on uPlot would need a **separate** tool
(server-side matplotlib/Bokeh, or a hand-built SVG re-render) for publication figures — exactly
the cost the ticket asks to flag explicitly.

### Plotly.js, ECharts, D3/d3-zoom, Observable Plot, Lightweight Charts

- **Plotly.js**: same engine Panel's Plotly pane already wraps; `plotly_relayout` is the
  underlying JS event the Python-side `viewport` param subscribes to. Not independently
  re-fetched against a JS-specific doc page this session — treated as the same mechanism already
  confirmed above via Panel.
- **ECharts**: `chart.on('dataZoom', callback)` is documented
  ([apache.github.io/echarts-handbook/concepts/event](https://apache.github.io/echarts-handbook/en/concepts/event/)),
  with a real, independently-confirmed wrinkle: the event payload's `start`/`end` (percent) are
  always populated, but `startValue`/`endValue` (the absolute values actually wanted) are *not*
  populated when the zoom is triggered by the slider component, only by the toolbox — confirmed
  across three separate upstream GitHub issues
  ([#10700](https://github.com/apache/echarts/issues/10700),
  [#10381](https://github.com/apache/incubator-echarts/issues/10381),
  [echarts-for-react#365](https://github.com/hustcc/echarts-for-react/issues/365)). The documented
  workaround is reading `chart.getOption().dataZoom[0]` inside the handler regardless of trigger
  source — a real but minor extra step, not a disqualifier. ECharts also natively supports an SVG
  renderer mode (`echarts.init(dom, null, {renderer: 'svg'})`,
  [apache.github.io/echarts-handbook/best-practices/canvas-vs-svg](https://apache.github.io/echarts-handbook/en/best-practices/canvas-vs-svg/)),
  the only JS candidate reviewed with a *native* (not bolted-on) vector-output mode — though the
  same docs recommend canvas, not SVG, once a series exceeds ~1,000 points, meaning the
  interactive view (canvas) and the publication export (SVG) would use different renderer configs
  set at `init()` time, not simultaneously.
- **D3 / d3-zoom**: `selection.call(d3.zoom().on('zoom', event => ...))` hands back
  `event.transform`, and `transform.rescaleX(xScale)` produces a new scale whose domain *is* the
  current visible range — textbook, confirmed directly against
  [d3js.org/d3-zoom](https://d3js.org/d3-zoom). Because D3 draws real SVG DOM nodes, the
  interactive view and a "static export" are the same artifact — there is no separate export
  step, no separate library, and no scenegraph-type constraint of the kind that broke
  HoloViews/Datashader, because D3 has no scenegraph at all to enforce one. The cost is that D3 is
  a framework, not a chart: axes, legends, the filmstrip layout, and the decimator hookup are all
  hand-built. uPlot, ECharts, and Lightweight Charts are all, at bottom, pre-built answers to the
  same problem D3 leaves open.
- **Observable Plot**: pan/zoom is **not shipped**. Checked directly against GitHub's issue
  tracker rather than a secondary write-up: `gh api repos/observablehq/plot/issues/1590` returns
  `"state": "open"`, `"title": "Panning and zooming"`, `"updated_at": "2024-11-01"` — a feature
  request open for nearly two years as of this research (September 2026), describing exactly the
  capability needed ("altering the scale domains and then re-rendering the plot") as *not yet
  built*. The maintainers' own documented workaround is bolting on `d3-zoom` manually
  ([observablehq.com/plot/features/interactions](https://observablehq.com/plot/features/interactions)
  and community threads) — i.e., you get D3's mechanism, not Plot's, so Plot adds API surface
  without adding capability on this axis. Its one genuine, independently-confirmed strength: the
  best facet/small-multiples system of any candidate reviewed —
  [observablehq.com/plot/features/facets](https://observablehq.com/plot/features/facets)
  documents `fx`/`fy` facet channels with automatic wrapping, directly relevant to the seven
  heterogeneous interchange types — but that strength doesn't offset the disqualification on the
  decisive axis.
- **Lightweight Charts** (TradingView): the single best-documented viewport API of any candidate
  reviewed, Python or JS. `ITimeScaleApi.subscribeVisibleTimeRangeChange()` and
  `.subscribeVisibleLogicalRangeChange()` are both first-party documented, the latter handing back
  `{from, to}` as plain numeric indices —
  [tradingview.github.io/lightweight-charts/docs/api/interfaces/ITimeScaleApi](https://tradingview.github.io/lightweight-charts/docs/api/interfaces/ITimeScaleApi) —
  which is structurally identical to what `x_range_to_sample_bounds` (`UI/plots.py:383`) already
  computes and needs handed back in. Same static-export gap as uPlot: canvas-only, no vector
  export path found. Multi-pane support (reportedly added around v4) was not independently
  verified this session.

### WebGL-generic and canvas-direct

Not evaluated as named products beyond what's already covered under Plotly (`Scattergl`) and
uPlot's canvas path. General, lower-confidence finding: there is no universal "viewport changed"
event at the WebGL level — it's whatever bookkeeping the specific library layers on top, which is
exactly what's already been checked for each named candidate above. Given this project's
already-solved 40k-point ceiling, a bespoke WebGL/GPU path adds real engineering cost against a
scaling problem that no longer exists — down-weighted per the ticket's own framing. Hand-rolled
canvas-direct trivially satisfies Q2 and Q3 by construction (you write the event handler, so you
always know the range, and there's no framework layer to fail silently) but provides zero
batteries — axes, legends, facets, and export are all bespoke code, a real cost against this
project's "agent-driven development speed" criterion (map issue #4, Constraints section).

---

## Shortlist, by frontend family

**Stay on Panel/Bokeh (smallest change).** The incumbent `RangeX`/`Curve`-only mechanism is
proven in production and should not be replaced reflexively. If the export-quality gap (no native
PDF, headless-browser dependency, SVG perf ceiling) becomes a real problem, **Plotly via Panel's
`Plotly` pane** is the lowest-risk swap within the same frontend family: it keeps Panel as the
server, trades HoloViews' DynamicMap type trap for a differently-shaped (unverified either way)
risk, and its `viewport` param is already a first-party Panel feature — confirmed, not inferred.

**Leave Panel for a JS-rendered frontend (bigger change, if #12 decides the stack moves).**
**uPlot** is the strongest fit for the core signal view: built for exactly this data shape, a
confirmed viewport hook, explicitly no built-in decimation (i.e., no architectural conflict with
this project's own `_minmax_decimate`). **Lightweight Charts** has the cleanest-documented
viewport API of anything reviewed and a range shape that maps directly onto
`x_range_to_sample_bounds`. Both share the same gap: no vector export, so publication figures
would need a second tool regardless — a real, stated cost, not a hidden one. **ECharts** is the
one JS candidate with a *native* SVG mode, trading a slightly re-derived zoom-event payload for a
single library that can plausibly cover both the interactive and static jobs. **D3** underlies all
three and is the fallback if none of the pre-built options fit — most control, most to build,
interactive and static output are provably identical since both are the same SVG DOM.

**Leave the browser entirely.** **PyQtGraph** outscored every other candidate on both of the
ticket's decisive axes (`sigRangeChanged` plus docs that call its SVG exporter "the preferred
method for generating publication graphics"). It is not recommended by this ticket only because
it is not a plotting-library decision — it is a decision to stop being a browser app, which is
squarely #12's call to make, not this ticket's.

**Eliminate:** VisPy (no confirmed viewport API, no vector export), Datashader (already tried,
already removed, and no longer solves an existing problem), Observable Plot for the decisive axis
(pan/zoom unshipped, confirmed via the open GitHub issue), Vega-Altair for the decisive axis in
this specific host (Jupyter-shaped, not confirmed in Panel), Matplotlib for the decisive axis in a
non-Jupyter browser context (real API, wrong host without `ipympl`).

---

## Verification gaps

Named explicitly, per the ticket's request for honesty about what documentation alone couldn't
confirm:

- **VisPy**: absence of a public viewport-changed event is based on the official API pages for
  `PanZoomCamera` and `BaseCamera` not documenting one — not a source-level audit of the whole
  event system, which might reveal an undocumented path.
- **PyQtGraph `sigRangeChanged`**: confirmed via pyqtgraph's own docs/source, but the specific
  page fetched in this session (`viewbox.html`) did not itself list the signal; the exact
  signature was corroborated via search results quoting the same official docs and source tree
  rather than a single direct fetch of the page containing it.
- **Datashader driven directly from Bokeh's own `x_range.on_change`, bypassing HoloViews'
  `DynamicMap` entirely**: plausible and implied by Datashader's own docs, but no working code
  sample was found or fetched in this session to confirm it avoids the type-consistency trap in
  practice.
- **Plotly.js-specific `plotly_relayout` documentation**: not independently fetched against a
  JS-only doc page; treated as identical to the mechanism already confirmed via Panel's Plotly
  pane and the Python `FigureWidget` docs, since both wrap the same underlying plotly.js.
- **uPlot's canonical `docs/API.md`**: returned HTTP 404 from both
  `raw.githubusercontent.com` and the GitHub blob URL in this session (repository layout may have
  moved it); the `hooks.setScale` mechanism was confirmed instead via uPlot's GitHub issues and
  maintainer examples, which is corroborating but not the primary API reference page itself.
- **Lightweight Charts multi-pane layouts**: reported to exist as of v4 in general awareness, not
  checked against a fetched primary source this session.
- **ECharts SVG-renderer performance specifically at ~40,000 points**: the "use canvas above
  ~1,000 points" guidance is general product guidance, not a benchmark run against this project's
  actual numbers.
- **Matplotlib's `viewlims` gallery page and the `plotly.com/python/figurewidget` page**: both
  returned HTTP 403/size-limit errors on direct fetch in this session; the relevant facts were
  recovered via search-engine excerpts of the same official pages rather than a direct render.
- **Vega-Altair `JupyterChart` inside Panel specifically**: no source, official or otherwise, was
  found either confirming or denying that Panel can host an AnyWidget-based component outside an
  actual Jupyter kernel process — flagged as an open risk, not resolved.
- **WebGL-generic category** (deck.gl, regl, raw WebGL2, Plotly `Scattergl` beyond what's already
  covered): not evaluated as individually named products; the "no universal viewport event" claim
  is a structural inference from how every named library in this table implements its own
  callback, not a survey of GPU-plotting libraries specifically.

---

*Research conducted 2026-09-10 for issue #7. Primary sources cited inline throughout; where a
direct fetch failed, the fallback source and its limitation are stated at the point of use.*
