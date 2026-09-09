"""
lionsmane12.py
===============
The Lion's mane corpus: `L_LM_Jul_26_J_raw_fs10`, five channels, 22,892,769
samples each, and the two operator-chosen regions drop_motifs12a detects
over.

Three things had to be MEASURED rather than read, and each one is a silent
corruption if it is assumed instead. `tests/test_drop_motifs_lionsmane12.py`
is the check on all three.

1. THE RECORDING IS NOT IN THE RECORDINGS TABLE
-----------------------------------------------
The work order says to verify the stem and the sampling rate against
`recordings`. There is nothing there to verify against: `recordings` holds
Fig2A, the M2/M4 catalogue exports and Mushroom_260720, and its highest id
is 470. `L_LM_Jul_26_J_raw_fs10` exists only as extracted channels under
`DATA/derived/channels/` with a `manifest.json` beside them.

Nothing here writes to the database. The corpus is defined from the on-disk
manifest and from the measurement below, and `RECORDING_ID` is a sentinel
rather than a row id, so no code path can mistake it for one.

2. THE CHANNELS ARE IN MILLIVOLTS, AND EVERYTHING ELSE ON DISK IS IN VOLTS
--------------------------------------------------------------------------
`DETECTION_AND_FIGURES.md` §2 states the convention: the `.npy` on disk is
volts, the store is millivolts, and `motifs5.rows_and_arrays` is the one
place the x1000 happens. These arrays break it. CH3 sits around -223 and
swings 450 - not -0.223 V but -223 mV.

Handed in raw, every depth, every derived floor and every slope in the store
would be 1000x its true value. The derived floor would scale with them and
so would look self-consistent; the comparison against the operator's 0.1 mV
global floor would not, and neither would any number quoted beside Reishi or
Oyster. `load_channel` divides by 1000 so that everything below
`Working/Detection/` sees the same units it sees everywhere else, and
`load_channel_native` exists only so the test can show the two differ.

3. fs = 10.0 Hz, VERIFIED - AND THE VERIFICATION IS ID 385
-----------------------------------------------------------
The channel manifest's own `fs_note` is honest that 10.0 Hz is inferred:
the `.mat` carries a single scalar MATLAB duration object instead of a
per-sample timestamp vector, so the rate was derived by dividing the sample
count by a ~26-day duration read off a plot.

There is a much harder check available, and it is the same measurement that
answers the work order's question about id385. Catalogue ID 385
(`Mushroom_260720_0509_4hrs_CH14_fs1`, 14,401 samples at 1 Hz) is a four-hour
1 Hz excerpt of this recording. Block-mean CH2 10:1 and cross-correlate:

    r = 0.9995, at CH2 sample 15,777,590
    gain 1.00075, offset -299.16 mV, residual RMS 0.055 mV
    the correlation peak is ONE SAMPLE wide (neighbours 0.979, 0.971)

That fixes all three facts at once. The peak is single-sample sharp over
four hours, which no rate other than exactly 10.0 Hz produces - a 0.1% error
would walk the two traces 14 samples apart and smear it. The gain is 1.000
against a trace known to be millivolts, which is the unit proof. And the
location is inside region B, which is what the work order believed and had
no measurement for.

The constant -299 mV offset is a referencing difference between the two
exports, not a scale error. It does not reach detection: every pass runs on
a detrended trace.

The regions
-----------
    region  channel  from        to          duration at 10 Hz
    A       CH3      7.4e6       2.0e7       ~350 h
    B       CH2      1.376e7     1.71e7      ~93 h

CH3 carries large isolated drops with slow recovery; CH2 carries dense
narrow spikes on a drifting baseline. They are not the same scale and are
not detected with the same window - see `probe12`.

No plotting library.
"""

import json
import os
from dataclasses import dataclass

import numpy as np
from scipy.signal import fftconvolve

STEM = "L_LM_Jul_26_J_raw_fs10"
SOURCE_FILE = "L_LM_Jul_26_J_raw.mat"
CHANNEL_DIR = os.path.join("DATA", "derived", "channels", STEM)

SPECIES = "lionsmane"
CORPUS = "lionsmane_10hz"

N_CHANNELS = 5
N_SAMPLES = 22_892_769
FS = 10.0

# The stored arrays are millivolts; everything below `Working/Detection/`
# expects volts. See the module docstring, point 2.
NATIVE_UNITS_PER_VOLT = 1000.0

# NOT a `recordings.id`. The recording has no row - see point 1 - and a
# plausible-looking integer here would eventually be joined against one.
# Every store row carries this and the negative sign is the flag.
RECORDING_ID = -1

# Catalogue ids for the five channels, in the same shape Fig2A's are
# (`corpora10.FIG2A_CATALOGUE_BASE` = 900). 910-914 are free: the catalogue
# tops out at 385 and Fig2A occupies 900-904.
CATALOGUE_BASE = 910

