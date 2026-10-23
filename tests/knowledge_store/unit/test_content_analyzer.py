"""
Unit tests for ContentAnalyzer - Phase 2a Core + Phase 2b LLM Integration.
"""

import json
import os
import subprocess
import sys
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
        expected_keys = {
            "auto_category",
            "auto_type",
            "auto_summary",
            "entities",
            "topics",
            "confidence_score",
        }
        assert expected_keys == set(result.keys())

    def test_title_param_accepted(self):
        """analyze() accepts optional title parameter."""
        analyzer = ContentAnalyzer(init_llm=False)
        result = analyzer.analyze("Invoice content", title="Invoice #123")
        assert result["auto_type"] == "invoice"


class TestSpacyModelChoice:
    def test_the_transformer_model_is_used_when_installed(self, monkeypatch):
        import spacy

        import app.services.content_analyzer as ca_mod

        monkeypatch.setattr(spacy, "load", MagicMock(side_effect=lambda name: f"nlp:{name}"))

        assert ca_mod._load_spacy_model() == "nlp:en_core_web_trf"

    def test_a_cpu_image_without_the_transformer_model_uses_the_small_one(self, monkeypatch):
        import spacy

        import app.services.content_analyzer as ca_mod

        def installed_models(name):
            if name == "en_core_web_trf":
                raise OSError(f"[E050] Can't find model '{name}'")
            return f"nlp:{name}"

        monkeypatch.setattr(spacy, "load", MagicMock(side_effect=installed_models))

        assert ca_mod._load_spacy_model() == "nlp:en_core_web_sm"

    def test_without_any_model_entities_come_from_the_regex_fallback(self, monkeypatch):
        import spacy

        import app.services.content_analyzer as ca_mod

        monkeypatch.setattr(spacy, "load", MagicMock(side_effect=OSError("[E050] no model")))

        assert ca_mod._load_spacy_model() is False


INVOICE = (
    "Invoice from Acme Corp to John Smith. Total due: $1,250.00 by 15 March 2026. "
    "A second payment of EUR 300 follows in April 2026."
)


class SpacyImports:
    def __init__(self):
        self.attempts: list[str] = []

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "spacy":
            self.attempts.append(name)
            raise ImportError(f"{name} must not be imported while spaCy is off")
        return None


@pytest.fixture
def spacy_off(monkeypatch):
    import app.services.content_analyzer as ca_mod

    monkeypatch.setenv("HORUS_SPACY", "off")
    monkeypatch.setattr(ca_mod, "_nlp_model", None)
    for name in [name for name in sys.modules if name.split(".")[0] == "spacy"]:
        monkeypatch.delitem(sys.modules, name)
    imports = SpacyImports()
    monkeypatch.setattr(sys, "meta_path", [imports, *sys.meta_path])
    return imports


class TestSpacyOff:
    @pytest.mark.parametrize("value", ["off", "OFF", " 0 ", "false", "no"])
    def test_the_setting_turns_spacy_off(self, monkeypatch, value):
        import app.services.content_analyzer as ca_mod

        monkeypatch.setenv("HORUS_SPACY", value)

        assert ca_mod.spacy_is_off()

    @pytest.mark.parametrize("value", [None, "", "on", "1", "yes"])
    def test_unset_or_on_leaves_spacy_on(self, monkeypatch, value):
        import app.services.content_analyzer as ca_mod

        if value is None:
            monkeypatch.delenv("HORUS_SPACY", raising=False)
        else:
            monkeypatch.setenv("HORUS_SPACY", value)

        assert not ca_mod.spacy_is_off()

    def test_with_spacy_off_spacy_is_never_imported_nor_loaded(self, spacy_off, caplog):
        with caplog.at_level("INFO", logger="app.services.content_analyzer"):
            analyzer = ContentAnalyzer(init_llm=False)
            analyzer.analyze(INVOICE)

        assert analyzer.nlp is None
        assert spacy_off.attempts == []
        assert "spacy" not in sys.modules
        assert "spaCy is off (HORUS_SPACY=off)" in caplog.text

    def test_with_spacy_off_the_regex_extraction_runs(self, spacy_off):
        result = ContentAnalyzer(init_llm=False).analyze(INVOICE)

        entities = result["entities"]
        assert entities["people"] == []
        assert entities["companies"] == []
        assert {"$1,250.00", "EUR 300"} <= set(entities["amounts"])
        assert "15 March 2026" in entities["dates"]
        assert "invoice" in result["topics"]
        assert result["auto_summary"].startswith("Invoice from Acme Corp")

    def test_with_spacy_on_the_model_loads_as_before(self, monkeypatch):
        import spacy

        import app.services.content_analyzer as ca_mod

        monkeypatch.setenv("HORUS_SPACY", "on")
        monkeypatch.setattr(spacy, "load", MagicMock(side_effect=lambda name: f"nlp:{name}"))

        assert ca_mod._load_spacy_model() == "nlp:en_core_web_trf"

    @pytest.mark.parametrize(("setting", "imports_spacy"), [("off", False), ("on", True)])
    def test_a_fresh_process_imports_spacy_only_when_it_is_on(self, setting, imports_spacy):
        import app.services.content_analyzer as ca_mod

        env = {**os.environ, "HORUS_SPACY": setting}
        done = subprocess.run(
            [sys.executable, "-B", "-c", FRESH_ANALYZER, ca_mod.__file__, INVOICE],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

        assert bool(json.loads(done.stdout.splitlines()[-1])) is imports_spacy


FRESH_ANALYZER = """
import importlib.util, json, sys
seen = []
class Watch:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "spacy":
            seen.append(name)
        return None
sys.meta_path.insert(0, Watch())
spec = importlib.util.spec_from_file_location("fresh_content_analyzer", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ContentAnalyzer(init_llm=False).analyze(sys.argv[2])
print(json.dumps(seen))
"""
