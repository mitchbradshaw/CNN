"""
similarity.py
==============
Interval-overlap similarity between annotation spans, used to warn about a
likely duplicate before saving (`find_similar_annotations`) and to audit an
entire channel for existing near-duplicates (`find_near_duplicate_pairs`).
Report-only — nothing here deletes or modifies anything.

Two spans count as near-duplicates when BOTH:
  - their interval IoU exceeds `SIMILARITY_IOU_THRESHOLD`
  - their widths are within `SIMILARITY_WIDTH_RATIO_THRESHOLD` of each other

IoU alone can't tell "the same span, saved twice" from "a short span that
happens to sit entirely inside a much longer one" (that second case can
have a high IoU-of-the-shorter-interval-relative-to-itself in some
formulations, but standard IoU — intersection / union — actually already
penalizes a large width mismatch, since union grows with the longer span.
The width-ratio check is a second, more direct guard against exactly that
pattern being missed at a middling IoU near the threshold.)

Thresholds live in `Working.config`, not here.
"""

from Working.config import SIMILARITY_IOU_THRESHOLD, SIMILARITY_WIDTH_RATIO_THRESHOLD
from Working.database.queries import list_annotations


def interval_iou(a_start, a_end, b_start, b_end):
    """Intersection-over-union of two [start, end) integer sample intervals.
    0.0 for non-overlapping or degenerate (zero-width) intervals."""
    inter = max(0, min(a_end, b_end) - max(a_start, b_start))
    if inter == 0:
        return 0.0
    union = (a_end - a_start) + (b_end - b_start) - inter
    if union <= 0:
        return 0.0
    return inter / union


def width_ratio(a_start, a_end, b_start, b_end):
    """max(width) / min(width) — 1.0 for equal widths, growing as they
    diverge. `None` if either width is zero (undefined)."""
    wa, wb = a_end - a_start, b_end - b_start
    if wa <= 0 or wb <= 0:
        return None
    return max(wa, wb) / min(wa, wb)


def is_near_duplicate(a_start, a_end, b_start, b_end,
                       iou_threshold=SIMILARITY_IOU_THRESHOLD,
                       width_ratio_threshold=SIMILARITY_WIDTH_RATIO_THRESHOLD):
    iou = interval_iou(a_start, a_end, b_start, b_end)
    if iou < iou_threshold:
        return False
    ratio = width_ratio(a_start, a_end, b_start, b_end)
    if ratio is None:
        return False
    return ratio <= width_ratio_threshold


def find_similar_annotations(conn, recording_id, start_idx, end_idx,
                              iou_threshold=SIMILARITY_IOU_THRESHOLD,
                              width_ratio_threshold=SIMILARITY_WIDTH_RATIO_THRESHOLD,
                              exclude_annotation_id=None):
    """Existing annotations on `recording_id` that are a near-duplicate of
    the candidate span (start_idx, end_idx) — e.g. a pending, not-yet-saved
    selection. Returns a list of `sqlite3.Row`s (the existing annotations),
    each with an added `iou` key. `exclude_annotation_id` skips comparing a
    span against itself when checking an already-saved annotation.
    """
    out = []
    for row in list_annotations(conn, recording_id):
        if exclude_annotation_id is not None and row["id"] == exclude_annotation_id:
            continue
        if row["start_idx"] >= end_idx or row["end_idx"] <= start_idx:
            continue  # cheap reject before the more precise IoU/ratio check
        if is_near_duplicate(start_idx, end_idx, row["start_idx"], row["end_idx"],
                              iou_threshold, width_ratio_threshold):
            iou = interval_iou(start_idx, end_idx, row["start_idx"], row["end_idx"])
            merged = dict(row)
            merged["iou"] = iou
            out.append(merged)
    out.sort(key=lambda r: r["iou"], reverse=True)
    return out


def find_near_duplicate_pairs(conn, recording_id,
                               iou_threshold=SIMILARITY_IOU_THRESHOLD,
                               width_ratio_threshold=SIMILARITY_WIDTH_RATIO_THRESHOLD):
    """Audit: every pair of EXISTING annotations on `recording_id` that are
    near-duplicates of each other. O(n^2) over the channel's annotation
    count, which is fine for the thousands-per-channel scale this app
    handles (list_annotations is already sorted by start_idx, so the inner
    loop breaks early once a candidate starts after the current span ends).

    Returns a list of dicts: {a: Row, b: Row, iou: float}, sorted by iou
    descending. Report-only — never deletes or modifies anything.
    """
    rows = list_annotations(conn, recording_id)
    pairs = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if b["start_idx"] >= a["end_idx"]:
                break  # sorted by start_idx -- nothing further can overlap `a`
            if is_near_duplicate(a["start_idx"], a["end_idx"], b["start_idx"], b["end_idx"],
                                  iou_threshold, width_ratio_threshold):
                iou = interval_iou(a["start_idx"], a["end_idx"], b["start_idx"], b["end_idx"])
                pairs.append({"a": a, "b": b, "iou": iou})
    pairs.sort(key=lambda p: p["iou"], reverse=True)
    return pairs
