"""
UI/workspaces/review
======================
Surfaces registered into the Review workspace (see `UI.workspaces`).

Import from here, not from a submodule.
"""

from UI.workspaces.review.queue_state import ReviewQueue
from UI.workspaces.review.surface import ReviewSurface

__all__ = ["ReviewQueue", "ReviewSurface"]
