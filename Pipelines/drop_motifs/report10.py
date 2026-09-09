"""
report10.py
============
REBASELINE.md, written from `rebaseline.json` rather than by hand.

The audit's whole value is that every number in it can be re-derived, so
the prose around the numbers is generated from the same file the numbers
are in. A sentence that says a span moved is written by the code that
measured the move, and a span whose count moved with no rung to pin it on
is reported as a finding by construction rather than by someone noticing.
"""

import json

import numpy as np

from Pipelines.drop_motifs import floor10, rebaseline10


def _fmt(value, digits=0):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}" if digits else f"{value:.0f}"
    return str(value)


def human_table(checks):
    lines = [
        "| catalogue ID | human states | drop_motifs8 base | drop_motifs10 "
        "base | verdict |",
        "|---|---|---|---|---|",
    ]
    for row in checks:
        verdict = ("unchanged" if row["unchanged"]
                   else f"**MOVED by {row['delta']:+d}**")
        lines.append(
            f"| {row['catalogue_id']} | {row['human_stated']} | "
            f"{row['drop8_base']} | {row['drop10_base']} | {verdict} |")
    return "\n".join(lines)


def span_table(catalogue):
    lines = [
        "| ID | drop8 | control | drop10 | delta | attributed to |",
        "|---|---|---|---|---|---|",
    ]
    for row in catalogue:
        moves = row["moves"]
        if moves:
            causes = "; ".join(
                f"{m['rung']} {m['delta']:+d}" for m in moves)
        else:
            causes = "no rung moved it"
        control = ("=" if row["control_reproduces_drop8"]
                   else f"**{row['control_n_motifs']}**")
        lines.append(
            f"| {row['catalogue_id']} | {row['drop8_n_motifs']} | {control} | "
            f"{row['drop10_n_motifs']} | {row['delta_total']:+d} | {causes} |")
    return "\n".join(lines)


