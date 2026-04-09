"""
content_analyzer.py
-------------------
ContentAnalyzer service that automatically analyzes uploaded documents to extract
categories, entities, topics, and summaries.

Combines spaCy NER with regex-based extraction and keyword-based classification.
Optionally uses LLM fallback for classification when keyword confidence is low,
and LLM-powered summary generation when transformers models are available.
"""

from __future__ import annotations

import os
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from collections import Counter

logger = logging.getLogger(__name__)

try:
    from spacy.lang.en.stop_words import STOP_WORDS
except ImportError:
    STOP_WORDS = set()

CATEGORY_KEYWORDS = {
    "accounting": [
        "invoice", "receipt", "bill", "payment", "tax", "vat", "ledger",
        "balance sheet", "p&l", "profit", "loss", "budget", "audit",
        "expense", "reimbursement", "payroll", "cfo", "finance", "account",
        "fiscal", "currency", "cost", "bank statement", "remittance",
        "eur", "usd", "€", "$", "amount", "salary", "compensation", "revenue",
    ],
    "hr": [
        "resume", "cv", "curriculum vitae", "contract", "offer letter",
        "hiring", "onboarding", "employee", "candidate", "interview",
        "termination", "resignation", "holiday", "vacation", "leave",
        "sick leave", "salary", "bonus", "benefits", "insurance",
        "human resources", "personnel", "workforce", "intern",
        "recruit", "policy", "performance", "training",
    ],
    "legal": [
        "agreement", "nda", "non-disclosure", "confidentiality", "contract",
        "clause", "gdpr", "compliance", "regulation", "law", "legal",
        "litigation", "lawsuit", "dispute", "intellectual property",
        "trademark", "copyright", "license", "terms of service", "conditions",
        "privacy policy", "attorney", "lawyer", "affidavit", "signature",
        "liability", "court",
    ],
    "operations": [
        "logistics", "supply chain", "inventory", "stock", "procurement",
        "purchase order", "shipping", "freight", "delivery", "warehouse",
        "maintenance", "facility", "facilities", "operations", "ops",
        "process", "procedure", "roster", "schedule", "planning",
        "supplier", "vendor", "manufacturing", "workflow", "production",
    ],
    "sales": [
        "proposal", "quote", "quotation", "crm", "lead", "prospect",
        "opportunity", "pipeline", "forecast", "deal", "client", "customer",
        "revenue", "sales", "discount", "pricing", "order", "purchase",
        "commission", "quota", "conversion",
    ],
    "technical": [
        "api", "sdk", "software", "hardware", "server", "database", "sql",
        "cloud", "aws", "azure", "architecture", "design document", "spec",
        "specification", "requirement", "bug", "issue", "jira", "git",
        "code", "script", "python", "java", "javascript", "devops",
        "ci/cd", "deployment", "technical", "manual", "user guide",
        "documentation", "readme", "integration", "system",
    ],
    "marketing": [
        "campaign", "social media", "brand", "branding", "seo", "sem",
        "content", "blog", "article", "newsletter", "analytics", "traffic",
        "conversion", "funnel", "market research", "advertising", "ad",
        "pr", "press release", "marketing", "cmo",
    ],
    "general": [
        "meeting", "minutes", "agenda", "memo", "memorandum", "announcement",
        "internal", "general", "admin", "administration", "office",
        "correspondence", "email", "letter", "note",
    ],
}

DOC_TYPE_KEYWORDS = {
    "invoice": [
        "invoice", "bill to", "ship to", "payment due", "invoice no",
        "invoice number", "tax invoice", "receipt", "total amount", "subtotal",
    ],
    "contract": [
        "agreement", "contract", "parties", "between", "witnesseth",
        "whereas", "signed", "signature", "effective date", "terms and conditions",
        "non-disclosure", "service level agreement", "sla",
    ],
    "resume": [
        "curriculum vitae", "cv", "resume", "work experience", "education",
        "skills", "languages", "certifications", "profile",
        "references", "contact",
    ],
    "financial_report": [
        "balance sheet", "profit and loss", "income statement", "cash flow",
        "financial statement", "audit report", "fiscal year", "quarterly report",
        "consolidated", "assets", "liabilities", "equity",
    ],
    "technical_spec": [
        "technical specification", "api reference", "system design",
        "architecture", "requirements", "user guide", "manual", "version",
        "changelog", "release notes", "endpoint", "parameters",
    ],
    "presentation": [
        "agenda", "overview", "introduction", "conclusion", "key takeaways",
        "roadmap", "next steps", "q&a", "slide",
    ],
    "email": [
        "subject:", "from:", "to:", "cc:", "bcc:", "sent:", "forwarded message",
        "original message", "regards", "best regards", "sincerely",
    ],
    "id_document": [
        "passport", "driver's license", "identity card", "nationality",
        "date of birth", "sex", "place of birth", "issued by", "expiry date",
    ],
    "memo": [
        "memorandum", "memo", "internal memo", "to:", "from:", "date:", "re:",
    ],
    "policy": ["policy", "policies", "guidelines"],
    "report": ["report", "summary", "analysis"],
}

