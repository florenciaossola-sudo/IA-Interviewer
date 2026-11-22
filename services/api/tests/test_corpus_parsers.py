from __future__ import annotations

from io import BytesIO

from docx import Document

from services.api.corpus import _extract_text


def _text_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode("ascii"))
        result.extend(body + b"\nendobj\n")
    xref_offset = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010} 00000 n \n".encode("ascii"))
    result.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF".encode("ascii")
    )
    return bytes(result)


def test_extracts_markdown_text() -> None:
    assert _extract_text("guide.md", b"Markdown corpus text") == "Markdown corpus text"


def test_extracts_docx_paragraphs_and_table_content() -> None:
    document = Document()
    document.add_paragraph("DOCX paragraph")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "DOCX table value"
    buffer = BytesIO()
    document.save(buffer)

    extracted = _extract_text("guide.docx", buffer.getvalue())

    assert "DOCX paragraph" in extracted
    assert "DOCX table value" in extracted


def test_extracts_pdf_text() -> None:
    extracted = _extract_text("guide.pdf", _text_pdf("PDF corpus text"))

    assert "PDF corpus text" in extracted