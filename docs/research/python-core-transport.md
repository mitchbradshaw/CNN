# Transport patterns for exposing a Python core to a non-Python frontend

Research for **wayfinder ticket #8** (map: #4). Gathers facts only; the binding decision on which
pattern to adopt is a separate ticket (#12).

## The shape the transport has to fit

Every pattern below is graded against the actual call this boundary has to carry, not a generic
"call a Python function from JS" story:

- `execute_recipe(recipe, db_path, force, on_progress, should_cancel, run_kwargs, on_step_result)`
  is **synchronous and blocking** (`Working/execution.py:180`). It returns a plain dict when the
  last step finishes; nothing about it is already async.
- Four distinct, non-interchangeable progress channels: `on_progress(step_index, n_steps, stage,
  algorithm)` fired *before* each step (`execution.py:337`); an adapter-internal callback forwarded
  only if that adapter's `run` declares it (`run_kwargs`, `execution.py:365-368`);
  `on_step_result(step_index, result)` fired *after* each step lands (`execution.py:438`); and a
  polling channel — the `runs` row's `current_step`, updated *before* `on_progress` fires
  (`execution.py:335`), so it is a DB-backed, transport-independent source of truth.
- **Cancellation is cooperative and between steps only**: `should_cancel()` is checked once per
  step, before it starts (`execution.py:328`). Nothing interrupts a step already inside `spec.run`.
  This is a property of `execute_recipe` itself, not of any transport — no pattern below can make
  cancellation finer-grained than the core already allows; the question for each pattern is only
  how faithfully it can carry a "stop after this step" signal in, and how it behaves if that signal
  never arrives (dropped connection, killed process).
- Bulk payloads are large: a channel is up to 183 MB of float64, memory-mapped
  (`_load_signal`, `execution.py:91-101`, using `np.load(..., mmap_mode="r")`). A viewport's worth
  of decimated signal is ~40,000 points — several orders of magnitude smaller. Any pattern that
  treats these as the same kind of payload will be wrong for one of them.
- A run can take hours; matrix-profile chains are routed to a cluster above a 900 s ceiling (per
  ticket). Whatever holds run state has to survive at least that long, and the frontend may reload
  mid-run regardless of transport.

Every section below is keyed to the ticket's six points: **(1)** blocking call + mid-flight
progress, **(2)** cancellation propagation, **(3)** binary bulk data / zero-copy / file-path
handoff, **(4)** state placement + frontend-reload behaviour, **(5)** failure modes (silent ones
flagged), **(6)** startup/packaging cost on conda-on-Windows.

## Verdict at a glance

| Pattern | Progress mid-flight | Cancellation | 183 MB array | Reload survives | New toolchain on conda-Windows |
|---|---|---|---|---|---|
| HTTP+JSON/MsgPack + SSE (FastAPI) | Yes, via thread+queue bridge | Cooperative, via disconnect → flag | File-path handoff, not the wire | Yes — DB poll fallback | None (pure pip) |
| WebSockets (FastAPI/Starlette) | Yes, duplex | Cooperative, client can push cancel | File-path handoff, not the wire | Partial — hand-rolled resume | None (pure pip) |
| Tauri + Python sidecar | Yes, via 2-hop event relay or an inner HTTP/WS server | Cooperative, but `kill()` **provably broken** for PyInstaller on Windows | File-path handoff (real asset — shared FS) | Yes — sidecar outlives webview reload | Rust + PyInstaller — new toolchain |
| Electron + Python child_process | Yes, same shape as Tauri | Cooperative; `kill()` works but shell-spawned grandchildren can survive it | File-path handoff | Yes — main process outlives renderer reload | Node/Electron + PyInstaller — new toolchain, heaviest baseline |
| pywebview JS↔Python bridge | Yes, in-process thread | Cooperative, in-process flag — cleanest of the bridges | Same process; still shouldn't cross the JS bridge | No independent backend — one process | pip-only; EdgeWebView2 ships with Win10/11 |
| Qt/PySide WebEngine + QWebChannel | Yes, QThread + signals | Cooperative, in-process flag | Same process; QByteArray marshaling still copies | No independent backend — one process | pip-only; PySide6 wheel bundles Chromium (large download, no external toolchain) |
| PyScript/Pyodide (browser WASM) | Possible but fights the sandbox | **Worker.terminate() breaks execute_recipe's own crash-safety** — no `finally` runs | **No real zero-copy FS access** — sandbox, Chromium-only, permission-gated | No — WASM heap dies on reload | None, but not the right tool here |
| Python-native frontend (Panel-style, truly in-process) | Direct callback, no channel | Direct in-process flag — the ceiling every other pattern approximates | No copy at all | UI-framework question, not transport | None — already the status quo |
| gRPC (server-streaming) | Yes, native fit | Native, still cooperative in effect | Needs file-path escape hatch; protobuf schema ceremony | Same DB-poll fallback applies | `grpcio` has Windows wheels; a non-Python client needs its own stack |
| ZeroMQ (pyzmq) | DIY, no built-in framing | None built-in — must hand-roll | Genuine zero-copy send of buffer-protocol objects, but 2 GB/message ceiling | DIY | pip-only, no compiler needed |

---

## A. HTTP + JSON/MessagePack with SSE or WebSockets (FastAPI/Flask)

Plain HTTP request/response cannot express the shape at all — a single call is a single reply — so
this pattern is really "HTTP for the read/write surface, a second always-on channel (SSE or
WebSocket) for progress," not one mechanism.

