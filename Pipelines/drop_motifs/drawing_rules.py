"""
drawing_rules.py
=================
The nine drawing rules of drop_motifs12b, in one place, imported by every
figure in the run. They are requirements rather than per-figure decisions,
which is why they are a module and not a paragraph in each figure's
docstring.

Why this module exists: what went wrong in round 11
----------------------------------------------------
Three faults, all diagnosed, all of them a *drawing* fault rather than a
measurement fault.

1. THE NORMALISED PANELS PLOTTED ONLY THE FALL. `store11.normalised_fall`
   resamples onset->trough and nothing else, so the shoulder the fall
   departs from and the recovery it returns through were cropped out. Every
   species then looked like the same monotone descent, because the middle
   of a drop IS the same monotone descent whatever drew it. `phase_trace`
   below keeps the approach and the recovery, and `PHASE_LO`/`PHASE_HI`
   put them in frame.

2. A 200-POINT RESAMPLE OF A SIX-SAMPLE FALL IS FIVE STRAIGHT SEGMENTS.
   The Reishi normalised curve in round 11 was literally that. The
   200-point z-normalised vector is a DISTANCE representation - it exists
   so two events of different length can be subtracted - and it is not a
   picture. Nothing here resamples. Every function returns the event's own
   samples at their own times, and the only thing normalisation touches is
   the VALUES.

3. THE WATERFALL OFFSET WAS ABOUT 4x EACH WAVEFORM'S OWN AMPLITUDE, which
   flattens every trace to a horizontal line however tall the panel is.
   `waterfall_offset` is 0.8x the DRAWN peak-to-peak, so successive traces
   slightly overlap and none is flattened.

The nine rules and where each one lives
----------------------------------------
    1 real samples, real seconds        `snippet_trace`, `framed_trace`,
                                        `phase_trace` - none resamples
    2 the whole stored snippet          `PRE_ONSET_FALLS`/`POST_TROUGH_FALLS`
    3 height-to-width locked            `figure_aspect`, `apply_aspect`,
                                        `aspect_caption`
    4 panels taller than wide           `TARGET_RATIO` = 1.8, in 1:1 - 3:1
    5 normalised axis -0.5 to 1.5       `PHASE_LO`, `PHASE_HI`
    6 offset = 0.8 x drawn p2p, <= 25   `waterfall_offset`, `thin`,
      traces, an explicit scale bar     `MAX_TRACES`, `scale_bar`
    7 colour graded by time             `time_colours`
    8 a raw reference strip on every    `reference_strip`
      sequence figure
    9 a drop must look like a drop      `drawn_ratio`, `check_drop_shape`

A note on rule 2, because the work order and the store disagree
----------------------------------------------------------------
The rule says "draw the whole stored snippet - 1.2 falls before onset, 1.8
after trough". Those are two different things on this store.
`motifs5.rows_and_arrays` writes `snippet_start_idx`/`snippet_end_idx` as
the DETECTOR'S WINDOW bounds - its own docstring says so - and the Reishi
corpus used a 50 s window for a 0.7 s fall. Drawing the whole of that puts
the event in 1.4% of the panel width, which is the flat-line failure rule 9
forbids, arrived at from the other direction.

So the frame is the one the same sentence specifies: 1.2 falls before the
onset to 1.8 falls after the trough, CLIPPED to what the stored snippet
actually holds. It is never cropped to onset->trough, which was the actual
round-11 fault. Where the stored window is shorter than the frame asks for,
`framed_trace` says so in its third return value rather than silently
returning less context than the label claims.

No detection, no measurement this module owns. It draws.
"""

import numpy as np
from matplotlib import colors as mcolors

from Pipelines.drop_motifs import config11, style7

# ==========================================================================
# Rule 2 - the frame
# ==========================================================================

# In multiples of the event's OWN fall duration: how much approach before
# the onset, and how much recovery after the trough. Never cropped to
# onset->trough; that crop is what made round 11's families identical.
PRE_ONSET_FALLS = 1.2
POST_TROUGH_FALLS = 1.8

SHAPE_FIELD = "detrended_mv"


def snippet_trace(row, snippets, field=SHAPE_FIELD):
    """`(t_from_onset_s, mv)` - the whole stored array, real samples.

    A crop and an offset, never a rescaling. `t` is seconds from this
    event's own onset and `y` is millivolts with the value at the onset
    removed, so events from different parts of a drifting trace can share
    an axis without any of them changing shape.
    """
    arrays = snippets.get(row["event_id"])
    if arrays is None:
        return None, None
    values = np.asarray(arrays[field], dtype=float)
    onset = int(row["onset_idx"]) - int(row["snippet_start_idx"])
    if values.size < 3 or not (0 <= onset < values.size):
        return None, None
    t = (np.arange(values.size) - onset) / float(row["fs"])
    return t, values - values[onset]


