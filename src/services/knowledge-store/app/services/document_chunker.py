from typing import List, Dict, Any
from app.core.logging import get_logger
import spacy

logger = get_logger("DocumentChunker")
_nlp_model = None

class DocumentChunker:
    """
    Service for splitting large text documents into smaller, overlapping chunks
    suitable for embedding and retrieval.
    """
    
    def __init__(self, chunk_size=1000, overlap=200):
        """
        Initialize the DocumentChunker.

        Args:
            chunk_size (int): The maximum size of each chunk in characters.
            overlap (int): The number of characters to overlap between chunks.
        
        Raises:
            RuntimeError: If the Spacy model cannot be loaded or found.
        """
        global _nlp_model
        if _nlp_model is None:
            try:
                _nlp_model = spacy.load("en_core_web_trf")
                logger.info("Spacy model loaded successfully")
            except (OSError, IOError):
                logger.info("Downloading Spacy model...")
                raise RuntimeError("Spacy model not found. Please download it using 'python -m spacy download en_core_web_trf'.")

        self.nlp = _nlp_model

        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_document(self, text: str) -> List[str]:
        """
        Split a document into chunks.

        Args:
            text (str): The full text of the document.

        Returns:
            List[str]: A list of text chunks.
        """
        logger.info(f"Starting document chunking. Text length: {len(text)} chars.")
        doc = self.nlp(text)
        chunks = self._text_divider(doc)
        logger.info(f"Document chunking completed. Generated {len(chunks)} chunks.")

        return chunks
    
    def _compute_overlap(self, sentences: List[str]) -> List[str]:
        """
        Calculate the overlapping sentences for the next chunk.

        Args:
            sentences (List[str]): The list of sentences in the current chunk.

        Returns:
            List[str]: The list of sentences to include in the next chunk as overlap.
        """
        current_overlap = 0
        overlap_sentences = []

        for sentence in reversed(sentences):
            if len(sentence) + current_overlap > self.overlap:
                break
            else:
                overlap_sentences.insert(0, sentence)
                current_overlap += len(sentence)
        
        if not overlap_sentences and sentences:
            overlap_sentences.append(sentences[-1])

        return overlap_sentences
    
    def _text_divider(self, doc) -> List[str]:
        """
        Divide the processed document into chunks based on sentence boundaries and size limits.

        Args:
            doc (spacy.tokens.Doc): The processed Spacy document.

        Returns:
            List[str]: A list of text chunks.
        """
        chunks = []
        current_sentences = []
        len_buffer = 0
        for sentence in doc.sents:
            clean_sentence = sentence.text.replace("\n", " ").strip()
            if not clean_sentence:
                continue

            if len_buffer + len(clean_sentence) > self.chunk_size and current_sentences:
                chunk = " ".join(current_sentences)
                chunks.append(chunk)
                current_sentences = self._compute_overlap(current_sentences)
                current_sentences.append(clean_sentence)
                len_buffer = sum(len(s) for s in current_sentences)
            else:
                current_sentences.append(clean_sentence)
                len_buffer += len(clean_sentence)
        
        if current_sentences:
            chunk = " ".join(current_sentences)
            chunks.append(chunk)

        return chunks
