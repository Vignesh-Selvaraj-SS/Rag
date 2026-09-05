import re
from pathlib import Path

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf"}

PAGE_SEPARATOR = "\n"

# Pages are kept separate so a citation can name a page number, not
# just a file. Markdown and text files become a single page.


def load_file(path: Path) -> dict | None:

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None

    if path.suffix.lower() == ".pdf":
        pages = _read_pdf(path)

    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
        pages = [{"page": 1, "text": text.replace("\r\n", "\n").strip()}]

    pages = [page for page in pages if page["text"].strip()]

    if not pages:
        return None

    full_text = PAGE_SEPARATOR.join(page["text"] for page in pages)

    heading = re.search(r"^#\s+(.+)$", full_text, re.MULTILINE)

    return {
        "source": path.name,
        "title": heading.group(1).strip() if heading else path.stem,
        "pages": pages,
        "text": full_text,
        "word_count": len(full_text.split()),
    }


def _read_pdf(path: Path) -> list[dict]:
    """
    Read a PDF page by page: extract normal text and tables with
    pdfplumber, OCR any embedded images (a diagram, a stamped form
    photo) with EasyOCR, and - only if a page still has nothing after
    all of that - OCR the whole rendered page as a last resort, which
    is what a fully scanned page with no text layer at all needs.
    """

    import pdfplumber
    import pymupdf

    from app.services.pdf_ocr import ocr_image_bytes, table_to_text

    pages = []

    with pdfplumber.open(str(path)) as pdf, pymupdf.open(str(path)) as image_doc:

        for number, (text_page, image_page) in enumerate(zip(pdf.pages, image_doc), start=1):

            parts = []

            page_text = text_page.extract_text() or ""
            if page_text.strip():
                parts.append(page_text)

            for table in text_page.extract_tables():
                parts.append(table_to_text(table))

            for image_info in image_page.get_images(full=True):

                base_image = image_doc.extract_image(image_info[0])

                # Skip tiny decorative icons/bullets - not worth OCR
                # time and not usually text-bearing.
                if base_image["width"] < 30 or base_image["height"] < 30:
                    continue

                image_text = ocr_image_bytes(base_image["image"])

                if image_text.strip():
                    parts.append(image_text)

            text = "\n\n".join(part for part in parts if part.strip())

            if not text.strip():
                pixmap = image_page.get_pixmap(dpi=200)
                text = ocr_image_bytes(pixmap.tobytes("png"))

            pages.append({"page": number, "text": text.replace("\r\n", "\n").strip()})

    return pages


def load_directory(directory: Path) -> list[dict]:

    documents = []

    for path in sorted(directory.rglob("*")):

        if not path.is_file():
            continue

        document = load_file(path)

        if document is not None:
            documents.append(document)

    return documents
