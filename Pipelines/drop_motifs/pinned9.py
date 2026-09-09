"""
pinned9.py
===========
Import the drop_motifs9 detector as it was when the shipped store was
built, from a snapshot, so round 2 is not measuring drop_motifs10.

WHY THIS EXISTS
---------------
`passes6`, `passes7`, `detect5`, `motifs5` and `cluster` are shared, and
drop_motifs10 is being written against them in this same checkout right
now. Between two runs of `run_round2_store.py` an hour apart the same
command produced 1736 and then 1676 raw motifs, and a third produced 2463,
because the files underneath had changed in between. None of those
differences are round 2's, and a store that carries them cannot say which
correction moved which number.

So round 2 does not import the working tree's detector. It imports a
SNAPSHOT:

  TRACKED modules come from a git commit - `PINNED_COMMIT`, the commit the
  shipped `Plots/drop_motifs9_fig2a` store was built from. `git show` is
  the source of truth, so no amount of editing in the working tree can
  move them.

  UNTRACKED modules (`passes9`, `refine9`, and their siblings - most of the
  drop_motifs9 pipeline was never committed) are copied from the working
  tree, because git has no other version of them, and are then PINNED
  through the isolation switches and constants drop_motifs10 added: see
  `SWITCH_PINS` and `DROP_MOTIFS10_PINS`.

Those pins are the weak half of this arrangement and they are VERIFIED
rather than trusted. The caller checks the re-detected per-channel counts
against the shipped `run_summary.json`; the key fix cannot move a count, so
any difference means an unpinned drop_motifs10 change is still active, and
that is a hard stop rather than a store.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not modify one byte of the working tree. drop_motifs10's author is
working in these files; round 2's job is to read them, not to edit them or
to stash them. The snapshot lives in a scratch directory and is rebuilt
from scratch on every run.
"""

import hashlib
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The commit the shipped drop_motifs9 store was built from. Everything
# tracked is read from here rather than from the working tree.
PINNED_COMMIT = "834c200"

# Every module the drop_motifs9 detector chain needs, in one list. Which
# SOURCE each comes from is not declared here and is not guessable: the
# drop_motifs9 pipeline was never committed, so `passes9`, `refine9`,
# `passes8`, `style8`, `clusterfigs8` and `clusterfigs9` exist only in the
# working tree, while `passes6`, `passes7`, `detect5`, `motifs5` and
# `cluster` are tracked and can be pinned properly. `build_snapshot` asks
# git first and falls back to the working tree, and records which answer it
# got for every file - so the store's provenance says exactly which modules
# are pinned to a commit and which are only as good as the tree they were
# copied from.
MODULES = (
    "Pipelines/drop_motifs/passes6.py",
    "Pipelines/drop_motifs/passes7.py",
    "Pipelines/drop_motifs/passes8.py",
    "Pipelines/drop_motifs/passes9.py",
    "Pipelines/drop_motifs/refine9.py",
    "Pipelines/drop_motifs/style7.py",
    "Pipelines/drop_motifs/style73.py",
    "Pipelines/drop_motifs/style8.py",
    "Pipelines/drop_motifs/clusterfigs6.py",
    "Pipelines/drop_motifs/clusterfigs7.py",
    "Pipelines/drop_motifs/clusterfigs73.py",
    "Pipelines/drop_motifs/clusterfigs8.py",
    "Pipelines/drop_motifs/clusterfigs9.py",
    "Working/Detection/drop_motifs/detect5.py",
    "Working/Detection/drop_motifs/detect.py",
    "Working/Detection/drop_motifs/autoparams.py",
    "Working/Detection/drop_motifs/motifs5.py",
    "Working/Detection/drop_motifs/cluster.py",
    "Working/Detection/drop_motifs/gradients.py",
    "Working/Detection/drop_motifs/store.py",
)

# THE ONE DELIBERATE EXCEPTION to "pin everything to the commit".
#
# `clusterfigs7._waveform_of` at PINNED_COMMIT is the version that CLIPS a
# length mismatch into a one-sample fall - the defect this whole round
# exists to remove. Pinning it would mean re-detecting with the fix and
# then measuring with the bug. So this one file is taken from the working
# tree, where it now raises. It is listed separately rather than dropped
# into the untracked pile because it is a CHOICE, and a reader has to see
# it as one.
FROM_WORKING_TREE = {
    "Pipelines/drop_motifs/clusterfigs7.py": (
        "_waveform_of must RAISE on a length mismatch, not clip it to a "
        "one-sample fall. The pinned commit's copy is the defect."),
}

