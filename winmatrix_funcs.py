from matrix_calc import *
from analysis.freq_analysis import stft_log_spectrum
from main import *
import numpy as np
import matplotlib.pyplot as py
from matplotlib.colors import LogNorm
from cnn.apply_cnn import *
from sax.sax_encoding import *
from analysis.entropy_analysis import _shannon_entropy, _svd_entropy, _sample_entropy, _spectral_entropy, _permutation_entropy, _approximate_entropy

# ------------------------------------------------------------------ #
#  Making window matrix object
# ------------------------------------------------------------------ #

def make_wm(FS,TIMESCALE,filename,stepfrac,matname='x',csvfilename=""):
    """
    Function to make a new window object
    """
    x,t = load_raw_data(filename,FS,matname)

    wm = create_matrix_at_timescale(stepfrac,x,TIMESCALE,FS)

    if csvfilename == "":
        csvfilename = f"{filename}_step{stepfrac}.csv"

    wm.save_window(csvfilename)
    return wm, csvfilename


def get_wm(FS,TIMESCALE,filename,stepfrac=1,matname="x", csvfilename=""):
    x, t = load_raw_data(filename,FS,matname)

    if csvfilename=="":
        csvfilename = f"{filename}_step{stepfrac}.csv"

    return load_matrix(f"MATRICES/{csvfilename}",x,TIMESCALE,FS)

def update_cnn_columns(wm,modelpath,csvfilename,imgtype,batchsize=64):
    wm = add_cnn_scores(wm,modelpath,image_type=imgtype,batch_size=batchsize)
    wm.save_window(csvfilename)

def update_fusion_prediction_v1_columns(wm,modelpath,csvfilename,batchsize=64):
    wm = add_fusion_prediction_v1_scores(wm,modelpath,batch_size=batchsize)
    wm.save_window(csvfilename)

def plot_cnn_columns(wm,filename,TIMESCALE,FS,matname='x'):
    x, t = load_raw_data(filename,FS,matname)

    window_samples = int(TIMESCALE * 60 * FS)   # 600 samples
    intvalues = wm.get_column("cnn_p_interesting")

    # x-axis for the score: mid-point of each window in seconds
    score_starts  = wm.df.index.to_numpy()                        # sample indices
    score_t_mid   = (score_starts + window_samples / 2) / FS   # seconds

    t_hours       = t / 3600.0
    score_t_hours = score_t_mid / 3600.0

    fig, (ax_sig, ax_score) = py.subplots(
        2, 1, figsize=(16, 6),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
    )

    # ── Top: raw signal ───────────────────────────────────────────────
    ax_sig.plot(t_hours, x * 1000, color="steelblue", linewidth=0.4, alpha=0.8)
    ax_sig.set_ylabel("Signal amplitude")
    ax_sig.set_title(f"{filename} — raw signal and CNN interesting score")

    # ── Bottom: CNN score ─────────────────────────────────────────────
    ax_score.step(score_t_hours, intvalues.to_numpy(),
                where="mid", color="tomato", linewidth=1.0)
    ax_score.fill_between(score_t_hours, intvalues.to_numpy(),
                        step="mid", alpha=0.25, color="tomato")
    ax_score.set_ylim(0, 1)
    ax_score.set_ylabel("P(interesting)")
    ax_score.set_xlabel("Time (hours)")
    ax_score.axhline(0.5, color="gray", linewidth=0.7, linestyle="--")

    py.tight_layout()
    py.show()
    
