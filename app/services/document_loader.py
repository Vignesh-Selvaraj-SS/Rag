import re
from pathlib import Path

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf"}

PAGE_SEPARATOR = "\n"


class DocumentLoader:
    """
    Service responsible for reading documents from disk.

    Pages are kept separate so a citation can name a page number,
    not just a file. Markdown and text files become a single page.
    """

    def load_file(self, path: Path) -> dict | None:

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return None

        if path.suffix.lower() == ".pdf":
            pages = self._read_pdf(path)
        else:
            pages = self._read_text(path)

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

    def load_directory(self, directory: Path) -> list[dict]:

        documents = []

        for path in sorted(directory.rglob("*")):

            if not path.is_file():
                continue

            document = self.load_file(path)

            if document is not None:
                documents.append(document)

        return documents

    @staticmethod
    def _read_text(path: Path) -> list[dict]:

        text = path.read_text(
            encoding="utf-8",
            errors="ignore"
        )

        return [
            {
                "page": 1,
                "text": text.replace("\r\n", "\n").strip(),
            }
        ]

    @staticmethod
    def _read_pdf(path: Path) -> list[dict]:

        from pypdf import PdfReader

        reader = PdfReader(str(path))

        pages = []

        for number, page in enumerate(reader.pages, start=1):

            text = page.extract_text() or ""

            pages.append(
                {
                    "page": number,
                    "text": text.replace("\r\n", "\n").strip(),
                }
            )

        return pages
