"""
import_drop_motifs
==================
Headless importer that reads the tracked drop-motif seed bundle
(`DATA/library_seed/drop_motifs5/motifs/`) and populates the shape-first
motif library.

The reader (`Working.Detection.drop_motifs.store`) and the shape clustering
(`Working.Detection.drop_motifs.cluster`) already exist and are imported,
not reimplemented. This package is the third step only: turning a clustering
into `motif_entry` / `motif_member` / `motif_edge` rows through the existing
writers in `Working.database.runs`.
"""

from Pipelines.import_drop_motifs.importer import (
    DEFAULT_BUNDLE_DIR,
    import_drop_motifs,
    main,
)

__all__ = ["DEFAULT_BUNDLE_DIR", "import_drop_motifs", "main"]
