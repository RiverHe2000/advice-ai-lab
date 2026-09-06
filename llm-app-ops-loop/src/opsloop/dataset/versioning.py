"""Versioned JSONL datasets: ``<root>/<name>/v<k>.jsonl`` + ``manifest.json`` with a content
hash over the canonical case lines, a changelog, near-duplicate rejection (rapidfuzz on the
normalised input) and tag slices."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from opsloop.dataset.curate import CuratedCase

_WS = re.compile(r"\s+")


def normalise_input(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


def canonical_line(case: CuratedCase) -> str:
    return json.dumps(case.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)


def content_hash(cases: Sequence[CuratedCase]) -> str:
    h = hashlib.sha256()
    for case in sorted(cases, key=lambda c: c.id):
        h.update(canonical_line(case).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:16]


class DatasetManifest(BaseModel):
    name: str
    version: int
    content_hash: str
    n_cases: int
    created: str
    parent_version: int | None = None
    parent_hash: str | None = None
    changelog: list[str] = Field(default_factory=list)
    slices: dict[str, int] = Field(default_factory=dict)
    duplicates_rejected: list[dict[str, Any]] = Field(default_factory=list)


class Dataset(BaseModel):
    manifest: DatasetManifest
    cases: list[CuratedCase]

    def slice(self, tag: str) -> list[CuratedCase]:
        return [c for c in self.cases if tag in c.tags]

    def slices(self, *, min_cases: int = 1) -> dict[str, list[CuratedCase]]:
        out: dict[str, list[CuratedCase]] = {}
        for c in self.cases:
            for t in c.tags:
                out.setdefault(t, []).append(c)
        return {t: cs for t, cs in sorted(out.items()) if len(cs) >= min_cases}


def find_near_duplicates(
    candidates: Sequence[CuratedCase], existing: Iterable[CuratedCase], *, threshold: float = 92.0
) -> tuple[list[CuratedCase], list[dict[str, Any]]]:
    kept: list[CuratedCase] = []
    rejected: list[dict[str, Any]] = []
    seen: list[tuple[str, str]] = [(c.id, normalise_input(c.input)) for c in existing]
    for case in candidates:
        norm = normalise_input(case.input)
        dup: tuple[str, float] | None = None
        for other_id, other in seen:
            score = float(fuzz.ratio(norm, other))
            if score >= threshold:
                dup = (other_id, score)
                break
        if dup is not None:
            rejected.append({"id": case.id, "duplicate_of": dup[0], "similarity": round(dup[1], 1)})
            continue
        kept.append(case)
        seen.append((case.id, norm))
    return kept, rejected


class DatasetStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _dir(self, name: str) -> Path:
        return self.root / name

    def versions(self, name: str) -> list[int]:
        d = self._dir(name)
        if not d.exists():
            return []
        out: list[int] = []
        for p in d.glob("v*.jsonl"):
            m = re.fullmatch(r"v(\d+)\.jsonl", p.name)
            if m:
                out.append(int(m.group(1)))
        return sorted(out)

    def names(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and self.versions(p.name))

    def load(self, name: str, version: int | None = None) -> Dataset:
        versions = self.versions(name)
        if not versions:
            msg = f"dataset {name!r} has no versions under {self.root}"
            raise FileNotFoundError(msg)
        v = version if version is not None else versions[-1]
        path = self._dir(name) / f"v{v}.jsonl"
        if not path.exists():
            msg = f"dataset {name}@v{v} not found"
            raise FileNotFoundError(msg)
        cases = [
            CuratedCase.model_validate(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        manifest = DatasetManifest.model_validate(
            json.loads((self._dir(name) / f"v{v}.manifest.json").read_text(encoding="utf-8"))
        )
        if manifest.content_hash != content_hash(cases):
            msg = f"dataset {name}@v{v}: content hash mismatch (file edited after build?)"
            raise ValueError(msg)
        return Dataset(manifest=manifest, cases=cases)

    def build(
        self,
        name: str,
        cases: Sequence[CuratedCase],
        *,
        version: int | None = None,
        now: str,
        changelog: str = "",
        dedup_threshold: float = 92.0,
        extend_previous: bool = True,
    ) -> Dataset:
        versions = self.versions(name)
        v = version if version is not None else (versions[-1] + 1 if versions else 1)
        if v in versions:
            msg = f"dataset {name}@v{v} already exists; versions are immutable"
            raise FileExistsError(msg)
        parent: Dataset | None = None
        if versions and extend_previous:
            parent = self.load(name, versions[-1])
        base_cases = list(parent.cases) if parent else []
        kept, rejected = find_near_duplicates(cases, base_cases, threshold=dedup_threshold)
        all_cases = base_cases + kept
        slices = {
            t: len(cs)
            for t, cs in Dataset(manifest=_placeholder(name, v), cases=all_cases).slices().items()
        }
        entries = list(parent.manifest.changelog) if parent else []
        entries.append(
            f"v{v} ({now}): +{len(kept)} cases from review, "
            f"{len(rejected)} near-duplicates rejected" + (f"; {changelog}" if changelog else "")
        )
        manifest = DatasetManifest(
            name=name,
            version=v,
            content_hash=content_hash(all_cases),
            n_cases=len(all_cases),
            created=now,
            parent_version=parent.manifest.version if parent else None,
            parent_hash=parent.manifest.content_hash if parent else None,
            changelog=entries,
            slices=slices,
            duplicates_rejected=rejected,
        )
        d = self._dir(name)
        d.mkdir(parents=True, exist_ok=True)
        with (d / f"v{v}.jsonl").open("w", encoding="utf-8") as fh:
            for case in all_cases:
                fh.write(canonical_line(case) + "\n")
        (d / f"v{v}.manifest.json").write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return Dataset(manifest=manifest, cases=all_cases)

    def diff(self, name: str, v_a: int, v_b: int) -> dict[str, Any]:
        a, b = self.load(name, v_a), self.load(name, v_b)
        ids_a = {c.id: c for c in a.cases}
        ids_b = {c.id: c for c in b.cases}
        added = sorted(set(ids_b) - set(ids_a))
        removed = sorted(set(ids_a) - set(ids_b))
        changed = sorted(
            i
            for i in set(ids_a) & set(ids_b)
            if canonical_line(ids_a[i]) != canonical_line(ids_b[i])
        )
        return {
            "name": name,
            "from": {"version": v_a, "hash": a.manifest.content_hash, "n": len(a.cases)},
            "to": {"version": v_b, "hash": b.manifest.content_hash, "n": len(b.cases)},
            "added": added,
            "removed": removed,
            "changed": changed,
            "slices_from": a.manifest.slices,
            "slices_to": b.manifest.slices,
        }


def _placeholder(name: str, version: int) -> DatasetManifest:
    return DatasetManifest(name=name, version=version, content_hash="", n_cases=0, created="")
