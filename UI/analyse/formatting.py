"""
Read-only readouts shared across the run panel: the diagnostics/derived
tables and the span-width caption.
"""

from Working.config import UI_TABLE_FONT_SIZE

from UI.plots import format_scale_viewed


_SEVERITY_STYLE = {
    "": "",
    "warn": "background:#fff3cd;color:#7a5b00;",
    "error": "background:#f8d7da;color:#7a1f28;",
}


def _rows_to_html(rows):
    """(label, value, severity) rows -> a compact read-only HTML table,
    warn rows amber and error rows red (Part 6, 4b) — plain HTML rather
    than a Tabulator since this is a small, purely read-only readout with
    no interaction, recomputed on every parameter change."""
    if not rows:
        return ""
    trs = []
    for label, value, severity in rows:
        style = _SEVERITY_STYLE.get(severity, "")
        trs.append(
            f'<tr style="{style}"><td style="padding:2px 8px 2px 0;white-space:nowrap;'
            f'font-weight:600;">{label}</td><td style="padding:2px 0;">{value}</td></tr>'
        )
    return f'<table style="border-collapse:collapse;font-size:{UI_TABLE_FONT_SIZE};">{"".join(trs)}</table>'


def _format_duration_human(seconds):
    """Space-separated variant of `UI.plots.format_scale_viewed` for a
    table cell / preview caption (Part 5, Sections A/C) — reuses that
    function's exact thresholds and rounding (so "10 min" here and the
    zoom-span label on an annotation always describe the same span
    identically) rather than a second, independently-tuned formatter."""
    label = format_scale_viewed((0.0, seconds), (0.0, seconds))
    for i, ch in enumerate(label):
        if ch.isalpha():
            return f"{label[:i]} {label[i:]}"
    return label
