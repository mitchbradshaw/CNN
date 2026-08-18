"""
Global keyboard shortcuts for the labelling loop. Panel has no hook for
these, so each one is a real but invisible button driven by a single
`keydown` listener -- see `_build_shortcut_widgets` for why the buttons are
transparent rather than zero-sized.
"""

import panel as pn


class ShortcutsMixin:
    """The hidden shortcut buttons and their `keydown` listener."""

    def _build_shortcut_widgets(self):
        # Part E5 (and Esc, pulled forward earlier since toggle-only
        # selection makes it essential, not a convenience): global keyboard
        # shortcuts for the labelling loop. Panel has no built-in
        # global-keyboard-shortcut hook, so each shortcut is a real,
        # visually-invisible Button wired to the same handler a visible
        # control would use, "clicked" programmatically by one shared
        # `pn.pane.HTML` script listening for `keydown` on `document` — see
        # `layout()`, where all of these are placed together.
        #
        # `opacity: 0` with real (1px) dimensions, not `width=0, height=0`
        # or `display: none` — either of those risks a browser/Bokeh CSS
        # layout rule collapsing a zero-size element out of the render
        # tree, which can make `.click()` silently do nothing in some
        # browsers (a real, plausible cause of an earlier Esc-doesn't-work
        # report). `pointer-events: none` just stops each button being an
        # invisible click-trap for the mouse; JS `.click()` bypasses that
        # entirely regardless.
        def _hidden_shortcut_button(css_class, handler):
            btn = pn.widgets.Button(
                name="", css_classes=[css_class], width=1, height=1,
                styles={"opacity": "0", "position": "fixed", "pointer-events": "none",
                        "top": "0", "left": "0"},
            )
            btn.on_click(handler)
            return btn

        self._shortcut_buttons = [
            _hidden_shortcut_button("shortcut-escape", self._on_clear_annotation_selection),
            _hidden_shortcut_button("shortcut-verdict-1", lambda _e: setattr(self, "verdict", "interesting")),
            _hidden_shortcut_button("shortcut-verdict-2", lambda _e: setattr(self, "verdict", "not_interesting")),
            _hidden_shortcut_button("shortcut-verdict-3", lambda _e: setattr(self, "verdict", "artifact")),
            _hidden_shortcut_button("shortcut-verdict-4", lambda _e: setattr(self, "verdict", "unsure")),
            _hidden_shortcut_button("shortcut-save", self._save_annotation),
            _hidden_shortcut_button("shortcut-next", self._on_nav_next),
            _hidden_shortcut_button("shortcut-prev", self._on_nav_prev),
            _hidden_shortcut_button("shortcut-review", self._mark_viewport_reviewed),
            _hidden_shortcut_button("shortcut-mode-pan", lambda _e: setattr(self.drag_mode, "value", "Pan")),
            _hidden_shortcut_button("shortcut-mode-newspan", lambda _e: setattr(self.drag_mode, "value", "New span")),
            _hidden_shortcut_button("shortcut-mode-selectann",
                                     lambda _e: setattr(self.drag_mode, "value", "Select annotations")),
        ]
        # `_escape_key_button`/`_escape_key_listener` names kept (rather
        # than renamed to "shortcut_listener") so anything that already
        # referenced them (tests, this turn's earlier C2 fix) still works.
        self._escape_key_button = self._shortcut_buttons[0]
        self._escape_key_listener = pn.pane.HTML(
            """
            <script>
            (function() {
                var KEY_MAP = {
                    'Escape': 'shortcut-escape',
                    '1': 'shortcut-verdict-1', '2': 'shortcut-verdict-2',
                    '3': 'shortcut-verdict-3', '4': 'shortcut-verdict-4',
                    'Enter': 'shortcut-save',
                    'n': 'shortcut-next', 'p': 'shortcut-prev',
                    'r': 'shortcut-review',
                    'z': 'shortcut-mode-pan', 'x': 'shortcut-mode-newspan', 'c': 'shortcut-mode-selectann'
                };
                function handleShortcut(e) {
                    var tag = (document.activeElement && document.activeElement.tagName) || '';
                    if (tag === 'INPUT' || tag === 'TEXTAREA') { return; }
                    var cls = KEY_MAP[e.key];
                    if (!cls) { return; }
                    var candidates = document.querySelectorAll('.' + cls + ', .' + cls + ' button');
                    candidates.forEach(function(el) {
                        if (el.tagName === 'BUTTON') { el.click(); }
                    });
                }
                document.removeEventListener('keydown', window.__annotationShortcutHandler || function(){});
                window.__annotationShortcutHandler = handleShortcut;
                document.addEventListener('keydown', handleShortcut);
            })();
            </script>
            """,
            width=1, height=1, margin=0, styles={"opacity": "0"},
        )
        self.shortcut_reference = pn.pane.Markdown(
            "**Keyboard shortcuts** (not while typing in a text field): "
            "`1`-`4` = verdict (interesting/not interesting/artifact/unsure) &nbsp;|&nbsp; "
            "`Enter` = save annotation &nbsp;|&nbsp; `n`/`p` = next/previous annotation &nbsp;|&nbsp; "
            "`Esc` = clear annotation selection &nbsp;|&nbsp; `r` = mark viewport reviewed &nbsp;|&nbsp; "
            "`z`/`x`/`c` = drag mode: Pan / New span / Select annotations",
            styles={"background": "#f0f0f0", "padding": "6px 10px", "border-radius": "4px"},
        )