# The 1 Hz excerpt this run retires, and where it actually is.
ID385_PATH = os.path.join(
    "DATA", "derived", "channels", "Mushroom_260720_0509_4hrs_CH14_fs1",
    "Mushroom_260720_0509_4hrs_CH14_fs1_CH00.npy")
ID385_DECIMATION = 10          # 10 Hz -> 1 Hz


@dataclass(frozen=True)
class Region:
    """One operator-chosen region: a channel and a half-open sample range."""

    key: str
    channel: int
    start: int
    stop: int
    note: str = ""

    @property
    def n_samples(self):
        return int(self.stop - self.start)

    @property
    def hours(self):
        return self.n_samples / FS / 3600.0

    @property
    def label(self):
        return f"region {self.key} CH{self.channel}"

    @property
    def key_stem(self):
        return f"region_{self.key}_CH{self.channel}"

    @property
    def catalogue_id(self):
        return CATALOGUE_BASE + int(self.channel)


REGIONS = {
    "A": Region("A", 3, 7_400_000, 20_000_000,
                "large isolated drops with slow recovery"),
    "B": Region("B", 2, 13_760_000, 17_100_000,
                "dense narrow spikes on a drifting baseline; "
                "contains catalogue ID 385"),
}


def channel_path(channel):
    return os.path.join(CHANNEL_DIR, f"CH{int(channel)}.npy")


def manifest():
    """The extractor's own manifest, including its `fs_note`."""
    with open(os.path.join(CHANNEL_DIR, "manifest.json"),
              encoding="utf-8") as handle:
        return json.load(handle)


def load_channel_native(channel, start=0, stop=None):
    """The stored array, in its own units. For the unit check only."""
    x = np.load(channel_path(channel), mmap_mode="r")
    stop = len(x) if stop is None else int(stop)
    return np.asarray(x[int(start):stop], dtype=float)


def load_channel(channel, start=0, stop=None):
    """One channel, or a slice of it, IN VOLTS.

    The one seam where the millivolt storage is corrected. Every caller
    below `Working/Detection/` gets the units the rest of the repo uses, so
    nothing downstream needs to know this recording is different.
    """
    return load_channel_native(channel, start, stop) / NATIVE_UNITS_PER_VOLT


def load_region(region):
    """`(x_volts, offset)` for a region, in the shape `spans5.load_span` uses."""
    region = REGIONS[region] if isinstance(region, str) else region
    return load_channel(region.channel, region.start, region.stop), region.start


def load_id385_mv():
    """Catalogue ID 385's trace, in millivolts."""
    return np.load(ID385_PATH).astype(float) * 1000.0


def locate_id385(channel=2, decimation=ID385_DECIMATION):
    """Where the 1 Hz excerpt sits in the 10 Hz recording, by measurement.

    Block-means the channel `decimation`:1 and slides the excerpt along it
    under a normalised cross-correlation. Returns the position, the peak
    correlation, and the linear fit of the excerpt against what was found -
    whose gain is the millivolt check and whose sharpness is the rate check.

    The block mean rather than a stride: the residual against the excerpt is
    0.055 mV under a block mean and an order worse under `x[::10]`, which
    says the 1 Hz export was itself an average and not a decimation.
    """
    q = load_id385_mv()
    q = (q - q.mean()) / q.std()
    m = len(q)

    native = load_channel_native(channel)
    usable = (len(native) // decimation) * decimation
    y = native[:usable].reshape(-1, decimation).mean(axis=1)

    numerator = fftconvolve(y, q[::-1], mode="valid")
    ones = np.ones(m)
    total = fftconvolve(y, ones, mode="valid")
    square = fftconvolve(y * y, ones, mode="valid")
    variance = square - total * total / m
    variance[variance <= 0] = np.inf
    r = numerator / np.sqrt(variance * m)

    at = int(np.argmax(r))
    window = y[at:at + m]
    gain, offset = np.polyfit(window, load_id385_mv(), 1)
    residual = float(np.std(load_id385_mv() - (gain * window + offset)))

    # How much of the peak is one sample. A rate error smears this.
    neighbours = [float(r[at + d]) for d in (-1, 1)
                  if 0 <= at + d < len(r)]

    return {
        "channel": int(channel),
        "start_idx": at * decimation,
        "stop_idx": (at + m) * decimation,
        "start_s": at * decimation / FS,
        "r": float(r[at]),
        "r_neighbours": neighbours,
        "gain": float(gain),
        "offset_mv": float(offset),
        "residual_rms_mv": residual,
        "n_samples_1hz": int(m),
        "decimation": int(decimation),
    }


def channels_without_events(rows, channels=range(N_CHANNELS)):
    """Which channels carried no detections. A result, not an omission."""
    seen = {int(r["channel"]) for r in rows}
    return [int(c) for c in channels if int(c) not in seen]
