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


def create_chunks(document: dict) -> list[dict]:
    """
    Turn one loaded document into chunks - one chunk per detected
    section, from one heading to the next. No size budget, no
    merging/splitting, no overlap - a chunk is exactly what the
    document's own structure says it is.
    """

    full_text = document["text"]

    # Map each page to the character offset where it starts, so a
    # chunk's position in full_text can be traced back to a page number.
    offsets = []
    cursor = 0
    for page in document["pages"]:
        offsets.append((cursor, page["page"]))
        cursor += len(page["text"]) + len(PAGE_SEPARATOR)
    starts = [offset for offset, _ in offsets]

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

        # Resolve this chunk's character span to the page(s) it spans.
        first = max(bisect_right(starts, start) - 1, 0)
        last = max(bisect_right(starts, max(start, end - 1)) - 1, 0)
        page_start, page_end = offsets[first][1], offsets[last][1]

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
