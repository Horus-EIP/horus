import pytest
from unittest.mock import MagicMock, patch
from app.services.document_chunker import DocumentChunker

@pytest.fixture(autouse=False)
def mock_spacy_chunker():
    import app.services.document_chunker as chunker_mod
    original_model = chunker_mod._nlp_model
    chunker_mod._nlp_model = None

    with patch("app.services.document_chunker.spacy") as mock_spacy_lib:
        nlp_mock = MagicMock()
        mock_spacy_lib.load.return_value = nlp_mock
        
        def nlp_side_effect(text):
            doc = MagicMock()
            raw_sents = [s.strip() for s in text.split('.') if s.strip()]
            sents_mocks = []
            for s in raw_sents:
                m = MagicMock()
                m.text = s + "."
                sents_mocks.append(m)
            doc.sents = sents_mocks
            return doc
            
        nlp_mock.side_effect = nlp_side_effect
        yield mock_spacy_lib

    chunker_mod._nlp_model = original_model

def test_chunk_document_basic(mock_spacy_chunker):
    chunker = DocumentChunker(chunk_size=100, overlap=20)
    text = "This is sentence one. This is sentence two. This is sentence three."
    
    chunks = chunker.chunk_document(text)
    assert isinstance(chunks, list)
    assert len(chunks) == 1
    assert "sentence one" in chunks[0]

def test_chunk_document_large(mock_spacy_chunker):
    # chunk_size small to force split
    chunker = DocumentChunker(chunk_size=20, overlap=5)
    text = "Short one. Short two. Short three. Short four."
    
    chunks = chunker.chunk_document(text)
    assert len(chunks) > 1
    # Check overlap
    # Overlap logic: last sentences of prev chunk inserted into new chunk.
    # We won't assert exact overlap logic here without tracing exact implementation
    # but we assert we have multiple chunks.

def test_chunker_init_exception():
    import app.services.document_chunker
    # Reset global singleton to force reload attempt
    original_model = app.services.document_chunker._nlp_model
    app.services.document_chunker._nlp_model = None
    
    try:
        with patch("app.services.document_chunker.spacy.load", side_effect=OSError("Error")):
            with pytest.raises(RuntimeError):
                DocumentChunker()
    finally:
        app.services.document_chunker._nlp_model = original_model

def test_compute_overlap_break():
    with patch("app.services.document_chunker.spacy.load"):
        # Overlap is 200 by default. chunk_size 1000.
        chunker = DocumentChunker(overlap=10) 
        
        # Sentences to overlap.
        # "Short" (5), "Short" (5). Total 10.
        # If we add another "Longer one", it might break.
        
        # Logic: 
        # for sentence in reversed(sentences):
        #   if len(sentence) + current_overlap > self.overlap: break
        
        s1 = "A" * 5
        s2 = "B" * 6  # 5+6 = 11 > 10. Should break after s1? No, reversed.
        
        # reversed: s2, s1.
        # s2: len 6. current 0. 6 <= 10. OK. overlap=["BBBBBB"], current=6.
        # s1: len 5. current 6. 11 > 10. Break.
        
        overlap_sentences = chunker._compute_overlap([s1, s2])
        assert len(overlap_sentences) == 1
        assert overlap_sentences[0] == s2

def test_text_divider_empty_sentence():
    with patch("app.services.document_chunker.spacy.load"):
        chunker = DocumentChunker()
        doc = MagicMock()
        
        s1 = MagicMock(); s1.text = "Valid."
        s2 = MagicMock(); s2.text = "\n  \n" # Empty after strip
        s3 = MagicMock(); s3.text = "Also valid."
        
        doc.sents = [s1, s2, s3]
        
        chunks = chunker._text_divider(doc)
        # Should ignore s2
        assert len(chunks) == 1 # Depending on size
        assert "Valid. Also valid." in chunks[0]

def test_text_divider_split():
    with patch("app.services.document_chunker.spacy.load"):
        chunker = DocumentChunker(chunk_size=10, overlap=0)
        doc = MagicMock()
        
        # "Five." (5)
        # "Five." (5) -> Total 10. OK.
        # "Five." (5) -> Total 15 > 10. Split.
        
        s1 = MagicMock(); s1.text = "Five."
        s2 = MagicMock(); s2.text = "Five."
        s3 = MagicMock(); s3.text = "Sixxxx."
        
        doc.sents = [s1, s2, s3]
        
        chunks = chunker._text_divider(doc)
        # Should contain at least 2 chunks
        assert len(chunks) >= 2
