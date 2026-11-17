"""Text helpers: HTML to plain text, token-aware term matching, normalisation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from html.parser import HTMLParser

_BLOCK_TAGS = frozenset(
    {
        "p", "br", "div", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
        "tr", "table", "section", "article", "blockquote", "pre", "hr",
    }
)  # fmt: skip
_SKIP_TAGS = frozenset({"script", "style", "noscript"})
_SPACES = re.compile(r"[ \t\r\f\v]+")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        elif tag == "li":
            self.parts.append("\n• ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _collapse(raw: str) -> str:
    """Normalise whitespace and keep at most one blank line between paragraphs."""
    out: list[str] = []
    for line in raw.replace("\xa0", " ").split("\n"):
        line = _SPACES.sub(" ", line).strip()
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def _parse(markup: str) -> _TextExtractor:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return parser


def html_to_text(markup: str | None) -> str:
    """Convert an HTML fragment into readable plain text, keeping paragraphs and bullets."""
    if not markup:
        return ""
    if "<" not in markup and "&" not in markup:
        return _collapse(markup)
    return _collapse("".join(_parse(markup).parts))


def extract_links(markup: str | None) -> list[str]:
    """Return every ``href`` in an HTML fragment, in document order."""
    return _parse(markup).links if markup else []


def normalize_key(value: str) -> str:
    """Lower-case and strip punctuation and bracketed noise; used for de-duplication."""
    value = re.sub(r"\(.*?\)|\[.*?\]", " ", value.lower())
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


@lru_cache(maxsize=8192)
def term_pattern(term: str) -> re.Pattern[str]:
    """Case-insensitive pattern matching ``term`` as a whole token ('next.js', 'ci/cd', 'n8n')."""
    return re.compile(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", re.IGNORECASE)


def find_terms(text: str, terms: Iterable[str]) -> list[str]:
    """Return the terms that occur in ``text`` as whole tokens, preserving input order."""
    if not text:
        return []
    return [term for term in terms if term_pattern(term).search(text)]
