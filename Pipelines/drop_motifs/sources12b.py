"""
sources12b.py
==============
Where the raw trace behind a store row lives, so rule 8's reference strip
can be drawn. Read-only, and it opens the database read-only.

Rule 8 asks every sequence figure to carry "the source trace over the
sequence's whole span". The store cannot supply it: it holds per-event
windows, and a sequence's events are separated by gaps of up to twice the
group's median interval, so stitching snippets would draw a strip with
holes in it and no way to see that they are holes. The trace has to come
off disk.

One lookup rule, not four
--------------------------
Every store row already carries `recording_id`, `channel` and `fs`, so the
resolution is by row and not by species:

    recording_id >= 0   ->  `recordings.npy_path`, in VOLTS, x1000 here
    recording_id  < 0   ->  the sentinel `lionsmane12.RECORDING_ID`; that
                            recording has no row (see `lionsmane12`) and
                            its arrays are already millivolts

That keeps oyster, Reishi, `sp385` and Lion's mane on one path, and it
means a fifth corpus needs a `recordings` row rather than a branch here.

Every read is `mmap_mode="r"` and sliced before it is materialised. A
Lion's mane channel is 22.9 million samples; loading one whole to draw a
strip over 3,000 of them would cost 183 MB per figure.
"""

import os
import sqlite3

import numpy as np

from Pipelines.drop_motifs import lionsmane12

DB = os.path.join("DATA", "db", "annotations.sqlite")


class Sources:
    """Slices of source channels, in millivolts, cached by recording id."""

    def __init__(self, db_path=DB):
        self.db_path = db_path
        self._conn = None
        self._paths = {}

    # -- the database, opened once and read-only ---------------------------
    def _connection(self):
        if self._conn is None:
            self._conn = sqlite3.connect(f"file:{self.db_path}?mode=ro",
                                         uri=True)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def npy_path(self, recording_id):
        recording_id = int(recording_id)
        if recording_id not in self._paths:
            row = self._connection().execute(
                "SELECT npy_path FROM recordings WHERE id = ?",
                (recording_id,)).fetchone()
            self._paths[recording_id] = row["npy_path"] if row else None
        return self._paths[recording_id]

    # -- the one call the figures make -------------------------------------
    def slice_mv(self, row, start_idx, stop_idx):
        """`x_mv` for `[start_idx, stop_idx)` of the channel `row` came from.

        Absolute sample indices against the WHOLE channel, which is the
        frame store rows are already in - `motifs5.rows_and_arrays` adds
        the span offset before writing `onset_idx`. Returns `None` when the
        source is not reachable, so a figure can fall back to no strip and
        say so rather than raising in the middle of a run.
        """
        start = max(0, int(start_idx))
        stop = int(stop_idx)
        if stop <= start:
            return None
        recording_id = int(row["recording_id"])

        if recording_id < 0:
            # The Lion's mane sentinel. Its arrays are millivolts already;
            # `load_channel` divides by 1000 to hand volts to the detector,
            # so the x1000 here is the same seam read the other way.
            return lionsmane12.load_channel(
                int(row["channel"]), start, stop) * 1000.0

        path = self.npy_path(recording_id)
        if not path or not os.path.exists(path):
            return None
        array = np.load(path, mmap_mode="r")
        return np.asarray(array[start:min(stop, len(array))],
                          dtype=float) * 1000.0

    def span_for(self, rows, *, context=0.06, min_pad_s=1.0):
        """`(start_idx, stop_idx)` covering every row, plus a little context.

        The strip is meant to show where the events came from, so it starts
        a little before the first onset and ends a little after the last
        trough. `context` is a fraction of the run's own extent and
        `min_pad_s` is the floor, so a five-event Reishi run 10 s long still
        gets a second either side rather than starting exactly on an event.
        """
        if not rows:
            return 0, 0
        fs = float(rows[0]["fs"])
        low = min(int(r["onset_idx"]) for r in rows)
        high = max(int(r["trough_idx"]) for r in rows)
        # The last event's recovery is part of what a reader wants to see,
        # so the end is padded past the trough by the same rule.
        pad = max(context * (high - low), min_pad_s * fs)
        return int(low - pad), int(high + pad)

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None
