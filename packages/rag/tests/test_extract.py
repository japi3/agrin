"""
Tests for reading a Vikaspedia page.

Most of these pin down things that were discovered by looking at the real
pages rather than by reasoning about HTML, and would silently regress if
someone tidied the parser without knowing why it does what it does.

The one that matters most is the bold heading. These pages are written in a
rich-text editor, and a section heading is a short fully-bold paragraph
rather than an <h3> -- the soil-carbon article has nineteen headings and no
heading tags at all. Miss that and every passage in the corpus loses the
section it belongs to, which is usually the only place the crop or the
disease is named. Retrieval still works and is quietly much worse.
"""

from rag.extract import article_from_page, blocks_from_html

PAGE = """<html><body><script id="__NEXT_DATA__" type="application/json">
{"props": {"pageProps": {
  "ssrPageContent": {
    "title": "Wheat cultivation",
    "lgn": "en",
    "updated_at": "2026-03-14T09:00:00.000+00:00",
    "created_by_name": "A. Researcher",
    "content": "<p><strong>Seed rate</strong></p><p>Use 100 kg per hectare.</p>"
  },
  "ssrBreadcrumbs": [{"title": "Agriculture", "url": "/agriculture"},
                     {"title": "Crops", "url": "/agriculture/crops"}]
}}}
</script></body></html>"""


class TestHeadingsTheEditorsActuallyUse:
    def test_a_fully_bold_short_paragraph_is_a_heading(self):
        blocks = blocks_from_html(
            "<p><strong>3. Why It Matters</strong></p><p>Because of this.</p>"
        )
        assert [b.kind for b in blocks] == ["heading", "text"]
        assert blocks[0].text == "3. Why It Matters"

    def test_a_bold_lead_in_is_a_sentence_not_a_section(self):
        """`<strong>Wet oxidation:</strong> Methods such as...` is a
        paragraph. Treating it as a heading would shred the article into
        dozens of one-line sections."""
        blocks = blocks_from_html(
            "<p><strong>Wet oxidation:</strong> Recovery varies among soils.</p>"
        )
        assert [b.kind for b in blocks] == ["text"]

    def test_a_long_bold_paragraph_is_emphasis_not_a_heading(self):
        blocks = blocks_from_html(f"<p><strong>{'word ' * 40}</strong></p>")
        assert blocks[0].kind == "text"

    def test_real_heading_tags_still_work(self):
        blocks = blocks_from_html("<h2>Diseases</h2><p>Rust appears in March.</p>")
        assert blocks[0].kind == "heading"
        assert blocks[0].level == 2


class TestTablesSurvive:
    def test_a_row_becomes_one_line_with_its_cells_intact(self):
        """The numbers on these pages live in tables. A row that loses its
        cell boundaries stops being quotable."""
        blocks = blocks_from_html(
            "<table><tr><td>Wheat</td><td>100 kg</td><td>25 kg</td></tr></table>"
        )
        assert blocks[0].kind == "row"
        assert blocks[0].text == "Wheat | 100 kg | 25 kg"

    def test_a_line_break_inside_a_cell_does_not_split_the_row(self):
        blocks = blocks_from_html(
            "<table><tr><td>Soil<br>Organic<br>Carbon</td><td>2%</td></tr></table>"
        )
        assert len([b for b in blocks if b.kind == "row"]) == 1
        assert "2%" in blocks[0].text

    def test_header_and_body_rows_are_separate_lines(self):
        blocks = blocks_from_html(
            "<table><thead><tr><th>Crop</th><th>Rate</th></tr></thead>"
            "<tbody><tr><td>Wheat</td><td>100 kg</td></tr></tbody></table>"
        )
        rows = [b.text for b in blocks if b.kind == "row"]
        assert rows == ["Crop | Rate", "Wheat | 100 kg"]


class TestTheThingsEditorsLeaveBehind:
    def test_an_immediately_repeated_line_is_dropped(self):
        """Observed on the live soil-carbon page: one sentence, then the same
        sentence again centred underneath. In a spoken answer it stutters."""
        blocks = blocks_from_html(
            "<p>Do not confuse the two.</p><p align='center'>Do not confuse the two.</p>"
        )
        assert len(blocks) == 1

    def test_the_same_line_further_down_is_kept(self):
        blocks = blocks_from_html(
            "<p>Apply twice.</p><p>Wait a fortnight.</p><p>Apply twice.</p>"
        )
        assert len(blocks) == 3

    def test_scripts_and_styles_never_become_text(self):
        blocks = blocks_from_html(
            "<script>var x = 'spray 500 ml';</script><p>Real advice.</p>"
        )
        assert [b.text for b in blocks] == ["Real advice."]

    def test_formatting_only_paragraphs_are_dropped(self):
        blocks = blocks_from_html("<p>&nbsp;</p><p>---</p><p>Real advice.</p>")
        assert [b.text for b in blocks] == ["Real advice."]

    def test_malformed_markup_costs_one_page_not_the_run(self):
        assert isinstance(blocks_from_html("<p><table><tr><td>broken"), list)


class TestThePageAsServed:
    def test_the_article_and_its_provenance_are_read_together(self):
        article = article_from_page(PAGE, "https://example.test/wheat?lgn=en")
        assert article is not None
        assert article.title == "Wheat cultivation"
        assert article.language == "en"
        assert article.updated == "2026-03-14"
        assert article.author == "A. Researcher"
        assert article.path == ["Agriculture", "Crops"]

    def test_a_folder_page_yields_nothing_rather_than_an_empty_article(self):
        """About a fifth of the sitemap is index pages. The caller counts
        what it got, so the distinction has to survive."""
        empty = PAGE.replace(
            '"content": "<p><strong>Seed rate</strong></p><p>Use 100 kg per hectare.</p>"',
            '"content": ""',
        )
        assert article_from_page(empty, "https://example.test/x") is None

    def test_a_page_without_the_embedded_json_yields_nothing(self):
        assert article_from_page("<html><body>nothing</body></html>", "u") is None

    def test_an_epoch_timestamp_is_read_as_a_date(self):
        """A few records carry milliseconds since the epoch instead of an ISO
        string, and one of them ended a crawl partway through."""
        page = PAGE.replace('"2026-03-14T09:00:00.000+00:00"', "1773484800000")
        article = article_from_page(page, "u")
        assert article is not None and article.updated == "2026-03-14"

    def test_an_unreadable_date_costs_the_date_not_the_page(self):
        page = PAGE.replace('"2026-03-14T09:00:00.000+00:00"', "null")
        page = page.replace('"created_by_name"', '"created_at": null, "created_by_name"')
        article = article_from_page(page, "u")
        assert article is not None and article.updated is None
