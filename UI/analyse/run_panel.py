"""
`RunPanel` -- the "Run algorithm" tab, assembled from the mixins in this
package.

What stays here is the state the seams genuinely share (the owning
`ViewerApp`, the worker thread, the last run's result and encoding), the
order the widget groups are built in, and the event wiring -- kept in one
place because the order handlers are attached in is load-bearing: the
`_on_stage_changed(None)` at the end fires a cascade that every watcher
below must already be attached for.
"""

import threading

from UI.analyse.controls import ControlsMixin
from UI.analyse.derive import DeriveMixin
from UI.analyse.encoding_display import EncodingDisplayMixin
from UI.analyse.execution import ExecutionMixin
from UI.analyse.layout import LayoutMixin
from UI.analyse.morphology import MorphologySearchMixin
from UI.analyse.motifs import MotifsMixin
from UI.analyse.noise_floor import NoiseFloorMixin
from UI.analyse.focus import FocusMixin
from UI.analyse.results import ResultsMixin
from UI.analyse.staged_chain import StagedChainMixin


class RunPanel(
    ControlsMixin,
    DeriveMixin,
    ExecutionMixin,
    ResultsMixin,
    FocusMixin,
    EncodingDisplayMixin,
    MorphologySearchMixin,
    NoiseFloorMixin,
    MotifsMixin,
    StagedChainMixin,
    LayoutMixin,
):
    """The "Run algorithm" tab.

    One class per the original design -- the run panel, the before/after
    comparison and the save-as-motif form share too much live state (the
    current recipe, the last run's result) to be separate objects -- but
    assembled from one mixin per seam, so that state is the only thing
    they share and not the file as well."""

    def __init__(self, app):
        # `app` is the owning ViewerApp — this panel reads its *current*
        # recording/viewport/selection live rather than duplicating that
        # state, since a run is always "on whatever channel/span is on
        # screen right now".
        self.app = app
        self.conn = app.conn

        self._thread = None
        self._cancel_event = threading.Event()
        self._last_run_result = None
        self._last_recipe = None
        self._last_recording = None

        # Part 6, 4a: recommend()/derive() bookkeeping — `_recommended_values`
        # is the LAST recommendation applied, used both to detect whether the
        # user has edited a widget away from it (per-widget "(modified)"
        # marker) and to decide whether a span change may silently re-apply
        # new recommended values (only when NOTHING has been touched yet).
        self._recommended_values = {}
        self._recommended_preprocess_window = None
        self._param_base_names = {}
        self._auto_preview_timer = None
        self._syncing_segment_controls = False  # re-entrancy guard for _sync_segment_mode_controls
        self._suppress_param_watchers = False   # see `_on_param_widget_changed`
        self._noise_floor_thread = None
        self._last_encoding = None  # (x, t, symbols, details, recording) for zoom-toggle/motif-seed re-render without re-running
        self._enc_range_stream = None  # the encoding view's shared RangeX stream (Part 6 3b) -- read by the "Visible range only" toggle

        self._build_control_widgets()
        self._build_run_widgets()
        self._build_result_widgets()
        self._build_encoding_widgets()
        self._build_morphology_widgets()
        self._build_noise_floor_widgets()
        self._build_encoding_section()
        self._build_detection_widgets()
        self._build_motif_widgets()
        self._build_staged_widgets()
        self._build_window_matrix_panel()

        self.stage_select.param.watch(self._on_stage_changed, "value")
        self.algorithm_select.param.watch(self._on_algorithm_changed, "value")
        self.run_button.on_click(self._on_run)
        self.cancel_button.on_click(self._on_cancel)
        self.save_motif_button.on_click(self._on_save_detection_as_motif)
        self.save_viewport_motif_button.on_click(self._on_save_viewport_as_motif)
        self.save_plot_button.on_click(self._on_save_plot)
        self.remove_staged_button.on_click(self._on_remove_staged)
        self.clear_staged_button.on_click(self._on_clear_staged)

        # Part 5, Section A: anything that changes WHICH span would
        # actually be run must refresh the preview (A4) and the save-as-
        # motif gating (C4) — never a duplicate, independent recomputation
        # (A5), always through `_refresh_preview`/`_current_span`.
        self.span_mode.param.watch(self._on_span_context_changed, "value")
        self.staged_table.param.watch(self._on_span_context_changed, "selection")
        self.yaxis_mode.param.watch(self._on_yaxis_mode_changed, "value")

        # Part 6, 4a/4b/4c: a span/preprocessing change re-derives
        # recommended defaults; any of these also refresh the read-only
        # `derive()` table and (debounced) the auto-preview.
        self.reset_recommended_button.on_click(lambda _e: self._apply_recommended_defaults(force=True))
        self.preprocess_select.param.watch(self._on_preprocess_changed, "value")
        self.preprocess_window.param.watch(self._on_preprocess_changed, "value")
        self.enc_view_toggle.param.watch(lambda _e: self._refresh_encoding_string_display(), "value")
        self.enc_yaxis_mode.param.watch(self._on_enc_yaxis_mode_changed, "value")
        self.enc_copy_button.js_on_click(args={"source": self.enc_string_pane}, code="""
            navigator.clipboard.writeText(source.value);
        """)
        self.enc_seed_motif_button.on_click(self._on_save_encoding_as_motif)
        self.enc_search_button.on_click(self._on_morphology_search)
        self.enc_search_input.param.watch(lambda _e: self._on_morphology_search(), "enter_pressed")
        self.enc_search_clear_button.on_click(self._on_morphology_search_clear)
        self.enc_search_prev_button.on_click(lambda _e: self._step_morphology_match(-1))
        self.enc_search_next_button.on_click(lambda _e: self._step_morphology_match(+1))
        self.enc_noise_floor_button.on_click(self._on_estimate_noise_floor)

        self._refresh_element_options()
        self._on_stage_changed(None)
        self.refresh_staged_list()
