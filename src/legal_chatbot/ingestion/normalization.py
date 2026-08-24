"""Deterministic, dependency-free normalization of untrusted legal HTML."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from hashlib import sha256
from html.parser import HTMLParser
from typing import Final

from legal_chatbot.ingestion.models import BlockKind, NormalizedBlock, NormalizedDocument

_IGNORED_TAGS: Final = frozenset({"script", "style", "noscript"})
_STRUCTURAL_CLASSES: Final[dict[str, BlockKind]] = {
    "prov-chapter": "chapter",
    "prov-section": "section",
    "prov-article": "article",
    "prov-clause": "clause",
    "prov-item": "item",
}
_PARAGRAPH_TAGS: Final = frozenset(
    {
        "address",
        "blockquote",
        "dd",
        "dt",
        "figcaption",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "pre",
        "td",
        "th",
    }
)
_BOUNDARY_TAGS: Final = _PARAGRAPH_TAGS | frozenset(
    {
        "article",
        "div",
        "dl",
        "figure",
        "footer",
        "header",
        "main",
        "ol",
        "section",
        "table",
        "tr",
        "ul",
    }
)
_WHITESPACE: Final = re.compile(r"\s+")


def _normalise_fragment(value: str) -> str:
    """Apply Unicode NFC and collapse HTML whitespace deterministically."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", value)).strip()


@dataclass
class _Capture:
    kind: BlockKind
    label: str | None
    start: int
    pieces: list[str] = field(default_factory=list)
    is_structural: bool = False


class _LegalHTMLParser(HTMLParser):
    """Extract text while treating input as data, never executable markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._text: list[str] = []
        self._captures: list[_Capture] = []
        self._completed: list[_Capture] = []
        self._ignored_depth = 0
        self._tag_stack: list[tuple[str, _Capture | None]] = []

    @property
    def text(self) -> str:
        return "".join(self._text).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _IGNORED_TAGS:
            self._ignored_depth += 1
            self._tag_stack.append((tag, None))
            return
        if self._ignored_depth:
            self._tag_stack.append((tag, None))
            return

        kind = self._structural_kind(attrs)
        capture: _Capture | None = None
        if kind is not None:
            self._boundary()
            capture = _Capture(
                kind=kind,
                label=self._explicit_label(attrs),
                start=len("".join(self._text)),
                is_structural=True,
            )
            self._captures.append(capture)
        elif tag in _PARAGRAPH_TAGS:
            self._boundary()
            capture = _Capture(
                kind="paragraph",
                label=None,
                start=len("".join(self._text)),
            )
            self._captures.append(capture)
        elif tag in _BOUNDARY_TAGS:
            self._boundary()
        elif tag == "br":
            self._line_break()
        self._tag_stack.append((tag, capture))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        if not self._tag_stack:
            return

        open_tag, capture = self._tag_stack.pop()
        if open_tag != tag:
            # HTMLParser intentionally tolerates malformed HTML.  The text is still data.
            self._tag_stack.append((open_tag, capture))
            return
        if self._ignored_depth or capture is None:
            return
        self._finish_capture(capture)

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        fragment = _normalise_fragment(data)
        if not fragment:
            return
        if self._text and not self._text[-1].endswith((" ", "\n")):
            self._text.append(" ")
            self._append_to_active(" ")
        self._text.append(fragment)
        self._append_to_active(fragment)

    def close(self) -> None:
        super().close()
        while self._tag_stack:
            _tag, capture = self._tag_stack.pop()
            if capture is not None:
                self._finish_capture(capture)

    def blocks(self) -> tuple[NormalizedBlock, ...]:
        document_text = self.text
        completed = sorted(self._completed, key=lambda capture: capture.start)
        blocks: list[NormalizedBlock] = []
        for capture in completed:
            end = min(len(document_text), self._capture_end(capture))
            text = document_text[capture.start : end].strip()
            if not text:
                continue
            start = document_text.find(text, capture.start, end)
            if start < 0:
                continue
            blocks.append(
                NormalizedBlock(
                    kind=capture.kind,
                    label=capture.label,
                    text=text,
                    start=start,
                    end=start + len(text),
                )
            )
        if not blocks and document_text:
            blocks.append(
                NormalizedBlock(
                    kind="paragraph",
                    text=document_text,
                    start=0,
                    end=len(document_text),
                )
            )
        return tuple(blocks)

    def _structural_kind(self, attrs: list[tuple[str, str | None]]) -> BlockKind | None:
        for name, value in attrs:
            if name.lower() != "class" or value is None:
                continue
            for class_name in value.split():
                kind = _STRUCTURAL_CLASSES.get(class_name)
                if kind is not None:
                    return kind
        return None

    def _explicit_label(self, attrs: list[tuple[str, str | None]]) -> str | None:
        for name, value in attrs:
            if name.lower() == "data-label" and value is not None:
                return _normalise_fragment(value) or None
        return None

    def _append_to_active(self, value: str) -> None:
        if self._captures:
            self._captures[-1].pieces.append(value)

    def _boundary(self) -> None:
        while self._text and self._text[-1].endswith(" "):
            self._text.pop()
        if self._text and not self._text[-1].endswith("\n\n"):
            self._text.append("\n\n")

    def _line_break(self) -> None:
        while self._text and self._text[-1].endswith(" "):
            self._text.pop()
        if self._text and not self._text[-1].endswith("\n"):
            self._text.append("\n")

    def _finish_capture(self, capture: _Capture) -> None:
        if capture not in self._captures:
            return
        self._captures.remove(capture)
        self._completed.append(capture)
        self._boundary()

    def _capture_end(self, capture: _Capture) -> int:
        """Use the emitted text extent rather than untrusted HTML tag positions."""
        return capture.start + len(_normalise_fragment("".join(capture.pieces)))


class HTMLNormalizer:
    """Normalize untrusted HTML into stable NFC text and source-neutral blocks."""

    version: Final = "html-v1"

    def normalize(self, html: str) -> NormalizedDocument:
        """Return canonical text or fail closed when HTML has no usable text."""
        if not isinstance(html, str):
            raise TypeError("html must be a string")
        parser = _LegalHTMLParser()
        parser.feed(html)
        parser.close()
        text = parser.text
        if not text:
            raise ValueError("HTML contains no normalizable text")
        return NormalizedDocument(
            text=text,
            sha256=sha256(text.encode("utf-8")).hexdigest(),
            blocks=parser.blocks(),
            normalizer_version=self.version,
        )
