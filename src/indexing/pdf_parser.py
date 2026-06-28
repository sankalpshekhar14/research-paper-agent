"""Convert a PDF to markdown and split it into section-based chunks."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pymupdf4llm

# Sections longer than this token estimate get sub-chunked.
_MAX_CHUNK_TOKENS = 1500
# Overlap in tokens between sub-chunks of a long section.
_OVERLAP_TOKENS = 150
# Rough chars-per-token estimate (avoids importing a tokenizer).
_CHARS_PER_TOKEN = 4


@dataclass
class PaperChunk:
    paper_id: str
    section_title: str
    chunk_index: int          # position within the paper (0-based)
    text: str
    metadata: dict = field(default_factory=dict)


def pdf_to_markdown(pdf_path: str | Path) -> str:
    """Return the full markdown string for a PDF using pymupdf4llm."""
    return pymupdf4llm.to_markdown(str(pdf_path))


def _split_into_sections(markdown: str) -> List[tuple[str, str]]:
    """Return list of (heading, body) pairs split on markdown headings."""
    # Match any heading level (# / ## / ###)
    pattern = re.compile(r"^(#{1,3} .+)$", re.MULTILINE)
    matches = list(pattern.finditer(markdown))

    if not matches:
        # No headings found — treat the whole document as one section.
        return [("Document", markdown.strip())]

    sections: List[tuple[str, str]] = []

    # Text before the first heading (preamble / title block)
    preamble = markdown[: matches[0].start()].strip()
    if preamble:
        sections.append(("Preamble", preamble))

    for i, match in enumerate(matches):
        heading = match.group(0).lstrip("#").strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        if body:
            sections.append((heading, body))

    return sections


def _sub_chunk(text: str, max_tokens: int, overlap_tokens: int) -> List[str]:
    """Split a long text into overlapping windows by character estimate."""
    max_chars = max_tokens * _CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * _CHARS_PER_TOKEN

    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap_chars

    return chunks


def chunk_paper(
    pdf_path: str | Path,
    paper_id: str,
    extra_metadata: dict | None = None,
) -> List[PaperChunk]:
    """
    Parse a PDF and return a flat list of PaperChunk objects.

    Each section becomes at least one chunk; sections longer than
    _MAX_CHUNK_TOKENS are split further with overlap.
    """
    markdown = pdf_to_markdown(pdf_path)
    sections = _split_into_sections(markdown)

    meta = extra_metadata or {}
    chunks: List[PaperChunk] = []
    chunk_idx = 0

    for section_title, body in sections:
        sub_texts = _sub_chunk(body, _MAX_CHUNK_TOKENS, _OVERLAP_TOKENS)
        for sub in sub_texts:
            chunks.append(
                PaperChunk(
                    paper_id=paper_id,
                    section_title=section_title,
                    chunk_index=chunk_idx,
                    text=sub,
                    metadata={**meta, "section": section_title},
                )
            )
            chunk_idx += 1

    return chunks