**1. Blocking call + progress.** FastAPI's own `BackgroundTasks` is not a fit on its own: it runs
*after* the response is already sent, in the same process, and the docs are explicit that "if you
need to perform heavy background computation... you might benefit from... Celery" — there is no
built-in way for the client to learn progress or even the result [FastAPI Background Tasks]. The
real pattern is Server-Sent Events via `sse-starlette`'s `EventSourceResponse`: an async generator
wraps `execute_recipe` run on a worker thread (`run_in_threadpool` / `asyncio.to_thread`), and the
generator `await`s an `asyncio.Queue` that `on_progress`/`on_step_result` push into from that
thread, yielding one SSE `data:` line per item [sse-starlette discussion via FastAPI GitHub
#9398]. This is a direct, mechanical mapping onto `execute_recipe`'s existing callback signature —
no protocol design needed, just wiring.

**2. Cancellation.** `sse-starlette` detects a client disconnect via `request.is_disconnected()`
and raises `asyncio.CancelledError` inside the generator task [sse-starlette DeepWiki / GitHub
README]. That cancels the *generator*, not the thread actually running `execute_recipe` — Python
threads cannot be killed. The disconnect handler must explicitly flip a shared `threading.Event`
that `should_cancel` reads, so `execute_recipe`'s own between-steps check does the real work. This
is the failure mode most tutorials skip: relying on `except asyncio.CancelledError` alone cancels
nothing on the core side.

**3. Binary bulk data.** JSON is a poor fit for a 183 MB float64 array (base64 inflates it ~33%,
and per-number ASCII encoding is expensive at this scale); MessagePack is more compact and has a
native binary type [msgpack.org], but still means one full copy into a message buffer. Given the
ticket's fixed context — frontend and core share a filesystem — the better answer for the bulk
array is to never put it on the wire: `execute_recipe` already resolves the channel through
`np.load(path, mmap_mode="r")` (`execution.py:94`), so the transport only needs to carry that path
(or a `/npy/<hash>` byte-range endpoint) and the already-decimated ~40,000-point viewport as
JSON/MessagePack.

**4. State + reload.** Run state (thread handle, queue, cancel flag) lives in the FastAPI process.
A frontend reload drops the SSE connection, but because `execute_recipe` already writes
`current_step`/`status` to the `runs` row before/after each step (`execution.py:335`, `:442`), a
reload-safe client just re-polls that row rather than needing the socket to survive — the DB
polling channel the ticket calls out is exactly the reattachment story every transport should fall
back to.

**5. Failure modes.** `BackgroundTasks` exceptions surface only in server logs, never to the
client, unless deliberately caught and re-emitted over SSE/WS — the docs' own example does not do
this. `sse-starlette`'s disconnect detection depends on the ASGI server promptly delivering an
`http.disconnect` ASGI message; on localhost with no reverse proxy this is reliable, but is worth
naming as the dependency it is.

**6. Packaging on conda-Windows.** FastAPI/Starlette/uvicorn are pip-installable pure Python (plus
small C-extension deps); `uvloop` isn't available on Windows but `asyncio`'s default loop and
`httptools` are — no new toolchain, no bundling step. Of every pattern surveyed this is the
cheapest, because the "frontend" is a browser that's already there.

## B. WebSockets throughout

**1. Blocking call + progress.** FastAPI/Starlette's `WebSocket.accept()` → `receive_*()`/`send_*()`
loop, with `WebSocketDisconnect` raised on close [FastAPI WebSockets docs]. The `websockets`
library's own FAQ recommends avoiding manual threading with its asyncio implementation and instead
using `asyncio.to_thread()`/`run_in_executor()` for anything that would block the event loop
[websockets FAQ / community guidance] — the identical thread+queue bridge as pattern A, just
wrapping a duplex socket instead of a one-way SSE generator.

**2. Cancellation.** Same cooperative-flag mechanism as A, but WebSockets are bidirectional per RFC
6455 ("two-way communication... over TCP") [RFC 6455 §1.1], so the client can push an explicit
`{"type": "cancel"}` message on the *same* socket it's reading progress from, rather than relying
on disconnect as the only signal — a real advantage over SSE's one-way stream for this specific
requirement.

**3. Binary bulk data.** RFC 6455 defines native binary frames (opcode `%x2`) alongside text frames
[RFC 6455 §5.6], so a viewport-sized chunk (~40,000 points, a few hundred KB) can cross as raw
bytes or MessagePack with no base64 tax. The 183 MB array gets the same verdict as A: file-path
handoff, not a framed transfer — even a "zero-copy" send still means one full serialize pass, where
mmap is lazy and page-granular.

**4. State + reload.** A raw WebSocket is more fragile across reload than SSE: `EventSource`
(browser SSE) auto-reconnects with `Last-Event-ID` built in; plain WebSocket reconnection and
resubscription to an in-flight `run_id` must be hand-rolled, then reconciled against the `runs` /
`step_artifacts` tables for anything missed while disconnected — the DB, again, is the actual
source of truth, not socket memory.

**5. Failure modes.** A stalled connection behind NAT/sleep can go silently dead without a close
frame — `WebSocketDisconnect` only fires on an orderly or protocol-level close, so `should_cancel`
never trips without an application-level heartbeat/ping-pong timeout you add yourself. Low risk on
localhost, not zero (e.g., laptop sleep).

**6. Packaging.** Same as A — no new toolchain.

## C. Desktop bridges

### C1. Tauri + Python sidecar

**1. Blocking call + progress.** A sidecar is a separate OS process: a PyInstaller-frozen `.exe`
named with the Rust target triple (`my-sidecar-x86_64-pc-windows-msvc.exe`) and referenced via
`bundle.externalBin` / `Command.sidecar()` [Tauri v2, Sidecar docs]. Tauri's **commands** (`invoke`)
are strict JSON-RPC-style request/response; **events** are the one-way fire-and-forget channel
[Tauri v2, Inter-Process Communication docs] — progress means either (a) the sidecar writes
line-delimited JSON to stdout, Rust reads it via `CommandEvent::Stdout` and re-emits it as a Tauri
event the webview listens for (a two-hop relay), or (b) the sidecar runs its own small FastAPI/WS
server and the webview talks to `localhost` directly, collapsing this pattern into A/B once the
process is up — worth recommending explicitly, since it avoids hand-rolling a stdout protocol.

**2. Cancellation.** Killing the sidecar is not automatic on app exit — Tauri's own guidance is to
store the `CommandChild` and call `.kill()` on `RunEvent::ExitRequested` [Tauri discussion #3273].
More seriously: a filed, open GitHub issue reports that `tauri-plugin-shell`'s `child.kill()`
**does not fully terminate a PyInstaller-built executable on Windows**, because PyInstaller's
bootloader launches a parent+child process pair and `kill()` only reaches the wrapper — the real
Python process keeps running [tauri-apps/tauri#11686]. This is a genuinely silent failure mode: the
UI believes cancellation succeeded while the run keeps consuming CPU and, in this core's case,
keeps writing to the database.

**3. Binary bulk data.** Sidecar and webview don't share memory, but per the ticket's fixed context
they do share a filesystem — this is the strongest case among the desktop bridges for the
file-path-handoff asset, since sidecar, Rust core, and webview are three OS-level entities that
never need to move the array itself, only a path, through any of their boundaries.

**4. State + reload.** The sidecar is a long-lived OS process independent of the webview's
lifecycle — a page reload inside the webview does not kill it. Cuts both ways: forgetting the
exit-request kill hook orphans the Python process past app quit, same class of bug as (2).

**5. Failure modes.** The `kill()` bug above; PyInstaller's one-file mode also has a real cold-start
cost (unzips to a temp dir on every launch), relevant to point 6.

**6. Packaging on conda-Windows.** The heaviest pattern surveyed: requires PyInstaller-freezing the
core (with numpy/scipy/aeon this repo depends on) into a single Windows exe with the exact
target-triple filename, *and* a Rust toolchain to build the Tauri shell itself. Both are new
toolchains beyond what's installed — this needs explicit sign-off per this repo's "no dependency
changes without sign-off" rule, not something to add silently.

### C2. Electron + Python child process

**1. Blocking call + progress.** Same shape as C1: `child_process.spawn()` launches the Python
executable, stdout is read incrementally (`python.stdout.on('data', ...)`), and relayed to the
renderer via `ipcMain`→`webContents.send()` / `ipcRenderer.on()` [Electron IPC tutorial;
community integration guides]. `ipcRenderer.invoke()`/`ipcMain.handle()` is Electron's clean
request/response pair (added in Electron 7 specifically to avoid a second listener for the reply)
but has no native streaming — progress needs the repeated one-way `send`/`on` channel, the same
constraint as Tauri's commands-vs-events split. As with Tauri, the pragmatic alternative is to have
the Python side run its own HTTP/WS server and let the renderer talk to `localhost` directly.

**2. Cancellation.** Node's `subprocess.kill()` docs are explicit that Windows has no POSIX
signals: `'SIGKILL'`, `'SIGTERM'`, `'SIGINT'` are all mapped to forceful termination on Windows, so
`kill()` works directly there — no Tauri-style bootloader indirection *unless* the Python side is
also PyInstaller-frozen, which reintroduces the identical double-process risk (PyInstaller's
Windows bootloader behaviour is not Tauri-specific). Node's own docs separately flag that children
spawned through a shell (`spawn(..., {shell: true})`) are not reaped when the parent is killed — the
same "orphaned grandchild" failure family as C1 [Node.js child_process docs, `subprocess.kill()`].

**3–4. Binary bulk data / state.** Same analysis as C1 — shared-filesystem path handoff for the
array; main process (not renderer) holds state and survives a renderer reload, the same
main/renderer split as Tauri's Rust-core/webview split.

**5. Failure modes.** Same kill() caveat as above, applies only if Python side is frozen.

**6. Packaging on conda-Windows.** Electron bundles a full Chromium + Node runtime (~150–200 MB
baseline before app code) — Tauri's cost plus a much heavier baseline binary, since Tauri uses the
OS's own WebView2 instead of shipping Chromium. Same new-toolchain problem as C1 (Node/npm +
electron-builder + PyInstaller) — needs sign-off.

### C3. pywebview JS↔Python bridge

**1. Blocking call + progress.** pywebview's own docs state that exposed `js_api` methods "are
executed in separate threads and are not thread-safe" [pywebview, Javascript–Python bridge guide]
— calls from JS return promises, and pywebview has *already* threaded the call off the UI thread
before your code runs. `execute_recipe` could be exposed close to directly as a `js_api` method;
progress crosses via `window.evaluate_js(...)` called from Python, from that same background
thread, to invoke a JS callback per `on_progress`/`on_step_result` event. This is the tightest match
to `execute_recipe`'s actual signature of any bridge surveyed — no sidecar, no stdout framing, no
separate HTTP server, because pywebview runs the Python core in the *same process* as the window.

**2. Cancellation.** Same process, so `should_cancel` can be a plain `threading.Event` flipped by a
synchronous JS→Python call — no serialization of a "cancel" message across an OS-process boundary
at all, and therefore none of C1/C2's kill()-related failure modes are even reachable.

**3. Binary bulk data.** Same address space, but the bridge itself still marshals through
JSON-like string round-trips — the array still shouldn't cross it; Python-side code can `mmap` the
file directly with no process or network hop before ever touching JS, marginally better than C1/C2.

**4. State + reload.** Reloading the embedded webview's content does not kill the Python process
(mirrors C1/C2's separation), but pywebview's window and its Python interpreter are the whole app —
there's no independently-survivable backend process the way a sidecar can outlive a crashed webview.

**5. Failure modes.** An open GitHub issue reports `evaluate_js` exceptions from a background
thread misbehaving ("Async evaluate_js results in exception in background thread")
[r0x0r/pywebview#906] — flagged as a known rough edge worth piloting rather than trusting from docs
alone; not independently verified here.

**6. Packaging on conda-Windows.** On Windows, pywebview renders via Microsoft Edge WebView2
(Chromium-based, ships with Win10/11 or auto-installs) [search-confirmed via pywebview
changelog/issues — WebView2 support]; pip-installable, no Rust/Node toolchain, no PyInstaller
required for development (only for a final single-exe distribution). Substantially cheaper than
C1/C2 — closer to A/B's near-zero cost while still being a real desktop app.

### C4. Qt/PySide WebEngine + QWebChannel

**1. Blocking call + progress.** Same-process as pywebview (PySide6 core and `QWebEngineView` are
one Python process). `QWebChannel` exposes `QObject` signals/slots to JS running in the
`QWebEngineView` [Qt for Python, `QWebChannel` docs]; the standard, well-documented Qt idiom for
long work is a `QThread`/worker-object pair emitting Qt signals, which are thread-safe by Qt's own
design across a queued connection [community guide, "Safe QThread Usage in PySide6: Signals,
Cancellation, and Error Handling"; Qt for Python `QThread` docs]. Wire `on_progress`/`on_step_result`
to emit signals; a `QWebChannel`-exposed object re-emits them into JS for live UI updates. If the
UI is native Qt widgets instead of `QWebEngineView`, there is no browser and no transport at all —
that's pattern D2.

**2. Cancellation.** Same-process, thread-safe Qt signal/slot back to a cooperative flag — as clean
as pywebview's story, no subprocess boundary to cross.

**3. Binary bulk data.** `QByteArray` marshaling through `QWebChannel` still copies/converts (typed
arrays or Base64 depending on the binding) for anything actually sent through it — don't send the
183 MB array this way; mmap directly in Python, ship only the viewport.

**4. State + reload.** Same as pywebview: one process, so a `QWebEngineView` content reload doesn't
kill the Python side, but losing the process loses the run.

**5. Failure modes.** No dramatic failure mode surfaced in the primary docs pulled for this survey
— `QWebChannel`'s own reference page is thin on specifics beyond the API shape; this is one of the
weaker-sourced corners of this survey and should be piloted rather than taken as fully
characterized.

**6. Packaging on conda-Windows.** `pip install pyside6` is a single command; `QtWebEngine` bundles
a Chromium build inside the wheel — a large download, but no *external* Rust/Node/PyInstaller
toolchain is required for development. Comparable cost to pywebview, heavier than plain FastAPI.

## D. In-process — no real network transport

### D1. PyScript/Pyodide (browser WASM) — honest feasibility check

This is the pattern to be most skeptical of for this specific boundary, and the primary sources
back that skepticism up on every axis:

**1. Blocking call + progress.** Pyodide's Python runs single-threaded inside WebAssembly; running
it on the browser's main thread freezes the UI — guidance is explicit that "the main thread should
only message, not compute" and Python must run in a Web Worker to avoid this [Pyodide/community
guidance on worker usage]. But *inside* that worker, Python is still one GIL-bound interpreter, so
`execute_recipe`'s own blocking call still blocks the worker's message loop the same way it blocks
a native thread — progress still has to be pushed out step-by-step via `postMessage`, the same
cooperative shape as every other pattern, just with a much narrower data channel (next point).

**2. Cancellation.** `Worker.terminate()` from the main thread hard-kills the worker with no
negotiation — much blunter than `execute_recipe`'s own contract of "clean between-step, `runs` row
marked `failed` with a traceback" (`execution.py:453-459`). Terminating the worker kills the
interpreter mid-write: no `except`/`finally` gets to run, so the `runs` row can be left
`status='running'` forever. This is a *worse* cancellation story than every process/thread-based
pattern above, because those all leave the OS process or Python thread alive long enough for
`execute_recipe`'s own cleanup to fire; only Pyodide's worker termination bypasses that entirely —
and it does so silently from the UI's point of view.

**3. Binary bulk data — the shared-filesystem assumption breaks here.** Pyodide's filesystem is a
virtual, in-memory Emscripten FS by default. Real host-filesystem access needs either Node.js
(`pyodide.mountNodeFS()`, not applicable to a browser deployment) or the browser's File System
Access API via `pyodide.mountNativeFS()` — which is **Chromium-only**, requires an explicit
per-session user permission grant (not an assumed-shared path), and the docs themselves note
"changes in the mounted file system is not synchronized by default" [Pyodide, Dealing with the
file system]. Passing a numpy array between the main thread and a worker without mounting a real
file at all means either full serialization (PyScript's own worker docs: "all data passed between
the main thread and workers must be serialisable... numpy arrays cannot be passed directly...
convert to a list first" [PyScript, Web Workers guide]) or a transferable `ArrayBuffer` consumed
via `np.frombuffer()`, which is zero-copy for the *transfer* step but still requires the array to
already be materialized as a JS `ArrayBuffer` in one thread. None of this is the free "file-path
handoff" the ticket flags as an asset elsewhere — for Pyodide, that asset does not exist by default.

**4. State + reload.** A page reload destroys the entire WASM heap and any in-flight Python state
immediately and totally. There is no server process to reconnect to. Given the ticket's own
"routed to a cluster above 900 s" rule, a multi-hour run cannot live inside a browser tab in any
deployment that has to survive a reload — Pyodide could only ever poll a real backend running the
actual job, which collapses this pattern back into A with an extra, weaker hop, not a genuine
in-process alternative to a transport.

**5. Failure modes.** Compile/import errors are visible, not silent. The worker-termination /
orphaned-`runs`-row problem in (2) is the one genuinely silent failure specific to this pattern.
Also worth flagging without over-claiming: not every scientific-Python dependency this core uses is
guaranteed to have a Pyodide/emscripten-forge build; each (numpy, scipy, and whatever this repo's
`aeon` dependency needs) would have to be individually audited before relying on this path, which
was not done as part of this survey.

**6. Startup/packaging.** No toolchain cost — it's a `<script>` tag and a CDN or self-hosted
Pyodide runtime — but that's irrelevant given the verdict above.

**Verdict.** Not viable as the primary transport for this core, on both the cancellation-integrity
and the bulk-data axes — not because WASM-numpy is slow, but because the browser sandbox
contradicts two of the ticket's own fixed assumptions (a shared filesystem, and a cancel that
degrades gracefully). It could still have a narrow, secondary role purely for client-side rendering
of an already-small, server-sent viewport array — not for running `execute_recipe` itself.

### D2. Python-native frontend — where "no transport" can mean two different things

If the frontend framework itself is Python, the transport question can collapse to zero: this is
close to what this codebase already does. `on_progress`, `should_cancel`, and `on_step_result` are
just ordinary Python callables passed straight into `execute_recipe()` from a UI callback — no
serialization, no framing, no binary-transfer question, because there is no boundary. This is
worth naming precisely because "Python-native frontend" is not one thing:

- **Truly in-process** (classic Panel/Streamlit/Dash server-rendered mode, and this app's current
  architecture): your callback code runs in the *same interpreter* as `Working/`. All six report
  points collapse — progress is a direct call, cancellation is a shared in-process flag (exactly
  what `execute_recipe` already assumes, cooperative between steps, by construction — this is the
  ceiling every transport above is trying to approximate, not exceed), binary data is a plain
  object reference or the existing `mmap_mode="r"` load, state is just process state, and failures
  are ordinary Python exceptions — visible by default. This is presumably *why* this repo's own
  Panel-surface risk is the "silently blank pane" failure (`CLAUDE.md`, Panel surfaces section)
  rather than a transport failure: there is no transport layer here to fail silently in the first
  place.
- **Python-authored but still networked**: several frameworks marketed as "just write Python" hide
  a real client/server split underneath — NiceGUI is built on FastAPI plus a Vue/Quasar client
  talking over a WebSocket, and Flet's Python server talks to a Flutter client over WebSocket too.
  These are Pattern B with the boilerplate hidden, not "no transport" in the sense this ticket
  means, and everything written about WebSockets in section B applies to them unchanged.

## E. Other patterns genuinely used for this shape

**gRPC (server-streaming RPC).** A primary-source-confirmed structural match for progress: "the
client sends a request to the server and gets a stream to read a sequence of messages back" [grpc.io,
Core Concepts]. Cancellation is native and bidirectional ("Either the client or the server can
cancel an RPC at any time") but the same docs immediately note "changes made before a cancellation
are not rolled back" — i.e., gRPC's cancellation is exactly as cooperative in effect as
`execute_recipe`'s own `should_cancel`, it just has a standard wire signal for it instead of a
hand-rolled flag. Binary payloads are protobuf `bytes` fields; the docs don't give large-message
guidance, and in practice the same file-path escape hatch applies for the 183 MB array. Packaging:
`grpcio`/`grpcio-tools` ship prebuilt Windows wheels, no compiler needed Python-side, but a
genuinely non-Python frontend needs its own gRPC-Web client stack, and every one of the seven
`Working.types` interchange types would need a maintained `.proto` schema kept in sync by hand —
real ceremony that HTTP+JSON avoids, and not obviously justified at single-researcher,
single-machine scale.

**ZeroMQ (pyzmq).** Supports genuine zero-copy sends of any buffer-protocol object, numpy arrays
included [pyzmq usage patterns, IPython/SciPy tutorial material] — architecturally the most
"native" fit for moving array bytes of anything surveyed. But it is a socket library, not a
protocol: REQ/REP is strict lockstep (blocks until a reply, a poor fit for "N progress messages
then a final result"), PUB/SUB has no delivery guarantee and no cancellation primitive at all, and
every framing/progress/cancel/reconnect behaviour above has to be hand-designed. There's also a
confirmed, concrete ceiling: libzmq has historically failed to send a single message over 2 GB
[zeromq/libzmq#4768] — comfortably above 183 MB but a real number worth knowing, and multi-part
`SNDMORE` framing is required today regardless. Verdict: a legitimate low-level building block, not
a pattern to adopt wholesale over HTTP+WS for this project — and file-path handoff on the already-
shared filesystem gets the same effective zero-copy result with far less protocol to hand-write.

**File-path handoff itself, named as a first-class pattern, not a footnote.** Given the ticket's
fixed context — frontend and core always share a filesystem, localhost, single machine — this
deserves to be the default answer to "how does binary bulk data cross" for every pattern above
except D1: `execute_recipe` already treats a channel as `np.load(path, mmap_mode="r")`
(`execution.py:94`), and every other transport surveyed (HTTP, WS, Tauri, Electron, pywebview, Qt)
can carry a bare string path far more cheaply, and more *correctly*, than it can carry the bytes
themselves. More correctly, because mmap gives lazy, OS-paged, partial reads matched to what a
viewport actually needs (~40,000 points out of up to 22.9M samples), where any "serialize the whole
array" approach forces a full read + copy + encode + transmit + decode + copy of data that is
~99.98% unused by that viewport. The one pattern where this asset evaporates is Pyodide/PyScript
(D1), for exactly the sandbox reasons in that section — which is precisely why D1 is the weak
pattern here, not because WASM-numpy is inherently slow.

## Cross-cutting findings

- **"Cooperative, between-step cancellation" is a property of `execute_recipe`, not of the
  transport.** No pattern surveyed can interrupt an in-flight numpy/scipy call; the only real
  differentiator between patterns is (a) how quickly and reliably a cancel signal reaches the
  `should_cancel` flag, and (b) what happens to the run's on-disk/DB state if the signal never
  arrives cleanly. On that second axis, Pyodide's hard `Worker.terminate()` is uniquely bad — it is
  the only pattern surveyed that can bypass `execute_recipe`'s own crash-safety (`except`/`finally`
  marking the `runs` row `failed`) entirely, because it can kill the interpreter mid-write rather
  than mid-step.
- **The recurring silent failure family is "kill() didn't actually kill it."** Confirmed
  independently for Tauri sidecars wrapping PyInstaller executables on Windows
  [tauri-apps/tauri#11686] and flagged in Node's own child_process docs for shell-spawned
  grandchildren — any pattern that freezes the core with PyInstaller and launches it as a
  subprocess should assume `kill()` needs verification (e.g., process-tree kill by PID, not a
  single `.kill()` call) rather than trusting it silently.
- **The `runs.current_step` DB column is the one reload-proof channel every pattern has in
  common.** Every transport-based pattern (A, B, C1–C4) should treat the socket/event stream as an
  optimization for live updates and the database row as the actual source of truth to reconcile
  against after a reload or reconnect — this was true before this survey (it's how `execute_recipe`
  is already built) and nothing here changes it.
- **"Frontend and core share a filesystem" is a real, load-bearing asset — everywhere except
  inside a browser sandbox.** It quietly does most of the work of answering point 3 for A, B, C1–C4,
  and is exactly the assumption that breaks for D1, which is the main reason D1 fails this survey.

## Sources

- FastAPI, [WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
- FastAPI, [Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- MessagePack, [msgpack.org](https://msgpack.org/)
- sse-starlette disconnect/cancellation behaviour, via [FastAPI GitHub Discussion #9398](https://github.com/fastapi/fastapi/discussions/9398) and [sysid/sse-starlette](https://github.com/sysid/sse-starlette)
- `websockets` library FAQ / community guidance on `asyncio.to_thread()` for blocking work
- IETF, [RFC 6455 — The WebSocket Protocol](https://datatracker.ietf.org/doc/html/rfc6455)
- Tauri v2, [Embedding External Binaries (Sidecar)](https://v2.tauri.app/develop/sidecar/)
- Tauri v2, [Inter-Process Communication](https://v2.tauri.app/concept/inter-process-communication/)
- Tauri, [Kill process on exit — Discussion #3273](https://github.com/orgs/tauri-apps/discussions/3273)
- Tauri, [`kill()` does not terminate a PyInstaller executable — Issue #11686](https://github.com/tauri-apps/tauri/issues/11686)
- Electron, [Inter-Process Communication tutorial](https://www.electronjs.org/docs/latest/tutorial/ipc)
- Community guides on Electron + Python child_process/PyInstaller integration
- Node.js, [`subprocess.kill()` docs](https://nodejs.org/api/child_process.html#subprocesskillsignal)
- pywebview, [Javascript–Python bridge guide](https://pywebview.flowrl.com/guide/interdomain.html)
- pywebview, [`evaluate_js` background-thread exception — Issue #906](https://github.com/r0x0r/pywebview/issues/906)
- Qt for Python, [`QWebChannel`](https://doc.qt.io/qtforpython-6/PySide6/QtWebChannel/QWebChannel.html)
- Qt for Python, [`QThread`](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html); community guide "Safe QThread Usage in PySide6: Signals, Cancellation, and Error Handling"
- Pyodide, [Dealing with the file system](https://pyodide.org/en/stable/usage/file-system.html) (retrieved via cached/search access — direct fetch returned 403)
- PyScript, [Web Workers](https://docs.pyscript.net/2026.3.1/user-guide/workers/)
- Community/browser guidance on Pyodide main-thread blocking and Web Worker usage
- grpc.io, [Core Concepts, Architecture and Lifecycle](https://grpc.io/docs/what-is-grpc/core-concepts/)
- pyzmq usage patterns (zero-copy buffer sends); [libzmq 2 GB single-message issue #4768](https://github.com/zeromq/libzmq/issues/4768)
- This repo: `Working/execution.py` (read directly, not modified)