# ROUND 2'S OWN FIX, applied to the snapshot as source text.
#
# This is the whole point of the round, so it is spelled out rather than
# inherited. At `PINNED_COMMIT` an event's key is
# (catalogue, recording, pass, absolute onset) and carries no window. Under
# `passes9.detect_sliding` the same drop sits in two overlapping windows,
# each detrending it against its own baseline and framing it with its own
# bounds - so the two are ONE key. `detect_sliding`'s `all_arrays.update`
# then keeps the LAST window's snippet while its dedup keeps the
# BEST-CENTRED row, and the surviving row's `snippet_start_idx` /
# `snippet_end_idx` belong to a different window from the surviving array.
# That is how 208 of 1736 rows got a `detrended_mv` of the wrong length,
# and how 22 refined motifs reached the shipped Ward tree as all-zero
# vectors.
#
# The fix is applied HERE, to the snapshot, and not to the working tree,
# because drop_motifs10's author is editing those files. Each patch asserts
# its target appears exactly once, so a snapshot that has drifted fails
# loudly instead of being silently unpatched.
KEY_FIX = (
    (
        "Pipelines/drop_motifs/passes6.py",
        "def motif_key(catalogue_id, recording_id, pass_key, "
        "absolute_onset):",
        "def motif_key(catalogue_id, recording_id, pass_key, "
        "absolute_onset,\n              window_index=None):",
        "motif_key takes the window",
    ),
    (
        "Pipelines/drop_motifs/passes6.py",
        '    return (f"id{int(catalogue_id):03d}_r{int(recording_id)}"\n'
        '            f"_{pass_key}_{int(absolute_onset)}")',
        '    tail = "" if window_index is None else f"_w{int(window_index)}"\n'
        '    return (f"id{int(catalogue_id):03d}_r{int(recording_id)}"\n'
        '            f"_{pass_key}_{int(absolute_onset)}{tail}")',
        "and puts it in the key; None reproduces the old string exactly, "
        "so a whole-span run is unchanged",
    ),
    (
        "Pipelines/drop_motifs/passes7.py",
        "                      sens_overrides=None, inv_overrides=None,\n"
        "                      micro_overrides=None):",
        "                      sens_overrides=None, inv_overrides=None,\n"
        "                      micro_overrides=None, window_index=None):",
        "detect_multiscale accepts the window",
    ),
    (
        "Pipelines/drop_motifs/passes7.py",
        '        new_key = motif_key(catalogue_id, recording_id, pass_key,\n'
        '                            row["onset_idx"])',
        '        new_key = motif_key(catalogue_id, recording_id, pass_key,\n'
        '                            row["onset_idx"],\n'
        '                            window_index=window_index)',
        "and threads it into every key it mints",
    ),
)


# Module-level constants drop_motifs10 changed in an untracked file, set
# back to their drop_motifs9 values. A constant has no switch, so this is
# the only way to pin it, and each entry names what it was changed FROM.
DROP_MOTIFS10_PINS = {
    "Pipelines.drop_motifs.passes9": {
        "MIN_WINDOW_SAMPLES": (
            64, "drop_motifs10 lowered it to 32; 64 is drop_motifs9's"),
    },
}

# Keyword switches drop_motifs10 added, and the value that restores
# drop_motifs9. Applied by the caller, listed here so the pin is in one
# place. Each names the function that owns it: they are not on the same
# one, and a keyword passed to the wrong function is swallowed by a
# `**kwargs` and silently does nothing.
SWITCH_PINS = {
    "remeasure_depth": {
        "owner": "passes9.detect_sliding",
        "value": False,
        "why": ("drop_motifs10 defect 5: re-measure a merged row's depth. "
                "Off so round 2's numbers are attributable to the key fix"),
    },
    "dedup_scale_by_fs": {
        "owner": "passes7.detect_multiscale",
        "value": False,
        "why": ("drop_motifs10: restore fs to the within-window dedup "
                "tolerance. At 10 Hz it merges far more candidates, so "
                "leaving it on would mix two corrections in one store"),
    },
}

_SNAPSHOT = None


def _repo_root():
    root = Path(__file__).resolve().parent
    while not (root / "Working").is_dir() and root != root.parent:
        root = root.parent
    return root


