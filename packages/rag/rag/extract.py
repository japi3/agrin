"""
Turning a Vikaspedia article into text worth embedding.

Vikaspedia serves its pages as a Next.js application: the HTML that arrives
is a shell, and the article itself sits inside the `__NEXT_DATA__` script as
escaped JSON. That is a gift rather than an obstacle. The JSON carries not
just the body but the title, the author, the folder path it lives under and
the date it was last touched -- everything a citation needs, already
structured, with no scraping of page furniture and no guessing at which
`<div>` holds the content.

What this module does is the second half: take that body, which is ordinary
editorial HTML, and reduce it to ordered blocks of plain text.

Two choices in here matter more than they look.

**Tables are kept.** A quarter of the markup on these pages is table cells,
and they are where the numbers live -- seed rates, row spacing, dosage per
acre, the pre-harvest interval on a pesticide. Flattening a table into a
paragraph would run those numbers together and make them impossible to quote
back safely. Each row becomes one line with its cells separated by pipes, so
a row survives retrieval as a unit and a farmer reading the answer sees the
dose next to the crop it belongs to.

**Headings are kept as structure, not as text.** A paragraph that says "apply
twice at fortnightly intervals" means nothing without the heading above it
saying which disease. The chunker uses these to give every chunk its context;
see `rag.chunking`.

Finding those headings takes one piece of local knowledge. Vikaspedia's
editors work in a rich-text box, and a section heading there is a short
paragraph set entirely in bold -- `<p><strong>3. Why Soil Organic Carbon
Matters</strong></p>`. Real `<h3>` tags are the exception: the soil-carbon
page has fifteen headings and not one heading tag. So a fully bold short
paragraph is read as a heading here. The qualifier "fully" is what keeps it
safe, because the same pages open a paragraph with a bold lead-in --
`<strong>Wet oxidation methods:</strong> Methods such as...` -- and that is a
sentence, not a section.

Written against the standard library's HTML parser on purpose. This project
adds a dependency only when it earns one, and the markup here is editorial
HTML from a single publisher rather than the open web.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

# Markup that carries no text a farmer would read, and whose contents must not
# be mistaken for prose.
_DROP = {"script", "style", "noscript", "iframe", "svg"}

# Anything that starts a new line of text rather than continuing the last one.
_BLOCK = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "ul", "ol", "blockquote",
}

_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BOLD = {"strong", "b"}

# Longest a bold paragraph can be and still be read as a heading rather than
# an emphasised sentence. Section headings on these pages are a few words.
BOLD_HEADING_MAX_CHARS = 110

# Bold headings sit at this depth, so that they nest under any real heading
# tags a page does happen to use.
BOLD_HEADING_LEVEL = 3


@dataclass
class Block:
    """One line of an article, and what kind of line it is.

    `level` is only meaningful for headings: 1 for an <h1>, 3 for an <h3>.
    Everything else carries 0.
    """
    kind: str          # "heading" | "text" | "row"
    text: str
    level: int = 0


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._buf: list[str] = []
        self._cells: list[str] = []
        self._skip = 0
        self._heading = 0
        self._in_cell = False
        self._in_row = False
        self._bold = 0
        self._bold_chars = 0
        self._plain_chars = 0

    # -- buffer handling --------------------------------------------------
    def _flush(self) -> None:
        text = _tidy("".join(self._buf))
        bold_only = self._bold_chars > 0 and self._plain_chars == 0
        self._buf.clear()
        self._bold_chars = self._plain_chars = 0
        if not text:
            return
        if self._heading:
            self._append(Block("heading", text, self._heading))
        elif bold_only and len(text) <= BOLD_HEADING_MAX_CHARS:
            self._append(Block("heading", text, BOLD_HEADING_LEVEL))
        else:
            self._append(Block("text", text))

    def _append(self, block: Block) -> None:
        """Add a block, unless it repeats the one before it.

        These pages are edited by hand and a pasted line is sometimes left in
        twice -- the soil-carbon page states one sentence, then restates it
        centred directly underneath. Repeating it in a passage would read as
        a stutter in an answer, and would waste room in a chunk that has a
        budget. Only an immediate repeat is dropped; the same sentence
        appearing again later in the article is left alone, because there it
        is usually deliberate.
        """
        if self.blocks and self.blocks[-1].text == block.text:
            return
        self.blocks.append(block)

    def _flush_row(self) -> None:
        cells = [_tidy(c) for c in self._cells]
        self._cells.clear()
        cells = [c for c in cells if c]
        if cells:
            self.blocks.append(Block("row", " | ".join(cells)))

    # -- parser callbacks -------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag in _DROP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in _BOLD:
            self._bold += 1
            return
        if tag in ("td", "th"):
            # A cell's text belongs to its row, not to the running paragraph.
            self._flush()
            self._in_cell = True
            self._buf.clear()
            return
        if tag == "tr":
            self._flush()
            self._in_row = True
            self._cells.clear()
            return
        if tag in _BLOCK:
            if self._in_cell:
                # A <br> or <p> inside a cell separates lines within that
                # cell; it must not end the cell or start a new block.
                self._buf.append(" ")
                return
            self._flush()
            if tag in _HEADINGS:
                self._heading = int(tag[1])

    def handle_endtag(self, tag):
        if tag in _DROP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in _BOLD:
            self._bold = max(0, self._bold - 1)
            return
        if tag in ("td", "th"):
            self._cells.append("".join(self._buf))
            self._buf.clear()
            self._in_cell = False
            return
        if tag == "tr":
            self._flush_row()
            self._in_row = False
            return
        if tag in _BLOCK:
            if self._in_cell:
                return
            self._flush()
            if tag in _HEADINGS:
                self._heading = 0

    def handle_data(self, data):
        if self._skip:
            return
        self._buf.append(data)
        if not self._in_cell:
            weight = len(data.strip())
            if self._bold:
                self._bold_chars += weight
            else:
                self._plain_chars += weight

    def close(self):  # noqa: D102
        super().close()
        if self._in_cell or self._cells:
            self._cells.append("".join(self._buf))
            self._buf.clear()
            self._flush_row()
        self._flush()


# Vikaspedia's editors paste from Word, which leaves non-breaking spaces,
# stray soft hyphens and runs of empty formatting behind.
_WS = re.compile(r"[\s ​  ]+")
_JUNK = re.compile(r"^[\s |\-–—_.:;•*]+$")


def _tidy(text: str) -> str:
    text = unescape(text).replace("­", "")
    text = _WS.sub(" ", text).strip()
    return "" if _JUNK.match(text) else text


def blocks_from_html(html: str) -> list[Block]:
    """Ordered blocks of readable text from one article body."""
    reader = _Reader()
    try:
        reader.feed(html)
        reader.close()
    except Exception:  # noqa: BLE001
        # Malformed markup on one page should cost that page, not the run.
        return []
    return reader.blocks


# --------------------------------------------------------------------------
# The page as served
# --------------------------------------------------------------------------

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S,
)


def _as_date(value) -> str | None:
    """The day a page was last touched, however the CMS chose to record it.

    Most pages carry an ISO timestamp string. A few carry an epoch integer --
    seconds on the older records, milliseconds on the newer ones -- and one of
    those was enough to end a crawl partway through. The date is only ever
    shown as provenance next to a quote, so an unparseable value becomes no
    date rather than a reason to lose the page.
    """
    if isinstance(value, str):
        return value[:10] or None
    if isinstance(value, (int, float)) and value > 0:
        seconds = value / 1000.0 if value > 1e11 else float(value)
        try:
            return _dt.datetime.fromtimestamp(
                seconds, _dt.timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return None
    return None


@dataclass
class Article:
    """One Vikaspedia page, with everything a citation needs."""
    url: str
    title: str
    language: str
    path: list[str]          # breadcrumb titles, outermost first
    updated: str | None
    author: str | None
    blocks: list[Block]

    @property
    def words(self) -> int:
        return sum(len(b.text.split()) for b in self.blocks)


def article_from_page(html: str, url: str) -> Article | None:
    """Parse one fetched page, or return None if it holds no article.

    About a fifth of the URLs in the sitemap are folder pages -- an index of
    links with no body of their own. They parse fine and yield nothing, and
    returning None rather than an empty Article keeps that distinction
    explicit for the caller counting what it got.
    """
    found = _NEXT_DATA.search(html)
    if not found:
        return None
    try:
        data = json.loads(found.group(1))
        props = data["props"]["pageProps"]
    except (ValueError, KeyError, TypeError):
        return None

    content = props.get("ssrPageContent") or {}
    body = content.get("content") or ""
    if not body.strip():
        return None

    blocks = blocks_from_html(body)
    if not blocks:
        return None

    crumbs = props.get("ssrBreadcrumbs") or []
    path = [c.get("title", "") for c in crumbs if isinstance(c, dict)]

    return Article(
        url=url,
        title=_tidy(content.get("title") or "") or "Untitled",
        language=content.get("lgn") or props.get("ssrLang") or "en",
        path=[p for p in path if p],
        updated=_as_date(content.get("updated_at") or content.get("created_at")),
        author=content.get("created_by_name") or None,
        blocks=blocks,
    )
