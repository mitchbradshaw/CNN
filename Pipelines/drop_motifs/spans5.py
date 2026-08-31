"""
spans5.py
==========
The sixteen spans the five-stage detector is evaluated on, and how to read
one out of the database.

Where the list came from
------------------------
Fifteen are operator-chosen catalogue IDs. The catalogue's own `ID_Number`
is NOT stored on the annotation - `Pipelines/import_catalogue` writes the
note and the span but not the row number - so the mapping here was
recovered by joining `DATA/catalogue/signal_catalog.xlsx` on start and stop
hours and is recorded explicitly rather than recomputed, because the join
is only unambiguous while both files stay as they are.

The sixteenth is Mushroom_260720, which is not on the operator's list. It
is here because it is the only non-M2 recording in the set and the only
span with a hand-built reference (26 detected against 25 marked, recall
0.96, under the three-stage detector), so without it the new detector
would be validated entirely on one experiment. Its icicles are also the
trough morphology at 3-47 s, an order of magnitude shorter than any other
trough candidate, which makes it the span most likely to catch a
regression in the mirrored window rule.

`annotated_n` is a CHECK and never an input. It is read into the report
and compared, but no parameter is derived from it: a period derived from
"16 cycles" would make finding sixteen events circular, and the
16-from-16 agreement on catalogue ID 1 is the only external validation
this work has.
"""

import numpy as np

# catalogue ID -> everything needed to run and to grade the span.
#
# `annotated_n` is the count the catalogue states in prose where it states
# one, and None where it does not. `expect` is the morphology a reader of
# the catalogue's `Elements` column would predict, recorded so the
# detector's own choice can be disagreed with in the report rather than
# accepted silently.
SPANS5 = {
    1:  dict(annotation=11266, recording=1,  span=(336.0, 346.0),
             annotated_n=16, expect="sharkfin",
             note="amplitude modulation increasing; frequency modulation "
                  "DECREASING; 16 cycles; 20-70 mV. The reference span: the "
                  "only one with an independent human count."),
    3:  dict(annotation=11268, recording=1,  span=(314.448, 316.831),
             annotated_n=16, expect="sharkfin",
             note="regular amplitude and frequency; transition from "
                  "crestedwave to sharkfin; 16 cycles; 10 mV."),
    8:  dict(annotation=11273, recording=1,  span=(267.4, 267.6),
             annotated_n=4, expect="sharkfin",
             note="halfdome x4; fm increasing, am constant; 50 mV. The "
                  "shortest span here at 720 samples."),
    10: dict(annotation=11275, recording=4,  span=(378.5, 381.0),
             annotated_n=None, expect="sharkfin",
             note="halfdome; 3 sequences, 20+ 7 9, variable width; 2-3 mV. "
                  "Cited in the catalogue for dynamic attractor "
                  "self-termination."),
    20: dict(annotation=11279, recording=1,  span=(337.089, 338.165),
             annotated_n=4, expect="sharkfin",
             note="4x sharkfin sequence. A sub-span of catalogue ID 1."),
    21: dict(annotation=11280, recording=1,  span=(314.526, 316.5),
             annotated_n=14, expect="sharkfin",
             note="14x sharkfin sequence. A sub-span of catalogue ID 3, and "
                  "the span with the strongest autocorrelation in the set."),
    22: dict(annotation=11281, recording=1,  span=(290.747, 293.335),
             annotated_n=None, expect="sharkfin",
             note="3 high-frequency patterns with 2 larger sharkfins "
                  "between them. TWO time scales in one span, which is the "
                  "case a single derived period cannot serve."),
    24: dict(annotation=11283, recording=2,  span=(400.0, 460.0),
             annotated_n=None, expect="sharkfin",
             note="long sequence starting at small scale, then larger. "
                  "60 hours; amplitude modulation over the whole span."),
    25: dict(annotation=11284, recording=2,  span=(295.0, 325.0),
             annotated_n=None, expect="trough",
             note="larger sharkfin/TROUGH sequence. The operator flagged "
                  "this as the one most like Mushroom_260720, and as harder "
                  "for a rise-anchored detector because the large drops "
                  "have no preceding UP section."),
    26: dict(annotation=11285, recording=7,  span=(610.0, 680.0),
             annotated_n=None, expect="sharkfin",
             note="lots of triangle shaped ridges along a longer "
                  "low-frequency signal. 70 hours; the weakest "
                  "autocorrelation in the set at 0.04."),
    28: dict(annotation=11287, recording=6,  span=(370.0, 460.0),
             annotated_n=None, expect="sharkfin",
             note="lots of little high-frequency ridges along a "
                  "low-frequency signal. 90 hours, the longest span here."),
    29: dict(annotation=11288, recording=1,  span=(247.2, 249.0),
             annotated_n=None, expect="trough",
             note="spike train oscillation pattern."),
    33: dict(annotation=11292, recording=16, span=(33.2, 34.6),
             annotated_n=None, expect="sharkfin",
             note="long thin sharkfin sequence."),
    34: dict(annotation=11293, recording=16, span=(46.1, 48.2),
             annotated_n=None, expect="sharkfin",
             note="multiple sharkfin sequences along a low-frequency ridge. "
                  "Like ID 22, two scales at once."),
    35: dict(annotation=11294, recording=16, span=(80.1, 80.9),
             annotated_n=None, expect="sharkfin",
             note="clean sharkfin sequence."),
    385: dict(annotation=None, recording=385, span=None,
              annotated_n=25, expect="trough",
              note="Mushroom_260720, whole recording. NOT on the operator's "
                   "list; included as the only non-M2 control and the only "
                   "span with a hand-built reference. Icicles are 3-47 s, "
                   "an order of magnitude shorter than any other trough "
                   "candidate here."),
}


def load_span(recording_row, span_hours):
    """`(samples, start_index)` for one span.

    `mmap_mode="r"` then an explicit copy of the slice, following
    `run_drop_report.load_span`: the M2_aug channels are millions of
    samples and a span usually wants a few tens of thousands of them.
    """
    x = np.load(recording_row["npy_path"], mmap_mode="r")
    fs = float(recording_row["fs"])
    if span_hours is None:
        return np.asarray(x, dtype=float), 0
    start = int(round(span_hours[0] * 3600.0 * fs))
    end = min(int(round(span_hours[1] * 3600.0 * fs)), len(x))
    if start >= end:
        raise SystemExit(f"span {span_hours} is empty in {len(x)} samples")
    return np.asarray(x[start:end], dtype=float), start
