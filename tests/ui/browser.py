"""
browser.py
==========
Browser-side helpers. Two things here are not obvious and cost an
afternoon to find, so they are written down rather than rediscovered.

**1. Bokeh 3.9 renders into shadow DOM.**
`page.evaluate("document.querySelectorAll('canvas')")` returns *zero*
elements on a fully-rendered plot, because every Bokeh canvas lives
inside a shadow root that `document.querySelectorAll` does not descend
into. Playwright's own locator engine *does* pierce open shadow roots, so
`page.locator("canvas")` and `page.wait_for_selector("canvas")` work
fine — it is only hand-written `evaluate` JS that needs `deep_all`.
Measured on Panel 1.9.4 / Bokeh 3.9.2: document-scope query 0, deep query
2, Playwright locator 2. A `wait_for_function` written the naive way
never becomes true and the test dies on timeout with no useful message.

**2. "Did it actually paint?" is answerable, with a calibrated threshold.**
`canvas_ink()` samples the largest canvas and reports how many distinct
colours it contains and what fraction is the single most common colour.
Measured on the same stack:

    a real curve            modal 0.975   distinct 261
    an EMPTY curve          modal 0.992   distinct  38   (axes + grid, no data)
    a wiped canvas          modal 1.000   distinct   1

So `distinct <= 4` reliably means "nothing was drawn at all" — the
blank-pane failure mode this repo has hit twice. It deliberately does NOT
try to separate "axes but no data" (38) from "axes and data" (261): that
gap varies per plot and a hardcoded number there would be a flaky test
pretending to be a strict one. Assert the *data* on the Python side,
where `hv.renderer("bokeh").get_plot(...)` gives exact renderer row
counts (see `tests/test_ribbon_panes.py`), and use this to prove the
browser rendered anything at all.
"""

_DEEP_ALL = """
  function deepAll(sel, root){
    root = root || document;
    const out = [];
    const walk = (node) => {
      if (!node) return;
      if (node.querySelectorAll) out.push(...node.querySelectorAll(sel));
      const kids = node.querySelectorAll ? node.querySelectorAll('*') : [];
      for (const k of kids) if (k.shadowRoot) walk(k.shadowRoot);
    };
    walk(root);
    return out;
  }
"""

_INK_BODY = """
  const cs = deepAll('canvas').filter(c => c.width > 50 && c.height > 50);
  if (!cs.length) return null;
  const c = cs.sort((a, b) => b.width * b.height - a.width * a.height)[0];
  const ctx = c.getContext('2d');
  if (!ctx) return {err: 'no-2d-context'};
  let dd;
  try { dd = ctx.getImageData(0, 0, c.width, c.height).data; }
  catch (e) { return {err: String(e)}; }
  const counts = {};
  let n = 0;
  // Stride by a prime number of pixels: a power-of-two stride can land on
  // a regular gridline spacing and systematically over- or under-count it.
  for (let i = 0; i < dd.length; i += 4 * 17) {
    const k = (dd[i] << 16) | (dd[i + 1] << 8) | dd[i + 2];
    counts[k] = (counts[k] || 0) + 1;
    n++;
  }
  let top = 0;
  for (const k in counts) if (counts[k] > top) top = counts[k];
  return {w: c.width, h: c.height, sampled: n,
          modalFrac: top / n, distinct: Object.keys(counts).length};
"""

# distinct colours at or below this means nothing was drawn. Calibrated
# above: a wiped canvas is 1, an axes-only plot is 38.
BLANK_DISTINCT_COLOURS = 4


def _js(body):
    return "(() => {" + _DEEP_ALL + body + "})()"


def deep_count(page, selector):
    """How many elements match `selector`, descending into shadow roots."""
    return page.evaluate(_js(f"return deepAll({selector!r}).length;"))


def canvas_ink(page):
    """Colour statistics for the largest painted canvas, or None."""
    return page.evaluate(_js(_INK_BODY))


def assert_not_blank(page, what="the main plot"):
    """Fail if the largest canvas was never drawn into.

    This is the check no Python-side assertion can make. A `DynamicMap`
    whose callback raises in the browser leaves a non-`None` pane object,
    a clean Python traceback, and an empty rectangle on screen.
    """
    ink = canvas_ink(page)
    assert ink is not None, f"{what}: no canvas of a plottable size was rendered at all"
    assert "err" not in ink, f"{what}: could not read the canvas ({ink['err']})"
    assert ink["distinct"] > BLANK_DISTINCT_COLOURS, (
        f"{what} rendered BLANK: {ink['distinct']} distinct colours across "
        f"{ink['sampled']} sampled pixels ({ink['w']}x{ink['h']}), "
        f"{ink['modalFrac']:.4f} of them identical. This is the silently-blank-pane "
        f"failure mode — check the browser console, not the Python traceback."
    )
    return ink


def open_tab(page, name, settle_ms=600):
    """Click a top-level workspace tab by its visible label.

    Panel's `Tabs` header does not expose `role="tab"` and its `.bk-tab`
    class is inside shadow DOM, so neither `get_by_role("tab")` nor a
    `.bk-tab` CSS selector finds it. The visible text does, and it is also
    what a human clicks, which makes it the honest selector here.
    """
    page.get_by_text(name, exact=True).first.click()
    page.wait_for_timeout(settle_ms)


def checkbox(page, label):
    """Locate a Panel `Checkbox` by its visible label.

    Panel's checkbox has **no accessible label association at all** on
    Panel 1.9.4 / Bokeh 3.9.2. The rendered markup is a bare
    `<input type="checkbox">` alone inside the shadow root of a
    `<div class="bk-Checkbox">`; the label text is a sibling within that
    same shadow root, tied to the input by neither `for=`, `aria-label`,
    nor a wrapping `<label>`. Measured directly:

        get_by_role("checkbox", name=...)              0 matches
        get_by_label(...)                              0 matches
        locator('label:has-text(...) input')           0 matches
        locator('div.bk-Checkbox', has_text=...)       1 match  <-- this

    So the host element is the handle. `has_text` and the descendant
    lookup both pierce shadow DOM through Playwright's own engine, and
    clicking the result does toggle the input (verified). If a future
    Panel release adds a proper `<label for=...>`, `get_by_label` becomes
    the right answer and this helper should collapse to it.

    Selects are NOT like this — `get_by_role("combobox", name=...)`
    resolves correctly — so only checkboxes need the workaround.
    """
    return page.locator("div.bk-Checkbox", has_text=label).locator("input[type=checkbox]")


def is_checked(page, label):
    return checkbox(page, label).first.is_checked()