def _git(root, *args):
    return subprocess.run(("git", *args), cwd=str(root), check=True,
                          capture_output=True).stdout


def _apply_key_fix(path, relative):
    """Apply round 2's key fix to one snapshot file. Returns what it did.

    Every substitution must match EXACTLY ONCE. A target that is missing,
    or that appears twice, means the file is not the one these patches were
    written against - and silently skipping it would produce a store that
    looks like round 2's and is not.
    """
    patches = [p for p in KEY_FIX if p[0] == relative]
    if not patches:
        return None
    text = path.read_text("utf-8")
    done = []
    for _, old, new, why in patches:
        found = text.count(old)
        if found != 1:
            raise RuntimeError(
                f"round 2's key fix does not apply to {relative}: the "
                f"target below appears {found} times, expected exactly "
                f"once.\n---\n{old}\n---\nThe snapshot is not the file "
                "these patches were written against. Do not build a store "
                "from it.")
        text = text.replace(old, new, 1)
        done.append(why)
    path.write_text(text, encoding="utf-8")
    return done


def build_snapshot(dest=None, commit=PINNED_COMMIT):
    """Materialise the pinned detector. Returns `(path, provenance)`.

    `provenance` carries a sha256 of every file that went in, so the store
    written from this snapshot records exactly which code produced it and
    a later run can prove it used the same.
    """
    root = _repo_root()
    dest = Path(dest or (Path(tempfile.gettempdir()) / "drop_motifs9_pinned"))
    if dest.exists():
        shutil.rmtree(dest)

    provenance = {"commit": commit, "root": str(root),
                  "pinned_to_commit": {}, "from_working_tree": {},
                  "not_in_commit": []}

    for relative in MODULES:
        reason = FROM_WORKING_TREE.get(relative)
        blob, source = None, None
        if reason is None:
            try:
                blob = _git(root, "show", f"{commit}:{relative}")
                source = "commit"
            except subprocess.CalledProcessError:
                # Never committed. The drop_motifs9 pipeline largely was
                # not, so this is expected for its own modules and is
                # recorded rather than treated as an error.
                provenance["not_in_commit"].append(relative)
        if blob is None:
            path = root / relative
            if not path.is_file():
                raise RuntimeError(
                    f"{relative} is neither in {commit} nor in the working "
                    "tree; the snapshot cannot be built.")
            blob = path.read_bytes()
            source = "working tree"

        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        entry = {"sha256_16": hashlib.sha256(blob).hexdigest()[:16]}
        applied = _apply_key_fix(target, relative)
        if applied:
            entry["key_fix"] = applied
            entry["sha256_16_after_fix"] = hashlib.sha256(
                target.read_bytes()).hexdigest()[:16]
        if source == "commit":
            provenance["pinned_to_commit"][relative] = entry
        else:
            entry["why"] = reason or "not present in the pinned commit"
            provenance["from_working_tree"][relative] = entry

    # -- packages that fall through to the real tree ----------------------
    #
    # The snapshot holds the detector chain and nothing else, but
    # `detect5` imports `Working.Detection.sax`, `Working.config` and
    # others that are not part of it and are not changing. Enumerating
    # every transitive dependency would be a second, worse copy of the
    # import graph, and would break the moment one of them grew an import.
    #
    # So each snapshot package EXTENDS its own `__path__` with the real
    # directory, snapshot first. A module the snapshot has is found in the
    # snapshot; a module it does not have falls through to the working
    # tree. That is the whole mechanism, and its one sharp edge is worth
    # naming: a fall-through module is NOT pinned, so if drop_motifs10
    # starts editing one of those, this snapshot will quietly pick the
    # change up. The count check against the shipped `run_summary.json` is
    # what catches that, which is why it is a hard stop and not a warning.
    for package in ("Pipelines", "Pipelines/drop_motifs", "Working",
                    "Working/Detection", "Working/Detection/drop_motifs"):
        marker = dest / package / "__init__.py"
        marker.parent.mkdir(parents=True, exist_ok=True)
        source = root / package / "__init__.py"
        original = source.read_text("utf-8") if source.is_file() else ""
        real = (root / package).as_posix()
        marker.write_text(
            original
            + "\n\n# Written by Pipelines/drop_motifs/pinned9.py. The "
              "snapshot holds only the\n# detector chain; everything else "
              "resolves from the real tree, snapshot first.\n"
              f"__path__.append({real!r})\n",
            encoding="utf-8")

    provenance["fall_through_root"] = str(root)

    return dest, provenance