def fall_duration_s(row):
    """The event's fall duration, never zero - one sample if the store says 0."""
    duration = abs(float(row.get("fall_duration_s", 0.0)))
    if not np.isfinite(duration) or duration <= 0:
        return 1.0 / float(row["fs"])
    return duration


def framed_trace(row, snippets, field=SHAPE_FIELD,
                 pre=PRE_ONSET_FALLS, post=POST_TROUGH_FALLS):
    """`(t, mv, complete)` - the rule-2 frame, clipped to the stored array.

    `complete` is False when the stored window is shorter than the frame
    asks for on either side, so a caller can say "this is all the context
    there is" instead of implying the frame was honoured.
    """
    t, y = snippet_trace(row, snippets, field=field)
    if t is None:
        return None, None, False
    fall = fall_duration_s(row)
    lo = -pre * fall
    hi = (1.0 + post) * fall
    keep = (t >= lo) & (t <= hi)
    if keep.sum() < 3:
        return t, y, False
    complete = bool(t[0] <= lo + 1e-9 and t[-1] >= hi - 1e-9)
    return t[keep], y[keep], complete


# How far back a sequence frame may reach, in multiples of the event's own
# fall. `sequence_frames` reaches to the PREVIOUS event's trough, which is
# what makes a sharkfin look like a sharkfin - the slow rise belongs to the
# motif and cropping it leaves only the fall. The cap is for the gap that is
# not a rise: one 40-minute silence in an Oyster run would otherwise set a
# 400-fall window and draw every event in the last 1% of it.
MAX_PRE_FALLS = 14.0


def sequence_frames(members, snippets, field=SHAPE_FIELD,
                    post=POST_TROUGH_FALLS, max_pre_falls=MAX_PRE_FALLS):
    """`(traces, rows, reach)` - each event framed back to the PREVIOUS trough.

    The whole cycle, not the fall: an Oyster event is a 6 s fall on the end
    of a 55 s rise, and `Plots/drop_motifs7/id003_overlays.png` is legible
    precisely because it draws both. A frame of 1.2 falls before the onset
    shows the last tenth of that rise, which is a shoulder rather than a
    sharkfin.

    The left edge is the previous member's trough, so the frame holds exactly
    the recovery-and-ramp that leads into this event and never reaches into
    the event before that. The first member of a run has no predecessor and
    falls back to `PRE_ONSET_FALLS`. Every frame is clipped to what the
    stored array holds.

    `reach` is the per-event distance from the onset back to the frame's
    left edge, in falls - the quantity a caller needs to choose an x view and
    to say how far back the panel actually reaches.
    """
    traces, kept, reach = [], [], []
    previous_trough = None
    for row in members:
        t, y = snippet_trace(row, snippets, field=field)
        if t is None:
            previous_trough = int(row["trough_idx"])
            continue
        fall = fall_duration_s(row)
        fs = float(row["fs"])
        if previous_trough is None:
            pre_s = PRE_ONSET_FALLS * fall
        else:
            pre_s = (int(row["onset_idx"]) - previous_trough) / fs
        pre_s = float(np.clip(pre_s, 0.0, max_pre_falls * fall))

        keep = (t >= -pre_s) & (t <= (1.0 + post) * fall)
        previous_trough = int(row["trough_idx"])
        if keep.sum() < 3:
            continue
        traces.append((t[keep], y[keep]))
        kept.append(row)
        reach.append(float(-t[keep][0] / fall))
    return traces, kept, reach


# ==========================================================================
# Rule 1 and rule 5 - normalising the VALUES, never the samples
# ==========================================================================

# The normalised x axis, in fall-fractions. 0 is the onset and 1 is the
# trough; the range runs either side so the approach and the recovery are
# in frame. Round 11 ran 0 to 1 and that alone made every species look the
# same - see the module docstring.
PHASE_LO = -0.5
PHASE_HI = 1.5


