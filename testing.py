from create_matrix import *
from plot_matrix import *
from aeon_analysis.transformations import add_catch22_to_matrix

FILENAME = "0.01_percent_M2_concat_fs1.mat"
WINSIZE  = 10       # minutes
FS = 1
STEPFRAC = 1
winsamples = FS * WINSIZE * 60
CSVFILE = "0.01_percent_M2_concat_fs1_consecutive.csv"

wm = get_wm(FS,WINSIZE,FILENAME,matname="VECTOR",csvfilename=CSVFILE)

plot_singlevalue_columns(wm,overlay=True)
