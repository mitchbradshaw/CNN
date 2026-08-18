"""
Marshalling background-thread results back onto the Bokeh document thread.
"""

def _run_on_ui_thread(doc, fn):
    """Schedule `fn` to run on the Bokeh document's own thread (required for
    thread-safe widget updates from a background thread) — `doc` must be
    captured via `pn.state.curdoc` on the *serving* thread before spawning
    the background thread; querying it from inside the background thread
    itself returns nothing useful. Falls back to calling `fn` directly if
    there's no live session (a script or test)."""
    if doc is not None:
        doc.add_next_tick_callback(fn)
    else:
        fn()
