import re
from bisect import bisect_right

from app.services.document_loader import PAGE_SEPARATOR

# Headings come in three families. Policy PDFs have no markdown at all,
# so matching only "#" would collapse a real document into one section.
#   markdown   "## 3. Severity tiers"
#   keyword    "SECTION 4 - Exclusions", "ARTICLE II"
#   numbered   "4.1 Loss Settlement"
#
# The numbered form requires a dot: a bare "1." is a list item, and
# treating list items as headings shatters the document.
HEADING_PATTERN = re.compile(
    r"""^(?:
        \#{1,6}\s+(?P<md>\S.*)
      | (?P<keyword>(?:SECTION|Section|ARTICLE|Article|CLAUSE|Clause|PART|Part
                     |SCHEDULE|Schedule|ENDORSEMENT|Endorsement|APPENDIX|Appendix)
                    \s+[\w.\-]+[^\n]*)
      | (?P<numbered>\d+(?:\.\d+)+\s+\S[^\n]*)
    )\s*$""",
    re.MULTILINE | re.VERBOSE,
)

# Fixed-size chunking parameters - only meaningful for the "fixed_size"
# strategy below. Overlap exists so an idea sitting right at a window
# boundary still appears whole in at least one chunk.
FIXED_CHUNK_WORDS = 300
FIXED_CHUNK_OVERLAP_WORDS = 50


def _build_page_offsets(pages: list[dict]) -> list[tuple[int, int]]:
    """
    Map each page to the character offset where it starts, so a
    chunk's position in the flattened document text can be traced
    back to a page number. Shared by both chunking strategies below.
    """

    offsets = []
    cursor = 0

    for page in pages:
        offsets.append((cursor, page["page"]))
        cursor += len(page["text"]) + len(PAGE_SEPARATOR)

    return offsets


def _resolve_page_span(
    start: int,
    end: int,
    offsets: list[tuple[int, int]]
) -> tuple[int, int]:
    """
    Resolve a character range to the page numbers it spans.
    """

    starts = [offset for offset, _ in offsets]

    first = max(bisect_right(starts, start) - 1, 0)
    last = max(bisect_right(starts, max(start, end - 1)) - 1, 0)

    return offsets[first][1], offsets[last][1]


def create_chunks(document: dict) -> list[dict]:
    """
    Heading-based chunking: one chunk per detected section, from one
    heading to the next. No size budget, no merging/splitting, no
    overlap - a chunk is exactly what the document's own structure
    says it is.
    """

    full_text = document["text"]

    offsets = _build_page_offsets(document["pages"])

    matches = list(HEADING_PATTERN.finditer(full_text))

    if not matches:
        sections = [{"heading": "Overview", "text": full_text.strip(), "start": 0}]

    else:
        sections = []

        if matches[0].start() > 0:
            preamble = full_text[:matches[0].start()].strip()
            if preamble:
                sections.append({"heading": "Overview", "text": preamble, "start": 0})

        for index, match in enumerate(matches):

            heading = (
                match.group("md")
                or match.group("keyword")
                or match.group("numbered")
                or "Section"
            ).strip()

            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(full_text)
            body = full_text[start:end].strip()

            if body:
                sections.append({"heading": heading, "text": body, "start": start})

    chunks = []

    for index, section in enumerate(sections):

        start = section["start"]
        end = start + len(section["text"])

        page_start, page_end = _resolve_page_span(start, end, offsets)

        chunks.append(
            {
                "chunk_id": f"{document['source']}::{index}",
                "index": index,
                "text": section["text"],
                "source": document["source"],
                "heading": section["heading"],
                "page_start": page_start,
                "page_end": page_end,
                "n_words": len(section["text"].split()),
            }
        )

    return chunks


def create_chunks_for_all(documents: list[dict]) -> list[dict]:

    chunks = []

    for document in documents:
        chunks.extend(create_chunks(document))

    return chunks


def create_fixed_size_chunks(document: dict) -> list[dict]:
    """
    Fixed-size chunking: split into overlapping windows of
    FIXED_CHUNK_WORDS words, ignoring document structure entirely.
    The classic RAG default - kept as a real, switchable alternative
    to the heading-based strategy above, not the default here because
    it was measured to perform worse on this corpus (see README.md).
    """

    full_text = document["text"]

    offsets = _build_page_offsets(document["pages"])

    words = list(re.finditer(r"\S+", full_text))

    if not words:
        return []

    step = FIXED_CHUNK_WORDS - FIXED_CHUNK_OVERLAP_WORDS

    chunks = []
    index = 0
    window_start = 0

    while window_start < len(words):

        window_end = min(window_start + FIXED_CHUNK_WORDS, len(words))

        start = words[window_start].start()
        end = words[window_end - 1].end()

        page_start, page_end = _resolve_page_span(start, end, offsets)

        chunks.append(
            {
                "chunk_id": f"{document['source']}::{index}",
                "index": index,
                "text": full_text[start:end],
                "source": document["source"],
                "heading": f"words {window_start + 1}-{window_end}",
                "page_start": page_start,
                "page_end": page_end,
                "n_words": window_end - window_start,
            }
        )

        index += 1

        if window_end == len(words):
            break

        window_start += step

    return chunks


def create_fixed_size_chunks_for_all(documents: list[dict]) -> list[dict]:

    chunks = []

    for document in documents:
        chunks.extend(create_fixed_size_chunks(document))

    return chunks


# Registry so the ingest pipeline can pick a strategy by name (e.g.
# from a UI dropdown) without importing chunking internals directly.
CHUNK_STRATEGIES = {
    "heading": create_chunks_for_all,
    "fixed_size": create_fixed_size_chunks_for_all,
}


def embed_text(chunk: dict) -> str:
    """
    What actually gets turned into a vector.

    The file and heading are prepended so a chunk reading "a separate
    deductible of $500 applies" carries what it is a deductible for.
    The stored text stays clean for display.
    """

    return f"{chunk['source']} > {chunk['heading']}\n\n{chunk['text']}"


def page_label(page_start: int, page_end: int) -> str:

    if page_start == page_end:
        return f"p.{page_start}"

    return f"pp.{page_start}-{page_end}"
