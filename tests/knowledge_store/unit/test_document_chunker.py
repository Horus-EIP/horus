import pytest

from app.services.document_chunker import DocumentChunker, TextChunk, page_of


def _sentences(count: int, width: int = 60) -> str:
    return " ".join(f"Sentence {n} " + "x" * (width - 14) + "." for n in range(count))


def _covered(chunks: list[TextChunk]) -> set[int]:
    return {i for chunk in chunks for i in range(chunk.char_start, chunk.char_end)}


def _non_space(text: str) -> set[int]:
    return {i for i, char in enumerate(text) if not char.isspace()}


def test_defaults_are_a_thousand_characters_with_two_hundred_overlap():
    chunker = DocumentChunker()

    assert (chunker.chunk_size, chunker.overlap) == (1000, 200)


def test_a_short_text_is_one_chunk_with_its_offsets():
    text = "  This is sentence one. This is sentence two.  "

    chunks = DocumentChunker().split(text)

    assert chunks == [TextChunk("This is sentence one. This is sentence two.", 2, 45)]


def test_empty_or_blank_text_gives_no_chunks():
    assert DocumentChunker().split("") == []
    assert DocumentChunker().split(" \n\t ") == []


def test_every_chunk_is_the_exact_slice_of_the_text_it_points_at():
    text = _sentences(80)

    chunks = DocumentChunker().split(text)

    assert len(chunks) > 3
    assert all(text[c.char_start:c.char_end] == c.text for c in chunks)


def test_no_chunk_is_longer_than_the_chunk_size():
    text = _sentences(80, width=170)

    chunks = DocumentChunker(chunk_size=1000, overlap=200).split(text)

    assert max(len(chunk.text) for chunk in chunks) <= 1000


def test_consecutive_chunks_overlap_by_at_most_the_overlap():
    text = _sentences(80)

    chunks = DocumentChunker(chunk_size=1000, overlap=200).split(text)

    for previous, following in zip(chunks, chunks[1:], strict=False):
        shared = previous.char_end - following.char_start
        assert 0 < shared <= 200


def test_the_chunks_cover_every_sentence():
    text = _sentences(80)

    chunks = DocumentChunker().split(text)

    assert _non_space(text) <= _covered(chunks)


def test_a_sentence_longer_than_a_chunk_is_cut_between_words_with_overlap():
    words = " ".join(f"word{n:04d}" for n in range(400))

    chunks = DocumentChunker(chunk_size=1000, overlap=200).split(words)

    assert len(chunks) >= 4
    assert all(len(chunk.text) <= 1000 for chunk in chunks)
    assert all(chunk.text.startswith("word") and chunk.text[-4:].isdigit() for chunk in chunks)
    for previous, following in zip(chunks, chunks[1:], strict=False):
        assert following.char_start < previous.char_end
    assert _non_space(words) <= _covered(chunks)


def test_line_breaks_end_a_sentence():
    text = "# Heading\n- first item\n- second item"

    chunker = DocumentChunker(chunk_size=20, overlap=0)

    assert [chunk.text for chunk in chunker.split(text)] == [
        "# Heading",
        "- first item",
        "- second item",
    ]


def test_without_overlap_chunks_do_not_share_text():
    text = _sentences(40)

    chunks = DocumentChunker(chunk_size=300, overlap=0).split(text)

    assert len(chunks) > 1
    for previous, following in zip(chunks, chunks[1:], strict=False):
        assert following.char_start >= previous.char_end


def test_chunk_document_returns_the_chunk_texts():
    text = _sentences(40)
    chunker = DocumentChunker(chunk_size=300, overlap=50)

    assert chunker.chunk_document(text) == [chunk.text for chunk in chunker.split(text)]


@pytest.mark.parametrize(("chunk_size", "overlap"), [(0, 0), (100, 100), (100, -1)])
def test_invalid_sizes_are_refused(chunk_size, overlap):
    with pytest.raises(ValueError):
        DocumentChunker(chunk_size=chunk_size, overlap=overlap)


class TestPageOf:
    def test_a_position_maps_to_the_page_it_falls_on(self):
        starts = (0, 100, 250)

        assert [page_of(at, starts) for at in (0, 99, 100, 249, 250, 999)] == [1, 1, 2, 2, 3, 3]

    def test_no_page_starts_means_the_page_is_unknown(self):
        assert page_of(10, ()) is None