def phase_trace(row, snippets, field=SHAPE_FIELD,
                lo=PHASE_LO, hi=PHASE_HI):
    """`(phase, z)` - real samples, both axes normalised, nothing resampled.

    `phase` is `(t - onset) / fall_duration`, so one unit is one fall and
    the axis is the "fraction of the fall" axis round 11 used - extended
    either side rather than replaced, because it is the right axis.

    `z` is the event's millivolts standardised by the mean and standard
    deviation OF ITS OWN FALL, applied to the whole frame. Taking the
    statistics from the fall and not from the frame is what makes two
    events comparable: a frame is 1.2 + 1 + 1.8 = 4 falls of mostly
    baseline, so a frame-wide sd is dominated by however much quiet
    happened to be included and would rescale the drop by the length of
    its own window.

    The number of points returned is the number of samples the event has.
    A six-sample fall comes back as six samples in the fall, and it looks
    like a six-sample fall, which is the honest picture of it.
    """
    t, y, _complete = framed_trace(row, snippets, field=field,
                                   pre=max(-lo, 0.0) + 0.1,
                                   post=max(hi - 1.0, 0.0) + 0.1)
    if t is None:
        return None, None
    fall = fall_duration_s(row)
    phase = t / fall
    keep = (phase >= lo) & (phase <= hi)
    if keep.sum() < 3:
        keep = np.ones(phase.size, dtype=bool)

    in_fall = (phase >= 0.0) & (phase <= 1.0)
    block = y[in_fall] if in_fall.sum() >= 2 else y
    sd = float(np.std(block))
    if not np.isfinite(sd) or sd == 0.0:
        return None, None
    return phase[keep], (y[keep] - float(np.mean(block))) / sd


def phase_block(rows, snippets, field=SHAPE_FIELD):
    """`(traces, kept)` - every drawable `phase_trace`, in the order given."""
    traces, kept = [], []
    for row in rows:
        try:
            phase, z = phase_trace(row, snippets, field=field)
        except (KeyError, ValueError):
            continue
        if phase is None:
            continue
        traces.append((phase, z))
        kept.append(row)
    return traces, kept


# ==========================================================================
# Rules 3 and 4 - height-to-width, locked and tall
# ==========================================================================

# The proportion the MEDIAN event of a figure is drawn at, height over
# width. Round 11's panels were about 1.6:1 landscape, which flattens a
# drop before any other rule gets a chance to. The work order's band is
# 1:1 to 3:1 and the target sits in the middle of it.
TARGET_RATIO = 1.8
MIN_RATIO = 1.0
MAX_RATIO = 3.0


def _depths_and_falls(rows):
    depths = np.array([abs(float(r.get("drop_depth_mv", 0.0))) for r in rows],
                      dtype=float)
    falls = np.array([fall_duration_s(r) for r in rows], dtype=float)
    good = (np.isfinite(depths) & np.isfinite(falls)
            & (depths > 0) & (falls > 0))
    return depths[good], falls[good]


def figure_aspect(rows, target=TARGET_RATIO):
    """`(aspect, drawn_ratio, capped)` for one figure or panel.

    `aspect` is what `set_aspect` wants: one millivolt of y is drawn that
    many times the display length of one second of x. Derived through
    `style7.seconds_per_mv`, which is the function that already exists for
    this and which clamps the extreme cases - a median event that is nearly
    flat, or nearly instantaneous, otherwise asks for an axes box thousands
    of times longer in one direction than the other and matplotlib answers
    by shrinking it to a hairline.

    `drawn_ratio` is the height-to-width the median event actually comes
    out at. It equals `target` unless `style7`'s clamp bit, and `capped`
    says which. A capped panel prints the realised ratio on its label
    rather than passing the target off as achieved - capping silently is
    what makes a figure lie about a shape.
    """
    depths, falls = _depths_and_falls(rows)
    if depths.size == 0:
        return 1.0, float("nan"), False
    aspect = style7.seconds_per_mv(depths, falls, target=target)
    drawn = float(aspect * float(np.median(depths)) / float(np.median(falls)))
    return aspect, drawn, bool(abs(drawn - target) > 1e-6)


def drawn_ratio(aspect, rows):
    """The height-to-width the median of `rows` is drawn at, at `aspect`."""
    depths, falls = _depths_and_falls(rows)
    if depths.size == 0 or not np.isfinite(aspect) or aspect <= 0:
        return float("nan")
    return float(aspect * np.median(depths) / np.median(falls))


def apply_aspect(ax, aspect, adjustable="box"):
    """Lock one axes to a millivolt-per-second scale. `style7`'s function."""
    style7.apply_aspect(ax, aspect, adjustable=adjustable)


