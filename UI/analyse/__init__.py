"""
UI/analyse
==========
The "Run algorithm" tab, one module per seam.

`RunPanel` was a single 2,248-line class with ~70 methods in `UI/run_panel.py`.
It is still one class -- the run controls, the before/after comparison and the
save-as-motif form share too much live state to be separate objects -- but it
is assembled from mixins, each owning one seam:

    staged_chain      the staged-span basket and which span a run would use
    controls          stage/algorithm/preprocessing selection
    derive            recommended defaults and the derived-quantities table
    execution         running a recipe, progress, cancellation
    results           the preview / Before-After pane and the detections table
    encoding_display  the encoding inspection section
    morphology        regex search over the symbol string
    noise_floor       the surrogate noise-floor estimate
    motifs            saving a span as a motif
    layout            the tab assembly

Import `RunPanel` from here, not from a submodule.
"""

from UI.analyse.run_panel import RunPanel

__all__ = ["RunPanel"]
