"""Rebuild the worktree fixture database.

`DATA/` is gitignored, so the fixture cannot be a committed artefact — it has to
be reconstructible. This is that reconstruction, and it is the definition of
what the fixture *is*:

* **Schema-current**, because it comes from `init_db()` rather than from a copy.
* **No annotations, no motifs, no runs.** The isolation guarantee is that an
  agent which cannot reach the 11,000-row annotation corpus cannot damage it,
  and that worktree test behaviour never depends on real annotation content.
* **Recording rows only, and only for the junctioned channels.** Not because
  metadata is harmless, but because `UI/app.py` constructs a full `ViewerApp` at
  import time: with no recording it raises `RuntimeError`, and with a recording
  whose `npy_path` is absent it raises `FileNotFoundError`. Either one is a
  collection error in the ten test files that import `UI.app`, which is what
  quarantined an innocent T01 in run-20260816-1943.

So the fixture is small but not empty, and every row it carries points at data
the junction actually supplies. Run it after changing `recordings` in
`config.toml`, or after a schema migration:

    python -m orchestrator.make_fixture
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Working.database import queries as q  # noqa: E402
from Working.database import vocabulary as v  # noqa: E402
from Working.database.schema import init_db  # noqa: E402

from .config import load_config  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.toml"
# The real database, read read-only. It is the only source of truth for the
# fs / n_samples / global_offset of a real recording, and getting those wrong
# would make the fixture lie about data the junction really does supply.
SOURCE_DB = REPO_ROOT / "DATA" / "db" / "annotations.sqlite"


def build(*, config_path: Path = DEFAULT_CONFIG, source_db: Path = SOURCE_DB) -> Path:
    config = load_config(config_path, repo_root=REPO_ROOT)
    destination = config.paths.fixture_db
    recordings = config.paths.recordings

    if not recordings:
        raise SystemExit(
            "config.toml declares no `recordings`, so the fixture would have no "
            "channel data to point at and UI.app could not be imported in a worktree"
        )
    if not source_db.is_file():
        raise SystemExit(f"no source database at {source_db} to read recording metadata from")

    source = sqlite3.connect(f"file:{source_db.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row

    if destination.exists():
        destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(str(destination))
    v.seed_vocabulary(conn)

    kept = 0
    absent = []
    for row in source.execute("SELECT * FROM recordings ORDER BY source_file, channel"):
        npy = (REPO_ROOT / row["npy_path"]).resolve()
        if not any(npy.is_relative_to(d) for d in recordings):
            continue
        if not npy.is_file():
            absent.append(row["npy_path"])
            continue
        q.insert_recording(conn, row["source_file"], row["channel"], row["fs"],
                           row["n_samples"], row["global_offset"], row["npy_path"],
                           commit=False)
        kept += 1
    conn.commit()

    if absent:
        # A row whose file is gone is worse than no row at all. `UI/app.py`
        # builds a `ViewerApp` at import time and loads the first recording it
        # finds; an absent `npy_path` raises `FileNotFoundError` during
        # collection, pytest abandons the session, and every test file that
        # imports `UI.app` errors. Nothing runs, in every worktree, all night.
        # The directory being junctioned is not enough — it can be empty, and in
        # run-20260817-1157 it was.
        raise SystemExit(
            f"{len(absent)} recording(s) in {source_db} point inside the junctioned "
            f"directories but their channel files do not exist:\n  "
            + "\n  ".join(absent[:8])
            + (f"\n  ... and {len(absent) - 8} more" if len(absent) > 8 else "")
            + "\n\nRematerialise them before building the fixture:\n"
              "    python Pipelines/materialize_channels/materialize_channels.py"
        )

    if not kept:
        raise SystemExit(
            f"no recording in {source_db} points inside the junctioned directories "
            f"{[str(d) for d in recordings]} — the fixture would be unusable"
        )

    annotations = conn.execute("SELECT count(*) FROM annotations").fetchone()[0]
    conn.close()
    source.close()
    assert annotations == 0, "the fixture must carry no annotations"
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG, type=Path)
    args = parser.parse_args()

    destination = build(config_path=args.config)
    size = destination.stat().st_size
    conn = sqlite3.connect(destination)
    counts = {
        table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("recordings", "annotations", "annotation_tags")
    }
    conn.close()
    print(f"{destination}: {size:,} bytes")
    for table, count in counts.items():
        print(f"  {table}: {count:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
