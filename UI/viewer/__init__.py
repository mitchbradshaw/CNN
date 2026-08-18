"""
UI/viewer
=========
The signal viewer and annotation application, one module per seam.

`ViewerApp` was a single 2,282-line class in `UI/app.py`, which meant every
ticket touching any part of the viewer queued on the same file. The class is
unchanged in behaviour; it is now assembled from mixins, each owning one seam:

    signal_view   which recording is loaded and the main plot
    overlays      the annotation/reviewed ribbons and their toggles
    table         the annotations Tabulator
    selection     the pending span, the shared selection, drag modes
    navigation    zoom, pan, view transforms, the annotation navigator
    annotations   the annotation form, staging, bulk actions, delete/undo
    filters       filter/search, the filtered-row query, exports
    session       session persistence
    shortcuts     the hidden keyboard-shortcut buttons
    layout        the seven-tab assembly

Import `ViewerApp` from here, not from a submodule.
"""

from UI.viewer.app import ViewerApp

__all__ = ["ViewerApp"]
