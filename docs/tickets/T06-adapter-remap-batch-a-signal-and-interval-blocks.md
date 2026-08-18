---
id: 6
title: "Adapter remap batch A: signal and interval blocks"
model: haiku
size: M
blocked_by: [5]
mutex: [5, 43]
files: ["Adapters/detection_rupture.py", "Adapters/preprocessing_bandpass.py", "detection_dehshibi_spikes.py", "detection_spike_v1.py", "preprocessing_detrend.py", "preprocessing_highpass.py", "preprocessing_lowpass.py"]
flags: []
level: 2
unblocks: 5
budget_minutes: 60
---
# 06 — Adapter remap batch A: signal and interval blocks

**Model:** [H] · **Size:** [M]

**What to build:** the seven adapters whose types are a straight rename declare their new types, with
no behavioural change.

**Blocked by:** 05

**Files/modules touched:** `Adapters/preprocessing_bandpass.py`, `preprocessing_detrend.py`,
`preprocessing_highpass.py`, `preprocessing_lowpass.py`, `Adapters/detection_rupture.py`,
`detection_spike_v1.py`, `detection_dehshibi_spikes.py`; their existing tests.

**Merge risk:** **MEDIUM vs ticket 43 (surrogate block)** — both produce `Signal` from `Signal`, and
both will be tempted to write a shared "signal transform" helper. This ticket owns that helper if one
is written; 43 imports it. **Do not edit `Adapters/base.py`** (frozen at 05).

**Acceptance criteria:**
- [ ] The four preprocessing adapters declare `input_kind="Signal"`, `output_kind="Signal"`.
- [ ] The three detection adapters declare `input_kind="Signal"`, `output_kind="SpanSet"`.
- [ ] Each `run` returns an `AdapterResult` populating both the legacy field and the new typed `value`.
- [ ] Existing tests for these seven adapters pass unmodified.
- [ ] No adapter in this batch declares a side-input or an estimator — that is other tickets' work.
