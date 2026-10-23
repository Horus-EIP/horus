import re
from bisect import bisect_right
from collections.abc import Iterator, Sequence
from typing import NamedTuple

from app.core.logging import get_logger

logger = get_logger("DocumentChunker")

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\s*\n\s*")


class TextChunk(NamedTuple):
    text: str
    char_start: int
    char_end: int


class _Span(NamedTuple):
    start: int
    end: int


def page_of(char_start: int, page_starts: Sequence[int]) -> int | None:
    if not page_starts:
        return None
    return max(1, bisect_right(page_starts, char_start))


class DocumentChunker:
    def __init__(self, chunk_size: int = 1000, overlap: int = 200):
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")
        if not 0 <= overlap < chunk_size:
            raise ValueError(f"overlap must be in [0, {chunk_size}), got {overlap}")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split(self, text: str) -> list[TextChunk]:
        text = text or ""
        pieces = [piece for sentence in _sentences(text) for piece in self._fit(text, sentence)]
        chunks = [
            TextChunk(text[group[0].start : group[-1].end], group[0].start, group[-1].end)
            for group in self._pack(pieces)
        ]
        logger.debug("Split %d characters into %d chunks", len(text), len(chunks))
        return chunks

    def chunk_document(self, text: str) -> list[str]:
        return [chunk.text for chunk in self.split(text)]

    def _fit(self, text: str, sentence: _Span) -> list[_Span]:
        if sentence.end - sentence.start <= self.chunk_size:
            return [sentence]
        windows: list[_Span] = []
        start = sentence.start
        while sentence.end - start > self.chunk_size:
            cut = _cut_before(text, start, start + self.chunk_size)
            windows.append(_Span(start, cut))
            start = _word_start(text, max(cut - self.overlap, start + 1), cut)
            while start < sentence.end and text[start].isspace():
                start += 1
        windows.append(_Span(start, sentence.end))
        return windows

    def _pack(self, pieces: list[_Span]) -> list[list[_Span]]:
        groups: list[list[_Span]] = []
        current: list[_Span] = []
        for piece in pieces:
            if current and piece.end - current[0].start > self.chunk_size:
                groups.append(current)
                current = self._carry_over(current, piece)
            current.append(piece)
        if current:
            groups.append(current)
        return groups

    def _carry_over(self, group: list[_Span], incoming: _Span) -> list[_Span]:
        kept: list[_Span] = []
        for piece in reversed(group):
            if group[-1].end - piece.start > self.overlap:
                break
            kept.insert(0, piece)
        if not kept and self.overlap:
            kept = [group[-1]]
        while kept and incoming.end - kept[0].start > self.chunk_size:
            kept.pop(0)
        return kept


def _sentences(text: str) -> Iterator[_Span]:
    start = 0
    for match in _SENTENCE_BREAK.finditer(text):
        yield from _trimmed(text, start, match.start())
        start = match.end()
    yield from _trimmed(text, start, len(text))


def _trimmed(text: str, start: int, end: int) -> Iterator[_Span]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        yield _Span(start, end)


def _cut_before(text: str, start: int, limit: int) -> int:
    floor = start + (limit - start) // 2
    cut = limit
    while cut > floor and not text[cut].isspace():
        cut -= 1
    if cut == floor:
        cut = limit
    while cut > start + 1 and text[cut - 1].isspace():
        cut -= 1
    return cut


def _word_start(text: str, position: int, limit: int) -> int:
    for candidate in range(position, limit):
        if text[candidate - 1].isspace() and not text[candidate].isspace():
            return candidate
    return position
