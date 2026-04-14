import argparse
import numpy as np
import scipy.io
import glob
import os
import re
import json
import random
#import tensorflow as tf
import matplotlib.pyplot as py
from manage_data.load_data import *
from manage_data.peruse_data import *
from manage_data.manage_raw import *
from gramian.gramian_calc import *
from manage_data.sort_data import *
from manage_data.interest_select import interest_select_windows
from cnn.interest_select_cnn import interest_select_cnn
from cnn.cnn_gfg import *
from analysis.entropy_analysis import *
from analysis.data_analysis import *
from analysis.freq_analysis import *
from PIL import Image


HELP_TEXT = """\
usage: python main.py [options]

  --timescale=10          Window size in minutes (default: 10)
  --file=M2_aug_...mat    Input .mat file (default: M2_aug_concat_fs1.mat)

  -scan                   Scan windows interactively
  -save                   Save raw windows to disk
  -load INDEX             Load window at start index INDEX
  -gram                   Save gramian (GASF) windows
  -cat CATEGORY           Target category: interesting or notinteresting
                          (used by -save, -load, -gram, --cnn)

  -freq                   Plot frequency histogram
  -entropy                Plot entropy histogram
  -stats                  Plot feature/stats histograms

  --cnn                   Run the conv net
  --image PATH            Image path for --cnn (default: auto from --timescale + -cat)
  --sort                  Run subcategorize_interesting_windows
  -select                 Run interest_select_windows (interactive labeller)
  -cnn_select             Run interest_select_cnn (CNN-assisted labeller)
  --suffix=STR            Suffix appended to output folder names for -select / -cnn_select
  --model_path=PATH       Path to .pth model for -cnn_select
  --image_type=TYPE       Image type for -cnn_select: fusion, GASF, GADF, recurrence (default: fusion)

  -h                      Show this help message and exit

examples:
  python main.py --timescale=5 -gram -cat=interesting
  python main.py -load 130201 -cat=notinteresting
  python main.py -freq -entropy -stats
  python main.py --cnn --image "10min_fs1.0_interesting_GASF\\GASF_149801.png"
"""

parser = argparse.ArgumentParser(description='EEG CNN analysis pipeline', add_help=False)
parser.add_argument('--timescale', type=float, default=10,
                    help='Window timescale in minutes (default: 10)')
parser.add_argument('--file', type=str, default='M2_aug_concat_fs1.mat',
                    help='Input .mat file (default: M2_aug_concat_fs1.mat)')
parser.add_argument('-scan', action='store_true',
                    help='Interactively scan windows')
parser.add_argument('-save', action='store_true',
                    help='Save raw windows to disk')
parser.add_argument('-load', type=int, default=None, metavar='INDEX',
                    help='Load window at given start index')
parser.add_argument('-gram', action='store_true',
                    help='Save gramian (GASF) windows')
parser.add_argument('-cat', type=str, default=None, metavar='CATEGORY',
                    help='Category to operate on: interesting or notinteresting')
parser.add_argument('-freq', action='store_true',
                    help='Plot frequency histogram')
parser.add_argument('-entropy', action='store_true',
                    help='Plot entropy histogram')
parser.add_argument('-stats', action='store_true',
                    help='Plot feature/stats histograms')
parser.add_argument('--cnn', action='store_true',
                    help='Run convolutional net')
parser.add_argument('--image', type=str, default=None,
                    help='Image path for CNN (default: auto-constructed from --timescale and -cat)')
parser.add_argument('--sort', action='store_true',
                    help='Run subcategorize_interesting_windows')
parser.add_argument('-select', action='store_true',
                    help='Run interest_select_windows (interactive labeller)')
parser.add_argument('-cnn_select', action='store_true',
                    help='Run interest_select_cnn (CNN-assisted labeller)')
parser.add_argument('--suffix', type=str, default='',
                    help='Suffix appended to output folder names for -select / -cnn_select')
parser.add_argument('--model_path', type=str, default=None,
                    help='Path to .pth model file for -cnn_select')
parser.add_argument('--image_type', type=str, default='fusion',
                    choices=['fusion', 'GASF', 'GADF', 'recurrence'],
                    help='Image type for -cnn_select (default: fusion)')
parser.add_argument('-h', action='store_true', dest='help',
                    help='Show this help message and exit')
args = parser.parse_args()

if args.help:
    print(HELP_TEXT)
    exit(0)

timescale = args.timescale
foldername = f"{timescale:g}min"   # e.g. 10 -> "10min", 10.5 -> "10.5min"
file = args.file

interesting, notinteresting, flag, fs = load_start_indices(foldername)
x, t = load_raw_data(file, fs)

window_samples = int(timescale * 60 * fs)

cats = {
    'interesting':    interesting,
    'notinteresting': notinteresting,
}

# -scan
if args.scan:
    cat = args.cat or 'interesting'
    scan_windows(x, t, cats[cat], timescale, fs)

# -save
if args.save:
    cat = args.cat or 'interesting'
    save_windows(x, cats[cat], timescale, fs, cat, window_samples)

# -load=INDEX
if args.load is not None:
    cat = args.cat or 'interesting'
    x, t = load_window(args.load, timescale, fs, cat)

# -gram
if args.gram:
    targets = [args.cat] if args.cat else ['interesting', 'notinteresting']
    for cat in targets:
        print(f"Processing '{cat}' windows...")
        save_gramian_windows(x, cats[cat], timescale, fs, cat, window_samples)
    print("Done.")

# --cnn
if args.cnn:
    if args.image:
        image_path = args.image
    else:
        cat = args.cat or 'interesting'
        image_path = os.path.join("DATA", f"{timescale:g}_MINUTES", f"{timescale:g}min_fs1.0_{cat}_GASF", "GASF_149801.png")
    print(get_dense_output(image_path, True))

# --sort
if args.sort:
    subcategorize_interesting_windows(timescale, fs)

# -select
if args.select:
    interest_select_windows(x, fs=fs, window_min=timescale, t=t, suffix=args.suffix)

# -cnn_select
if args.cnn_select:
    if not args.model_path:
        print("Error: -cnn_select requires --model_path=<path to .pth>")
    else:
        interest_select_cnn(
            x,
            fs=fs,
            window_min=timescale,
            model_path=args.model_path,
            image_type=args.image_type,
            t=t,
            suffix=args.suffix,
        )

# -freq
if args.freq:
    plot_freq_histogram(
        x,
        {"interesting": interesting, "notinteresting": notinteresting},
        fs,
        window_samples,
        freq_bin_width=0.02,
        log_scale=False,
    )

# -stats
if args.stats:
    plot_feature_histograms(
        x,
        {"interesting": interesting, "notinteresting": notinteresting},
        window_samples,
    )

# -entropy
if args.entropy:
    plot_entropy_histograms(
        x,
        {"interesting": interesting, "notinteresting": notinteresting},
        window_samples,
    )


