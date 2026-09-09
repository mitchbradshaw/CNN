"""
reportfigs_atlas.py
====================
Report figure 1: `ATLAS_shapes.pdf`, the drop_motifs10 atlas redrawn at
full resolution.

The layout, the ordering, the colour scheme, the annotations and the log
duration strip along the bottom are `figures10.plot_atlas`'s and are meant
to be. One thing changes, and it is what the figure is for.

What changed: the waveform
---------------------------
`figures10` drew `tree10`'s FEATURE vector - the fall resampled to 200
points and z-normalised, which is the representation the Ward tree
clusters on. That is the right object to cluster and the wrong object to
look at. Resampling a 3-sample fall up to 200 points interpolates a
straight line through three real measurements and draws it as if the
detail were there, and resampling a 266-sample fall down to 200 loses
detail that is.

Every panel here is instead the event's OWN SAMPLES, at their own
spacing, from `PAD_FRACTION` of a fall before the onset to the same after
the trough. So a 3-sample fall is drawn as three points plus its context
and looks like the coarse thing it is, and a 266-sample fall is drawn with
all 266.

Why the context matters twice
-----------------------------
It is not only "a little more shape either side". Adding it changes the
ASPECT of the drop, which is the complaint the pad answers. When the fall
alone fills the panel width, every fall is drawn as though it took the
whole frame to happen, and a spike that in the recording is a near-vertical
edge comes out as a gentle diagonal. Padding compresses the fall into
`1 / (1 + 2 * PAD_FRACTION)` of the width, so it is drawn nearer the aspect
it has in the trace, and the shoulder it falls from and the floor it lands
on are both visible.

The z-normalisation is taken over THE FALL, not over the padded trace, so
the vertical scale of each panel means what it meant in drop_motifs10 -
the rule line at y = 0 is still the fall's own mean - and the context is
free to run outside it. A panel autoscales to whatever it holds, exactly
as before.

The medoid is still a real member and never a mean.
"""

import numpy as np

from Pipelines.drop_motifs import config11, corpora10, reportstyle, style10, tree10

# The atlas panel title carries the CORPUS key, not the species key - and
# `reishi_10hz`/`reishi_1hz` are two corpora for one species, `sp385` is
# the store's internal name for Lion's mane. Everywhere else in this run
# resolves display names through `config11`; this is the one place a
# corpus string reaches a title directly, so every corpus is resolved to
# its species' label by hand here, `corpora10.species_of` and all.
_CORPUS_DISPLAY = {corpus: config11.SPECIES[corpora10.species_of(corpus)]["label"]
                   for corpus in corpora10.CORPORA}


def _corpus_display(corpus):
    return _CORPUS_DISPLAY.get(corpus, corpus)

# Context either side, as a fraction of the fall's own length in samples.
# The operator asked for "+-10%, enough to see some shape", and 0.15 is
# that rounded up after looking at the plate: it puts the median panel at
# 29% context, which is enough to show the shoulder the fall departs from
# and the floor it lands on without either dominating.
PAD_FRACTION = 0.15

# A floor in samples, because a fraction of a 3-sample fall rounds to
# nothing. ONE and not two: at two, a 3-sample fall - and the short end of
# this atlas is where most of the grid lives - came out 57% context, and a
# panel whose middle third is the drop reads as an oscillation rather than
# as a drop. The floor is here to guarantee the shoulder is on the page,
# not to frame the event.
PAD_MIN_SAMPLES = 1

COLS = 6


