"""Corpus orchestration: deterministic document ids, one seeded RNG per document, gold JSON,
holdings snapshots, PDFs (or JSON text documents for tests) and a ``manifest.jsonl``."""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from advicedoc.corpus.common import doc_rng
from advicedoc.corpus.holdings import simulate_holdings
from advicedoc.corpus.layout import LayoutDocument, to_document
from advicedoc.corpus.products import DEFAULT_MASTER, ProductMaster
from advicedoc.corpus.render import render_pdf
from advicedoc.corpus.soa import build_facts, build_layout
from advicedoc.corpus.templates import TEMPLATES
from advicedoc.identifiers import generate_abn
from advicedoc.ingest import Document, document_from_json, document_to_json, load_pdf
from advicedoc.schema import DOC_TYPES, DocMetadata, DocType, GoldRecord, HoldingsSnapshot


@dataclass(frozen=True, slots=True)
class CorpusSpec:
    n_per_type: int = 60
    n_soa: int = 120
    seed: int = 7
    p_discrepancy: float = 0.35


@dataclass(slots=True)
class GeneratedDocument:
    gold: GoldRecord
    layout: LayoutDocument
    holdings: HoldingsSnapshot | None = None

    @property
    def document(self) -> Document:
        return to_document(self.layout)


def licensee_abn(seed: int) -> str:
    return generate_abn(random.Random(f"{seed}:licensee"))


def generate_documents(
    spec: CorpusSpec, *, master: ProductMaster = DEFAULT_MASTER
) -> Iterator[GeneratedDocument]:
    abn = licensee_abn(spec.seed)
    for i in range(1, spec.n_soa + 1):
        doc_id = f"soa_{i:04d}"
        rng = doc_rng(spec.seed, doc_id)
        facts = build_facts(doc_id, rng, abn=abn, master=master)
        layout = build_layout(facts, rng)
        holdings = simulate_holdings(
            facts.gold, doc_id, rng, p_discrepancy=spec.p_discrepancy, master=master
        )
        metadata = DocMetadata(
            doc_type="soa",
            client_names=list(facts.gold.client_names),
            adviser_name=facts.gold.adviser_name,
            document_date=facts.gold.advice_date,
        )
        gold = GoldRecord(
            doc_id=doc_id,
            doc_type="soa",
            variant=facts.style.variant,
            n_pages=layout.n_pages,
            metadata=metadata,
            soa=facts.gold,
            available_funds=facts.available_funds,
            pdf_path=f"soa/{doc_id}.pdf",
            holdings_path=f"soa/{doc_id}.holdings.json",
        )
        yield GeneratedDocument(gold=gold, layout=layout, holdings=holdings)
    for doc_type in DOC_TYPES:
        if doc_type == "soa":
            continue
        template = TEMPLATES[doc_type]
        for i in range(1, spec.n_per_type + 1):
            doc_id = f"{doc_type}_{i:04d}"
            rng = doc_rng(spec.seed, doc_id)
            metadata, layout = template(doc_id, rng, abn, master)
            gold = GoldRecord(
                doc_id=doc_id,
                doc_type=doc_type,
                variant=layout.style.variant,
                n_pages=layout.n_pages,
                metadata=metadata,
                pdf_path=f"{doc_type}/{doc_id}.pdf",
            )
            yield GeneratedDocument(gold=gold, layout=layout)


def write_corpus(
    spec: CorpusSpec,
    out_dir: str | Path,
    *,
    render: bool = True,
    master: ProductMaster = DEFAULT_MASTER,
    progress: Callable[[str], None] | None = None,
) -> list[GoldRecord]:
    """Write ``<out>/<type>/<id>.pdf`` (or ``.doc.json`` when ``render`` is False),
    ``<id>.gold.json``, ``<id>.holdings.json`` for SoAs, and ``manifest.jsonl``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    records: list[GoldRecord] = []
    for gen in generate_documents(spec, master=master):
        gold = gen.gold
        type_dir = out / gold.doc_type
        type_dir.mkdir(parents=True, exist_ok=True)
        if render:
            render_pdf(gen.layout, type_dir / f"{gold.doc_id}.pdf")
        else:
            gold = gold.model_copy(update={"pdf_path": f"{gold.doc_type}/{gold.doc_id}.doc.json"})
            (type_dir / f"{gold.doc_id}.doc.json").write_text(
                document_to_json(gen.document), encoding="utf-8"
            )
        (type_dir / f"{gold.doc_id}.gold.json").write_text(
            gold.model_dump_json(indent=2), encoding="utf-8"
        )
        if gen.holdings is not None:
            (type_dir / f"{gold.doc_id}.holdings.json").write_text(
                gen.holdings.model_dump_json(indent=2), encoding="utf-8"
            )
        records.append(gold)
        if progress is not None:
            progress(gold.doc_id)
    with (out / "manifest.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(r.model_dump_json() + "\n")
    (out / "spec.json").write_text(
        json.dumps(
            {
                "n_per_type": spec.n_per_type,
                "n_soa": spec.n_soa,
                "seed": spec.seed,
                "p_discrepancy": spec.p_discrepancy,
                "rendered_pdf": render,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return records


def load_manifest(corpus_dir: str | Path) -> list[GoldRecord]:
    path = Path(corpus_dir) / "manifest.jsonl"
    return [
        GoldRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_holdings(corpus_dir: str | Path, record: GoldRecord) -> HoldingsSnapshot | None:
    if record.holdings_path is None:
        return None
    return HoldingsSnapshot.model_validate_json(
        (Path(corpus_dir) / record.holdings_path).read_text(encoding="utf-8")
    )


def load_corpus_document(corpus_dir: str | Path, record: GoldRecord) -> Document:
    path = Path(corpus_dir) / record.pdf_path
    if path.suffix == ".json":
        return document_from_json(path.read_text(encoding="utf-8"), source=record.doc_id)
    return load_pdf(path)


def records_of_type(records: list[GoldRecord], doc_type: DocType) -> list[GoldRecord]:
    return [r for r in records if r.doc_type == doc_type]
