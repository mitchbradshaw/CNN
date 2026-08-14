"""
build_ui_previews.py
======================
Renders the encoding view's four panels to standalone HTML, headlessly, so
the two quantisation DOMAINS can be compared side by side without starting
the app.

    python "Experimentation/Detection experiments/build_ui_previews.py"

Writes into `Experimentation/Detection experiments/dsax_validation/`:
  - `dsax_ui_preview.html`  — the sharkfin and mixed-sine fixtures, dSAX
  - `csax_ui_preview.html`  — the same two signals, cSAX

Why plain Overlays rather than the live DynamicMaps
-----------------------------------------------------
`build_encoding_panels` returns `DynamicMap`s driven by a `RangeX` stream.
Saving one of those to a static file cannot preserve what makes it a
DynamicMap — there is no Python process behind the file to answer the next
range event — so `hv.save` would either embed a single frame anyway or
embed a widget that does nothing. This script therefore materialises each
panel at ONE fixed x-range (`dmap[()]`, the frame the stream currently
holds) and lays those four Overlays out as a static Layout, which is
exactly what §7.4 of the work order allows for. The frames are the real
ones the live app would show at that range: same callbacks, same data,
same opts.

The fixtures are imported from `tests/test_dsax_engineered.py`, so these
pages show the identical arrays the encoder's own assertions run against.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import holoviews as hv
import panel as pn

hv.extension("bokeh")
pn.extension()

from Working.Detection.sax.csax_python.csax import csax
from Working.Detection.sax.dsax_python.dsax import dsax
from Adapters._sax_common import diagnostic_rows
from Adapters.detection_sax_dsax import delta_diagnostic_rows
from UI.plots import (
    build_encoding_panels, cutline_domain, symbols_to_rle, symbols_to_string,
    symbol_letters, value_axis_label,
)

from tests.test_dsax_engineered import MIXED, SHARKFIN

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dsax_validation")
SEED = 20260810

FIXTURES = [
    {"name": "sharkfin",
     "x": SHARKFIN, "sps": 100,
     "blurb": ("One segment of fast rise then five of exponential decay - the "
               "morphology the regex <code>UD{3,}</code> is written for."),
     "dsax_kwargs": dict(normalize=False, threshold_mode="absolute", absolute_threshold=0.25)},
    {"name": "mixed_sine_noise",
     "x": MIXED, "sps": 40,
     "blurb": ("A 700-sample sine plus N(0, 0.5) noise - a realistic case where "
               "the trend alternates continuously and the SAME band's width "
               "genuinely decides the encoding."),
     "dsax_kwargs": dict()},
]

_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px;
       background: #ffffff; color: #1a1a1a; max-width: 1400px; }
h1 { font-size: 22px; margin-bottom: 4px; }
h2 { font-size: 17px; margin-top: 36px; border-bottom: 2px solid #ddd; padding-bottom: 4px; }
p.blurb { color: #555; font-size: 13px; margin: 4px 0 12px 0; }
code, pre { font-family: ui-monospace, Consolas, monospace; }
pre.string { background: #f6f6f6; padding: 8px; border-radius: 4px; font-size: 12px;
             white-space: pre-wrap; word-break: break-all; margin: 6px 0; }
table.diag { border-collapse: collapse; font-size: 12px; margin: 8px 0; }
table.diag td { padding: 3px 10px; border-bottom: 1px solid #eee; vertical-align: top; }
table.diag td.warn { background: #fff3cd; }
table.diag td.error { background: #f8d7da; }
.meta { font-size: 12px; color: #666; }
"""


def _encode_dsax(x, sps, **kwargs):
    np.random.seed(SEED)
    n_symbols = len(x) // sps
    return dsax(x, len(x), (n_symbols + 0.5) / len(x), return_details=True, **kwargs)


def _encode_csax(x, sps):
    np.random.seed(SEED)
    n_symbols = len(x) // sps
    return csax(x, len(x), (n_symbols + 0.5) / len(x), return_details=True)


def _static_panels(x, t, symbols, details):
    """The four live panel callbacks, materialised at their current range."""
    dmaps = build_encoding_panels(x, t, symbols, details)
    return [dmap[()] for dmap in dmaps[:4]]


def _diag_html(symbols, details):
    rows = list(diagnostic_rows(symbols, details))
    if cutline_domain(details) == "delta":
        rows += delta_diagnostic_rows(symbols, details)
    trs = "".join(
        f"<tr><td><b>{label}</b></td><td class='{severity}'>{value}</td></tr>"
        for label, value, severity in rows
    )
    return f"<table class='diag'>{trs}</table>"


def _section(title, blurb, x, t, symbols, details):
    letters = symbol_letters(details)
    string = symbols_to_string(symbols, letters)
    rle = symbols_to_rle(symbols, letters)
    panels = _static_panels(x, t, symbols, details)
    header = pn.pane.HTML(
        f"<h2>{title}</h2>"
        f"<p class='blurb'>{blurb}</p>"
        f"<p class='meta'>domain <b>{cutline_domain(details)}</b> &middot; "
        f"quantisation axis <b>{value_axis_label(details)}</b> &middot; "
        f"{details['n_symbols']} symbols &middot; "
        f"alphabet {details['alphabet_size']} &middot; "
        f"sps {details['samples_per_symbol']}</p>"
        f"<pre class='string'>{string}</pre>"
        f"<p class='meta'>RLE: <code>{rle}</code></p>"
        f"{_diag_html(symbols, details)}",
        sizing_mode="stretch_width",
    )
    return pn.Column(header, *[pn.pane.HoloViews(p, sizing_mode="stretch_width")
                               for p in panels], sizing_mode="stretch_width")


def build(kind):
    sections = []
    for fx in FIXTURES:
        x = np.asarray(fx["x"], dtype=float)
        t = np.arange(len(x), dtype=float)
        if kind == "dsax":
            symbols, details = _encode_dsax(x, fx["sps"], **fx["dsax_kwargs"])
        else:
            symbols, details = _encode_csax(x, fx["sps"])
        sections.append(_section(fx["name"], fx["blurb"], x, t, symbols, details))

    title = ("dSAX encoding view - DELTA domain (rise per segment)" if kind == "dsax"
             else "cSAX encoding view - AMPLITUDE domain (segment mean)")
    intro = (
        "Panel 2 draws one sloped line per segment, coloured by symbol and centred on "
        "the segment mean, so its rise IS the quantity that chose the symbol. Panel 3's "
        "y-axis is <b>rise per segment</b>, not amplitude - the cutlines are a threshold "
        "on a rise, and drawing them against a level would be a category error."
        if kind == "dsax" else
        "Unchanged from before dSAX existed, and pinned by "
        "<code>tests/test_encoding_view_dsax.py::test_amplitude_*</code>: panel 2's PAA "
        "bars are flat at the segment mean, and panel 3's y-axis is amplitude. Open this "
        "beside <code>dsax_ui_preview.html</code> to compare the two domains."
    )
    page = pn.Column(
        pn.pane.HTML(f"<style>{_CSS}</style><h1>{title}</h1><p class='blurb'>{intro}</p>"),
        *sections, sizing_mode="stretch_width",
    )
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{kind}_ui_preview.html")
    page.save(path, embed=False, resources="inline", title=title)
    return path


def main():
    print("Building static encoding-view previews")
    print("=" * 70)
    for kind in ("dsax", "csax"):
        path = build(kind)
        size = os.path.getsize(path)
        print(f"  {kind:<5} -> {path}  ({size / 1024:.0f} KB)")
    print("\nOpen both and compare panel 2 and panel 3 between them.")


if __name__ == "__main__":
    main()
