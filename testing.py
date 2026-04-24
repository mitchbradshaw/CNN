from create_matrix import *
from plot_matrix import *
from aeon_analysis.transformations import add_catch22_to_matrix
import matplotlib.pyplot as plt
import numpy as np
import os

FILENAME = "0.01_percent_M2_concat_fs1.mat"
WINSIZE  = 10       # minutes
FS = 1
STEPFRAC = 1
winsamples = FS * WINSIZE * 60
CSVFILE = "0.01_percent_M2_concat_fs1_consecutive.csv"

wm = get_wm(FS,WINSIZE,FILENAME,matname="VECTOR",csvfilename=CSVFILE)

plot_singlevalue_columns(wm,overlay=False)

# --- Plot 8257200.npy --
# 
'''
import numpy as np
import matplotlib.pyplot as plt
import os

data = np.load("8257200.npy", allow_pickle=True)
signal, timestamps = data[0]*1000, data[1]/3600

plt.figure(figsize=(12, 4))
plt.plot(timestamps, signal, linewidth=3)
plt.xlabel("Time (hr)")
plt.ylabel("Signal Amplitude (mV)")
plt.title("Example of flagged data")
plt.tight_layout()
plt.show()
'''

