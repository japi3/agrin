"""
Cutting an article into passages that can be quoted back.

Retrieval returns whatever unit you indexed, so the unit has to be one a
farmer could be read out loud without it being wrong. That rules out both
extremes. A whole article is too much to quote and dilutes the embedding
until a page about nine crops matches a question about none of them. A single
sentence is small enough to lose the thing it depends on -- "spray again
after fifteen days" is not advice until you know what the spray is.

So the target here is a passage: a few paragraphs, around a thousand
characters, cut at a boundary the author already put there.

Three rules make the passages safe rather than merely well-sized.

**Every chunk carries its heading path.** The text that gets embedded is
prefixed with the article title and the headings above the passage -- "Wheat >
Diseases > Yellow rust" -- so a paragraph that only says "spray at 0.1%"
still matches a question about rust in wheat, and still reads correctly when
shown. The prefix is stored separately from the passage so the answer can
cite the section without the prefix being mistaken for the source's words.

**A table row is never split, and a table's header follows it.** The numbers
on these pages live in tables. If a dosage table runs past the chunk size,
the continuation keeps the header row, because a row that reads
"Wheat | 100 kg | 25 kg" is meaningless once "Crop | Nitrogen | Phosphorus"
has been left in the previous chunk.

**Passages overlap by one block.** A boundary always falls somewhere, and the
sentence that explains a recommendation is often the one just before it.
Repeating the last block costs a little storage and avoids losing the join.

None of this is tuned against a benchmark -- there isn't an Indian
agricultural-advisory retrieval set to tune against. The sizes below are
chosen to be defensible and are stated as constants so they can be argued
with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .extract import Article, Block

# Roughly 150-200 words: long enough to hold a recommendation and its reason,
# short enough to read aloud and to keep one subject per vector.
TARGET_CHARS = 1100

# Below this a passage is usually a stray heading or a one-line caption. It is
# merged forward rather than embedded on its own, where it would be a
# high-scoring match with nothing useful in it.
MIN_CHARS = 200

# A single block longer than this is split on sentence boundaries. Rare -- a
# few pages have one enormous paragraph.
MAX_CHARS = 1800


@dataclass
class Chunk:
    """One retrievable passage, with the provenance to cite it."""
    text: str
    title: str
    url: str
    language: str
    section: list[str] = field(default_factory=list)
    updated: str | None = None
    author: str | None = None

    @property
    def heading(self) -> str:
        """The article and section this passage came from, for display."""
        return " > ".join([self.title, *self.section])

    def for_embedding(self) -> str:
        """What actually gets vectorised.

        The heading path goes in because a passage is retrieved for a
        question about its subject, and the subject is usually named in the
        heading rather than in the paragraph.
        """
        return f"{self.heading}\n\n{self.text}"

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "title": self.title,
            "url": self.url,
            "language": self.language,
            "section": self.section,
            "updated": self.updated,
            "author": self.author,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        return cls(
            text=d["text"], title=d["title"], url=d["url"],
            language=d.get("language", "en"), section=d.get("section") or [],
            updated=d.get("updated"), author=d.get("author"),
        )


_SENTENCE = re.compile(r"(?<=[.!?।])\s+")


def _split_long(text: str) -> list[str]:
    """Break one over-long block at sentence ends, Devanagari danda included."""
    parts, current = [], ""
    for sentence in _SENTENCE.split(text):
        if current and len(current) + len(sentence) + 1 > TARGET_CHARS:
            parts.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current.strip():
        parts.append(current.strip())
    return parts or [text]


def chunk_article(article: Article) -> list[Chunk]:
    """Cut one article into passages, each knowing where it came from."""
    chunks: list[Chunk] = []
    section: list[str] = []
    levels: list[int] = []

    lines: list[str] = []          # blocks in the passage being built
    table_header: str | None = None
    carried: str | None = None     # last block of the previous passage

    def flush(overlap: bool = True) -> None:
        nonlocal lines, carried
        body = "\n".join(lines).strip()
        lines = []
        if not body:
            return
        chunks.append(Chunk(
            text=body, title=article.title, url=article.url,
            language=article.language, section=list(section),
            updated=article.updated, author=article.author,
        ))
        carried = lines_tail(body) if overlap else None

    def lines_tail(body: str) -> str | None:
        tail = body.split("\n")[-1].strip()
        # Only worth carrying if it is prose; a lone table row repeated out of
        # its table reads as a fragment.
        return tail if len(tail) >= 40 and " | " not in tail else None

    def length() -> int:
        return sum(len(line) + 1 for line in lines)

    for block in article.blocks:
        if block.kind == "heading":
            # Close the passage at a heading: it is the author's own boundary.
            if length() >= MIN_CHARS:
                flush(overlap=False)
            while levels and levels[-1] >= block.level:
                levels.pop()
                section.pop()
            levels.append(block.level)
            section.append(block.text)
            table_header = None
            continue

        if block.kind == "row":
            if table_header is None:
                table_header = block.text
        else:
            table_header = None

        pieces = [block.text]
        if block.kind == "text" and len(block.text) > MAX_CHARS:
            pieces = _split_long(block.text)

        for piece in pieces:
            if lines and length() + len(piece) > TARGET_CHARS:
                flush()
                if carried:
                    lines.append(carried)
                    carried = None
                # A table continuing across the cut keeps its header.
                if block.kind == "row" and table_header and table_header != piece:
                    lines.append(table_header)
            lines.append(piece)

    flush(overlap=False)

    # A trailing scrap -- an article ending on a one-line note -- is folded
    # back into the passage before it rather than embedded alone, where it
    # would match its subject and contain no advice about it.
    #
    # Only within the same section, though. A short closing line under its own
    # heading is a different claim from the paragraph above it, and merging
    # across that boundary would file the text under a heading its author did
    # not put it under. A passage that is small is a nuisance; a passage
    # attributed to the wrong section is the failure this module exists to
    # prevent, so the scrap is left to stand alone instead.
    if (len(chunks) > 1 and len(chunks[-1].text) < MIN_CHARS
            and chunks[-1].section == chunks[-2].section):
        tail = chunks.pop()
        chunks[-1].text = f"{chunks[-1].text}\n{tail.text}"
    return chunks
