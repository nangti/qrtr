"""QR generation via segno. Error-correction level H and a proper quiet zone by
default — the two things that make printed QRs survive logos and rough print
(docs/DESIGN.md risk #10). SVG is the print-shop format; PNG for quick checks."""
import io

import segno


def qr_png(content: str, scale: int = 12) -> bytes:
    q = segno.make(content, error="h")
    out = io.BytesIO()
    q.save(out, kind="png", scale=scale, border=4)
    return out.getvalue()


def qr_svg(content: str) -> bytes:
    q = segno.make(content, error="h")
    out = io.BytesIO()
    q.save(out, kind="svg", border=4, xmldecl=False, svgclass=None, lineclass=None)
    return out.getvalue()
