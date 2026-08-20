"""
workspaces/__init__.py
======================
Registration point for workspace content. Each workspace (Explore, Analyse,
Review, Library) registers its panel content here without editing the shell
itself. This allows workspace tickets to add content without modifying the
shell module after it's frozen.
"""

# Registry of workspace panels: name -> callable returning panel content
_WORKSPACE_REGISTRY = {}


def register_workspace(name, panel_fn):
    """Register a workspace panel factory.
    
    Parameters
    ----------
    name : str
        The workspace name (e.g., 'Explore', 'Analyse', 'Review', 'Library')
    panel_fn : callable
        A function that returns the panel content for this workspace
    """
    if name in _WORKSPACE_REGISTRY:
        raise ValueError(f"Workspace '{name}' is already registered")
    _WORKSPACE_REGISTRY[name] = panel_fn


def get_workspace(name):
    """Get the panel content for a registered workspace.
    
    Parameters
    ----------
    name : str
        The workspace name
    
    Returns
    -------
    panel object or None
        The panel content if registered, None otherwise
    """
    if name not in _WORKSPACE_REGISTRY:
        return None
    return _WORKSPACE_REGISTRY[name]()


def list_workspaces():
    """Return list of registered workspace names."""
    return list(_WORKSPACE_REGISTRY.keys())
