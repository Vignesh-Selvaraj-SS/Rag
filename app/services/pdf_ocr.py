import sys

# Cached across calls - EasyOCR loads real neural network weights,
# same reasoning as the embedding model cache in embedding_service.py.
_reader = None


def get_ocr_reader():
    """
    Load the OCR model once. The first call on a fresh machine
    downloads the weights.
    """

    global _reader

    if _reader is None:

        # EasyOCR's first-run model-download progress bar prints a
        # Unicode block character that crashes on Windows' default
        # console encoding (cp1252) before the download finishes.
        # Reconfiguring stdout/stderr makes this robust regardless of
        # how the app was launched (uvicorn, ingest.py, a plain shell).
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

        import easyocr

        _reader = easyocr.Reader(["en"], gpu=False)

    return _reader


def ocr_image_bytes(image_bytes: bytes) -> str:
    """OCR raw image bytes (PNG/JPEG/etc.) and return the recognised text."""

    results = get_ocr_reader().readtext(image_bytes, detail=0)

    return " ".join(results)


def table_to_text(table: list[list]) -> str:
    """
    Render a pdfplumber table (a list of rows, each a list of cell
    strings) as a simple markdown-style table, so it reads naturally
    once folded into a chunk's plain text.
    """

    rows = [
        "| " + " | ".join(cell or "" for cell in row) + " |"
        for row in table
    ]

    return "\n".join(rows)