def activate(dest=None, commit=PINNED_COMMIT):
    """Put the snapshot ahead of the working tree on `sys.path`.

    MUST be called before anything imports `Pipelines.drop_motifs.*` or
    `Working.Detection.drop_motifs.*`. Any of those already in
    `sys.modules` is evicted, so a caller that imported them by accident
    still gets the pinned copies rather than a silent mixture of the two.
    """
    global _SNAPSHOT
    path, provenance = build_snapshot(dest, commit)
    _SNAPSHOT = (path, provenance)

    for name in list(sys.modules):
        if (name.startswith("Pipelines.drop_motifs")
                or name.startswith("Working.Detection.drop_motifs")
                or name in ("Pipelines", "Working", "Working.Detection")):
            del sys.modules[name]

    if str(path) in sys.path:
        sys.path.remove(str(path))
    sys.path.insert(0, str(path))
    importlib.invalidate_caches()

    _apply_compat_shims()

    applied = {}
    for module_name, pins in DROP_MOTIFS10_PINS.items():
        module = importlib.import_module(module_name)
        for attribute, (value, why) in pins.items():
            was = getattr(module, attribute, None)
            setattr(module, attribute, value)
            applied[f"{module_name}.{attribute}"] = {
                "was": was, "pinned_to": value, "why": why}
    provenance["constant_pins"] = applied
    provenance["compat_shims"] = _apply_compat_shims()
    provenance["switch_pins"] = SWITCH_PINS

    # Prove the modules actually came from the snapshot. An import that
    # silently resolved to the working tree would make every pin above a
    # no-op, and the store would be drop_motifs10's without saying so.
    from Pipelines.drop_motifs import passes9
    from Working.Detection.drop_motifs import motifs5
    for module in (passes9, motifs5):
        if not str(Path(module.__file__).resolve()).startswith(str(path)):
            raise RuntimeError(
                f"{module.__name__} was imported from {module.__file__}, "
                f"not from the pinned snapshot at {path}. Something "
                "imported it before activate() ran.")

    provenance["verified_import_paths"] = {
        "passes9": passes9.__file__, "motifs5": motifs5.__file__}
    return path, provenance


def _apply_compat_shims():
    """Let a working-tree module import against a pinned one.

    The snapshot mixes eras on purpose: `passes6` is pinned to the commit,
    while `passes8` and `passes9` are untracked and can only come from the
    working tree, where drop_motifs10 has already edited them. So a later
    module can reference a name an earlier one does not have.

    There is exactly one such name today. `passes8` line 66 does
    `_fs_of = passes6._fs_of`, and drop_motifs10 added `_fs_of` to
    `passes6`; the pinned `passes6` has no such attribute and the import
    fails. The shim below supplies it.

    IT IS BEHAVIOURALLY INERT FOR THIS CHAIN, and that is what makes it a
    shim rather than a silent adoption of drop_motifs10. `passes8._fs_of`
    is used only inside `passes8.deduplicate`, and `passes9` imports only
    `size_split` from `passes8` - it never calls that dedup. The pinned
    `passes6.deduplicate` does not call `_fs_of` at all, because at the
    pinned commit the fs scaling does not exist. So this restores an
    import, not a behaviour.

    A shim that is NOT inert must not be added here. If a future
    drop_motifs10 change needs one, the honest move is to stop and decide
    what round 2's basis is, which is what the count check enforces.
    """
    from Pipelines.drop_motifs import passes6

    if not hasattr(passes6, "_fs_of"):
        def _fs_of(payload, default=1.0):
            """The sampling rate carried alongside a candidate, if any."""
            if isinstance(payload, dict):
                return float(payload.get("fs", default) or default)
            if isinstance(payload, (tuple, list)) and payload:
                row = payload[0]
                if isinstance(row, dict) and "fs" in row:
                    return float(row["fs"] or default)
            return float(default)

        _fs_of.__module__ = passes6.__name__
        passes6._fs_of = _fs_of
        return {"Pipelines.drop_motifs.passes6._fs_of":
                "compat shim; inert for the drop_motifs9 chain"}
    return {}


def switch_kwargs(owner):
    """The pinned switches belonging to `owner`, as a kwargs dict."""
    return {k: v["value"] for k, v in SWITCH_PINS.items()
            if v["owner"] == owner}