def aspect_caption(aspect, drawn=None, capped=False):
    """The lock, in the words rule 3 asks for, stated once per figure."""
    text = style7.aspect_caption(aspect)
    if drawn is not None and np.isfinite(drawn):
        text += f"; median event drawn {drawn:.2g}:1 height-to-width"
    if capped:
        text += " (capped)"
    return text


def check_drop_shape(ratio, floor=MIN_RATIO, ceiling=MAX_RATIO):
    """Rule 9, as a predicate. `(ok, why)`.

    The flat direction is the one that destroys the figure: an event drawn
    below 1:1 is the near-horizontal line the whole run exists to stop.
    Above the ceiling a panel is a sliver, which is bad but visible.
    """
    if not np.isfinite(ratio):
        return False, "no median event to measure"
    if ratio < floor:
        return False, (f"median event drawn {ratio:.2g}:1 - flatter than "
                       f"{floor:g}:1, so a drop does not look like a drop")
    if ratio > ceiling:
        return False, (f"median event drawn {ratio:.2g}:1 - taller than "
                       f"{ceiling:g}:1, so the panel is a sliver")
    return True, f"median event drawn {ratio:.2g}:1 height-to-width"


# ==========================================================================
# Rule 6 - the waterfall
# ==========================================================================

# At most this many traces in one waterfall. Round 11 drew up to 42 and
# they smeared; 25 is the work order's number and it is also about where
# an 0.8 overlap stops being readable.
MAX_TRACES = 25

# Successive traces are separated by this fraction of the panel's own drawn
# peak-to-peak, so they overlap slightly. Round 11 used roughly 4x, which
# is what flattened them.
OFFSET_FRACTION = 0.8


def thin(members, limit=MAX_TRACES):
    """`(drawn, k)` - every `k`th member, first and last always kept.

    Evenly spaced rather than the first `limit`: a sequence's whole point
    is that its ends differ, and taking a prefix throws the far end away.
    `k` is stated on the figure, as the rule requires.
    """
    members = list(members)
    if len(members) <= limit:
        return members, 1
    k = int(np.ceil(len(members) / float(limit)))
    picks = list(range(0, len(members), k))
    if picks[-1] != len(members) - 1:
        picks.append(len(members) - 1)
    while len(picks) > limit:
        picks.pop(-2)
    return [members[i] for i in picks], k


def waterfall_offset(traces, fraction=OFFSET_FRACTION):
    """`fraction` x the median DRAWN peak-to-peak of the traces in a panel.

    Measured on what is actually plotted, not on `drop_depth_mv`: the frame
    carries the approach and the recovery, so its excursion is larger than
    the fall's depth, and an offset derived from the depth would leave the
    recoveries overlapping by much more than 0.8.
    """
    spans = [float(np.ptp(np.asarray(y, dtype=float)))
             for _t, y in traces if np.asarray(y).size]
    spans = [s for s in spans if np.isfinite(s) and s > 0]
    if not spans:
        return 1.0
    return float(fraction) * float(np.median(spans))


def scale_bar(ax, size, unit="mV", *, x_fraction=0.035, y_anchor=0.0,
              colour=None, fontsize=None, lw=2.2):
    """A drawn bar of `size` units of y, with its own label.

    Required by rule 6, because a waterfall's y axis is offsets and carries
    no readable ticks. Placed a little inside the left spine with the label
    to its right - drawn exactly on the spine the two overprint.
    """
    colour = colour or style7.RULE_COLOUR
    fontsize = fontsize or config11.FS_ANNOT
    low, high = ax.get_xlim()
    x = low + x_fraction * (high - low)
    ax.plot([x, x], [y_anchor, y_anchor - size], color=colour, lw=lw,
            zorder=6, solid_capstyle="butt")
    ax.annotate(f"{size:.3g} {unit}", xy=(x, y_anchor - size / 2.0),
                xytext=(6, 0), textcoords="offset points", ha="left",
                va="center", fontsize=fontsize, color="0.30", zorder=6)
    return x


# ==========================================================================
# Rule 7 - colour graded by time within the sequence
# ==========================================================================

def species_ramp(species, resolved=None):
    """A light-to-dark ramp through the species' OWN hue.

    `overlays6`/`overlays7` grade by time within one hue; their hue comes
    from a family index, which in a species figure draws an oyster sequence
    in reishi's green. The ramp is built from the species' configured
    colour so that colour carries species here as it does everywhere else,
    and time is graded within it.
    """
    base = np.array(mcolors.to_rgb(config11.colour_of(species, resolved)))
    light = 1.0 - 0.80 * (1.0 - base)
    dark = 0.42 * base
    return mcolors.LinearSegmentedColormap.from_list(
        f"time_{species}", [light, base, dark], N=256)


