---
id: 7
title: "Adapter remap batch B: encoding blocks"
model: haiku
size: M
blocked_by: [5]
mutex: [5, 8, 9]
files: ["Adapters/catalogue_gramian_gasf.py", "Adapters/detection_sax_csax.py", "Adapters/detection_wavelet_scattering.py", "catalogue_gramian_fusion.py", "catalogue_gramian_gadf.py", "catalogue_gramian_recurrence.py", "detection_freq_stft.py", "detection_sax_dsax.py", "detection_sax_psax.py"]
flags: ['done']
level: 2
unblocks: 3
budget_minutes: 60
---
# 07 — Adapter remap batch B: encoding blocks

**Model:** [H] · **Size:** [M]

**What to build:** the nine adapters that genuinely produce an image or symbolic representation declare
`Encoding`, with no behavioural change.

**Blocked by:** 05

**Files/modules touched:** `Adapters/catalogue_gramian_gasf.py`, `catalogue_gramian_gadf.py`,
`catalogue_gramian_recurrence.py`, `catalogue_gramian_fusion.py`, `Adapters/detection_sax_csax.py`,
`detection_sax_psax.py`, `detection_sax_dsax.py`, `Adapters/detection_wavelet_scattering.py`,
`detection_freq_stft.py`; their existing tests.

**Merge risk:** **MEDIUM vs ticket 08** — 08 defines how a `WindowSet` carries attached features, and
the four Gramian adapters declare `max_span_samples` because they consume a span, not a window set.
Whichever lands first fixes the convention for whether an encoder's input is `Signal` or `WindowSet`;
the second must adopt it, not redefine it. **Do not edit `Adapters/base.py`.**

**Acceptance criteria:**
- [ ] All nine declare `output_kind="Encoding"` and an explicit `input_kind`.
- [ ] The three SAX adapters keep their existing `recommend` and `derive` callables working unchanged —
      a test asserts `recommend` still returns span-aware values and `derive` still returns its
      readout rows.
- [ ] The four Gramian adapters keep `max_span_samples` enforced, verified by a test that a too-long
      span still raises before `run` is called.
- [ ] Existing tests for these nine adapters pass unmodified.