CONFIDENCE_THRESHOLD = 0.6

_nlp_model = None


def _try_import_transformers() -> Tuple[bool, Any]:
    """Try to import transformers pipeline. Returns (success, pipeline_module)."""
    try:
        from transformers import pipeline
        return True, pipeline
    except Exception as e:
        logger.debug("Transformers not available: %s", e)
        return False, None


class ContentAnalyzer:
    """
    Analyzes document content to extract category, type, entities, topics, and summary.

    Combines spaCy NER with regex-based extraction. Uses keyword-based classification
    with optional LLM fallback when confidence < threshold.
    """

    def __init__(
        self,
        llm_model_name: str = "t5-small",
        summarization_model: str = "sshleifer/distilbart-cnn-6-6",
        init_llm: bool = True,
    ):
        global _nlp_model
        if _nlp_model is None:
            try:
                import spacy
                _nlp_model = spacy.load("en_core_web_trf")
                logger.info("spaCy model en_core_web_trf loaded successfully")
            except (OSError, IOError, ImportError):
                logger.warning(
                    "spaCy model en_core_web_trf not available; "
                    "entity extraction will use regex fallback"
                )
                _nlp_model = False

        self.nlp = _nlp_model if _nlp_model is not False else None
        self.category_keywords = CATEGORY_KEYWORDS
        self.doc_type_keywords = DOC_TYPE_KEYWORDS

        self.llm_model_name = llm_model_name
        self.summarization_model = summarization_model
        self._classify_pipe = None
        self._summarize_pipe = None
        if init_llm:
            self._init_llm()

    # ------------------------------------------------------------------
    # LLM initialisation (Phase 2b)
    # ------------------------------------------------------------------

    def _init_llm(self) -> None:
        """Lazily initialize LLM pipelines for classification and summarization."""
        if os.getenv("HF_HUB_OFFLINE", "").strip().lower() in ("1", "true", "yes"):
            logger.info("Skipping optional HF pipelines (HF_HUB_OFFLINE=1); keyword/spaCy paths only.")
            return
        ok, pipeline_mod = _try_import_transformers()
        if not ok or pipeline_mod is None:
            return
        try:
            self._classify_pipe = pipeline_mod(
                "text2text-generation",
                model=self.llm_model_name,
                device=-1,
            )
            logger.info("LLM classification pipeline initialized (%s)", self.llm_model_name)
        except Exception as e:
            logger.warning("Could not init classification pipeline: %s", e)
        try:
            self._summarize_pipe = pipeline_mod(
                "summarization",
                model=self.summarization_model,
                device=-1,
            )
            logger.info("LLM summarization pipeline initialized (%s)", self.summarization_model)
        except Exception as e:
            logger.warning("Could not init summarization pipeline: %s", e)

    # ------------------------------------------------------------------
    # Main analysis entry point
    # ------------------------------------------------------------------

    def analyze(self, text: str, title: str = "") -> Dict[str, Any]:
        """
        Perform a comprehensive analysis of the provided text.

        Returns a dict with keys: auto_category, auto_type, auto_summary,
        entities, topics, confidence_score.
        """
        text = (text or "").strip()
        if not text:
            return self._empty_analysis()

        category, confidence = self._classify_category(text)

        if confidence < CONFIDENCE_THRESHOLD:
            llm_category = self._classify_with_llm(text)
            if llm_category:
                category = llm_category
                confidence = 0.85

        regex_entities = self._extract_entities_regex(text)

        if self.nlp:
            doc = self.nlp(text[:5000])
            spacy_entities = self._extract_entities_spacy(doc)
            topics = self._extract_topics_spacy(doc)

            all_dates = list(set(
                regex_entities.get("dates", []) + spacy_entities.get("dates", [])
            ))
            all_amounts = list(set(
                regex_entities.get("amounts", []) + spacy_entities.get("amounts", [])
            ))
            entities = {
                "people": spacy_entities.get("people", []),
                "companies": spacy_entities.get("companies", []),
                "amounts": all_amounts,
                "dates": all_dates,
            }
        else:
            entities = regex_entities
            entities.setdefault("people", [])
            entities.setdefault("companies", [])
            topics = self._extract_topics_simple(text)

        doc_type = self._detect_document_type(text, title)

        summary = self._generate_summary_with_llm(text)
        if not summary:
            if self.nlp:
                nlp_doc = self.nlp(text[:10000]) if len(text) > 5000 else doc
                summary = self._generate_summary_spacy(nlp_doc)
            else:
                summary = self._extractive_summary(text)

        logger.info(
            "Analysis complete. Category: %s (%.2f), Type: %s, Topics: %d",
            category, confidence, doc_type, len(topics),
        )

        return {
            "auto_category": category,
            "auto_type": doc_type,
            "auto_summary": summary,
            "entities": entities,
            "topics": topics,
            "confidence_score": round(confidence, 2),
        }

    def _empty_analysis(self) -> Dict[str, Any]:
        return {
            "auto_category": "general",
            "auto_type": "unknown",
            "auto_summary": "",
            "entities": {"people": [], "companies": [], "amounts": [], "dates": []},
            "topics": [],
            "confidence_score": 0.0,
        }

    # ------------------------------------------------------------------
    # Category classification
    # ------------------------------------------------------------------

    def _classify_category(self, text: str) -> Tuple[str, float]:
        """Classify using keyword matching. Returns (category, confidence)."""
        text_lower = text.lower()
        scores: Dict[str, int] = {}

        for cat, keywords in self.category_keywords.items():
            count = sum(1 for kw in keywords if kw in text_lower)
            if count > 0:
                scores[cat] = count

        if not scores:
            return "general", 0.3

        best_cat = max(scores, key=scores.get)
        best_count = scores[best_cat]
        total_keywords = len(self.category_keywords.get(best_cat, []))
        confidence = min(0.95, 0.5 + (best_count / max(total_keywords * 0.2, 1)) * 0.5)
        return best_cat, confidence

    def _classify_with_llm(self, text: str) -> Optional[str]:
        """LLM classification fallback when keyword confidence < threshold."""
        if self._classify_pipe is None:
            return None

        snippet = text[:1500]
        categories_str = ", ".join(CATEGORY_KEYWORDS.keys())
        prompt = (
            f"Classify this document into exactly one category. "
            f"Categories: {categories_str}. "
            f"Reply with only the category name, nothing else.\n\n"
            f"Document:\n{snippet}"
        )
        try:
            result = self._classify_pipe(prompt, max_length=20, min_length=1, do_sample=False)
            if result and isinstance(result, list) and result[0].get("generated_text"):
                raw = result[0]["generated_text"].strip().lower()
                for cat in CATEGORY_KEYWORDS:
                    if cat in raw or raw.startswith(cat[:4]):
                        return cat
                return "general"
        except Exception as e:
            logger.warning("LLM classification failed: %s", e)
        return None

    # ------------------------------------------------------------------
    # Entity extraction
    # ------------------------------------------------------------------

    def _extract_entities_regex(self, text: str) -> Dict[str, List[str]]:
        """Extract amounts and dates using regex."""
        regex_amounts = (
            r"(?:\$|€|USD|EUR)\s?\d+(?:[.,]\d+)*"
            r"|\d+(?:[.,]\d+)*\s?(?:\$|€|USD|EUR)"
        )
        amounts = re.findall(regex_amounts, text)

        months = (
            "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
            "|January|February|March|April|June|July|August"
            "|September|October|November|December"
        )
        patt_num = r"\b\d{4}[-/.]\d{2}[-/.]\d{2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b"
        patt_text = (
            rf"\b(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{months})[,\s]+\d{{4}}"
            rf"|(?:{months})\s+\d{{1,2}}(?:st|nd|rd|th)?[,\s]+\d{{4}})\b"
        )
        patt_month_year = rf"\b(?:{months})[,\s]+\d{{4}}\b"
        patt_no_year = (
            rf"\b(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{months})"
            rf"|(?:{months})\s+\d{{1,2}}(?:st|nd|rd|th)?)\b"
        )
        patt_year = r"\b(?:19|20)\d{2}\b"
        full_date_pattern = f"{patt_num}|{patt_text}|{patt_month_year}|{patt_no_year}|{patt_year}"
        dates = [d.strip() for d in re.findall(full_date_pattern, text, re.IGNORECASE) if d.strip()]

        return {"amounts": amounts, "dates": dates}

    def _extract_entities_spacy(self, doc) -> Dict[str, List[str]]:
        """Extract named entities using spaCy NER."""
        people, companies, money, dates = [], [], [], []

        for ent in doc.ents:
            if ent.label_ == "PERSON":
                people.append(ent.text.strip())
            elif ent.label_ == "ORG":
                companies.append(ent.text.strip())
            elif ent.label_ == "MONEY":
                money.append(ent.text.strip())
            elif ent.label_ == "DATE":
                dates.append(ent.text.strip())

        return {
            "people": list(set(people)),
            "companies": list(set(companies)),
            "amounts": list(set(money)),
            "dates": list(set(dates)),
        }

    # ------------------------------------------------------------------
    # Topic extraction
    # ------------------------------------------------------------------

    def _extract_topics_spacy(self, doc, max_topics: int = 10) -> List[str]:
        """Extract topics from spaCy noun chunks."""
        chunks = []
        for chunk in doc.noun_chunks:
            root = chunk.root
            if root.pos_ not in ("PROPN", "NOUN"):
                continue
            if root.is_punct or root.is_stop or root.text.lower() in STOP_WORDS:
                continue
            if len(chunk.text.strip()) < 3:
                continue
            chunks.append(chunk.text.lower().strip())

        counts = Counter(chunks)
        return [term for term, _ in counts.most_common(max_topics)]

    def _extract_topics_simple(self, text: str, max_topics: int = 5) -> List[str]:
        """Fallback topic extraction using word frequency."""
        words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
        stop = {
            "that", "this", "with", "from", "have", "been", "were",
            "which", "their", "there", "would", "could", "about",
            "these", "other", "some", "also", "more", "when",
        }
        freq: Dict[str, int] = {}
        for w in words:
            if w not in stop:
                freq[w] = freq.get(w, 0) + 1
        return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:max_topics]]

    # ------------------------------------------------------------------
    # Document type detection
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str, title: str = "") -> str:
        """Detect document type from content and title using keyword matching."""
        combined = f"{title} {text}".lower()
        scores: Dict[str, int] = {}

        for doc_type, keywords in self.doc_type_keywords.items():
            count = sum(1 for kw in keywords if kw in combined)
            if count > 0:
                scores[doc_type] = count

        if not scores:
            return "standard"
        return max(scores, key=scores.get)

    # ------------------------------------------------------------------
    # Summary generation
    # ------------------------------------------------------------------

    def _generate_summary_with_llm(self, text: str, max_length: int = 150) -> Optional[str]:
        """Generate summary using LLM. Returns None on failure (graceful fallback)."""
        if self._summarize_pipe is None:
            return None
        snippet = text[:1024] if len(text) > 1024 else text
        try:
            result = self._summarize_pipe(
                snippet, max_length=max_length, min_length=30, do_sample=False,
            )
            if result and isinstance(result, list) and result[0].get("summary_text"):
                return result[0]["summary_text"].strip()
        except Exception as e:
            logger.warning("LLM summary generation failed: %s", e)
        return None

    def _generate_summary_spacy(self, doc, max_sentences: int = 3) -> str:
        """Extractive summary using spaCy sentence boundaries."""
        sentences = []
        for i, sent in enumerate(doc.sents):
            if i >= max_sentences:
                break
            sentences.append(sent.text.replace("\n", " ").strip())
        return " ".join(sentences)

    def _extractive_summary(self, text: str, max_sentences: int = 3) -> str:
        """Simple extractive summary fallback using regex sentence splitting."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) <= max_sentences:
            return text.strip()
        return " ".join(sentences[:max_sentences]).strip()
