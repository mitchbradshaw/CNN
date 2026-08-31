# Verifying a UI change

Added 2026-08-31. Read this before working a ticket that changes anything
under `UI/`.

## The problem this exists for

`CLAUDE.md` states the failure mode plainly:

> a broken dynamic map renders as a **silently blank pane**, not an error.
> Tests pass, review passes, the feature is missing.

The mitigation until now was a headless construction test asserting the
surface returns the expected panes with non-`None` objects. That catches
an *absent* pane. It cannot catch a *present* pane that throws in the
browser, and it cannot see layout, spacing, overlap, or whether the thing
is usable. Both times this bug shipped, the Python side was clean.

So there are now two gates, and they answer different questions.

| | Question | Command |
|---|---|---|
| Headless suite (`tests/`) | Is the right object there, with the right data in it? | `pytest` |
| Browser suite (`tests/ui/`) | Did it actually render, and did the console stay clean? | `pytest -m ui` |

`pytest` alone does **not** run the browser suite — `pytest.ini` excludes
`-m ui` so the fast feedback loop stays fast. Both must pass before a UI
ticket is done.

## One-time setup

Per machine, not a project dependency change:

```
pip install pytest-playwright
python -m playwright install chromium
```

Without it, `tests/ui/` is skipped at collection and `pytest` is green
anyway — so a green run is not evidence the UI was checked. `pytest -m ui`
reporting "no tests ran" means the tooling is missing, not that the UI is
fine.

## Running the browser suite

```
pytest -m ui                       # all of it, headless
pytest -m ui --headed --slowmo 500 # watch it drive
pytest -m ui -k explore            # one surface
```

Every test writes screenshots to `runs/ui-screenshots/<test-name>/`
(gitignored). Look at them. That is the point.

## Looking at the app yourself

For exploratory work — "does this feel right", "why is this control
doing that" — drive a real browser rather than writing a test first:

```
python scripts/dev_serve.py
```

It serves on `http://127.0.0.1:5006` against a **throwaway copy** of the
real database and a throwaway session file, so you can click Delete,
save annotations, and reorder things without touching
`DATA/db/annotations.sqlite`. Never run `panel serve UI/serve.py` for
this — that opens the real database, and the project's
never-touch-the-real-DB rule is not negotiable.

`.mcp.json` configures two browser servers for agents:

- **`chrome-devtools`** — navigate, screenshot, read the console and the
  network log, run performance traces. Reach for this when debugging:
  "why is this blank", "what is that error", "why is this slow".
- **`playwright`** — a fuller automation surface. Reach for this when
  driving a flow you intend to turn into a test.

The loop for a visual change is: start `dev_serve.py`, make the change,
screenshot, look, iterate. Then write the browser test that pins whatever
you fixed.

## What a UI ticket must produce

In addition to the standard test-first discipline:

1. **A headless construction test** — unchanged from existing policy.
   Follow `tests/test_run_panel.py`, `tests/test_motif_browser.py`,
   `tests/test_ribbon_panes.py`.
2. **A browser test in `tests/ui/`** covering the surface you touched.
   If the surface is already covered by
   `test_workspace_opens_without_browser_errors`, adding a case is only
   required when the ticket adds a *control* or a *new pane*.
3. **A screenshot in the ticket report.** `runs/ui-screenshots/` already
   has them after a `pytest -m ui` run; name the ones a reviewer should
   look at. A reviewer who has not seen the pixels has not reviewed a UI
   change.

## Writing a browser test

Read `tests/ui/browser.py` first — it records three findings that cost
real time to establish, each with the measurement behind it:

- **Bokeh 3.9 renders into shadow DOM.** `document.querySelectorAll` in
  page JS finds *zero* canvases on a healthy plot. Playwright's own
  locators pierce shadow roots; hand-written `evaluate` JS needs
  `deep_all`.
- **Panel checkboxes have no accessible label.**
  `get_by_role("checkbox", name=...)` and `get_by_label(...)` both return
  0. Use `browser.checkbox(page, label)`. Selects are fine —
  `get_by_role("combobox", name=...)` works.
- **"Did it paint?" is answerable.** `assert_not_blank(page)` reads the
  canvas back. Calibrated: a real curve has 261 distinct colours, an
  axes-only frame 38, a blank canvas 1.

Two rules for what to assert:

**Drive state in Python, assert in the browser.** Bokeh canvas
coordinates are not addressable by Playwright. A test that fakes a drag
on the plot is testing the test. Set the range on the app object (the
`ui_app` fixture hands it to you) or click the app's own button, then
check what rendered.

**Do not diff screenshots in CI.** Screenshots are for humans. Antialiasing,
font availability and GPU differences make pixel comparison a source of
false failures that trains people to ignore the suite. Assert structure and
the console; look at the pictures yourself.

## Never

- Point any of this at `DATA/db/annotations.sqlite` or
  `DATA/db/ui_session.json`. `tests/ui/harness.py` and
  `scripts/dev_serve.py` both handle this; do not write a third path that
  does not.
- Widen the ignorable-console-message list in `tests/ui/conftest.py` to
  make a test pass. That list is the gate. An entry there needs a reason
  written next to it.
