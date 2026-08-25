"""
`ViewerApp` -- the class the whole viewer hangs off, assembled from the
mixins in this package.

What stays here is only what is genuinely shared: the database connection,
the cross-cutting state every seam reads, the order in which the widget
groups are built, and the startup bootstrap that picks the initial recording
and restores the saved session.
"""

import panel as pn
import param

from Working.database import queries as q
from Working.database import vocabulary as v
from Working.database.schema import init_db

from UI.admin import VocabularyAdmin
from UI.file_import import FileImportPanel
from UI.analyse import RunPanel
from UI.workspaces.analyse.history import RunHistoryBrowser
from UI.motif_browser import MotifBrowser
from UI.workspaces.analyse import ChainBuilder
from UI.workspaces.review import ReviewSurface
from UI.viewer.annotations import AnnotationsMixin
from UI.viewer.filters import FiltersMixin
from UI.viewer.layout import LayoutMixin
from UI.viewer.navigation import NavigationMixin
from UI.viewer.overlays import OverlaysMixin
from UI.viewer.selection import SelectionMixin
from UI.viewer.session import SessionPersistenceMixin
from UI.viewer.shortcuts import ShortcutsMixin
from UI.viewer.signal_view import SignalViewMixin
from UI.viewer.table import AnnotationTableMixin


