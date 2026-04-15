from matrix_calc import *
from aeon_analysis.transformations import add_catch22_to_matrix
from manage_data.load_data import load_raw_data
from analysis.entropy_analysis import _shannon_entropy, _svd_entropy, _sample_entropy, _spectral_entropy, _permutation_entropy, _approximate_entropy
import numpy as np

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
    from cnn.apply_cnn import add_cnn_scores
    wm = add_cnn_scores(wm,modelpath,image_type=imgtype,batch_size=batchsize)
    wm.save_window(csvfilename)

def update_fusion_prediction_v1_columns(wm,modelpath,csvfilename,batchsize=64):
    from cnn.apply_cnn import add_fusion_prediction_v1_scores
    wm = add_fusion_prediction_v1_scores(wm,modelpath,batch_size=batchsize)
    wm.save_window(csvfilename)

def update_randomforest_columns(wm, modelpath, csvfilename, overwrite=False):
    """
    Apply a saved Catch22 + RandomForest pipeline to every window in wm and
    store the raw class probabilities as two new columns.

    Adds
    ----
    rf_p_interesting    : P(class == interesting)
    rf_p_notinteresting : P(class == not-interesting)

    predict_proba is used directly, so threshold optimisation does not apply —
    both a plain pipeline and a ThresholdedPipeline work here.

    Parameters
    ----------
    wm          : WindowMatrix
    modelpath   : str or Path   path to a .joblib model file
    csvfilename : str           filename passed to wm.save_window
    overwrite   : bool          if False (default), skip if columns already exist

    Returns
    -------
    wm  (for chaining)

    Note
    ----
    Only the raw signal is used (1 channel).  The .npy training files had a
    second channel of absolute time which is recording-specific and causes
    constant 0.5 predictions when applied to a different recording.
    """
    import joblib
    import sys

    # The model was saved while classification.py ran as __main__, so
    # ThresholdedPipeline is stored as '__main__.ThresholdedPipeline'.
    # Register it here so joblib can deserialise existing model files.
    from aeon_analysis.classification import ThresholdedPipeline
    sys.modules["__main__"].ThresholdedPipeline = ThresholdedPipeline

    if not overwrite and "rf_p_interesting" in wm.columns:
        return wm

    model = joblib.load(modelpath)

    # Build (n_valid, 1, win_len) — signal channel only.
    # Skip any trailing windows shorter than win_len (signal runs out at the end).
    win_len       = wm._window_samples
    windows       = []
    valid_indices = []
    for idx in wm.df.index:
        sig = wm.get_window_signal(idx)
        if len(sig) < win_len:
            continue                               # incomplete tail window — skip
        windows.append(sig.reshape(1, -1))
        valid_indices.append(idx)
    X = np.stack(windows).astype(np.float32)       # (n_valid, 1, win_len)

    # predict_proba → (n_valid, 2): col 0 = P(not-interesting), col 1 = P(interesting)
    probas = model.predict_proba(X)

    # Write back via index-keyed dicts — skipped rows become NaN automatically
    p_int  = dict(zip(valid_indices, probas[:, 1]))
    p_nint = dict(zip(valid_indices, probas[:, 0]))
    wm.add_external_column("rf_p_interesting",    p_int,  overwrite=overwrite)
    wm.add_external_column("rf_p_notinteresting", p_nint, overwrite=overwrite)

    wm.save_window(csvfilename)
    print(f"RF probability columns added → {csvfilename}")
    return wm


# language encodings
# sax - gaussian breakpoints, cSax - mean shift clustering, pSax - KDE and lloyd-max
def encode_psax_windowed(wm, csvfilename, dim_ratio=0.1, alphabet_size=8):
    from sax.sax_encoding import make_psax_encoder
    wm.add_computed_column("psax_windowed",make_psax_encoder(dim_ratio=dim_ratio,alphabet_size=alphabet_size))
    wm.save_window(csvfilename)
    print("Successfully computed psax window encoding")
    return wm

def encode_psax_entire(wm, csvfilename, dim_ratio=0.1, alphabet_size=8, training_frac=1):
    from sax.sax_encoding import encode_dataset_psax
    wm = encode_dataset_psax(wm,dim_ratio=dim_ratio,alphabet_size=alphabet_size,training_frac=training_frac,column_name="psax_entire")
    wm.save_window(csvfilename)
    print("Successfully computed psax entire encoding")
    return wm

def encode_csax_windowed(wm, csvfilename, dim_ratio=0.1):
    from sax.sax_encoding import make_csax_encoder
    wm.add_computed_column("csax_windowed",make_csax_encoder(dim_ratio=dim_ratio))
    wm.save_window(csvfilename)
    print("Successfully computed csax window encoding")
    return wm

def encode_csax_entire(wm, csvfilename, dim_ratio=0.1, training_frac=1):
    from sax.sax_encoding import encode_dataset_csax
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

def encode_catch22(wm, csvfilename):
    add_catch22_to_matrix(wm)
    wm.save_window(csvfilename)
    return wm
