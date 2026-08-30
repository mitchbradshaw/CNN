"""
focus.py
=========
Focus mode (ticket 65): one block of a chain opened at full size, as an
alternative to the filmstrip rather than a pane beside it.

Split out of `results.py` when that module passed the package's 600-line
limit. The seam is a real one, not a size-driven guess: focus mode is a whole
post-run surface with its own adapter hook, while `results.py` keeps the
staged-span preview, the Before/After pair, the filmstrip, the detections table
and artifact saving.

The per-adapter hook
--------------------
Most blocks focus to their input and output through the single type renderer.
The SAX blocks show far more — signal, PAA, quantisation with cutlines, symbol
strip — because that is where the encoding decision is visible and the output
symbols alone do not show it. That is per-ADAPTER knowledge, so it rides on
`AdapterSpec.detail_view` rather than on the type renderer.

The hook itself has to be attached from the UI side: it returns HoloViews
objects, and `Adapters/` may not import a plotting library (the one-way
dependency `tests/test_ui_packages.py` enforces). Attaching happens once, at
import of this module — it used to happen inside `_build_result_widgets`, which
made mutating the shared adapter registry a side effect of constructing a
widget, so two run panels did it twice and any consumer that had not built one
saw adapters with no hook at all.
"""

import holoviews as hv

from Adapters.registry import discover_adapters, get_adapter

from Working.database import queries as q

from UI.analyse.chain_state import ChainState
from UI.plots import build_encoding_panels, render_value

_SAX_DETAIL_VIEW_ADAPTERS = (
    "detection.sax_csax",
    "detection.sax_psax",
    "detection.sax_dsax",
)


def _sax_detail_view(result, **params):
    """The per-adapter focus hook shared by the three SAX blocks.

    Reuses the exact `build_encoding_panels` call the run panel's full
    encoding view uses, so focus mode and the encoding section can never
    draw the same run differently. Returns the four panels — encoded
    signal, PAA, quantisation (with cutlines), symbol strip — stacked as
    one focus layout.
    """
    x = result.meta["encoded_x"]
    t = result.meta["encoded_t"]
    symbols = result.value.values
    details = result.meta["details"]
    dmap_signal, dmap_paa, dmap_quant, dmap_strip, _ = build_encoding_panels(
        x, t, symbols, details,
    )
    return hv.Layout([dmap_signal, dmap_paa, dmap_quant, dmap_strip]).cols(1).opts(
        shared_axes=True,
    )


def _install_sax_detail_view_hooks():
    """Attach the SAX focus hook to the three SAX adapter specs.

    The hook is UI-side — it returns HoloViews panels, and `Adapters/` may not
    import a plotting library — so the specs carry it rather than declaring it,
    and something on the UI side has to attach it.

    Called once, at import of this module. It used to run from
    `_build_result_widgets`, which made mutating the shared adapter registry a
    side effect of constructing a widget: two run panels installed it twice,
    and any consumer that had not built one saw adapters with no hook at all.
    Attaching at import makes it a property of the UI package being loaded,
    which is what it actually is. Idempotent either way — the same function
    object is assigned every time.
    """
    discover_adapters()  # idempotent — guarantees SAX specs exist even if imported standalone
    for name in _SAX_DETAIL_VIEW_ADAPTERS:
        try:
            get_adapter(name).detail_view = _sax_detail_view
        except KeyError:
            # A missing SAX adapter is not a focus-mode error: the rest of the
            # surface still works and simply has no SAX blocks.
            continue


_install_sax_detail_view_hooks()


