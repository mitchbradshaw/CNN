import os
import numpy as np
from manage_data.load_data import load_raw_data
from gramian.gramian_calc import plot_gramian_suite
from matplotlib import pyplot as py

FOLDER   = "DATA/RAW"
FILENAME = "M2_concat_fs1_CH2.npy"
FS       = 1.0   # Hz (matches folder name)

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
x, t = load_raw_data(FILENAME,FS,"VECTOR")
x = x * 1000
t = t / 3600

full = False
# plot channel

if full:
    py.plot(t,x)
    py.xlabel("Time (hr)")
    py.ylabel("Signal (mV)")
    py.show()

else:
    # plot partial
    sthr = 230
    len = 50

    sidx = int(sthr * 3600)
    eidx = int(sidx + len * 60)
    t = t[sidx:eidx]
    x = x[sidx:eidx]

    py.plot(t,x)
    py.xlabel("Time (hr)")
    py.ylabel("Signal (mV)")
    py.show()