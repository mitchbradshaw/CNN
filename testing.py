from winmatrix_funcs import *

from aeon_analysis.transformations import add_catch22_to_matrix

FILENAME = "0.01_percent_M2_concat_fs1.mat"
WINSIZE  = 10       # minutes
FS = 1
STEPFRAC = 1
winsamples = FS * WINSIZE * 60
CSVFILE = "0.01_percent_M2_concat_fs1_consecutive.csv"

wm = get_wm(FS,WINSIZE,FILENAME,matname="VECTOR",csvfilename=CSVFILE)



add_catch22_to_matrix(wm)
wm.save_window(CSVFILE)
