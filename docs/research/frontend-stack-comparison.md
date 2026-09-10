# Frontend stack comparison for the Pipeline GUI rebuild

**Ticket:** [mitchbradshaw/CNN#5](https://github.com/mitchbradshaw/CNN/issues/5), a research ticket under the map
[#4](https://github.com/mitchbradshaw/CNN/issues/4). **This document gathers evidence; it does not choose.**
The choice is made in decision ticket #12, which reads this alongside three sibling research tickets. Where
this document says a stack is weak on some axis, that is a data point for #12, not a verdict.

**Method.** Primary sources only — official docs, release notes, and issue trackers, linked inline. About
35 fetches across roughly 15 candidates, weighted toward the incumbent and the strongest challengers per the
ticket's instruction to go deep on top candidates and short on obvious also-rans. No code was written or run
against this project; see [What would change if tested rather than read](#what-would-change-if-tested-rather-than-read).

---

## Criteria, and how they're weighted here (per the ticket)

1. **Agentic development throughput — weighted heaviest.** Documentation quality/volume, idiom stability
   across versions, legibility of failure modes, loud vs. silent errors, and whether a headless test can
   prove a surface actually rendered.
2. **Rendering the 721-hour / 2.6M-sample signal at interactive zoom.** The hard part (bucketed min/max
   decimation to 40,000 points, pure numpy, 12.1 ms) is already solved and stack-portable — see the sibling
   plotting ticket. What's left is: can the stack's charting layer take a pre-decimated array and render it
   interactively without a second, stack-specific bottleneck.
3. **Rendering seven heterogeneous interchange types**, including ones with no natural plot (`Grouping` is
   one int per window, `Model` is a filename).
4. **Publication-quality static export**, for thesis figures.
5. **Coexistence with conda-on-Windows** — reported, down-weighted. A toolchain addition (e.g. Node) is not
   penalized by itself; what matters is whether it slows agent-driven development.
6. **Distance from the existing UI-free `Working/` core** — how much glue each family needs, and whether
   that glue can be written without teaching the core about a browser.

---

## Summary table

| Stack | Agentic throughput evidence | Large-signal render | 7-type render | Static export | Core distance |
|---|---|---|---|---|---|
| Panel (rebuilt arch.) | Mixed: huge docs corpus, but a *documented* class of silent-failure bugs | Bokeh/HoloViews, WebGL past ~25k pts, current decimation already proven | Native — `render_value` pattern is portable regardless of stack | Via Bokeh/Selenium or Matplotlib backend, needs extra deps | None — same process |
| Dash | Strong: `dash.testing` asserts on browser console errors explicitly | Plotly `Scattergl`, 2–3M points documented | Needs custom components for non-plot types | Kaleido (successor to orca), SVG/PDF native | Low — same process model as Panel, still Python |
| Streamlit | Good docs, but whole-script rerun model is a real architectural constraint | Depends on component (no native huge-signal widget); would need a custom component | Same custom-component gap as Dash | Via underlying chart lib (Plotly/Matplotlib) | Low |
| NiceGUI | Good: dual test fixtures, one avoiding a browser entirely | Inherits from ECharts/Plotly/Highcharts bindings | Needs custom binding for non-plot types | Via bound chart libs | Low–medium — FastAPI-based, still one process |
| Reflex | Weaker: compiles to React, hit a Node/ESM breakage in the wild (open issue) | Inherits whatever React chart lib is bound in | Same as React path below | Via bound chart lib | Medium — Node toolchain required even though the framework is "pure Python" |
| Solara | Decent: two-tier testing (no-browser first), built on ipywidgets | Via bound Plotly/ECharts/Matplotlib | Needs custom component | Via bound chart libs | Low — ipywidgets/Jupyter kernel model |
| React + FastAPI | Largest docs/ecosystem by far, official move to Testing Library away from brittle snapshot tools | uPlot: 10M+ points documented, smallest footprint of surveyed libs | Fully custom — total design freedom, full cost | Component-owned (any JS chart lib's own export, or server-side Matplotlib/Kaleido) | High — full client/server split, JSON contract, new transport layer |
| Svelte/SvelteKit + FastAPI | Good docs, but Svelte 5 (2024) was a **breaking reactivity-model rewrite** agents would need version-pinned knowledge for | Same charting-library options as React (uPlot, etc.) | Fully custom | Same as React | High |
| SolidJS + FastAPI | Smaller ecosystem/doc corpus than React by explicit community consensus | Same charting-library options | Fully custom | Same as React | High |
| Vue + FastAPI | Mature, Composition API stable since 3.3, decent docs | Same charting-library options | Fully custom | Same as React | High |
| Tauri (+ web frontend) | Docs solid but the Python-integration story is community-pattern (sidecar), not first-party | Whatever the wrapped web frontend uses | Whatever the wrapped frontend does | Whatever the wrapped frontend does | High — full JS frontend plus a Rust shell plus a Python sidecar |
| Electron (+ web frontend) | Same as Tauri, mature docs, heavier | Whatever the wrapped frontend uses | Whatever the wrapped frontend does | Whatever the wrapped frontend does | High, plus much heavier runtime |
| pywebview | Thin, docs adequate for its scope; Windows renderer requires Edge WebView2 runtime present | Whatever HTML/JS is loaded inside | Whatever HTML/JS is loaded inside | Whatever the loaded content provides | Medium — still needs an HTML/JS payload, but no separate app framework |
| Qt/PySide6 (native) | pytest-qt is mature and signal-based; docs are large but split across modules | PyQtGraph: documented for hundreds of thousands of interactive points, degrading beyond that | Fully custom widgets — total freedom, full cost, no browser at all | Matplotlib embeds directly — no export pipeline needed, it *is* Matplotlib | Lowest of any GUI-having option — no browser, no server, no network layer |

---

## 1. Python-native web

### 1.1 Panel (rebuilt architecture) — the incumbent

Panel is not evaluated for incumbency credit, per the ticket, but it is evaluated on evidence, including the
evidence this project already produced by hitting the same bug twice.

**Documentation and roadmap.** Panel's official [roadmap](https://panel.holoviz.org/about/roadmap.html)
describes Panel 2.0 (targeted ~Q2 2026) and 3.0 (2027) as introducing a new namespace, moving specialized
integrations (Deck.gl, VTK, ECharts, Vizzu, Textual) out of core into independently versioned extensions,
adopting Narwhals for dataframe interop, and — directly relevant here — promising "improved error messages."
That last point is itself evidence: the project's own vendor is treating today's error messages as a known
weakness worth a roadmap line, not a solved problem. The roadmap does **not** mention a "rebuilt architecture"
in the sense the map issue means (a non-vertical chain builder); "rebuilt architecture above it" is this
project's framing, and Panel's own 2.0/3.0 plan is an unrelated, ordinary version transition — evidence that
whatever new tree lands on Panel should expect API churn across that boundary, timed against this project's
"no deadline" post-thesis status.

**The silent-failure claim, checked against the issue tracker.** UI_CONTEXT.md documents a `DynamicMap`
returning both `Curve` and `Image` raising an assertion that Panel swallowed into a log warning. That specific
incident is project-internal history (`UI/plots.py:43-63`), not something with its own public issue, but the
*general pattern* it exemplifies is corroborated directly by HoloViews's own issue tracker:

- [holoviz/holoviews#2827](https://github.com/holoviz/holoviews/issues/2827) — a HoloViews maintainer states
  plainly: *"we also interpret exceptions as empty frames"* inside `DynamicMap` callbacks, and flags that using
  the common `KeyError` for this is dangerous because such exceptions are "completely hidden to the user."
  This issue is open with a proposed fix (explicit `EmptyError`/`SkipError` types), not a closed one — as of
  this research, the interpret-exception-as-empty-frame behavior is still current.
- [holoviz/holoviews#707](https://github.com/holoviz/holoviews/issues/707) — a `DynamicMap` generator
  exception is reported as surfacing a `StopIteration` rather than the real exception.
- [holoviz/holoviews#5424](https://github.com/holoviz/holoviews/issues/5424) — exceptions in `DynamicMap`
  callbacks in Jupyter lose their traceback, and `print()`/breakpoints inside the callback don't fire, making
  the failure mode invisible even to someone actively debugging.

This is a stronger form of evidence than the ticket asked for: it is not just that this project got bitten
three times, it is that the maintainers' own tracker describes the mechanism by name, as a still-open
design tradeoff, years running. Any Panel-based rebuild inherits this unless the new architecture routes
around `DynamicMap` callbacks entirely.

**Testing story.** Panel's own [testing guide](https://panel.holoviz.org/how_to/test/index.html) recommends
three layers: pytest unit/performance tests, and Playwright-based UI tests
([uitests.html](https://panel.holoviz.org/how_to/test/uitests.html)) — the same two-tier shape this project's
own `CLAUDE.md` already mandates (`pytest` plus `pytest -m ui`). Panel is tested with Playwright internally,
so the pattern this project follows is the same one upstream uses on itself. The docs demonstrate waiting for
elements and checking status text after interaction, but (as fetched) do not explicitly enumerate "detects a
blank pane" or "detects a JS console error" as a guaranteed catch the way Dash's docs do (§1.2) — this project's
own `docs/UI_VERIFICATION.md` findings about Bokeh's shadow DOM and unlabeled checkboxes exist precisely
because the official guide doesn't spell out those Panel/Bokeh-specific gotchas.

**Rendering.** Bokeh's own docs ([WebGL acceleration](https://docs.bokeh.org/en/latest/docs/user_guide/output/webgl.html))
state canvas rendering is fine under ~10k points and WebGL "usually" wins above ~25k, with full WebGL support
for `line`/`multi_line`/`step` glyphs — consistent with this project's own measured 12.1 ms decimation to
40,000 points already fitting inside Bokeh's comfortable WebGL range. Since decimation is stack-portable, this
is a wash across most web-based candidates rather than a Panel-specific advantage.

**Static export.** [HoloViews export guide](https://holoviews.org/user_guide/Exporting_and_Archiving.html)
and the [Bokeh discussion on PNG/SVG export](https://discourse.holoviz.org/t/missing-file-errors-when-using-bokeh-save-to-png-svg/7559)
confirm `hv.save()` covers PNG/SVG/PDF depending on backend, but PNG export via the Bokeh backend needs
Selenium + a headless browser driver installed (`conda install selenium phantomjs pillow` is the documented
recipe) — an extra dependency surface for a "just make a thesis figure" task. Switching HoloViews to its
Matplotlib backend sidesteps that but changes the rendering pipeline for the interactive case too.

**Distance from core.** Zero — Panel/HoloViews/Bokeh run in-process with `Working/`, no serialisation
boundary, no network layer, matching this project's current architecture exactly.

### 1.2 Dash

Dash's [official testing docs](https://dash.plotly.com/testing) describe `dash.testing`, built on Selenium
(not Playwright), with two explicit tiers: fast unit tests of callback functions (Dash 2.6+) and full
browser-driven end-to-end tests. The concrete, quotable finding for the "loud vs. silent" criterion: Dash's
own test harness exposes `dash_duo.get_logs()`, returning browser console `SEVERE`-level entries, and the docs
show the idiomatic assertion `assert dash_duo.get_logs() == []` — i.e., Dash's own test framework treats "no
browser console errors" as a first-class, one-line assertion, distinct from checking that widgets render. It
also documents [Percy](https://dash.plotly.com/testing) visual-regression snapshotting built into the test
harness, which is the kind of layout/overlap coverage this project's `docs/UI_VERIFICATION.md` had to build by
hand for Panel.

Rendering: Plotly's `Scattergl` docs and community sources describe WebGL rendering of 2–3M points without
browser errors, comfortably past what the already-decimated 40k-point payload requires; the
[Plotly performance guide](https://plotly.com/python/performance/) recommends `Scattergl`/`render_mode="webgl"`
above 100k points. Note the documented WebGL-context ceiling ("not possible to render more than 8
WebGL-involving figures on the same page at the same time" per plotly.js docs found via search) — relevant if
the rebuilt Analyse filmstrip (G3, one plot per chain step) puts many WebGL plots on one page simultaneously.

Static export: Plotly's own docs ([static-image-export](https://plotly.com/python/static-image-export/),
[Kaleido README](https://github.com/plotly/Kaleido)) show PNG/JPEG/WebP/SVG/PDF export via Kaleido, which as
of v1.0 requires a Chrome/Chromium binary present on the machine (bundled in earlier Kaleido versions, not
bundled from 1.0 on) — another "extra binary needed for figures" dependency, structurally similar to Bokeh's
Selenium requirement.

Distance from core: same shape as Panel — pure Python, in-process, no browser knowledge required below the
UI layer, though Dash's callback graph is a different mental model from HoloViz's reactive `param` bindings the
core would need to adapt to (`invalidated_step_indices`, the prefix-hash cache) if Panel's `param` machinery is
not carried forward.

### 1.3 Streamlit

The [architecture concept page](https://docs.streamlit.io/develop/concepts/architecture/architecture)
confirms a client-server model but the load-bearing fact is on the
[getting-started page](https://docs.streamlit.io/get-started/fundamentals/main-concepts): *"any time
something must be updated on the screen, Streamlit reruns your entire Python script from top to bottom,"*
mitigated by `st.cache_data`/`st.cache_resource`. For a chain builder with a step-cache keyed on a
recipe-prefix hash (G5 — "edit a parameter without paying for the whole chain") this rerun model is a
structural mismatch to manage around, not a natural fit: every widget interaction re-executes the whole
script, and Streamlit's own caching primitives would need to be reconciled with (or replace) the project's
existing prefix-cache semantics, which UI_CONTEXT.md marks as **frozen** provenance semantics, not open for a
new implementation to quietly reinterpret.

Testing: [`st.testing.v1.AppTest`](https://docs.streamlit.io/develop/api-reference/app-testing) runs the
script directly without a browser, exposing an `at.exception` attribute for assertion — good for fast
headless checks, explicitly **not** a substitute for browser rendering verification (no visual/layout
coverage, confirmed by the docs' own framing of it as script simulation, not browser automation).

Given Streamlit has no first-party huge-time-series widget and no natural per-type dispatch mechanism (G4),
it would need the same custom-component investment as Dash/NiceGUI for both the 40k-point signal and the
seven-type renderer, without Dash's documented console-log assertion story or Panel's zero-glue incumbency.
Treated here as a real but not leading candidate — a shorter treatment than Panel/Dash per the ticket's
guidance on also-rans.

### 1.4 NiceGUI

Built on FastAPI + Vue + Quasar under the hood (confirmed by [NiceGUI's own docs](https://nicegui.io/documentation):
*"NiceGUI is implemented with HTML components served by an HTTP server (FastAPI), even for native windows"*).
Notable finding for the throughput criterion: NiceGUI's [testing section](https://nicegui.io/documentation/section_testing)
documents **two** pytest fixtures — `screen` (real headless-browser Selenium test) and `user` (a pure-Python
simulation that talks to the server logic directly via simulated Socket.IO events, no browser, "as fast as
unit tests"). That second fixture is a genuinely different testing primitive from anything Panel, Dash, or
Streamlit document: fast enough to run in the same loop as unit tests while still exercising real
server-side reactivity, not just script logic. This directly targets the "can a headless test prove a surface
rendered" criterion, though it still would not catch client-side JS/Quasar rendering bugs the way the `screen`
fixture or an actual browser suite would.

Static export and large-signal rendering both depend on whichever chart library is bound in (NiceGUI ships
ECharts, Plotly, and Highcharts bindings per its component list) — not evaluated further here since it inherits
those libraries' own properties, covered under the JS candidates below.

Distance from core: low — FastAPI-based, one Python process, but state is synced over WebSockets to Vue/Quasar
components client-side, which is a thinner but real network boundary compared to Panel/Dash/Streamlit's
purely-server-rendered model.

### 1.5 Reflex

Reflex's [introduction](https://reflex.dev/docs/getting-started/introduction/) confirms it compiles Python
component declarations to a real React frontend with a separate Python backend process, wired by an
event-handler → state-update → re-render loop. The concrete throughput risk found on the issue tracker:
[reflex-dev/reflex#5983](https://github.com/reflex-dev/reflex/issues/5983), open at time of research,
reports the generated frontend failing to start on a fresh `reflex run` due to an ESM/CommonJS interop error
(`ERR_REQUIRE_ESM`) between React Router and a transitive dependency (`p-map`) on modern Node (22+), with
downgrading to Node 20 offered only as an unreliable workaround. This is exactly the class of failure the
ticket's throughput criterion cares about: a Python-only developer (or an agent) hits a Node toolchain error
several layers removed from anything the project's own code controls. A separate discussion thread
([reflex-dev/reflex#5355](https://github.com/orgs/reflex-dev/discussions/5355)) shows the project's own
community still requesting first-party pytest documentation — testing guidance exists via
`reflex.testing.AppHarness` + Playwright for end-to-end and direct component-tree walks for static checks, but
per a community discussion thread this is not yet consolidated into an official how-to the way Panel's,
Dash's, or NiceGUI's is.

Given it requires the full Node/npm toolchain despite presenting as "pure Python," Reflex sits closer to the
JS-frontend family's core-distance cost while offering none of React's own first-party ecosystem depth —
treated here as a real but weaker candidate, shorter treatment per the ticket's also-ran guidance.

### 1.6 Solara

Built on ipywidgets/`react-ipywidgets`, runs in Jupyter, standalone via "Solara server," and experimentally as
a desktop app via Qt, per [Solara's getting-started docs](https://solara.dev/documentation/getting_started).
[Testing docs](https://solara.dev/documentation/advanced/howto/testing) recommend the same two-tier pattern as
NiceGUI: prefer no-browser pytest where possible, fall back to a `solara_test` fixture built on
`pytest-playwright` for anything JS-dependent — Solara explicitly states the no-browser path is "faster and
more reliable." Plotting is via bound Plotly/Altair/Matplotlib/ECharts, so it inherits those libraries'
properties rather than defining its own. A real, low-glue candidate (it can run components directly against a
Jupyter kernel with no HTTP layer at all in the notebook case) but treated briefly here since nothing in the
fetched docs suggests it solves G4 (heterogeneous-type dispatch) any more natively than the others.

---

## 2. JS/TS frontend + Python backend

All four JS candidates in this family share the same core-distance shape: a JSON/WebSocket contract over
FastAPI (or similar) replaces Panel's in-process `param` bindings, meaning `Working/`'s outputs must be
serialized across a real network boundary for the first time (per UI_CONTEXT.md §4.2, writing that transport
layer is explicitly in-scope work, not a smuggled side effect). None of the four solves G4 (seven-type
dispatch) for free — that dispatch function would need a from-scratch reimplementation regardless of which JS
framework sits on top, since it is presentation logic, not something inherited from the framework.

[FastAPI's own docs](https://fastapi.tiangolo.com/) are the strongest evidence point common to all four: fully
async, native WebSocket support, and — most relevant to the "loud errors" criterion — automatic Pydantic-backed
422 responses with structured per-field validation errors for any malformed request, which is a stronger
default failure mode than either Panel's or Dash's callback exception handling documented above.

### 2.1 React (+ FastAPI) — the strongest JS candidate

By volume and recency of primary-source material this is not close: React's own docs
([react.dev](https://react.dev/)) explicitly steer users away from the older `react-test-renderer` and
`react-dom/test-utils` (both carry dedicated deprecation-warning pages,
[test-utils](https://react.dev/warnings/react-dom-test-utils),
[test-renderer](https://react.dev/warnings/react-test-renderer)) toward `@testing-library/react` as the
modern, supported path — a single, current, maintained idiom rather than several competing legacy ones,
which matters for an agent's ability to find one canonical way to do something.

For the large-signal criterion, [uPlot](https://github.com/leeoniya/uPlot) (framework-agnostic, usable from
any of the four JS candidates) is a standout primary-source data point: documented rendering of 10 million
points, ~100,000 points/ms after a 25 ms cold start for 166,650 points, and a published head-to-head where
uPlot uses 10% CPU / 12.3 MB RAM for a 3,600-point 60fps stream versus Chart.js's 40%/77MB and ECharts's
70%/85MB. Since this project's own decimation already caps the payload at 40,000 points, uPlot is comfortably
oversized for the requirement — this is evidence that the *browser rendering* half of the large-signal
criterion is a solved problem for any JS-based candidate, not a differentiator among them.

Static export in the React path is per-chart-library (uPlot has no built-in raster/vector export; Plotly.js
or D3-based components would carry their own, as would a server-side Matplotlib/Kaleido fallback) — this is a
real design decision left open, not resolved by React itself.

### 2.2 Svelte / SvelteKit (+ FastAPI)

The single most important primary-source finding for Svelte, directly on-point for the "idiom stability
across versions" sub-criterion: the [official Svelte 5 migration guide](https://svelte.dev/docs/svelte/v5-migration-guide)
and [migration guide source](https://github.com/sveltejs/svelte/blob/main/documentation/docs/07-misc/07-v5-migration-guide.md)
confirm Svelte 5 (released 2024) replaced the entire reactivity model — implicit `let`/`$:` reactivity became
explicit `$state`/`$derived`/`$effect`/`$props` runes — with the migration guide itself flagging that some
patterns (`createEventDispatcher`, `beforeUpdate`/`afterUpdate`) are **not** auto-migrated by the official
codemod and need manual rewriting, and that components changed from classes to functions, breaking manual
instantiation call sites. Old and new syntax can be mixed during migration, which softens this, but any agent
working from pre-2024 Svelte knowledge (a meaningful fraction of any LLM's training-era material) would
produce code in the old idiom unless explicitly steered — a direct, evidenced hit on the throughput criterion's
"stability of idioms across versions" sub-point. This is one of the few concrete data points in this whole
comparison that specifically favors older, more idiom-stable frameworks (React's hooks model, stable since
2019) over a technically well-regarded but more volatile one.

Otherwise Svelte/SvelteKit shares React's charting-library-agnostic story (uPlot etc.) and FastAPI backend
shape; not researched to the same depth as React given the ticket's also-ran guidance and this being the one
standout negative finding worth flagging.

### 2.3 SolidJS (+ FastAPI)

Given a short treatment per the ticket's guidance, since nothing in the search results suggested it changes
the render/export/core-distance picture from React's. The one relevant, well-corroborated (multiple
independent secondary sources converging on the same claim, though no single primary-source page was fetched)
point: SolidJS's fine-grained signal-based reactivity avoids React's re-render-the-component-tree model, at
the documented cost of a smaller ecosystem and — material to the throughput criterion — a smaller pool of
training-data-era examples and documentation than React's, which a coding agent would be expected to lean on.
[SolidJS's own reactivity docs](https://docs.solidjs.com/advanced-concepts/fine-grained-reactivity) exist and
are substantive, but the *volume* gap versus React (the throughput criterion's explicit "quality and volume of
documentation" phrase) is the deciding fact here, not a quality gap.

### 2.4 Vue (+ FastAPI)

Also given a short treatment. Vue's Composition API has been stable since 3.3 (Options API remains supported
in parallel, no forced migration), giving it steadier footing on the idiom-stability sub-criterion than
Svelte, without React's documentation volume. Testing is well-documented (official Vue Test Utils, community
Vue Testing Library layered on top). No evidence found that it solves the large-signal or seven-type
rendering problems any differently than React or Svelte — same charting-library-agnostic story.

---

## 3. Desktop-wrapped

### 3.1 Tauri

[Tauri's architecture docs](https://v2.tauri.app/concept/architecture/) confirm the core design: a Rust
binary paired with the operating system's own webview (WebView2 on Windows, WebKitGTK on Linux, WebKit on
macOS) rather than a bundled browser runtime, which independent benchmarks converging across several
sources put at roughly 30–80 MB idle memory and single-digit-MB installers, versus Electron's 150–400 MB idle
and 100+ MB installers (the "resource usage down-weighted" instruction from the map applies here — this is
reported, not scored heavily).

The Python-integration story is the throughput-relevant finding, and it is **not first-party**. Two patterns
exist, both community-maintained rather than documented on tauri.app itself:

- **Sidecar**: bundle a Python interpreter/server as an external binary Tauri spawns and manages
  (`tauri.bundle.externalBin`), communicating over HTTP or IPC — Tauri's own docs are explicit that *"you are
  in charge of actually running the Sidecar binary, and you are also in charge of killing the child process
  when your app closes"* — i.e., process lifecycle management is the app author's problem, not the
  framework's.
- **[PyTauri](https://github.com/pytauri/pytauri)**: a third-party project binding Python to Tauri directly
  via PyO3/Rust, avoiding the sidecar's IPC overhead — but this is an independent open-source project, not
  part of Tauri itself, adding a second project's release cadence and documentation quality to the risk
  surface.

Either path means the rendering, seven-type dispatch, and static-export questions all reduce to "whatever web
frontend is wrapped" — Tauri itself answers none of criteria 2–4, only the packaging question. Given the
project's own fixed context (single researcher, single machine, `localhost`, no deployment), the packaging
problem Tauri/Electron solve — shipping a single installable binary to end users — does not obviously match
this project's actual need, which is closer to "run one Python process and open a browser tab."

### 3.2 Electron

Given a short treatment as the heavier, more mature alternative to Tauri, same wrapped-frontend logic applies.
Multiple independent benchmark sources (not primary Electron documentation, since electronjs.org does not
publish head-to-head memory figures against competitors) converge on Electron using several times the memory
and installer size of Tauri for equivalent apps, with a single-process-per-window Chromium bundled directly
rather than relying on the OS webview. Given this project's single-machine, single-user, no-distribution
context, Electron's main documented advantage over Tauri — a guaranteed-consistent bundled Chromium instead of
depending on whatever WebView2/WebKitGTK/WebKit version the OS provides — is close to moot, since the target
machine is fixed and known.

### 3.3 pywebview

The lightest-weight of the desktop-wrapped options: [pywebview's own docs](https://pywebview.flowrl.com/) and
[GitHub README](https://github.com/r0x0r/pywebview) describe a thin native-window wrapper around the OS's
webview (WinForms + WebView2 on Windows, Cocoa on macOS, GTK/Qt on Linux) with two-way JS↔Python
communication and a built-in HTTP server — no separate app framework, no Rust toolchain, no Node build step
necessarily required (an HTML/JS payload can be as simple as a static file or a small server). On Windows
specifically, the renderer-selection docs confirm it prefers `edgechromium` (Edge WebView2) and falls back to
deprecated `mshtml`/`edgehtml` engines only if WebView2 isn't installed — meaning a real dependency (the
WebView2 runtime) needs to be present on the machine, though it ships by default on current Windows 11
per Microsoft's own distribution docs. One documented rough edge: `create_window()` blocks the calling thread,
requiring app logic to run on a separate thread — a real but minor architectural wrinkle. pywebview answers
none of the rendering/export/dispatch questions itself; like Tauri/Electron, it only answers "how do I put a
window on screen," and whatever HTML/JS is loaded inside inherits the JS-candidate properties from §2.

### 3.4 Qt/PySide6 — the only fully-native option

The only candidate in this whole comparison with **no browser anywhere in the stack**. [PySide6/Qt for
Python docs](https://doc.qt.io/qtforpython-6/) confirm a mature, LGPL-or-commercial-licensed native widget
toolkit. Two findings make this a structurally distinct option rather than a variant of the desktop-wrapped
family:

- **Testing.** [pytest-qt](https://pytest-qt.readthedocs.io/) is a first-party-feeling, actively maintained
  pytest plugin (`pytest-dev` GitHub org) built around a `qtbot` fixture with `waitSignal`/`waitSignals` —
  testing is Qt's own signal/slot mechanism made pytest-native, not a browser-automation bolt-on. This is a
  materially different, and arguably more legible, testing story than anything web-based: no DOM, no shadow
  DOM, no JS console to check — a test either receives the expected Qt signal or it doesn't.
- **Rendering and export are the same library.** PyQtGraph (per multiple corroborating sources, including
  its own [SciPy proceedings paper](https://proceedings.scipy.org/articles/gerudo-f2bc6f59-00e)) is documented
  handling "thousands to millions of points" with specific numbers — 10,000 points drawn in under 10 ms, 60 Hz
  maintainable to roughly 30,000 points — comfortably inside this project's 40,000-point decimated payload,
  via `setDownsampling()`/`setClipToView()`. Independent user reports on the PyQtGraph mailing list describe
  laggy zoom/pan in the hundreds-of-thousands-of-points range even with those optimizations on, which is well
  past what this project's decimation ever hands to any renderer. And because Matplotlib embeds directly into
  Qt via `FigureCanvasQTAgg`, the "publication-quality static export" criterion isn't a separate pipeline to
  build (no Kaleido, no Selenium, no headless-browser binary) — it is the same Matplotlib this project
  presumably already uses for other analysis, rendering to screen and to PDF/SVG/PNG through one code path.

The cost is symmetric with the benefit: **zero web technology anywhere** means the seven-type dispatch (G4)
and every other rendering concern must be built as native Qt widgets from scratch, with no npm/JS ecosystem to
draw on, and no `localhost` URL a researcher could just open in a browser — this is the maximum-distance
option from "modern web app," even though it is architecturally the *minimum*-distance option from
`Working/`, since it never needs a network/serialization boundary at all: a PySide6 app can import `Working/`
directly, same as Panel does today, with signals/slots replacing `param` reactivity.

---

## What I could not determine

- **Whether Panel's roadmapped "improved error messages" (2.0/2027 timeline) will actually close the
  `DynamicMap`-swallows-exceptions gap**, or is a separate, smaller UX change (better messages for errors that
  *do* surface, not a fix for exceptions currently converted to empty frames). The roadmap page doesn't say,
  and issue #2827 is still open with no linked fix PR at time of research.
- **Real numbers for how the seven-type dispatch (G4) would actually be built in each framework.** Every
  family's docs describe general component/plotting mechanisms, but none document a "type discriminated union
  → renderable" pattern analogous to this project's existing `render_value`. This is a design question for
  whichever ticket implements the chosen stack, not something documentation search can answer.
- **Actual measured latency for any of these stacks against the real 2.6M-sample recording**, since the
  decimation is already proven fast in isolation but no fetched source benchmarks a *specific* framework
  against *this project's specific* data shape (fixed-context specifics like memory-mapped 183 MB `.npy`
  files feeding a live pan/zoom loop). All large-signal numbers above are from each library's own general
  benchmarks, not from this project's data.
- **Whether PyTauri (the third-party Python↔Tauri binding) is mature enough to trust for a thesis-deadline-free
  but still real project** — it exists and has documentation via DeepWiki and its own GitHub, but no release
  history, adoption signal, or issue-tracker health was assessed; out of scope for the fetch budget here.
- **Reflex's actual current stability**, beyond the one open Node/ESM issue found. It may well be a
  version-specific regression already fixed by the time #12 is decided; the issue's "open" status was current
  only as of this research session.
- **How each stack's testing story specifically catches a *present-but-broken* pane** (the harder half of this
  project's twice-bitten failure mode, per `CLAUDE.md`'s own framing: "it cannot catch a present pane that
  throws in the browser"). Dash's `get_logs()` assertion and NiceGUI's dual fixtures are the two most concrete,
  citable answers found; Panel's own docs, Streamlit's `AppTest`, and most JS-framework testing docs describe
  presence-checking more than paint-verification, and pytest-qt's signal-based model sidesteps the question
  by having no browser to paint into. Whether any of these actually catches this project's specific historical
  bug (a swallowed assertion from mixed `Curve`/`Image` types) was not empirically tested against any
  candidate.
- **License and cost implications of PySide6's LGPL/commercial split** for this project's specific use — likely
  irrelevant for unpublished thesis instrumentation, but not verified against the project's actual
  distribution plans (there don't appear to be any, per the map's "no deployment" fixed context).

## What would change if tested rather than read

- **The Panel silent-failure risk** is the highest-value thing to actually test: build one small `DynamicMap`
  (or its rebuilt-architecture equivalent) that deliberately raises inside a callback, and confirm empirically
  whether it currently produces a blank pane, a logged warning, or (if the roadmap's error-message work has
  already landed piecemeal) something louder. Everything above is issue-tracker text, not this project's
  actual Panel version behaving in front of an agent.
- **uPlot/PyQtGraph/Bokeh-WebGL numbers are all vendor or community benchmarks on synthetic data.** None were
  run against this project's actual memory-mapped 183 MB `.npy` files with the project's actual decimation
  function feeding them. The gap between "renders 10M synthetic points" and "renders this project's specific
  183 MB memory-mapped file's decimated output while the OS is also paging in the file for the first time"
  is exactly the kind of thing that only shows up once real data hits real code.
- **Reflex's Node/ESM breakage** could be stale by the time #12 is read — a live `reflex run` against a fresh
  install would settle it in minutes, versus the issue-tracker snapshot here.
- **Whether NiceGUI's `user` fixture or Dash's `get_logs()` assertion would have caught this project's actual
  historical bug** is answerable by literally reproducing a `Curve`/`Image`-mixing scenario in each framework's
  test harness and checking whether the harness's headless assertions flag it — a half-day spike per
  candidate, not a docs-reading exercise, and probably the single most decision-relevant experiment available
  given how heavily the ticket weights this criterion.
- **The seven-type dispatch (G4) cost** is unknowable from documentation in any of these frameworks because no
  framework ships this pattern out of the box; only a spike that actually builds the `Grouping`/`Model`
  renderers in two or three candidate stacks would produce comparable numbers, rather than the qualitative
  "fully custom" verdict recorded above for every JS/desktop candidate.
- **Dependency-tree friction on this specific conda-on-Windows machine** (down-weighted per the ticket, but
  reportable) was not tested at all — no install was attempted for Reflex's Node toolchain, Tauri's Rust
  toolchain, or PyQtGraph/PySide6 alongside the existing HoloViz stack. A real `conda create` dry run per
  candidate would surface actual conflicts this document cannot.

---

## Sources consulted

Panel: [roadmap](https://panel.holoviz.org/about/roadmap.html), [testing index](https://panel.holoviz.org/how_to/test/index.html), [UI testing guide](https://panel.holoviz.org/how_to/test/uitests.html). HoloViews: [DynamicMap exceptions issue #2827](https://github.com/holoviz/holoviews/issues/2827), [#707](https://github.com/holoviz/holoviews/issues/707), [#5424](https://github.com/holoviz/holoviews/issues/5424), [export guide](https://holoviews.org/user_guide/Exporting_and_Archiving.html). Bokeh: [WebGL acceleration docs](https://docs.bokeh.org/en/latest/docs/user_guide/output/webgl.html). Dash: [testing docs](https://dash.plotly.com/testing), [Graph component docs](https://dash.plotly.com/dash-core-components/graph). Plotly: [static image export](https://plotly.com/python/static-image-export/), [Kaleido](https://github.com/plotly/Kaleido), [performance guide](https://plotly.com/python/performance/). Streamlit: [architecture](https://docs.streamlit.io/develop/concepts/architecture/architecture), [app testing](https://docs.streamlit.io/develop/api-reference/app-testing), [main concepts](https://docs.streamlit.io/get-started/fundamentals/main-concepts). NiceGUI: [documentation](https://nicegui.io/documentation), [testing](https://nicegui.io/documentation/section_testing). Reflex: [introduction](https://reflex.dev/docs/getting-started/introduction/), [issue #5983](https://github.com/reflex-dev/reflex/issues/5983), [discussion #5355](https://github.com/orgs/reflex-dev/discussions/5355). Solara: [getting started](https://solara.dev/documentation/getting_started), [testing](https://solara.dev/documentation/advanced/howto/testing). FastAPI: [docs home](https://fastapi.tiangolo.com/). React: [react.dev](https://react.dev/), [test-utils deprecation](https://react.dev/warnings/react-dom-test-utils), [test-renderer deprecation](https://react.dev/warnings/react-test-renderer). Svelte: [v5 migration guide](https://svelte.dev/docs/svelte/v5-migration-guide). SolidJS: [fine-grained reactivity docs](https://docs.solidjs.com/advanced-concepts/fine-grained-reactivity). uPlot: [GitHub](https://github.com/leeoniya/uPlot). Tauri: [architecture](https://v2.tauri.app/concept/architecture/), [PyTauri](https://github.com/pytauri/pytauri). pywebview: [docs](https://pywebview.flowrl.com/), [GitHub](https://github.com/r0x0r/pywebview). Qt for Python: [doc.qt.io/qtforpython-6](https://doc.qt.io/qtforpython-6/). pytest-qt: [readthedocs](https://pytest-qt.readthedocs.io/). PyQtGraph: [SciPy proceedings paper](https://proceedings.scipy.org/articles/gerudo-f2bc6f59-00e), [pyqtgraph.com](https://pyqtgraph.com/).
