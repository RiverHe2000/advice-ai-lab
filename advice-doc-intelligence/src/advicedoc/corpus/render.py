"""Render a ``LayoutDocument`` to a real PDF with reportlab. ``rl_config.invariant`` pins the
creation date and document id so the same layout renders to byte-identical bytes."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from advicedoc.corpus.layout import Heading, LayoutDocument, Para, Spacer, Style, TableBlock


def _styles(style: Style) -> dict[str, Any]:
    from reportlab.lib.styles import ParagraphStyle

    bold = {"Helvetica": "Helvetica-Bold", "Times-Roman": "Times-Bold", "Courier": "Courier-Bold"}[
        style.font
    ]
    size = style.body_size
    return {
        "title": ParagraphStyle(
            "title", fontName=bold, fontSize=size + 8, leading=size + 12, spaceAfter=10
        ),
        "h1": ParagraphStyle(
            "h1", fontName=bold, fontSize=size + 3, leading=size + 6, spaceBefore=8, spaceAfter=5
        ),
        "body": ParagraphStyle(
            "body", fontName=style.font, fontSize=size, leading=size * 1.35, spaceAfter=5
        ),
        "small": ParagraphStyle(
            "small",
            fontName=style.font,
            fontSize=size - 1.5,
            leading=(size - 1.5) * 1.3,
            spaceAfter=4,
        ),
        "label": ParagraphStyle(
            "label", fontName=bold, fontSize=size, leading=size * 1.35, spaceAfter=3
        ),
        "bullet": ParagraphStyle(
            "bullet",
            fontName=style.font,
            fontSize=size,
            leading=size * 1.35,
            leftIndent=14,
            bulletIndent=4,
            spaceAfter=4,
        ),
        "cell": ParagraphStyle(
            "cell", fontName=style.font, fontSize=size - 1, leading=(size - 1) * 1.25
        ),
        "cellhead": ParagraphStyle(
            "cellhead", fontName=bold, fontSize=size - 1, leading=(size - 1) * 1.25
        ),
    }


def column_widths(
    rows: list[list[str]], width: float, font: str, size: float, *, padding: float = 8.0
) -> list[float]:
    """Column widths from real font metrics: every column gets at least its widest single
    word (so words are never split across lines), and the remaining width is shared in
    proportion to the widest full cell."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    n_cols = max(len(r) for r in rows)
    min_w: list[float] = []
    pref_w: list[float] = []
    for c in range(n_cols):
        cells = [r[c] for r in rows if c < len(r)]
        words = [w for cell in cells for w in cell.split()] or [""]
        min_w.append(max(stringWidth(w, font, size) for w in words) + padding)
        pref_w.append(max(stringWidth(cell, font, size) for cell in cells) + padding)
    if sum(pref_w) <= width:
        extra = (width - sum(pref_w)) / n_cols
        return [w + extra for w in pref_w]
    if sum(min_w) >= width:
        scale = width / sum(min_w)
        return [w * scale for w in min_w]
    slack = [p - m for p, m in zip(pref_w, min_w, strict=True)]
    share = (width - sum(min_w)) / max(1e-9, sum(slack))
    return [m + s * share for m, s in zip(min_w, slack, strict=True)]


def render_pdf(layout: LayoutDocument, path: str | Path, *, title: str = "") -> None:
    from reportlab import rl_config
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Table,
        TableStyle,
    )
    from reportlab.platypus import (
        Spacer as RLSpacer,
    )

    rl_config.invariant = 1
    styles = _styles(layout.style)
    width = A4[0] - 40 * mm

    def decorate(canvas: Any, _doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(layout.style.font, 8)
        canvas.drawString(20 * mm, A4[1] - 12 * mm, layout.header)
        page_no = layout.style.page_numbers.format(n=canvas.getPageNumber())
        canvas.drawString(20 * mm, 10 * mm, f"{layout.footer}  {page_no}")
        canvas.restoreState()

    flow: list[Any] = []
    for i, blocks in enumerate(layout.pages):
        if i > 0:
            flow.append(PageBreak())
        for b in blocks:
            if isinstance(b, Heading):
                flow.append(Paragraph(escape(b.text), styles["title" if b.level == 0 else "h1"]))
            elif isinstance(b, Para):
                if b.style == "bullet":
                    flow.append(Paragraph(escape(b.text), styles["bullet"], bulletText="-"))
                else:
                    flow.append(Paragraph(escape(b.text), styles[b.style]))
            elif isinstance(b, TableBlock):
                rows = [list(r) for r in b.rows]
                col_widths = column_widths(
                    rows, width, layout.style.font, layout.style.body_size - 1
                )
                data = [
                    [
                        Paragraph(escape(cell), styles["cellhead" if ri == 0 else "cell"])
                        for cell in r
                    ]
                    for ri, r in enumerate(rows)
                ]
                table = Table(data, colWidths=col_widths, repeatRows=1)
                table.setStyle(
                    TableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e6e6")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 4),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ]
                    )
                )
                flow.append(table)
                flow.append(RLSpacer(1, 6))
            elif isinstance(b, Spacer):
                flow.append(RLSpacer(1, b.height))
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=title or layout.doc_id,
        author="Northshore Financial Advice Pty Ltd",
        invariant=1,
    )
    doc.build(flow, onFirstPage=decorate, onLaterPages=decorate)