def padded_waveform(row, snippets, *, field="detrended_mv",
                    pad_fraction=PAD_FRACTION,
                    pad_min=PAD_MIN_SAMPLES):
    """`(t_rel_s, z, info)` - the event's own samples, with context.

    `t_rel_s` is seconds from the onset, so the fall runs 0 to its own
    duration and the context is negative before and beyond after. `z` is
    the trace z-normalised on the FALL's mean and standard deviation.

    Returns `(None, None, info)` when the row has no array or the store
    disagrees with itself about the snippet's length - the same two
    refusals `clusterfigs7._waveform_of` makes, and for its reasons. A
    silent clip here is how a one-sample "fall" reached a shipped figure.
    """
    arrays = snippets.get(row["event_id"])
    if arrays is None:
        return None, None, {"reason": "no_array"}
    values = np.asarray(arrays[field], dtype=float)
    start = int(row["snippet_start_idx"])
    expected = int(row["snippet_end_idx"]) - start
    if values.size != expected:
        return None, None, {"reason": "store_mismatch",
                            "have": int(values.size), "want": int(expected)}

    onset = int(np.clip(int(row["onset_idx"]) - start, 0, values.size - 1))
    trough = int(np.clip(int(row["trough_idx"]) - start,
                         onset + 1, values.size))
    fall = values[onset:trough]
    if fall.size < 2:
        return None, None, {"reason": "fall_shorter_than_two_samples"}

    pad = max(int(pad_min), int(np.ceil(pad_fraction * fall.size)))
    lo = max(0, onset - pad)
    hi = min(values.size, trough + pad)
    trace = values[lo:hi]

    # z on the FALL, so y = 0 stays the fall's mean and the panel's
    # vertical scale still means what drop_motifs10's meant.
    centre = float(np.mean(fall))
    spread = float(np.std(fall))
    if spread <= 0.0:
        return None, None, {"reason": "constant_fall"}
    z = (trace - centre) / spread

    fs = float(row["fs"])
    t_rel = (np.arange(lo, hi) - onset) / fs
    return t_rel, z, {
        "reason": None,
        "n_samples_drawn": int(trace.size),
        "n_samples_in_fall": int(fall.size),
        "pad_requested_samples": int(pad),
        "pad_before_samples": int(onset - lo),
        "pad_after_samples": int(hi - trough),
        "context_fraction_of_width":
            float((trace.size - fall.size) / trace.size),
    }


def atlas_entries(trees_by_corpus, snippets, *, cut="fine", **pad_kw):
    """`figures10.atlas_entries` with the real waveform attached.

    Per corpus rather than from a pooled tree, unchanged: "every family
    medoid from every corpus" is the question, and a pooled coarse cut
    answers a different one. Ordered by NATIVE fall duration, so the
    reading direction of the grid is absolute scale.
    """
    entries, refused = [], []
    for corpus, tree in trees_by_corpus.items():
        if tree is None:
            continue
        labels = tree[cut]
        rows = tree["rows"]
        for family, index in tree10.medoids(tree["features"], labels).items():
            row = rows[index]
            members = [r for r, lab in zip(rows, labels) if int(lab) == family]
            t_rel, z, info = padded_waveform(row, snippets, **pad_kw)
            if t_rel is None:
                refused.append({"corpus": corpus, "family": int(family),
                                "event_id": row["event_id"], **info})
                continue
            entries.append({
                "corpus": corpus,
                "family": int(family),
                "n": len(members),
                "event_id": row["event_id"],
                "species": row["species"],
                "fs": float(row["fs"]),
                "native_fall_s": float(row["fall_duration_s"]),
                "native_depth_mv": abs(float(row["drop_depth_mv"])),
                "n_samples_in_fall": int(row["n_samples_in_fall"]),
                "t_rel_s": t_rel,
                "z": z,
                "trace": info,
            })
    entries.sort(key=lambda e: e["native_fall_s"])
    return entries, refused


