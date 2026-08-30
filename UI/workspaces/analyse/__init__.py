"""
UI/workspaces/analyse
======================
Surfaces registered into the Analyse workspace (see `UI.workspaces`).

Import from here, not from a submodule.
"""

from UI.workspaces.analyse.builder import ChainBuilder
from UI.workspaces.analyse.export import RunGroupExporter
from UI.workspaces.analyse.history import RunHistoryBrowser
from UI.workspaces.analyse.window_matrix import WindowMatrixPanel

__all__ = ["ChainBuilder", "RunGroupExporter", "RunHistoryBrowser", "WindowMatrixPanel"]


def analyse_sidebar(app, content):
    """Build Analyse's run-history sidebar and make it section-aware.

    Ticket 70: the sidebar collapses to a ribbon while the chain builder is the
    active section, so the canvas gets the width. `content` is the Analyse
    section `pn.Tabs`; the browser watches its active section to apply the
    default.

    Lives in the Analyse package rather than in `UI.workspaces`, which owns the
    GENERIC sidebar-registration machinery. With this here too, that module
    changed for two unrelated reasons — new registration machinery, and Analyse
    deciding what its own sidebar does. Only one of those is its job.
    """
    sidebar = app.run_history.layout()
    app.run_history.bind_sections(content)
    return sidebar
