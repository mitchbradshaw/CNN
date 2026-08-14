"""
admin.py
=========
Small admin panel for the controlled tag vocabulary: add a new term to a
category, or deactivate/reactivate an existing one. Deactivating never
deletes `annotation_tags` rows — it only hides the term from future
dropdowns (`vocabulary.deactivate_term`).

A plain Python callback list (`on_change`) lets `app.py` know when to
refresh its own tag dropdowns, without this module importing `app.py`.
"""

import pandas as pd
import panel as pn

from Working.database import vocabulary as v

TERM_COLUMNS = ["id", "category", "value", "description", "active"]

# provenance is set automatically by importers, not offered in the
# per-annotation dropdowns in app.py -- but it's still manageable here,
# since the admin panel is about the vocabulary list itself, not per-row
# tagging.
ALL_CATEGORIES = ["element", "quality", "structure", "provenance", "status"]


class VocabularyAdmin:
    def __init__(self, conn):
        self.conn = conn
        self.on_change = []  # callables invoked after any add/deactivate/reactivate

        self.category_select = pn.widgets.Select(
            name="Category", options=ALL_CATEGORIES, value="element",
        )
        self.new_value = pn.widgets.TextInput(name="New term value", placeholder="e.g. spiral")
        self.new_description = pn.widgets.TextInput(name="Description (optional)")
        self.add_button = pn.widgets.Button(name="Add term", button_type="primary")
        self.add_button.on_click(self._on_add)

        self.status = pn.pane.Markdown("")
        self.terms_table = pn.widgets.Tabulator(
            pd.DataFrame(columns=TERM_COLUMNS), page_size=15, show_index=False,
            selectable=1, disabled=True, sizing_mode="stretch_width",
        )
        self.deactivate_button = pn.widgets.Button(name="Deactivate selected", button_type="danger")
        self.deactivate_button.on_click(self._on_deactivate)
        self.reactivate_button = pn.widgets.Button(name="Reactivate selected", button_type="default")
        self.reactivate_button.on_click(self._on_reactivate)

        self.category_select.param.watch(lambda _e: self._refresh_table(), "value")
        self._refresh_table()

    def _notify(self):
        for cb in self.on_change:
            cb()

    def _refresh_table(self):
        rows = v.list_terms(self.conn, category=self.category_select.value, active_only=False)
        df = pd.DataFrame([dict(r) for r in rows], columns=TERM_COLUMNS)
        self.terms_table.value = df

    def _on_add(self, _event=None):
        self.status.object = ""
        value = self.new_value.value.strip()
        if not value:
            self.status.object = "**Enter a term value first.**"
            return
        v.add_term(self.conn, self.category_select.value, value,
                   self.new_description.value.strip() or None)
        self.new_value.value = ""
        self.new_description.value = ""
        self._refresh_table()
        self.status.object = f"Added {self.category_select.value}={value!r}."
        self._notify()

    def _selected_term_ids(self):
        df = self.terms_table.value
        return [int(df.iloc[i]["id"]) for i in self.terms_table.selection]

    def _on_deactivate(self, _event=None):
        ids = self._selected_term_ids()
        if not ids:
            self.status.object = "**No rows selected.**"
            return
        for tid in ids:
            v.deactivate_term(self.conn, tid)
        self._refresh_table()
        self.status.object = f"Deactivated {len(ids)} term(s). Existing tag assignments are untouched."
        self._notify()

    def _on_reactivate(self, _event=None):
        ids = self._selected_term_ids()
        if not ids:
            self.status.object = "**No rows selected.**"
            return
        for tid in ids:
            v.reactivate_term(self.conn, tid)
        self._refresh_table()
        self.status.object = f"Reactivated {len(ids)} term(s)."
        self._notify()

    def layout(self):
        return pn.Column(
            pn.pane.Markdown(
                "### Vocabulary admin\n"
                "Add new morphology/quality/structure terms as you find them, or "
                "deactivate ones you no longer want offered. Deactivating a term "
                "does not remove it from annotations already tagged with it."
            ),
            pn.Row(self.category_select, self.new_value, self.new_description, self.add_button),
            self.status,
            self.terms_table,
            pn.Row(self.deactivate_button, self.reactivate_button),
            sizing_mode="stretch_width",
        )
