"""Dataset curation: review queue -> curated cases -> versioned JSONL datasets with a content
hash, changelog, near-duplicate detection and tag slices."""

from opsloop.dataset.curate import CuratedCase, ReviewItem, build_review_queue, curate_from_trace
from opsloop.dataset.versioning import Dataset, DatasetManifest, DatasetStore

__all__ = [
    "CuratedCase",
    "Dataset",
    "DatasetManifest",
    "DatasetStore",
    "ReviewItem",
    "build_review_queue",
    "curate_from_trace",
]
