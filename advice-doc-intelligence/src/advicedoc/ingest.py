"""PDF → ``Document(pages=[Page(number, text, lines, tables)])``.

Text PDFs are read with ``pdfplumber``: words are clustered into lines by their vertical
position and tables come from ``extract_tables``. Scanned documents would enter through an
OCR layer (Google Document AI / Vision) that produces the same ``Document`` — the pipeline is
deliberately independent of which OCR produced the text, and ``apply_noise`` injects seeded
OCR-like corruptions so robustness can be measured without real OCR.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Table = list[list[str]]


@dataclass(slots=True)
class Page:
    number: int
    lines: list[str]
    tables: list[Table] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass(slots=True)
class Document:
    source: str
    pages: list[Page]

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    @property
    def n_tables(self) -> int:
        return sum(len(p.tables) for p in self.pages)

    @property
    def tables(self) -> list[Table]:
        return [t for p in self.pages for t in p.tables]

    def head_text(self, n_pages: int = 2) -> str:
        return "\n".join(p.text for p in self.pages[:n_pages])

    @property
    def lines(self) -> list[str]:
        return [line for p in self.pages for line in p.lines]

    @classmethod
    def from_text(cls, text: str, *, source: str = "text") -> Document:
        """Pages are separated by form feeds; lines by newlines. No tables."""
        pages = [
            Page(number=i + 1, lines=[ln.rstrip() for ln in chunk.split("\n")])
            for i, chunk in enumerate(text.split("\f"))
        ]
        return cls(source=source, pages=pages)

    @classmethod
    def from_pages(
        cls, pages: Sequence[tuple[Sequence[str], Sequence[Table]]], *, source: str = "text"
    ) -> Document:
        return cls(
            source=source,
            pages=[
                Page(number=i + 1, lines=list(lines), tables=[list(map(list, t)) for t in tables])
                for i, (lines, tables) in enumerate(pages)
            ],
        )


def lines_from_words(words: Sequence[dict[str, Any]], *, y_tol: float = 3.0) -> list[str]:
    """Cluster pdfplumber words into lines by their ``top`` coordinate."""
    ordered = sorted(words, key=lambda w: (float(w["top"]), float(w["x0"])))
    lines: list[list[dict[str, Any]]] = []
    for w in ordered:
        if lines and abs(float(w["top"]) - float(lines[-1][0]["top"])) <= y_tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    out: list[str] = []
    for group in lines:
        group.sort(key=lambda w: float(w["x0"]))
        out.append(" ".join(str(w["text"]) for w in group))
    return out


def _clean_table(table: Sequence[Sequence[str | None]]) -> Table:
    return [[(c or "").replace("\n", " ").strip() for c in row] for row in table]


def load_pdf(path: str | Path) -> Document:
    import pdfplumber

    pages: list[Page] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            tables = [_clean_table(t) for t in page.extract_tables()]
            tables = [t for t in tables if len(t) >= 2 and any(any(row) for row in t)]
            pages.append(Page(number=i + 1, lines=lines_from_words(words), tables=tables))
    return Document(source=Path(path).stem, pages=pages)


def document_to_json(doc: Document) -> str:
    return json.dumps(
        {
            "source": doc.source,
            "pages": [{"lines": p.lines, "tables": p.tables} for p in doc.pages],
        },
        ensure_ascii=False,
    )


def document_from_json(text: str, *, source: str | None = None) -> Document:
    data = json.loads(text)
    return Document.from_pages(
        [(p["lines"], p["tables"]) for p in data["pages"]], source=source or str(data["source"])
    )


def load_document(path: str | Path) -> Document:
    """PDF, a JSON document dump (``*.doc.json``) or plain text (form feeds separate pages)."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(p)
    if suffix == ".json":
        stem = p.name[: -len(".doc.json")] if p.name.endswith(".doc.json") else p.stem
        return document_from_json(p.read_text(encoding="utf-8"), source=stem)
    return Document.from_text(p.read_text(encoding="utf-8"), source=p.stem)


def load_many(
    paths: Sequence[Path],
    *,
    cache_path: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[Document]:
    """Load documents with an optional JSON cache keyed by path and modification time, so a
    corpus of PDFs is parsed once per evaluation session."""
    cache: dict[str, Any] = {}
    if cache_path is not None and cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    docs: list[Document] = []
    dirty = False
    for i, p in enumerate(paths):
        key = f"{p.resolve()}::{p.stat().st_mtime_ns}"
        if key in cache:
            docs.append(document_from_json(cache[key]))
        else:
            doc = load_document(p)
            cache[key] = document_to_json(doc)
            docs.append(doc)
            dirty = True
        if progress is not None:
            progress(i + 1, len(paths))
    if cache_path is not None and dirty:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return docs


# ----- OCR-like noise -----------------------------------------------------------------------

CONFUSIONS: dict[str, str] = {
    "0": "O",
    "O": "0",
    "1": "l",
    "l": "1",
    "5": "S",
    "S": "5",
    "8": "B",
    "B": "8",
    "I": "l",
    "e": "c",
    "a": "o",
    "n": "r",
}


def _noisy_text(text: str, rate: float, rng: random.Random) -> str:
    out: list[str] = []
    for ch in text:
        if rng.random() >= rate:
            out.append(ch)
        elif ch == " ":
            continue  # dropped space
        elif ch in CONFUSIONS:
            out.append(CONFUSIONS[ch])
        else:
            out.append(ch)
    return "".join(out)


def apply_noise(doc: Document, rate: float, *, seed: int = 0) -> Document:
    """Corrupt each character independently with probability ``rate``: digit/letter
    confusions (``0/O``, ``1/l``, ``5/S``, ``8/B`` …) and dropped spaces. Seeded, so the same
    document and seed always give the same corruption; the expected fraction of touched
    characters is ``rate``."""
    if rate <= 0:
        return doc
    rng = random.Random(f"{seed}:{doc.source}")
    pages = [
        Page(
            number=p.number,
            lines=[_noisy_text(ln, rate, rng) for ln in p.lines],
            tables=[[[_noisy_text(c, rate, rng) for c in row] for row in t] for t in p.tables],
        )
        for p in doc.pages
    ]
    return Document(source=doc.source, pages=pages)
