"""
Tests for cutting an article into quotable passages.

Retrieval returns whatever unit was indexed, and that unit gets read out to
someone standing in a field. So these tests are mostly about what a passage
must never lose: the heading that names the crop, the header row that says
which column is the dose, the sentence before the recommendation that
explains it.
"""

from rag.chunking import (
    MIN_CHARS, OVERLAP_CHARS, TARGET_CHARS, Chunk, chunk_article,
)
from rag.extract import Article, Block


def article(*blocks: Block, **kw) -> Article:
    return Article(
        url=kw.get("url", "https://example.test/wheat?lgn=en"),
        title=kw.get("title", "Wheat cultivation"),
        language=kw.get("language", "en"),
        path=kw.get("path", ["Agriculture", "Crops"]),
        updated=kw.get("updated", "2026-03-14"),
        author=kw.get("author", "A. Researcher"),
        blocks=list(blocks),
    )


def para(text: str) -> Block:
    return Block("text", text)


# Comfortably past TARGET_CHARS on its own, so two of these must be cut apart.
# Sized from the constant rather than hard-coded, so that changing the passage
# size does not quietly turn these tests into assertions about one chunk.
_SENTENCE = "This is a sentence about growing wheat in the rabi season. "
LONG = _SENTENCE * (TARGET_CHARS // len(_SENTENCE) + 4)


def enough_rows(prefix: str) -> int:
    """How many table rows it takes to overflow a passage."""
    return TARGET_CHARS // len(prefix) * 3


class TestEveryPassageKnowsWhatItIsAbout:
    def test_the_heading_above_a_passage_travels_with_it(self):
        """"Spray at 0.1%" is not advice until you know of what, on what."""
        chunks = chunk_article(article(
            Block("heading", "Yellow rust", 3),
            para("Spray at 0.1 percent when pustules appear."),
        ))
        assert chunks[0].section == ["Yellow rust"]
        assert "Yellow rust" in chunks[0].heading
        assert "Wheat cultivation" in chunks[0].heading

    def test_what_is_embedded_carries_the_heading_the_passage_does_not(self):
        chunks = chunk_article(article(
            Block("heading", "Yellow rust", 3),
            para("Spray at 0.1 percent when pustules appear."),
        ))
        embedded = chunks[0].for_embedding()
        assert "Yellow rust" in embedded
        # ...but the passage itself stays the source's own words, so a quote
        # never silently includes text the source did not write there.
        assert "Yellow rust" not in chunks[0].text

    def test_a_deeper_heading_nests_under_the_one_above_it(self):
        chunks = chunk_article(article(
            Block("heading", "Diseases", 2),
            Block("heading", "Yellow rust", 3),
            para("Spray at 0.1 percent when pustules appear."),
        ))
        assert chunks[0].section == ["Diseases", "Yellow rust"]

    def test_a_sibling_heading_replaces_rather_than_nests(self):
        chunks = chunk_article(article(
            Block("heading", "Diseases", 2), para(LONG),
            Block("heading", "Storage", 2), para("Keep the grain dry."),
        ))
        assert chunks[-1].section == ["Storage"]

    def test_provenance_reaches_every_passage(self):
        chunks = chunk_article(article(para(LONG), para(LONG), para(LONG)))
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.url.startswith("https://")
            assert chunk.updated == "2026-03-14"
            assert chunk.language == "en"


class TestTablesStayReadable:
    def test_a_table_carried_across_a_cut_keeps_its_header(self):
        """Without this, a continuation reads "Wheat | 100 | 25" with nothing
        saying which column is nitrogen."""
        header = "Crop | Nitrogen | Phosphorus"
        rows = [Block("row", header)]
        rows += [Block("row", f"Crop number {i} | {i * 10} kg | {i * 5} kg")
                 for i in range(enough_rows(header))]
        chunks = chunk_article(article(*rows))
        assert len(chunks) > 1
        for chunk in chunks:
            assert "Crop | Nitrogen | Phosphorus" in chunk.text

    def test_a_row_is_never_split_across_passages(self):
        rows = [Block("row", f"Crop {i} | {i * 10} kg per acre | spray twice")
                for i in range(enough_rows("Crop 00 | 000 kg per acre | spray twice"))]
        chunks = chunk_article(article(*rows))
        for chunk in chunks:
            for line in chunk.text.split("\n"):
                if " | " in line:
                    assert line.count(" | ") == 2


class TestPassageSizes:
    def test_passages_stay_near_the_target(self):
        chunks = chunk_article(article(*[para(LONG) for _ in range(20)]))
        assert len(chunks) > 1
        for chunk in chunks[:-1]:
            assert len(chunk.text) <= TARGET_CHARS * 1.6

    def test_one_enormous_paragraph_is_split_on_sentences(self):
        chunks = chunk_article(article(para("Grow wheat carefully. " * 400)))
        assert len(chunks) > 1
        assert all(c.text.strip().endswith(".") for c in chunks)

    def test_a_devanagari_sentence_end_is_a_split_point(self):
        chunks = chunk_article(article(para("गेहूं की बुवाई करें। " * 600)))
        assert len(chunks) > 1

    def test_a_trailing_scrap_is_folded_back_rather_than_embedded_alone(self):
        """A one-line note at the end of an article would otherwise become a
        passage that matches its subject and contains no advice."""
        chunks = chunk_article(article(
            para(LONG), para(LONG), para("Source: ICAR."),
        ))
        assert all(len(c.text) >= MIN_CHARS for c in chunks)
        assert "Source: ICAR." in chunks[-1].text

    def test_a_scrap_under_its_own_heading_is_left_where_its_author_put_it(self):
        """Folding it backwards would file it under the previous section --
        a citation pointing at a heading the text does not sit under."""
        chunks = chunk_article(article(
            Block("heading", "Diseases", 2), para(LONG),
            Block("heading", "Storage", 2), para("Keep the grain dry."),
        ))
        assert chunks[-1].section == ["Storage"]
        assert chunks[-1].text == "Keep the grain dry."

    def test_a_short_article_is_one_passage(self):
        chunks = chunk_article(article(para("Sow in November.")))
        assert len(chunks) == 1


class TestPassagesOverlap:
    def test_the_end_of_a_passage_opens_the_next(self):
        """A boundary falls somewhere, and the sentence that explains a
        recommendation is often the one just before it."""
        chunks = chunk_article(article(*[para(LONG) for _ in range(6)]))
        assert len(chunks) > 1
        opening = chunks[1].text.split("\n")[0]
        assert chunks[0].text.rstrip().endswith(opening)

    def test_the_overlap_is_a_joining_sentence_not_a_second_copy(self):
        """At this passage size a single paragraph can fill a whole chunk.
        Repeating one wholesale would embed the same text twice and spend a
        rationed quota on a duplicate."""
        chunks = chunk_article(article(*[para(LONG) for _ in range(6)]))
        assert len(chunks) > 1
        assert len(chunks[1].text.split("\n")[0]) <= OVERLAP_CHARS

    def test_a_heading_boundary_does_not_overlap(self):
        """The author put the break there on purpose; repeating across it
        would attribute one section's sentence to the next."""
        chunks = chunk_article(article(
            Block("heading", "Diseases", 2), para(LONG), para(LONG),
            Block("heading", "Storage", 2), para("Keep the grain dry and cool."),
        ))
        storage = [c for c in chunks if c.section == ["Storage"]]
        assert storage and "rabi season" not in storage[0].text


class TestAPassageThatSpansSections:
    """These articles head their sections flat, so a passage that runs past a
    short heading usually covers siblings with no parent between them. What it
    must never do is claim to be from one of them."""

    def short(self, name: str) -> list:
        return [Block("heading", name, 3), para("A short note about " + name + ".")]

    def test_short_sections_run_together_rather_than_becoming_scraps(self):
        chunks = chunk_article(article(
            *self.short("Sowing"), *self.short("Spacing"), *self.short("Weeding"),
        ))
        assert len(chunks) == 1

    def test_and_the_citation_names_every_section_it_covers(self):
        chunks = chunk_article(article(
            *self.short("Sowing"), *self.short("Spacing"),
        ))
        assert chunks[0].covers == ["Sowing", "Spacing"]
        assert "Sowing; Spacing" in chunks[0].heading

    def test_it_is_not_filed_under_whichever_heading_was_open_last(self):
        """The failure this exists to prevent: a citation pointing a reader at
        a section that does not contain the sentence they were read."""
        chunks = chunk_article(article(
            *self.short("Sowing"), *self.short("Spacing"),
        ))
        assert chunks[0].section != ["Spacing"]

    def test_siblings_under_a_shared_parent_are_filed_under_the_parent(self):
        chunks = chunk_article(article(
            Block("heading", "Diseases", 2),
            *self.short("Rust"), *self.short("Smut"),
        ))
        assert chunks[0].section == ["Diseases"]
        assert chunks[0].covers == ["Rust", "Smut"]

    def test_a_section_long_enough_to_stand_alone_still_does(self):
        chunks = chunk_article(article(
            Block("heading", "Sowing", 3), para(LONG),
            Block("heading", "Spacing", 3), para(LONG),
        ))
        assert len(chunks) > 1
        assert chunks[0].section == ["Sowing"]
        assert not chunks[0].covers

    def test_the_words_of_the_heading_survive_into_the_embedding(self):
        """The heading is often the only place the crop is named, so losing it
        would quietly cost the passage its subject."""
        chunks = chunk_article(article(
            *self.short("Yellow rust"), *self.short("Loose smut"),
        ))
        embedded = chunks[0].for_embedding()
        assert "Yellow rust" in embedded and "Loose smut" in embedded


class TestRoundTrip:
    def test_a_passage_survives_being_written_to_disk_and_read_back(self):
        chunk = chunk_article(article(
            Block("heading", "Yellow rust", 3), para("Spray at 0.1 percent."),
        ))[0]
        assert Chunk.from_dict(chunk.as_dict()).as_dict() == chunk.as_dict()
