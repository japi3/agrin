"""
Cutting an article into passages that can be quoted back.

Retrieval returns whatever unit you indexed, so the unit has to be one a
farmer could be read out loud without it being wrong. That rules out both
extremes. A whole article is too much to quote and dilutes the embedding
until a page about nine crops matches a question about none of them. A single
sentence is small enough to lose the thing it depends on -- "spray again
after fifteen days" is not advice until you know what the spray is.

So the target here is a passage: a section or so of an article, around two
and a half thousand characters, cut at a boundary the author already put
there.

That size was chosen twice. The first time it was 1,100 characters, on the
reasoning that a tighter passage keeps one subject per vector. The second
time the free tier decided it: embedding is capped at a thousand passages per
key per day, so passage size is also coverage. At 1,100 the corpus was 17,875
passages and nine days of quota; at 2,500 it is about a third of that and
fits in two. Six hundred tokens is still comfortably inside what the
embedding model reads, and a passage this size holds a whole recommendation
rather than half of one -- so the trade costs some precision in ranking and
buys the difference between shipping the material and not.

Three rules make the passages safe rather than merely well-sized.

**A passage may span sections, and then it is cited by what contains it.**
These articles are written in short sections -- the median one is a couple of
paragraphs -- so ending a passage at every heading produced passages a
quarter of the intended size, and against a rationed embedding quota that is
the difference between shipping half the corpus and a tenth of it. Short
sections are therefore allowed to run together. What keeps that honest is the
citation. A passage covering "Diseases > Rust" and "Diseases > Smut" is filed
under "Diseases" -- the narrowest heading that truly contains all of it --
and names both sections it covers, rather than being filed under whichever
one happened to be open when the passage was closed.

Naming them matters as much as the honesty does. These articles head their
sections flat, as a run of siblings with no parent between them, so the
narrowest containing heading for two adjacent sections is usually nothing at
all. Citing by the article alone would be truthful and would also throw away
the words that say what the passage is about -- and those words are often the
only place the crop or the disease is named. So the citation carries both:
where the passage sits, and what it covers.

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

**Passages overlap by a sentence or two.** A boundary always falls somewhere,
and the sentence that explains a recommendation is often the one just before
it. Repeating the tail of the previous passage costs a little storage and
avoids losing the join.

Only the tail, though, and only when it is short. Carrying a whole block
worked when blocks were a fifth of a passage; at this size a single paragraph
can be a passage on its own, and repeating one wholesale would not be overlap
but duplication -- the same text embedded twice, crowding out variety in the
results and inflating the corpus against a rationed quota.

None of this is tuned against a benchmark -- there isn't an Indian
agricultural-advisory retrieval set to tune against. The sizes below are
chosen to be defensible and are stated as constants so they can be argued
with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .extract import Article, Block

# Roughly 400 words -- a section of an article. See the note above on why this
# is not smaller: passage size is coverage when embedding is rationed daily.
TARGET_CHARS = 2500

# Below this a passage is usually a stray heading or a one-line caption. It is
# merged forward rather than embedded on its own, where it would be a
# high-scoring match with nothing useful in it.
MIN_CHARS = 300

# A single block longer than this is split on sentence boundaries. Rare -- a
# few pages have one enormous paragraph.
MAX_CHARS = 4000

# The most of the previous passage that may be repeated at the start of the
# next one. A joining sentence or two, not a second copy of a paragraph.
OVERLAP_CHARS = TARGET_CHARS // 4

# How much a passage must already hold before a heading is allowed to end it.
# Under this, the section was too short to be a passage on its own and runs
# into the next; see the note on spanning sections above.
SECTION_BREAK_CHARS = 1400


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
    covers: list[str] = field(default_factory=list)

    @property
    def heading(self) -> str:
        """The article and section this passage came from, for display."""
        parts = [self.title, *self.section]
        if len(self.covers) > 1:
            parts.append("; ".join(self.covers))
        elif self.covers and not self.section:
            parts.extend(self.covers)
        return " > ".join(parts)

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
            "covers": self.covers,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        return cls(
            text=d["text"], title=d["title"], url=d["url"],
            language=d.get("language", "en"), section=d.get("section") or [],
            updated=d.get("updated"), author=d.get("author"),
            covers=d.get("covers") or [],
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
    covered: list[list[str]] = []  # every section this passage reaches into
    table_header: str | None = None
    carried: str | None = None     # last block of the previous passage

    def common_section() -> list[str]:
        """The narrowest heading path containing everything in the passage."""
        if not covered:
            return list(section)
        shared = covered[0]
        for path in covered[1:]:
            keep = 0
            for a, b in zip(shared, path):
                if a != b:
                    break
                keep += 1
            shared = shared[:keep]
            if not shared:
                break
        return list(shared)

    def flush(overlap: bool = True) -> None:
        nonlocal lines, carried, covered
        body = "\n".join(lines).strip()
        where = common_section()
        covered_now = list(covered)
        lines = []
        covered = []
        if not body:
            return
        leaves: list[str] = []
        for path in covered_now:
            leaf = path[len(where):]
            if leaf and (not leaves or leaves[-1] != leaf[0]):
                leaves.append(leaf[0])
        chunks.append(Chunk(
            text=body, title=article.title, url=article.url,
            language=article.language, section=where,
            updated=article.updated, author=article.author,
            covers=leaves,
        ))
        carried = lines_tail(body) if overlap else None

    def lines_tail(body: str) -> str | None:
        tail = body.split("\n")[-1].strip()
        # A lone table row repeated out of its table reads as a fragment.
        if len(tail) < 40 or " | " in tail:
            return None
        if len(tail) <= OVERLAP_CHARS:
            return tail
        # Too long to repeat whole: keep the closing sentences that fit, which
        # is the part the next passage actually follows on from.
        kept: list[str] = []
        for sentence in reversed(_SENTENCE.split(tail)):
            if sum(len(x) + 1 for x in kept) + len(sentence) > OVERLAP_CHARS:
                break
            kept.insert(0, sentence)
        joined = " ".join(kept).strip()
        return joined if len(joined) >= 40 else None

    def length() -> int:
        return sum(len(line) + 1 for line in lines)

    for block in article.blocks:
        if block.kind == "heading":
            # A heading is the author's own boundary, and worth ending a
            # passage on -- but only once the passage is big enough to stand
            # alone. Below that the section is too short to be a passage, and
            # is allowed to run into the next one; common_section() keeps the
            # citation truthful when that happens.
            if length() >= SECTION_BREAK_CHARS:
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

        if not covered or covered[-1] != section:
            covered.append(list(section))

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