def time_colours(members, species, resolved=None):
    """`(colours, norm, cmap)` - one colour per event, oldest to newest.

    The norm runs over elapsed seconds FROM THE START OF THE SEQUENCE. An
    oyster sequence starting at 1,362,824 s otherwise gives a colourbar
    reading "1.3630 ... 1.3665, x1e6", which nobody can use.
    """
    cmap = species_ramp(species, resolved)
    onsets = np.array([float(r["onset_s"]) for r in members], dtype=float)
    if onsets.size == 0:
        return [], None, cmap
    elapsed = onsets - onsets.min()
    high = float(elapsed.max())
    norm = mcolors.Normalize(vmin=0.0, vmax=high if high > 0 else 1.0)
    return [cmap(norm(value)) for value in elapsed], norm, cmap


# ==========================================================================
# Rule 8 - the raw reference strip
# ==========================================================================

# Columns of min-max envelope across a reference strip. A sequence can span
# a million samples and they cannot be drawn one per pixel; a STRIDE would
# delete narrow events, which is the one thing a strip exists to show.
# `regionfigs12.envelope` is the function and its docstring is the reason.
STRIP_COLUMNS = 4000

# The narrowest a shaded event may be drawn on a strip, as a fraction of
# the strip. See `reference_strip`.
MIN_SHADE_FRACTION = 0.0015

# The strip's own line weight. `style7.LW_SIGNAL` is the weight for a trace
# sitting BEHIND overlays; here the trace is the subject of its own panel and
# at that weight it is almost invisible over a 4,000-second span.
STRIP_LW = 1.15


def reference_strip(ax, x_mv, fs, start_idx, rows, colours, *,
                    time_unit="s", signal_colour=None, lw=None,
                    alpha=0.34):
    """The source trace over a sequence's whole span, events shaded.

    Rule 8, and it is the panel round 11 was missing: without it a reader
    has no way to see where the waveforms beneath came from. `x_mv` is the
    slice of the channel in millivolts, `start_idx` its absolute first
    sample, and each row is shaded from its onset to its trough in that
    event's own gradient colour.

    Returns the x values used, so a caller can set limits against them.
    """
    from Pipelines.drop_motifs.regionfigs12 import envelope

    x_mv = np.asarray(x_mv, dtype=float)
    divisor = 3600.0 if time_unit == "h" else 1.0
    centres, lo, hi = envelope(x_mv, columns=STRIP_COLUMNS)
    t = (start_idx + centres) / float(fs) / divisor

    colour = signal_colour or style7.SIGNAL_COLOUR
    width = STRIP_LW if lw is None else lw
    if lo.size and np.allclose(lo, hi):
        # Fewer samples than envelope columns, so the envelope collapsed to
        # the trace itself. That is the Oyster case - a 4,000 s sequence at
        # 1 Hz is 4,000 samples against 4,000 columns - and it was drawn at
        # `style7.LW_SIGNAL`, which is the weight for a background trace
        # behind overlays rather than for the panel a reader is meant to
        # read the sequence off. It is the SUBJECT of this panel.
        ax.plot(t, lo, color=colour, lw=width, zorder=3,
                solid_capstyle="round", solid_joinstyle="round")
    else:
        # A min-max band can still be a hairline where the signal is smooth,
        # so the band is stroked as well as filled and the stroke sets its
        # minimum drawn weight.
        ax.fill_between(t, lo, hi, facecolor=colour, edgecolor=colour,
                        lw=width, zorder=3)

    # A shaded span narrower than this fraction of the strip is widened to
    # it. A 0.4 s Lion's mane fall inside a 2,500 s sequence is a fifth of
    # one pixel column and vanishes, which defeats the panel: the reader is
    # here to see WHERE the events are, and a mark too thin to see is worse
    # than a mark slightly wider than the event. It is symmetric about the
    # event, so nothing moves.
    span = float(t[-1] - t[0]) if t.size else 1.0
    floor = MIN_SHADE_FRACTION * span
    for row, event_colour in zip(rows, colours):
        onset = int(row["onset_idx"]) / float(fs) / divisor
        trough = int(row["trough_idx"]) / float(fs) / divisor
        if trough - onset < floor:
            centre = 0.5 * (onset + trough)
            onset, trough = centre - floor / 2.0, centre + floor / 2.0
        ax.axvspan(onset, trough, color=event_colour, alpha=alpha, lw=0.0,
                   zorder=2)
    if t.size:
        ax.set_xlim(float(t[0]), float(t[-1]))
    ax.set_ylabel(f"mV, raw")
    ax.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)
    return t