def plot_fusion_prediction_v1_error(wm, filename, TIMESCALE, FS, matname="VECTOR"):
    x, t = load_raw_data(filename, FS, matname)

    window_samples = int(TIMESCALE * 60 * FS)
    error_values = wm.get_column("fusion_pred_v1_error")

    # x-axis: mid-point of each window in hours
    score_starts  = wm.df.index.to_numpy()
    score_t_mid   = (score_starts + window_samples / 2) / FS
    t_hours       = t / 3600.0
    score_t_hours = score_t_mid / 3600.0

    error_arr = error_values.to_numpy().astype(float)

    fig, (ax_sig, ax_err) = py.subplots(
        2, 1, figsize=(16, 6),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
    )

    # ── Top: raw signal ───────────────────────────────────────────────
    ax_sig.plot(t_hours, x * 1000, color="steelblue", linewidth=0.4, alpha=0.8)
    ax_sig.set_ylabel("Signal amplitude")
    ax_sig.set_title(f"{filename} — raw signal and fusion prediction v1 error")

    # ── Bottom: prediction error ──────────────────────────────────────
    ax_err.step(score_t_hours, error_arr, where="mid", color="darkorange", linewidth=1.0)
    ax_err.fill_between(score_t_hours, error_arr, step="mid", alpha=0.25, color="darkorange")
    ax_err.set_ylabel("Prediction error")
    ax_err.set_xlabel("Time (hours)")
    ax_err.axhline(0, color="gray", linewidth=0.7, linestyle="--")

    py.tight_layout()
    py.show()


# language encodings 
# sax - gaussian breakpoints, cSax - mean shift clustering, pSax - KDE and lloyd-max
def encode_psax_windowed(wm, csvfilename, dim_ratio=0.1, alphabet_size=8):
    # Function to add a column of computed psax encoding per window
    # Since encoding is window specific, paa cutlines are also window specific
    # dim_ratio is percentage of window-size samples that are returned as values averaged under paa
    wm.add_computed_column("psax_windowed",make_psax_encoder(dim_ratio=dim_ratio,alphabet_size=alphabet_size))
    wm.save_window(csvfilename) 
    print("Successfully computed psax window encoding")
    return wm
    
def encode_psax_entire(wm, csvfilename, dim_ratio=0.1, alphabet_size=8, training_frac=1):
    # Function to add a column to the wm object of computed psax encoding
    # psax encoding is performed on the entire dataset, then split into specified windows in wm
    # training frac is how much of the data is used to train the paa cutlines
    wm = encode_dataset_psax(wm,dim_ratio=dim_ratio,alphabet_size=alphabet_size,training_frac=training_frac,column_name="psax_entire")
    wm.save_window(csvfilename) 
    print("Successfully computed psax entire encoding")
    return wm

def encode_csax_windowed(wm, csvfilename, dim_ratio=0.1):
    # Function to add a column of computed psax encoding per window
    # Since encoding is window specific, paa cutlines are also window specific
    # dim_ratio is percentage of window-size samples that are returned as values averaged under paa
    wm.add_computed_column("csax_windowed",make_csax_encoder(dim_ratio=dim_ratio))
    wm.save_window(csvfilename) 
    print("Successfully computed csax window encoding")
    return wm
    
def encode_csax_entire(wm, csvfilename, dim_ratio=0.1, training_frac=1):
    # Function to add a column to the wm object of computed psax encoding
    # psax encoding is performed on the entire dataset, then split into specified windows in wm
    # training frac is how much of the data is used to train the paa cutlines
    wm = encode_dataset_csax(wm,dim_ratio=dim_ratio,training_frac=training_frac,column_name="csax_entire")
    wm.save_window(csvfilename) 
    print("Successfully computed csax entire encoding")
    return wm

def encode_all_entropy_columns(wm, csvfilename):
    funcs = [_sample_entropy, _shannon_entropy, _permutation_entropy, _svd_entropy, _spectral_entropy, _approximate_entropy]

    for func in funcs:
        wm.add_computed_column(func.__name__.replace("_", " "), func)

    wm.save_window(csvfilename)
    print("Successfully computed all entropy (per window) columns")
    return wm

def encode_stft_columns(wm, csvfilename):
    return None

def plot_wm_signal(wm):
    x = wm.get_entire_signal()
    fs = wm._fs
    t = np.linspace(0,len(x)*fs,len(x))
    plt.plot(t/3600,x*1000)
    plt.xlabel("Time (hr)")
    plt.ylabel("Signal (mV)")
    plt.show()
