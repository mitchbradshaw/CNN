# UI/

**The signal viewer and annotation tool.** The only place in this repo that
imports Panel, HoloViews or Datashader — everything in `Working/` and
`Pipelines/` must stay runnable headless on the SLURM cluster. The UI adapts
to the analysis code, never the reverse: it only ever calls into
`Working.Preprocessing.database.queries`, the same plain-function API a
headless script would use.

## Running it

```bash
panel serve UI/app.py --show
# or
python UI/app.py
```

Requires `panel`, `holoviews`, `datashader`, `bokeh` (not in the root
requirements list yet — install alongside the stage you need, per the root
README). Also requires the database to be populated first:

```bash
python Pipelines/materialize_channels/materialize_channels.py
python Pipelines/import_labels/import_10min_labels.py
```

## Layout

```
app.py     Panel entry point — the ViewerApp param.Parameterized class:
           widgets, callbacks, and the layout. Owns the database connection.
plots.py   Pure HoloViews/Datashader construction — no Panel, no database
           calls. Builds the zoom-driven rasterized curve and the
           annotation/reviewed-span overlays.
```

## How the plot stays responsive and honest

A channel is 1-5M+ samples. `plots.build_channel_dmap` drives a
`hv.DynamicMap` off a `hv.streams.RangeX` stream: each callback slices the
`np.load(..., mmap_mode='r')`'d channel to just the currently visible span
(only that span pages in off disk) and hands the slice to `rasterize` — not
`datashade`, so aggregated values stay inspectable rather than being baked
into a fixed RGB image. At full zoom-out the slice is the whole channel; at
high zoom it's small and effectively shows every sample.

Annotations and reviewed spans are drawn as `hv.Rectangles` — **one
vectorized element per group** (imported vs manual), not one HoloViews
element per row. A channel can carry hundreds of annotations, and
overlaying that many individual elements (the first version of this used
`hv.VSpan` per row) makes HoloViews' internal path de-duplication
pathologically slow — a confirmed multi-minute hang building the Bokeh
model for ~700 elements. Vectorized `Rectangles` with a `verdict` value
dimension renders in well under a second regardless of row count.

## Visual encoding

- **Colour** = verdict (green interesting / gray not-interesting / red
  artifact / purple unsure).
- **Alpha + border** = source — imported annotations are low-alpha with no
  border; manual ones are higher-alpha with a black border.
- A faint blue band = a reviewed span (examined, whether or not anything
  was annotated in it).
- A dashed outline = the current drag-selected span, pending save.

## Editing rules

Imported annotations (`source='imported_10min'`) cannot be edited or
deleted from the UI — enforced in `Working/Preprocessing/database/queries.py`
(`update_annotation` / `delete_annotation` raise `PermissionError` unless
`force=True`), not just hidden in the UI layer.
