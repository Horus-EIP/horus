"""
Unit tests for ContentAnalyzer - Phase 2a Core + Phase 2b LLM Integration.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.content_analyzer import (
    CATEGORY_KEYWORDS,
    CONFIDENCE_THRESHOLD,
    ContentAnalyzer,
)


class TestKeywordClassification:
    """Tests for keyword-based classification."""

    def test_accounting_document_high_confidence(self):
        """Documents with accounting keywords get high confidence."""
        analyzer = ContentAnalyzer(init_llm=False)
        text = "Invoice #123. Payment of €1,500 due. Budget report for Q1. Tax audit."
        result = analyzer.analyze(text)
        assert result["auto_category"] == "accounting"
        assert result["confidence_score"] >= CONFIDENCE_THRESHOLD

    def test_hr_document_classification(self):
        """HR documents classified correctly."""
        analyzer = ContentAnalyzer(init_llm=False)
        text = "Employee onboarding policy. Intern compensation. Benefits and vacation."
        result = analyzer.analyze(text)
        assert result["auto_category"] == "hr"
        assert result["confidence_score"] >= 0.4

    def test_low_confidence_triggers_llm_fallback(self):
        """When keyword confidence < 0.6, _classify_with_llm is called."""
        analyzer = ContentAnalyzer(init_llm=False)
        text = "Some ambiguous document with no clear category keywords."
        with patch.object(analyzer, "_classify_with_llm", return_value="legal") as mock_llm:
            result = analyzer.analyze(text)
            if result["confidence_score"] < CONFIDENCE_THRESHOLD:
                mock_llm.assert_called()
            assert result["auto_category"] in list(CATEGORY_KEYWORDS.keys())

    def test_invoice_document_type(self):
        """Invoice keywords trigger invoice doc type."""
        analyzer = ContentAnalyzer(init_llm=False)
        text = "This is an invoice for payment due on January 15."
        result = analyzer.analyze(text)
        assert result["auto_type"] == "invoice"

    def test_unknown_text_returns_standard_type(self):
        """Text with no doc type keywords returns 'standard'."""
        analyzer = ContentAnalyzer(init_llm=False)
        text = "Just some random text here with no document markers."
        result = analyzer.analyze(text)
        assert result["auto_type"] == "standard"


class TestLLMClassification:
    """Tests for LLM-based classification (mocked)."""

    def test_classify_with_llm_returns_category(self):
        """_classify_with_llm returns valid category when LLM succeeds."""
        analyzer = ContentAnalyzer(init_llm=False)
        analyzer._classify_pipe = MagicMock()
        analyzer._classify_pipe.return_value = [{"generated_text": "accounting"}]

        result = analyzer._classify_with_llm("Invoice and payment terms.")
        assert result == "accounting"

    def test_classify_with_llm_graceful_fallback_when_none(self):
        """_classify_with_llm returns None when pipeline is unavailable."""
        analyzer = ContentAnalyzer(init_llm=False)
        analyzer._classify_pipe = None

        result = analyzer._classify_with_llm("Some text")
        assert result is None

    def test_classify_with_llm_graceful_fallback_on_exception(self):
        """_classify_with_llm returns None on exception."""
        analyzer = ContentAnalyzer(init_llm=False)
        analyzer._classify_pipe = MagicMock(side_effect=RuntimeError("Model error"))

        result = analyzer._classify_with_llm("Some text")
        assert result is None


class TestSummaryGeneration:
    """Tests for summary generation."""

    def test_llm_summary_when_available(self):
        """LLM summary used when pipeline available."""
        analyzer = ContentAnalyzer(init_llm=False)
        analyzer._summarize_pipe = MagicMock()
        analyzer._summarize_pipe.return_value = [{"summary_text": "This is the LLM summary."}]

        result = analyzer._generate_summary_with_llm("Long document text here.")
        assert result == "This is the LLM summary."

    def test_extractive_fallback_when_llm_fails(self):
        """Extractive summary used when LLM fails."""
        analyzer = ContentAnalyzer(init_llm=False)
        analyzer._summarize_pipe = None

        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        result = analyzer.analyze(text)
        assert result["auto_summary"]
        assert "First sentence" in result["auto_summary"] or "sentence" in result["auto_summary"]

    def test_graceful_fallback_on_llm_exception(self):
        """Summary fallback when LLM raises."""
        analyzer = ContentAnalyzer(init_llm=False)
        analyzer._summarize_pipe = MagicMock(side_effect=RuntimeError("Out of memory"))

        result = analyzer._generate_summary_with_llm("Some text to summarize.")
        assert result is None


class TestEntityExtraction:
    """Tests for entity extraction."""

    def test_extract_amounts(self):
        """Amounts extracted from text."""
        analyzer = ContentAnalyzer(init_llm=False)
        text = "Payment of €1,500 and $2,000. Total EUR 3,500."
        result = analyzer.analyze(text)
        assert len(result["entities"]["amounts"]) >= 1

    def test_extract_dates(self):
        """Dates extracted from text."""
        analyzer = ContentAnalyzer(init_llm=False)
        text = "Due date: 15/03/2024. Meeting on 2024-01-10."
        result = analyzer.analyze(text)
        assert len(result["entities"]["dates"]) >= 1

    def test_entities_have_all_keys(self):
        """Entity dict always has people, companies, amounts, dates."""
        analyzer = ContentAnalyzer(init_llm=False)
        text = "Some generic text."
        result = analyzer.analyze(text)
        entities = result["entities"]
        assert "people" in entities
        assert "companies" in entities
        assert "amounts" in entities
        assert "dates" in entities


class TestEmptyContent:
    """Tests for edge cases."""

    def test_empty_content_returns_general(self):
        """Empty content returns general category."""
        analyzer = ContentAnalyzer(init_llm=False)
        result = analyzer.analyze("")
        assert result["auto_category"] == "general"
        assert result["confidence_score"] == 0.0
        assert result["auto_summary"] == ""

    def test_whitespace_only_returns_general(self):
        """Whitespace-only returns general."""
        analyzer = ContentAnalyzer(init_llm=False)
        result = analyzer.analyze("   \n\t  ")
        assert result["auto_category"] == "general"


class TestConfidenceScoring:
    """Tests for confidence scoring logic."""

    def test_confidence_threshold_constant(self):
        """CONFIDENCE_THRESHOLD is 0.6 as per acceptance criteria."""
        assert CONFIDENCE_THRESHOLD == 0.6

    def test_high_keyword_match_high_confidence(self):
        """Strong keyword match yields confidence >= 0.6."""
        analyzer = ContentAnalyzer(init_llm=False)
        text = "Invoice payment budget tax audit financial accounting payroll salary"
        result = analyzer.analyze(text)
        assert result["confidence_score"] >= CONFIDENCE_THRESHOLD
        assert result["auto_category"] == "accounting"


class TestTopicExtraction:
    """Tests for topic extraction (simple fallback mode)."""

    def test_simple_topics_extracted(self):
        """Simple frequency-based topics are extracted when spaCy is unavailable."""
        import app.services.content_analyzer as ca_mod
        original_model = ca_mod._nlp_model
        ca_mod._nlp_model = False
        try:
            analyzer = ContentAnalyzer(init_llm=False)
            text = (
                "Machine learning and artificial intelligence drive data science forward. "
                "Machine learning models require training data. "
                "Artificial intelligence research continues to advance machine learning techniques."
            )
            result = analyzer.analyze(text)
            assert len(result["topics"]) >= 1
        finally:
            ca_mod._nlp_model = original_model

    def test_topics_is_list(self):
        """Topics should always be a list."""
        analyzer = ContentAnalyzer(init_llm=False)
        result = analyzer.analyze("Simple text.")
        assert isinstance(result["topics"], list)


class TestReturnFormat:
    """Tests that the return dict has the correct keys."""

    def test_all_keys_present(self):
        """analyze() returns all expected keys."""
        analyzer = ContentAnalyzer(init_llm=False)
        result = analyzer.analyze("Test document about accounting invoices.")
        expected_keys = {"auto_category", "auto_type", "auto_summary", "entities", "topics", "confidence_score"}
        assert expected_keys == set(result.keys())

    def test_title_param_accepted(self):
        """analyze() accepts optional title parameter."""
        analyzer = ContentAnalyzer(init_llm=False)
        result = analyzer.analyze("Invoice content", title="Invoice #123")
        assert result["auto_type"] == "invoice"
