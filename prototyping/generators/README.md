# generators

Python that produces the `.pen` concept documents one folder up.

## Layout

    pen_kit.py            primitives — palette, text/rect/ellipse/path nodes,
                          trace(), write_doc(); no page knowledge
    pen_widgets.py        charts and controls — wander, symbol_strip, slope_bars,
                          dendrogram, heat_grid, slider, selectbox, toggle, stat

    build_blocks.py       shared chrome (nav, head, card, toolbar, ribbon, page)
                          plus every Analyse page function
    build_v3.py           the two original Discovery page functions

    build_explore_flow.py    -> ../UI_explore_flow_v2.pen
    build_analyse_files.py   -> ../UI_analyse_chain_v1.pen
                                ../UI_analyse_interrogation_v1.pen
                                ../UI_analyse_training_v1.pen
    build_discovery.py       -> ../UI_discovery_v1.pen
    build_review.py          -> ../UI_review_v1.pen
    build_library.py         -> ../UI_library_v2.pen
    build_settings.py        -> ../UI_settings_v1.pen

    verify_pen.py         check harness

## Running

    cd prototyping/generators
    python3 build_settings.py
    python3 verify_pen.py ../UI_settings_v1.pen

`write_doc()` resolves a bare filename against the parent folder when it is run
from a directory named `generators`, so builders drop their `.pen` beside the
other concept documents rather than in here. Pass an absolute path to override.

No third-party dependencies. Standard library only.

## verify_pen.py

Run it after every build. It checks:

- **geometry overflow** — recursively, every node against its parent's box
- **duplicate ids** — `pen_kit.nid()` is a global counter, so a module reloaded
  mid-run can collide
- **node types** — only `frame`, `text`, `rectangle`, `ellipse`, `polygon`,
  `path` are confirmed against Pencil v2.17
- **text width** — `.pen` text nodes have no width and do **not** wrap, so an
  over-long string silently runs past its container. The check is an estimate
  from `CHAR_W`, not a real measurement; treat hits as candidates to look at.

Known outstanding: 14 caption overruns across the four Analyse/Discovery
documents. Copy is correct, line breaks are not. Deferred deliberately.

## Editing a page

Edit its function, re-run its builder, re-run `verify_pen.py`. The `.pen` files
are build output — never hand-edit them, the next build overwrites it.

Two constraints worth remembering, both learned the hard way:

- text nodes have no `width` and never wrap — break lines yourself
- `path.geometry` is SVG in **local** coordinates, relative to the node's x/y