# ==========================================================================
# the one-line statement every figure carries
# ==========================================================================

def rules_footer(aspect, drawn, *, n_drawn=None, k=1, capped=False):
    """The lock, the drawn proportion and any thinning, in one line."""
    parts = [aspect_caption(aspect, drawn, capped)]
    if n_drawn is not None:
        parts.append(f"{n_drawn} traces, {every_kth(k)} drawn")
    return "; ".join(parts)


def every_kth(k):
    """`every event` / `every 2nd event` / `every 3rd event`, spelled right."""
    k = int(k)
    if k <= 1:
        return "every event"
    tens = k % 100
    suffix = "th" if tens in (11, 12, 13) else {1: "st", 2: "nd",
                                                3: "rd"}.get(k % 10, "th")
    return f"every {k}{suffix} event"


# ==========================================================================
# distances - a representation, never a picture
# ==========================================================================

# The length the phase frame is resampled to when two events of different
# sample count have to be SUBTRACTED. This vector is a distance
# representation and rule 1 forbids drawing it; `phase_trace` is what gets
# drawn. The two cover the same frame - `PHASE_LO` to `PHASE_HI` - so the
# number under a panel measures the shapes the panel shows, which was not
# true in round 11: its distances were measured onset-to-trough while its
# panels claimed to show a waveform.
N_FEATURE = 200


def phase_feature(row, snippets, n=N_FEATURE, field=SHAPE_FIELD):
    """The phase frame on a common grid, for distance only. Never plotted."""
    phase, z = phase_trace(row, snippets, field=field)
    if phase is None or phase.size < 3:
        return None
    grid = np.linspace(PHASE_LO, PHASE_HI, int(n))
    return np.interp(grid, phase, z)


def phase_features(rows, snippets, n=N_FEATURE, field=SHAPE_FIELD):
    """`(matrix, kept)` - every drawable phase feature, in the order given."""
    block, kept = [], []
    for row in rows:
        try:
            vector = phase_feature(row, snippets, n=n, field=field)
        except (KeyError, ValueError):
            continue
        if vector is None or not np.all(np.isfinite(vector)):
            continue
        block.append(vector)
        kept.append(row)
    if not block:
        return np.empty((0, int(n))), []
    return np.vstack(block), kept


def rms(a, b):
    """Euclidean distance over a fixed grid, / sqrt(n).

    Reads as the RMS z difference per point, so it stays comparable across
    figures and across grid lengths.
    """
    a = np.asarray(a, dtype=float)
    return float(np.linalg.norm(a - np.asarray(b, dtype=float))
                 / np.sqrt(a.size))


# ==========================================================================
# how many traces fit before a locked column stops fitting a page
# ==========================================================================

# Stacking N traces at 0.8 of their own peak-to-peak makes a column about
# 0.8N peak-to-peaks tall and one event wide. Lock each event at 1.8:1 and
# the COLUMN is then about 10:1 at 25 traces, which does not fit a page at
# any width a trace is legible at. Round 11 solved this by drawing the
# column in a landscape box, which is precisely what flattened every trace.
#
# The honest solution is to draw fewer traces and say so - rule 6 says "at
# most 25" and "state k" for exactly this reason. This is the ratio a
# waterfall column is allowed to reach before the trace count is cut.
MAX_COLUMN_RATIO = 5.5


def waterfall_capacity(aspect, offset, x_range, n_available,
                       max_ratio=MAX_COLUMN_RATIO, limit=MAX_TRACES):
    """How many traces a locked column can hold at a printable shape.

    `aspect` is the lock, `offset` the per-trace separation in y units and
    `x_range` the frame's width in x units. Returns at least three: below
    that a waterfall is not a waterfall, and a figure of two traces should
    say so rather than be silently drawn.
    """
    if not (np.isfinite(aspect) and aspect > 0 and offset > 0 and x_range > 0):
        return int(min(limit, n_available))
    fits = int(np.floor(max_ratio * float(x_range)
                        / (float(aspect) * float(offset))))
    return int(max(3, min(limit, n_available, max(fits, 3))))