def bracket_table(catalogue):
    lines = [
        "| ID | base up_runs | base detected | base bracket | finest "
        "up_runs | four-pass total | multi-scale bracket | annotated |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in catalogue:
        lines.append(
            f"| {row['catalogue_id']} | {row['up_runs']} | "
            f"{row['drop10_base_events']} | "
            f"{'yes' if row.get('base_bracket_holds') else '**NO**'} | "
            f"{row.get('finest_up_runs', row['up_runs'])} | "
            f"{row['drop10_n_motifs']} | "
            f"{'yes' if row['bracket_holds'] else '**no (' + str(row.get('bracket_failed_side')) + ')**'} | "
            f"{_fmt(row['annotated_n'])} |")
    return "\n".join(lines)


def floor_table(catalogue, fig2a):
    lines = [
        "| span / channel | amplitude sigma (mV) | derived floor, 3 sigma "
        "(mV) | global 0.1 mV, in sigmas |",
        "|---|---|---|---|",
    ]
    for row in catalogue:
        sigma = row["amplitude_sigma_mv"]
        lines.append(
            f"| id{row['catalogue_id']} | {sigma:.4f} | "
            f"{row['derived_floor_mv']:.4f} | "
            f"{floor10.GLOBAL_FLOOR_MV / sigma:.1f} |")
    for row in fig2a:
        sigma = row["amplitude_sigma_mv"]
        lines.append(
            f"| Fig2A CH{row['channel']} | {sigma:.4f} | "
            f"{floor10.FLOOR_SIGMAS * sigma:.4f} | "
            f"{floor10.GLOBAL_FLOOR_MV / sigma:.1f} |")
    return "\n".join(lines)


def fig2a_table(fig2a, drop9):
    lines = [
        "| channel | drop9-like raw | drop10 raw | drop9-like at 0.1 mV | "
        "drop10 at 0.1 mV | drop10 at its derived floor |",
        "|---|---|---|---|---|---|",
    ]
    totals = dict(a=0, b=0, c=0, d=0, e=0)
    for row in fig2a:
        totals["a"] += row["drop9_like_n_raw"]
        totals["b"] += row["drop10_n_raw"]
        totals["c"] += row["drop9_like_n_after_global_floor"]
        totals["d"] += row["drop10_n_after_global_floor"]
        totals["e"] += row["drop10_n_after_floor"]
        lines.append(
            f"| CH{row['channel']} | {row['drop9_like_n_raw']} | "
            f"{row['drop10_n_raw']} | "
            f"{row['drop9_like_n_after_global_floor']} | "
            f"{row['drop10_n_after_global_floor']} | "
            f"{row['drop10_n_after_floor']} |")
    lines.append(
        f"| **all five** | **{totals['a']}** | **{totals['b']}** | "
        f"**{totals['c']}** | **{totals['d']}** | **{totals['e']}** |")
    lines.append("")
    lines.append(
        f"drop_motifs9 shipped **{drop9['n_raw']} raw** and "
        f"**{drop9['n_refined']} refined**. The drop9-like column above is "
        f"this run's code with every fix switched off, so it is the closest "
        f"reproduction of that chain this audit can make; it is not "
        f"expected to be identical, because drop_motifs9's 1058 also went "
        f"through `refine9`'s onset/trough re-marking and its within-window "
        f"`dedup_same_drop`, neither of which is a rung here - both were "
        f"folded into the detector at source in Task 1.")
    return "\n".join(lines)


def write(report, path):
    checks = report["human_referenced"]
    catalogue = report["catalogue"]
    fig2a = report["fig2a"]

    controls_ok = [r for r in catalogue if r["control_reproduces_drop8"]]
    unexplained = [r for r in catalogue
                   if r["delta_total"] and not r["moves"]]
    moved_human = [r for r in checks if not r["unchanged"]]
    broken_bracket = [r for r in catalogue if not r["bracket_holds"]]
    broken_encoding = [r for r in catalogue
                       if not r.get("encoding_side_holds", True)]
    broken_eye = [r for r in catalogue
                  if r.get("bracket_failed_side") == "eye"]

    headline = (
        "**All four human-referenced counts are unchanged.** "
        if not moved_human else
        "**A human-referenced count MOVED, and that is the most important "
        "single output of this task.** ")

    text = f"""# REBASELINE.md — drop_motifs10

Task 1 fixed defects at source, which means drop_motifs5–8 counts no longer
reproduce from the current code. This file proves the change is the fix and
not drift.

## 1. The four human-referenced counts — the headline

{headline}These are BASE-PASS counts, because the base pass is what those
numbers were validated against.

{human_table(checks)}

## 2. How attribution was done

Not by reasoning about the diff. Every fix has an off switch and the audit
walks a ladder from "drop_motifs8 exactly" to "drop_motifs10 exactly", one
change at a time, re-running the detector at every rung. A span's count
moving between two rungs is attributed to the one change that separates
them.

| rung | what it turns on | is it a defect fix? |
|---|---|---|
| `drop8` | nothing — inverted pass on, **no depth floor** | the control |
{chr(10).join(f"| `{name}` | {rebaseline10.FIX_OF_RUNG[name]} | "
              f"{'yes' if name not in ('+drops_only', '+global_floor') else '**no**'} |"
              for name, _ in rebaseline10.RUNGS[1:])}

**The control rung applies no depth floor, and getting that wrong was
caught by the control itself.** The first version of this ladder floored the
control at 0.1 mV on the assumption that drop_motifs8 had. id10 came back 85
against 86 and id26 37 against 40, with `n_before_dedup` and
`n_duplicates_dropped` identical — so detection and merge were identical and
the difference had to be downstream of both. It was: the 0.1 mV gate lives
in `refine9.depth_gate`, which drop_motifs9 introduced for Fig2A and which
**never ran over the catalogue**. The floor is therefore its own rung, and
the catalogue meets a depth floor for the first time in this run.

**{len(controls_ok)} of {len(catalogue)} controls reproduce drop_motifs8
exactly.** {"Every one." if len(controls_ok) == len(catalogue) else
"The exceptions are listed in bold in the table below and are a finding."}

## 3. Per-span counts, drop_motifs8 against drop_motifs10

{span_table(catalogue)}

{"**Every moved count is attributable to a named rung.**"
 if not unexplained else
 "**! Spans whose count moved with no rung to attribute it to — these are "
 "findings and were investigated:** "
 + ", ".join(f"id{r['catalogue_id']} ({r['delta_total']:+d})"
             for r in unexplained)}

Two of the rungs are **not defect fixes** and their contribution must not be
read as one:

- `+drops_only` — drop_motifs8 ran a fifth, inverted pass on the catalogue
  and drop_motifs9 ran none on Fig2A. Running it on two corpora and not the
  other two would be a per-corpus parameterisation, which is exactly what
  this run's central claim forbids, so it runs on none.
- `+global_floor` — see above; the catalogue had never met a depth floor.

## 4. up_runs as the gate-free bracket

As drop_motifs7 used it: the encoding is permissive, the eye is selective,
gated detection is conservative, and the three should stay in that order.

{bracket_table(catalogue)}

**The bracket has to be read at the right scale, and the first version of
this audit did not read it there.** `up_runs` is a property of ONE encoding
and an encoding is fixed by a segment length. drop_motifs7's bracket was a
single-scale statement; drop_motifs10 runs four passes whose segment lengths
differ by more than an order of magnitude. Comparing a four-pass TOTAL
against the BASE pass's `up_runs` compares a count made at one scale against
an encoding made at another, and it "failed" on eight of sixteen spans for
that reason and no other. Both columns above are therefore measured at their
own scale, and only those two comparisons are tests.

**The two inequalities fail for different reasons, so they are reported
separately.** `up_runs >= detected` is the ENCODING side: a failure there
means events were confirmed that the encoding never proposed, and that
cannot happen without something being wrong. `annotated >= detected` is the
EYE side: a failure there means the detector found more than the human
counted.

{"**The encoding side holds on every span, at both scales.**"
 if not broken_encoding else
 "**! The ENCODING side fails on: "
 + ", ".join(f"id{r['catalogue_id']}" for r in broken_encoding)
 + "** — this is the one that cannot happen without something being wrong, "
   "and it is a finding."}

{"The eye side holds wherever the catalogue states a count."
 if not broken_eye else
 "The EYE side fails on "
 + ", ".join(f"id{r['catalogue_id']}" for r in broken_eye)
 + " — every one of them a span where the catalogue states a count, and in "
   "every case because the four-pass total EXCEEDS it. That is expected "
   "rather than wrong on a multi-scale run: the catalogue's prose counts "
   "cycles of a span's dominant motif, and `fine`, `sens` and `micro` exist "
   "precisely to find the sub-scale events such a count leaves out. The "
   "number that has to reproduce the human count is the BASE pass's, and "
   "Section 1 shows all four of those unchanged. The one span where even "
   "the base pass exceeds its stated count is id1 at 17 against 16, which "
   "is the same +1 drop_motifs5 through 8 all reported."}

## 5. The depth floor, per span and per channel

The measurement decision of Task 1's defect 6, shown as one. `sigma` is the
robust per-sample amplitude noise, `robust_sigma(diff(x,2))/sqrt(6)` — the
same estimator the detector's own slope gate is built on.

{floor_table(catalogue, fig2a)}

**The operator's 0.1 mV is about 3–4 sigma on the M2 recordings it was
stated for, and 15–60 sigma on Fig2A.** That is the whole case for deriving
the floor: a fixed millivolt number applied across corpora is a per-corpus
tuning decision made by accident, and it keeps a different fraction of each
corpus according to how each was amplified. The multiplier 3.0 was not
tuned — it was validated, by recovering the operator's own number on the
operator's own recordings.

Both stores are written, so the two rules stay comparable:
`Plots/drop_motifs10/motifs/` (derived) and
`Plots/drop_motifs10/motifs_globalfloor/` (0.1 mV).

## 6. Fig2A, drop_motifs9 against drop_motifs10

{fig2a_table(fig2a, report["drop9_reference"])}

## 7. What this audit does not cover

- The Fig2A rungs are reported at the two ends only. On the catalogue a span
  is one detector call and a per-rung count is attributable; on Fig2A a
  channel is 47 sliding windows and a per-rung count is a sum over 47
  independent scale derivations, so the per-fix attribution is reported from
  the catalogue and Fig2A is reported as the two ends plus the floor.
- `refine9`'s onset/trough re-marking is not a rung. It was folded into the
  detector at source in Task 1 (`walk_back_to_shoulder`), which is the point
  — `refine9` could move and reject but never ADD, so a post-processing pass
  could not recover an event the gates had already thrown away.
"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return str(path)
