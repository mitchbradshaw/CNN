"""
detail.py
=========
Cross-channel classification action for the library entry detail (ticket 41).

This is the UI half of a library-level action. The computation itself lives in
`Working.cross_channel` and the edge update lives in `Working.library`; this
module only wires a Panel button to that seam and reports how many edges were
classified. If the UI action is cut, `Working.cross_channel` can still be run
as a script.
"""

import panel as pn

from Working.library import classify_cross_channel_edges


class CrossChannelClassifier:
    """The classify-cross-channel action for a single `motif_entry`.

    `app` only needs to expose `conn`, matching the minimal contract the other
    library surfaces already use for database reads.
    """

    def __init__(self, app, entry_id):
        self.app = app
        self.conn = app.conn
        self.entry_id = entry_id
        self.button = pn.widgets.Button(
            name="Classify cross-channel", button_type="primary",
        )
        self.status = pn.pane.Markdown("")
        self.button.on_click(self._on_click)

    def _on_click(self, event=None):
        try:
            results = classify_cross_channel_edges(self.conn, self.entry_id)
            self.status.object = (
                f"Classified {len(results)} cross-channel edge(s)."
            )
        except Exception as exc:  # surfaced in the pane, not the console
            self.status.object = f"**{exc}**"

    def layout(self):
        return pn.Column(self.button, self.status)
