import numpy as np
import matplotlib.pyplot as plt

def scan_windows(x, t, start_indexes, timescale, fs):
    # function to sort through the windows of interest
    # plots window in x from start_index, with length timescale (minutes)
    # lets user browse through all windows in start index using left/right arrow keys

    window_samples = int(timescale * 60 * fs)
    state = {"idx": 0}

    fig, ax = plt.subplots()

    def draw(i):
        ax.cla()
        start = start_indexes[i]
        end = start + window_samples
        ax.plot(t[start:end], x[start:end])
        ax.set_title(f"Window {i + 1} / {len(start_indexes)}  (start={t[start]:.1f}s)")
        ax.set_xlabel("Time (s)")
        fig.canvas.draw()

    def on_key(event):
        if event.key == "right":
            state["idx"] = min(state["idx"] + 1, len(start_indexes) - 1)
        elif event.key == "left":
            state["idx"] = max(state["idx"] - 1, 0)
        else:
            return
        draw(state["idx"])

    fig.canvas.mpl_connect("key_press_event", on_key)
    draw(0)
    plt.show()