class ViewerApp(
    NavigationMixin,
    SignalViewMixin,
    SelectionMixin,
    AnnotationsMixin,
    ShortcutsMixin,
    OverlaysMixin,
    AnnotationTableMixin,
    FiltersMixin,
    SessionPersistenceMixin,
    LayoutMixin,
    param.Parameterized,
):
    """The signal viewer and annotation application.

    Assembled from one mixin per seam so that the modules under
    `UI/viewer/` can be worked on independently. The mixins carry no
    state of their own: every attribute they touch is created here or in
    a `_build_*` method called from `__init__`, in the order below."""

    source_file = param.Selector(default=None, objects=[])
    channel = param.Selector(default=None, objects=[])
    verdict = param.Selector(default="interesting", objects=list(q.VERDICTS))
    note = param.String(default="")

    def __init__(self, db_path=None, **params):
        super().__init__(**params)
        self.conn = init_db(db_path)
        v.seed_vocabulary(self.conn)

        self._recording_id = None
        self._fs = None
        self._n_samples = None
        self._dmap = None
        self._range_stream = None
        self._bounds_stream = None
        self._refresh_trigger = None  # set in _rebuild_plot; see module-level _RefreshTrigger
        self._full_extent = (0.0, 1.0)
        self._y_extent = (0.0, 1.0)
        self._pending_bounds = None
        self._updating_time_fields = False  # re-entrancy guard, see _sync_time_fields_from_bounds
        self._time_unit = "s"  # "s" or "h" — see ViewerApp._unit_scale and _on_time_unit_toggle
        self._selected_annotation_ids = set()  # the one shared selection model — table & plot both read/write this
        self._updating_annotation_selection = False  # re-entrancy guard, see _sync_table_selection_from_ids
        self._similar_annotation_id = None  # best near-duplicate match for the pending span, if any
        self._staged_spans = []  # in-memory cross-tab basket; see _stage_span (Part 3)
        self._channel_mmap = None  # set in _rebuild_plot; reused for the ribbons' local y-range
        self._y_pan_fraction = 0.0  # vertical pan offset (Part C3), fraction of current y-span
        self._nav_current_id = None  # annotation navigator's current position (Part E1)
        self._pending_bulk_action = None  # (kind, value) staged by a "Stage ... change" button (Part E6)
        self._last_deleted_ids = []  # most recent soft-delete batch, for undo (Part E7)
        self._restoring_session = False  # re-entrancy guard: suppress saves while applying a loaded session
        self._init_complete = False  # suppresses saves during __init__'s own source_file/channel bootstrap
        self._session_state = self._load_session_state()  # read once here; applied after widgets exist (Part E9)
        # Part B6: accordion open/closed is UI chrome, not recording-specific
        # data, so (unlike filters/viewport) it's read here UNCONDITIONALLY --
        # not gated on the saved source_file matching what actually loads --
        # and applied at accordion-construction time in `layout()`, which
        # runs after `__init__` and needs the value before the widgets exist.
        self._initial_accordion_active = (self._session_state or {}).get("accordion_active", {})

        self.status = pn.pane.Markdown("", styles={"color": "#a33"})
        self.selection_info = pn.pane.Markdown("")
        self.summary_pane = pn.pane.Markdown("")

        self._build_navigation_widgets()
        self._build_signal_view_widgets()
        self._build_selection_widgets()
        self._build_staged_and_bulk_widgets()
        self._build_shortcut_widgets()
        self._build_ribbon_panes()
        self._build_plot_pane()
        self._build_annotation_table()
        self._build_annotation_form()
        self._build_filter_widgets()
        self._build_overlay_toggles()
        self._wire_filter_watchers()
        # Imperative, not `@param.depends(watch=True)`: that decorator
        # resolves against the class it's defined on, and these two methods
        # live on SignalViewMixin while `source_file`/`channel` are declared
        # here — see SignalViewMixin's docstring for why that combination
        # fails silently. Registered before the bootstrap assignments below
        # so they fire during `__init__` exactly as they would have on the
        # pre-split class.
        self.param.watch(lambda _e: self._on_source_file_change(), "source_file")
        self.param.watch(lambda _e: self._on_channel_change(), "channel")

        self.admin = VocabularyAdmin(self.conn)
        self.admin.on_change.append(self._refresh_vocabulary_options)
        self._refresh_vocabulary_options()

        self.file_import = FileImportPanel(self.conn, on_imported=[self._refresh_source_file_options])
        self.run_panel = RunPanel(self)
        self.run_history = RunHistoryBrowser(self)
        self.motif_browser = MotifBrowser(self)
        self.chain_builder = ChainBuilder(self)
        self.tabs = None  # set in layout(); lets RunHistoryBrowser switch tabs on "Reopen"

        source_files = sorted({r["source_file"] for r in q.list_recordings(self.conn)})
        if not source_files:
            raise RuntimeError(
                "No recordings in the database. Run "
                "Pipelines/materialize_channels/materialize_channels.py first."
            )
        self.param.source_file.objects = source_files
        saved = self._session_state
        initial_source_file = source_files[0]
        # Part C1: a stale session (its recording or channel has since been
        # removed) must degrade to defaults VISIBLY, not just silently --
        # otherwise a broken/misleading view (wrong channel, or filters
        # meant for a different recording) could look like a real bug in
        # the current one. Checked once, up front, so both halves of a
        # partial mismatch (recording gone entirely vs. just this channel)
        # get their own specific notice.
        stale_notice = None
        if saved and saved.get("source_file") and saved["source_file"] not in source_files:
            stale_notice = (
                f"**Saved session referenced recording \"{saved['source_file']}\" which no "
                "longer exists — starting with defaults.**"
            )
        elif saved and saved.get("source_file") in source_files:
            initial_source_file = saved["source_file"]
            saved_channels = sorted(
                r["channel"] for r in q.list_recordings(self.conn, initial_source_file)
            )
            if saved.get("channel") is not None and saved["channel"] not in saved_channels:
                stale_notice = (
                    f"**Saved session referenced channel {saved['channel']} of "
                    f"\"{initial_source_file}\", which no longer exists — using the "
                    "default channel instead.**"
                )
        self.source_file = initial_source_file
        self.filter_source.options = [q.SOURCE_IMPORTED_10MIN, q.SOURCE_MANUAL_UI, "excel_catalog"]
        self._refresh_channel_options()
        if saved and saved.get("channel") in self.param.channel.objects:
            self.channel = saved["channel"]
        self._load_recording()
        # Built after the recording above exists so the Review surface's
        # first render has a recording to show rather than starting empty.
        self.review_surface = ReviewSurface(self)
        if stale_notice:
            self.status.object = stale_notice

        # Part E9: filters/search/toggles/view-transforms/time-unit/viewport,
        # restored once here (after the recording above is already loaded,
        # since the viewport restore needs `_range_stream` to exist) --
        # `_restoring_session` suppresses the save-on-change watchers below
        # so loading a session never immediately re-writes the same file.
        #
        # Only applied when the saved session's source_file is the one we
        # actually just loaded -- a session file from a DIFFERENT database
        # (a different `db_path`, e.g. a test's own temp sqlite file, or a
        # stale save from a source_file that's since been removed) must
        # never silently impose its filters/viewport onto an unrelated
        # recording set. This also keeps every temp-DB-backed test that
        # doesn't isolate SESSION_STATE_PATH from picking up unrelated
        # leftover state, though tests should isolate it too (see
        # tests/test_session_persistence.py's `_ScratchSessionFile`).
        if saved and saved.get("source_file") == initial_source_file:
            self._restoring_session = True
            try:
                self._restore_session_state(saved, stale_notice=stale_notice)
            finally:
                self._restoring_session = False
        self._init_complete = True
