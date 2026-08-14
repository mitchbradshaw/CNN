"""
parsing.py
===========
Pure parsing/derivation functions for the `signal_catalog.xlsx` importer —
no pandas, no database, no side effects, so they're trivially unit-testable
in isolation from the actual spreadsheet.

Validated against the real `DATA/catalogue/signal_catalog.xlsx` (37 rows,
32 kept after the DATASET filter) before being wired into the importer —
see `import_signal_catalogue.py`'s module docstring for that audit.
"""

import re

N_CHANNELS = 16

# Typos/variants in the source spreadsheet that map onto an existing seeded
# vocabulary term rather than being genuinely new morphologies. Extend this
# if future catalogue rows have similar near-misses.
ELEMENT_ALIASES = {
    "stegasauras": "stegasaurus",
}

# Row-specific handling that isn't a generalizable text rule — ID 13
# ("Bad News" / "All channels identical, apart from DC") reads as an
# equipment fault, not a signal morphology, per explicit confirmation.
ARTIFACT_ID_NUMBERS = {13}


def pack_channel_to_global(pack, channel):
    """global_channel = pack * 4 + channel. Raises ValueError if out of
    [0, 16) — never silently clip."""
    global_channel = int(pack) * 4 + int(channel)
    if not (0 <= global_channel < N_CHANNELS):
        raise ValueError(
            f"pack={pack} channel={channel} -> global_channel={global_channel}, "
            f"outside [0, {N_CHANNELS})"
        )
    return global_channel


def hours_to_sample_index(hours, fs):
    """Channel-local hours -> channel-local sample index."""
    return round(hours * 3600 * fs)


def normalize_parent_id(parent_id):
    """0 means "no parent" -> None. Anything else is returned as an int for
    the caller to resolve against the imported ID_Number -> annotation_id map."""
    if parent_id is None:
        return None
    parent_id = int(parent_id)
    return None if parent_id == 0 else parent_id


def normalize_element_term(raw_term, known_vocab=()):
    """lower/underscore/trim a raw Elements entry, singularize a trailing
    's' if that resolves to a known vocabulary term, and apply
    `ELEMENT_ALIASES` for known source typos."""
    term = re.sub(r"\s+", "_", raw_term.strip().lower())
    term = ELEMENT_ALIASES.get(term, term)
    if known_vocab and term not in known_vocab and term.endswith("s") and term[:-1] in known_vocab:
        term = term[:-1]
    return term


def split_elements(raw, known_vocab=()):
    """Split a semicolon/comma-separated Elements cell into normalized terms.
    Returns [] for a NaN/empty cell (caller should check first for pandas NaN)."""
    if not raw or not str(raw).strip():
        return []
    parts = re.split(r"[;,]", str(raw))
    return [normalize_element_term(p, known_vocab) for p in parts if p.strip()]


_MULTI_COUNT_HINT = re.compile(r"\d+\D+then\s+\d+", re.I)
_SINGLE_CYCLE = re.compile(r"\bsingle\s+cycle\b", re.I)
_BARE_ONE = re.compile(r"^\s*1\s+\S+\s*$")
_X_SEQUENCE = re.compile(r"(\d+)\s*x\s+\S+.*?sequence", re.I)
_COUNT_KEYWORDS = re.compile(
    r"(\d+)\s+(cycles?|sequences?|sharps?|furrycaterpillars?|spikes?|patterns?|sharkfins?)\b",
    re.I,
)


def parse_event_count(sequence_structure, notes):
    """Parse a single, unambiguous event count from sequence_structure/Notes.

    Returns None (never guesses) when: no count is stated, or more than one
    distinct count is stated (e.g. "60 spikes ... then 40 spikes", or several
    different "N <noun>" phrases) — the full text still goes in the note
    regardless, so nothing is lost.
    """
    ss = sequence_structure or ""
    nt = notes or ""
    text = f"{ss} {nt}".strip()
    if not text:
        return None

    if _MULTI_COUNT_HINT.search(text):
        return None
    if _SINGLE_CYCLE.search(ss):
        return 1
    if _BARE_ONE.match(ss.strip()):
        return 1

    m = _X_SEQUENCE.search(text)
    if m:
        return int(m.group(1))

    counts = {int(m.group(1)) for m in _COUNT_KEYWORDS.finditer(text)}
    if len(counts) == 1:
        return counts.pop()
    return None  # zero or multiple distinct counts -> don't guess


def derive_structure(sequence_structure):
    """single_cycle / sequence / nested_sequence / type_specimen, or None
    if the text doesn't clearly state one."""
    s = (sequence_structure or "").lower()
    if "type specimen" in s:
        return "type_specimen"
    if "single cycle" in s:
        return "single_cycle"
    if "nested" in s:
        return "nested_sequence"
    if "sequence" in s or re.search(r"\bseq\b", s):
        return "sequence"
    return None


def derive_relation_kind(sequence_structure, notes, has_parent):
    """'type_specimen' if the text says so; 'sub_window' if it has a parent
    but isn't a specimen; else None."""
    text = f"{sequence_structure or ''} {notes or ''}".lower()
    if "type specimen" in text:
        return "type_specimen"
    if has_parent:
        return "sub_window"
    return None
