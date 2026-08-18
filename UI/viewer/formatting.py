"""
Span-width wording shared by the viewport readout (`navigation`) and the
pending-span readout (`selection`). Both must describe the same span with
the same words, so there is one formatter, not two.
"""

def _format_duration_human(seconds):
    """"12 min 30 s" / "3 h 20 min" / "45 s" — the two largest applicable
    units, dropping the smaller one when it's zero. Used for the pending
    span's live width readout (Part 2b)."""
    seconds = abs(seconds)
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    total_s = int(round(seconds))
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h} h {m} min" if m else f"{h} h"
    if m > 0:
        return f"{m} min {s} s" if s else f"{m} min"
    return f"{s} s"