class FocusMixin:
    """Focus mode, mixed into `RunPanel`. Reads the last run's per-step
    results; it never launches a run of its own."""

    def _focus_input(self, recipe, step_results, focus_position, input_value, recording):
        """The typed value feeding the focused step, plus its metadata.

        Step 0's input is the chain's root signal; any later step's input is
        the previous step's output, already computed into `step_results`."""
        if focus_position == 0:
            return self._root_signal_value(recipe, input_value, recording), {}
        previous = step_results.get(focus_position - 1)
        if previous is None:
            raise ValueError(
                f"focus: no result for step {focus_position - 1}, so step "
                f"{focus_position}'s input cannot be rendered"
            )
        return previous.value, previous.meta

    def _build_focus(self, recipe, step_results, focus_position, input_value=None,
                     recording=None):
        """Render one block at full size.

        A block whose adapter declares `detail_view` routes through that
        hook; every other block falls back to the single type renderer for
        its input and output. The decision is made per adapter, not per type
        or per algorithm name, so future per-adapter richness has one place
        to go.

        Returns a HoloViews `Layout`, never `None`. `focus_position` is the
        0-based execution position of the focused step.
        """
        plan = ChainState.from_recipe(recipe).filmstrip_plan(self.conn)
        entry = next((e for e in plan if e["position"] == focus_position), None)
        if entry is None:
            raise ValueError(f"focus: no filmstrip entry for position {focus_position}")

        step = recipe["steps"][focus_position]
        spec = get_adapter(f"{step['stage']}.{step['algorithm']}")
        result = step_results.get(focus_position)
        if result is None:
            raise ValueError(
                f"focus: no result for step {focus_position} ({entry['label']})"
            )

        if spec.detail_view is not None:
            params = spec.validate_params(step.get("params") or {})
            detail = spec.detail_view(result, **params)
            if isinstance(detail, hv.Layout):
                return detail
            if detail is None:
                raise ValueError(
                    f"focus: detail_view hook for {spec.name} returned None"
                )
            # One element. A hook wanting several stacks them into a Layout
            # itself — `AdapterSpec.detail_view` documents the return as an
            # element or a Layout, and handling shapes no hook produces is
            # speculative generality.
            return hv.Layout([detail]).cols(1)

        input_value, input_meta = self._focus_input(
            recipe, step_results, focus_position, input_value, recording,
        )
        input_el = render_value(entry["input_type"], input_value, input_meta).opts(
            title=f"{entry['label']} — input {entry['input_type']}",
        )
        output_el = render_value(entry["output_type"], result.value, result.meta).opts(
            title=f"{entry['label']} — {entry['output_type']}",
        )
        return hv.Layout([input_el, output_el]).cols(1).opts(shared_axes=False)

    def request_focus(self, position):
        """Focus the block at `position` — the "Show algorithm" control on a
        block card (T65's trigger).

        Draws from the LAST RUN's results: focus shows what a step actually
        produced, and before a run there is nothing to show. That is a normal
        state, not an error, so it is reported in the status line — this is
        reached from a button callback, where an exception would break the
        widget rather than the run.
        """
        recipe = getattr(self, "_last_recipe", None)
        results = getattr(self, "_last_step_results", None)
        if not recipe or not results:
            self.status.object = (
                "**Run the chain first** — focus shows what a step produced, "
                "and nothing has been produced yet."
            )
            return None
        if position not in results:
            self.status.object = (
                f"**Step {position + 1} has no result from the last run.** "
                "Re-run the chain to inspect it."
            )
            return None

        # The recording is required whenever the focused step's input is the
        # chain's ROOT signal (position 0, or any step fed from the root),
        # because that input is not a previous step's output and has to be
        # loaded from the channel file. Looked up from the recipe rather than
        # remembered, so it is always available and cannot go stale.
        recording = q.get_recording_by_id(self.conn, recipe["recording_id"])
        self._show_focus(recipe, results, position, recording=recording)
        self.back_to_filmstrip_button.visible = True
        # The card lives on the Chain builder; focus renders on the run
        # surface, so bring that forward or the click appears to do nothing.
        activate = getattr(self.app, "activate_workspace", None)
        if activate is not None:
            activate("Analyse", "Run algorithm")
        return position

    def _on_back_to_filmstrip(self, _event=None):
        """Leave focus and show the whole chain again.

        The recording is looked up from the recipe rather than remembered from
        whatever call last drew the filmstrip: the recipe carries the recording
        id, so this reconstructs the same input the original render used and
        cannot go stale against it.
        """
        self.back_to_filmstrip_button.visible = False
        recipe = getattr(self, "_last_recipe", None)
        results = getattr(self, "_last_step_results", None)
        if not recipe or not results:
            return
        recording = q.get_recording_by_id(self.conn, recipe["recording_id"])
        self._show_filmstrip(recipe, results, recording=recording)

    def _show_focus(self, recipe, step_results, focus_position, input_value=None,
                    recording=None):
        """Put a focused block on screen in the single result pane, hiding
        the filmstrip — the two are alternative post-run surfaces, exactly
        like the filmstrip and the pre-run staged-span preview are."""
        self.result_pane.visible = True
        self.filmstrip_pane.visible = False
        self.result_pane.object = self._build_focus(
            recipe, step_results, focus_position,
            input_value=input_value, recording=recording,
        )
        self._last_before_after = None
        self.scale_note.object = ""