def plot_atlas(trees_by_corpus, snippets, path, *, cut="fine",
               cols=COLS, proof_png=None, **pad_kw):
    """Every family medoid from every corpus, real samples, one axis each.

    No figure title: rule 3 keeps process text off the plate, and this
    report caption - "N family medoids from M corpora..." - is the one
    line of context left, so the band above the grid is sized for it
    rather than for a suptitle nobody draws.
    """
    from matplotlib import pyplot as plt

    reportstyle.apply_style()
    entries, refused = atlas_entries(trees_by_corpus, snippets, cut=cut,
                                     **pad_kw)
    if not entries:
        return None, {"reason": "no medoids", "refused": refused}

    n = len(entries)
    rows_n = int(np.ceil(n / cols))

    # The cell is taller than drop_motifs10's because the type is. At
    # 6.6 pt titles and 6.3 pt captions a 1.62 in row held both with room
    # to spare; at 9 pt and 8 pt it does not, and the caption climbed into
    # the panel below. The plot band is a FRACTION of the cell and the two
    # text bands are absolute, so raising the type raises the row rather
    # than eating the waveform.
    # Trimmed from 1.80: the legend moved below the strip's own tick labels
    # (see `strip_axis_room_in` below) needs a taller bottom block than
    # before, and shrinking every row by the same amount pays for it
    # without growing the page.
    cell_h_in = 1.70

    # Every other band is an absolute inch height too, and all of them are
    # sized for exactly what they hold - one caption line, one legend row,
    # one duration strip - so shrinking any of them is a one-line change
    # here rather than a fraction tuned against a suptitle that is gone.
    top_margin_in = 0.14
    caption_h_in = 0.30
    grid_top_gap_in = 0.06
    strip_gap_in = 0.08
    strip_h_in = 0.26
    # The strip's own tick labels and its "native fall duration..." xlabel
    # render BELOW its axes box, not inside it - matplotlib reserves that
    # room itself and this layout has to leave it clear too, or the label
    # runs into whatever sits underneath. It used to be the legend, and the
    # two overlapped and the label clipped against the figure edge; the
    # legend now sits below this band instead of overlapping it.
    strip_axis_room_in = 0.34
    legend_gap_in = 0.10
    legend_h_in = 0.22
    bottom_margin_in = 0.07

    top_block_in = top_margin_in + caption_h_in + grid_top_gap_in
    bottom_block_in = (strip_gap_in + strip_h_in + strip_axis_room_in
                       + legend_gap_in + legend_h_in + bottom_margin_in)
    fig_h = cell_h_in * rows_n + top_block_in + bottom_block_in
    fig = plt.figure(figsize=(11.7, fig_h))

    left, right = 0.045, 0.985
    top = 1.0 - top_block_in / fig_h
    bottom = bottom_block_in / fig_h
    cell_w = (right - left) / cols
    cell_h = (top - bottom) / rows_n

    # Bands within a cell, as fractions of it: title, waveform, caption.
    # Explicit, so no two of them can be asked to share a millimetre.
    plot_frac = 0.46
    plot_top_frac = 0.72

    for i, entry in enumerate(entries):
        r, c = divmod(i, cols)
        cell_bottom = top - (r + 1) * cell_h
        ax = fig.add_axes([left + c * cell_w + 0.007,
                           cell_bottom + (plot_top_frac - plot_frac) * cell_h,
                           cell_w - 0.014,
                           plot_frac * cell_h])

        colour = style10.colour_of(entry["species"])
        ax.plot(entry["t_rel_s"], entry["z"], color=colour,
                linestyle=style10.dash_of(entry["species"]),
                lw=1.5, solid_capstyle="round")
        ax.axhline(0.0, color=reportstyle.RULE_COLOUR, lw=0.5, alpha=0.35)
        ax.set_xticks([])
        ax.set_yticks([])
        for side in ("top", "right", "bottom", "left"):
            ax.spines[side].set_visible(False)

        fall = entry["native_fall_s"]
        fall_text = f"{fall:.1f} s" if fall < 100 else f"{fall:.0f} s"
        # No `n=` here: rule 3 sends the per-family count to the JSON
        # (see `medoids` below) rather than widening every one of forty
        # titles on a ten-column grid where the corpus name alone is most
        # of the available cell width.
        ax.set_title(f"{_corpus_display(entry['corpus'])} F{entry['family']}",
                     fontsize=reportstyle.FS_ANNOT, pad=3.0, color="0.20")
        # Hung off the CELL and not off the axes, so a panel whose data
        # happens to be tall cannot push its own caption down onto the
        # row beneath.
        # "smp" not "samples": at ten columns a triple-digit oyster count
        # ("266 samples @ 1 Hz") is wider than the cell and runs into its
        # neighbour. Four characters back is the difference between
        # touching and not.
        fig.text(left + c * cell_w + cell_w / 2.0,
                 cell_bottom + 0.14 * cell_h,
                 f"{fall_text}   {entry['native_depth_mv']:.3g} mV\n"
                 f"{entry['n_samples_in_fall']} smp @ {entry['fs']:g} Hz",
                 ha="center", va="center",
                 fontsize=reportstyle.FS_ANNOT, color="0.30",
                 linespacing=1.3)

    # -- the duration axis, so the range is shown and not asserted --------
    strip_bottom_in = (bottom_margin_in + legend_h_in + legend_gap_in
                       + strip_axis_room_in)
    strip = fig.add_axes([left + 0.02, strip_bottom_in / fig_h,
                          right - left - 0.04, strip_h_in / fig_h])
    falls = np.asarray([e["native_fall_s"] for e in entries])
    for entry in entries:
        strip.plot([entry["native_fall_s"]], [0.5],
                   marker=style10.marker_of(entry["species"]),
                   color=style10.colour_of(entry["species"]),
                   markersize=6, alpha=0.85, linestyle="none")
    strip.set_xscale("log")
    strip.set_ylim(0, 1)
    strip.set_yticks([])
    strip.set_xlabel("native fall duration of each medoid (s, log scale)",
                     fontsize=reportstyle.FS_LABEL)
    strip.tick_params(labelsize=reportstyle.FS_TICK)
    strip.grid(True, axis="x", color="0.88", lw=0.6)
    strip.set_axisbelow(True)
    for side in ("top", "right", "left"):
        strip.spines[side].set_visible(False)

    decades = float(np.log10(falls.max() / max(falls.min(), 1e-9)))
    fig.text(0.5, 1.0 - (top_margin_in + caption_h_in / 2.0) / fig_h,
             f"{n} family medoids from {len(trees_by_corpus)} corpora, each "
             f"drawn from its own samples and z-normalised on its fall. "
             f"Fall duration spans {decades:.1f} orders of magnitude "
             f"({falls.min():g} s to {falls.max():g} s).",
             ha="center", va="center", fontsize=reportstyle.FS_ANNOT,
             color="0.30")
    # `config11.handles`, not `style10.species_handles`: the atlas is one
    # of the few places a corpus string reaches the page directly, and
    # `config11` is where `sp385` already resolves to "Lion's mane"
    # everywhere else in this run (see `_corpus_display` above).
    species_present = {e["species"] for e in entries}
    # A dedicated axes rather than `fig.legend(bbox_to_anchor=...)`: the
    # anchor semantics of `loc="lower center"` plus a figure-fraction
    # anchor point do not place the box where the point says - the offset
    # is a legend internal, not this layout's arithmetic - so the legend
    # is centred inside its own reserved band instead, the same fix
    # `config11.legend_axis` uses elsewhere in this run.
    legend_ax = fig.add_axes([left, bottom_margin_in / fig_h,
                              right - left, legend_h_in / fig_h])
    legend_ax.set_axis_off()
    legend_ax.legend(handles=config11.handles(species_present), loc="center",
                     ncol=3, frameon=False, fontsize=reportstyle.FS_LEGEND)

    contexts = [e["trace"]["context_fraction_of_width"] for e in entries]
    info = {
        "cut": cut,
        "n_medoids": n,
        "corpora": list(trees_by_corpus),
        "waveform": "the event's own samples, onset - pad to trough + pad; "
                    "nothing resampled",
        "pad_fraction_of_fall": pad_kw.get("pad_fraction", PAD_FRACTION),
        "pad_min_samples": pad_kw.get("pad_min", PAD_MIN_SAMPLES),
        "z_normalised_on": "the fall, so y=0 is the fall's own mean",
        "context_fraction_of_panel_width": {
            "min": float(np.min(contexts)),
            "median": float(np.median(contexts)),
            "max": float(np.max(contexts))},
        "native_fall_range_s": [float(falls.min()), float(falls.max())],
        "orders_of_magnitude": decades,
        "samples_drawn_range": [
            int(min(e["trace"]["n_samples_drawn"] for e in entries)),
            int(max(e["trace"]["n_samples_drawn"] for e in entries))],
        "refused": refused,
        "medoids": [{k: v for k, v in e.items()
                     if k not in ("t_rel_s", "z")} for e in entries],
    }
    bad = reportstyle.check_type_sizes(fig)
    info["type_sizes_outside_band"] = bad
    return reportstyle.save(fig, path, proof_png=proof_png), info
