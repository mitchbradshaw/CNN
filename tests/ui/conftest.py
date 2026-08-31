"""
conftest.py (tests/ui)
======================
Fixtures for the browser-driven UI suite.

Three things every test in this directory gets for free:

- **A served app.** `ui_app` yields `(page, url, app)` with the page
  already navigated and the Bokeh document settled.
- **A console-error gate.** `console_errors` collects every JS error and
  failed request; `ui_app` fails the test if any appeared. This is the
  check that catches the failure mode this repo has hit twice — a broken
  `DynamicMap` renders as a blank pane with a clean Python traceback and
  a loud browser console. Nothing on the Python side can see it.
- **A screenshot.** `snap(name)` writes into
  `runs/ui-screenshots/<test-name>/`, gitignored, for a human (or a
  reviewing agent) to look at.

If `pytest-playwright` is not installed this whole directory is skipped
at collection, so the headless suite is unaffected on a machine that has
never run `playwright install`.
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:  # pragma: no cover - environment probe
    import playwright.sync_api  # noqa: F401
    _HAVE_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    _HAVE_PLAYWRIGHT = False

# Skip collection rather than error. A contributor who has not installed
# the browser tooling still gets a green `pytest` run; they just do not
# get UI coverage, and `pytest -m ui` tells them so.
collect_ignore_glob = [] if _HAVE_PLAYWRIGHT else ["test_*.py"]

SCREENSHOT_ROOT = os.path.join(PROJECT_ROOT, "runs", "ui-screenshots")

# Console noise that is not a defect. Keep this list SHORT and justify
# every entry — a permissive filter here quietly disables the gate.
_IGNORABLE_CONSOLE = (
    "favicon.ico",              # Panel serves no favicon by default
    "Failed to load resource: the server responded with a status of 404 (Not Found)",
)


def pytest_collection_modifyitems(items):
    """Mark everything in this directory `ui` so the default `pytest` run
    (which excludes `-m ui`, see pytest.ini) stays at its current
    wall-clock and the browser suite is an explicit, separate gate."""
    for item in items:
        if os.path.dirname(str(item.fspath)).replace("\\", "/").endswith("tests/ui"):
            item.add_marker(pytest.mark.ui)


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """A viewport wide enough for the real layout.

    The default 1280x720 puts the sidebar and the plot in a squeeze that
    no real user sees, and produces screenshots that read as broken
    layout when the layout is fine.
    """
    return {**browser_context_args, "viewport": {"width": 1600, "height": 1000}}


@pytest.fixture
def console_errors(page):
    """Every JS error and failed request the page produced."""
    errors = []

    def _on_console(msg):
        if msg.type == "error" and not any(s in msg.text for s in _IGNORABLE_CONSOLE):
            errors.append(f"console.error: {msg.text}")

    def _on_pageerror(exc):
        errors.append(f"pageerror: {exc}")

    def _on_requestfailed(request):
        if not any(s in request.url for s in _IGNORABLE_CONSOLE):
            errors.append(f"requestfailed: {request.url}")

    page.on("console", _on_console)
    page.on("pageerror", _on_pageerror)
    page.on("requestfailed", _on_requestfailed)
    return errors


@pytest.fixture
def snap(request, page):
    """`snap("after-zoom")` -> runs/ui-screenshots/<test>/after-zoom.png."""
    out_dir = os.path.join(SCREENSHOT_ROOT, request.node.name.replace("/", "_"))
    os.makedirs(out_dir, exist_ok=True)

    def _snap(name, full_page=True):
        path = os.path.join(out_dir, f"{name}.png")
        page.screenshot(path=path, full_page=full_page)
        return path

    return _snap


@pytest.fixture
def ui_app(page, console_errors):
    """Serve the app, navigate to it, wait for the document to settle.

    Yields `(page, url, app)`. Asserts a clean console on teardown — a
    test that legitimately expects an error must drain `console_errors`
    itself and say why.
    """
    from tests.ui.harness import channel_available, served_app

    if not channel_available():
        pytest.skip("real channel data not present; UI suite needs DATA/derived/channels")

    with served_app() as (url, app):
        page.goto(url, wait_until="networkidle")
        wait_for_bokeh(page)
        yield page, url, app

    assert not console_errors, (
        "The page reported browser-side errors. This is the blank-pane failure "
        "mode: Python is clean, the console is not.\n  - "
        + "\n  - ".join(console_errors)
    )


def wait_for_bokeh(page, timeout=30_000):
    """Wait until Bokeh has attached and painted at least one canvas.

    `networkidle` only says the transport went quiet; the Bokeh document
    arrives afterwards over the websocket, so asserting straight after
    `goto` races the first paint and fails intermittently.

    Note the two different query mechanisms. `wait_for_selector` uses
    Playwright's own engine, which pierces open shadow roots, so plain
    `"canvas"` finds a Bokeh canvas. `wait_for_function` runs *page* JS,
    where `document.querySelectorAll` does NOT descend into shadow DOM
    and would wait forever on a perfectly healthy plot — hence
    `deep_count`. See `tests/ui/browser.py` for the measurements.
    """
    from tests.ui.browser import deep_count

    page.wait_for_selector("canvas", state="attached", timeout=timeout)
    deadline = timeout
    step = 100
    while deadline > 0:
        if deep_count(page, "canvas") > 0 and deep_count(page, ".pn-loading") == 0:
            return
        page.wait_for_timeout(step)
        deadline -= step
    raise AssertionError(
        "Bokeh never finished painting: no canvas in the shadow DOM, or a pane "
        "stayed in the .pn-loading state past the timeout."
    )
