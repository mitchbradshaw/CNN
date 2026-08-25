"""
UI/workspaces/library
======================
Surfaces registered into the Library workspace (see `UI.workspaces`).

Import from here, not from a submodule.
"""

from UI.workspaces.library.grid import LibraryGrid
from UI.workspaces.library.detail import EntryDetail

__all__ = ["LibraryGrid", "EntryDetail"]
