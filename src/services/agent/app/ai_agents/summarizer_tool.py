"""
summarizer_tool.py
-------------------
Summarizes text. Implements Tool.run using transformers when available
and a simple extractive fallback otherwise.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional, Tuple
import os
import re
import logging

logger = logging.getLogger(__name__)

class SummarizerTool:
    name = "summarize"

    def __init__(self):
        self._pipe = None
        self._summarization_attempted = False

    def _ensure_summarization_pipeline(self) -> None:
        if self._summarization_attempted:
            return
        self._summarization_attempted = True
        if os.getenv("HF_HUB_OFFLINE", "").strip().lower() in ("1", "true", "yes"):
            logger.debug("Skipping HF summarization pipeline (HF_HUB_OFFLINE=1); using extractive path.")
            self._pipe = None
            return
        try:
            from transformers import pipeline

            self._pipe = pipeline("summarization")
        except (ImportError, Exception) as e:
            logger.debug(f"Transformers summarization pipeline not available: {e}")
            self._pipe = None

    def run(self, payload: Dict[str, Any]) -> str:
        """
        Run the summarization tool.
        
        Args:
            payload: Dict containing 'text' or 'query', optional 'max_sentences', 'protect_keywords'.
            
        Returns:
            The summary text.
        """
        text = (payload.get("text") or payload.get("query") or "").strip()
        logger.debug(f"SummarizerTool run invoke (text len={len(text)})")

        if not text:
            return ""
        max_sentences = int(payload.get("max_sentences") or 3)
        protect_keywords_raw = payload.get("protect_keywords")
        return_indices = bool(payload.get("return_indices"))

        protect_keywords: List[str] = []
        if protect_keywords_raw:
            if isinstance(protect_keywords_raw, list):
                protect_keywords = [str(k).lower().strip() for k in protect_keywords_raw if str(k).strip()]
            elif isinstance(protect_keywords_raw, str):
                parts = [p.strip() for p in re.split(r"[;,]", protect_keywords_raw) if p.strip()]
                protect_keywords = [p.lower() for p in parts]

        self._ensure_summarization_pipeline()

        # If protect/indices requested, use extractive for determinism and auditability
        if self._pipe is not None and not protect_keywords and not return_indices:
            try:
                result = self._pipe(text, max_length=200, min_length=30, do_sample=False)
                if isinstance(result, list) and result and isinstance(result[0], dict) and "summary_text" in result[0]:
                    return result[0]["summary_text"].strip()
            except Exception:
                pass

        summary, indices = self._extractive_summary(
            text, max_sentences=max_sentences, protect_keywords=protect_keywords
        )
        if return_indices:
            try:
                import json  # local import to avoid dependency if unused
                return json.dumps({"summary": summary, "kept_sentence_indices": indices})
            except Exception:
                # Fallback to a readable plain-text footer if JSON fails for any reason
                return f"{summary}\n\n[kept_sentence_indices: {indices}]"
        return summary

    def _extractive_summary(
        self, text: str, max_sentences: int, protect_keywords: Optional[List[str]] = None
    ) -> Tuple[str, List[int]]:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) <= max_sentences:
            return text, list(range(len(sentences)))

        words = re.findall(r"\w+", text.lower())
        freq: Dict[str, int] = {}
        for w in words:
            if len(w) <= 2:
                continue
            freq[w] = freq.get(w, 0) + 1

        def score(sentence: str) -> int:
            tokens = re.findall(r"\w+", sentence.lower())
            return sum(freq.get(t, 0) for t in tokens)

        protected_indices: List[int] = []
        if protect_keywords:
            kw_set = [k.lower() for k in protect_keywords]
            for i, s in enumerate(sentences):
                ls = s.lower()
                if any(k in ls for k in kw_set):
                    protected_indices.append(i)

        protected_indices = sorted(set(protected_indices))
        selected: List[int] = []
        # Take protected sentences first (in original order)
        for i in protected_indices:
            if len(selected) < max_sentences:
                selected.append(i)
            else:
                break

        # Rank remaining sentences by score
        remaining = [
            (score(s), i)
            for i, s in enumerate(sentences)
            if i not in set(selected)
        ]
        remaining.sort(key=lambda x: x[0], reverse=True)
        for _, i in remaining:
            if len(selected) >= max_sentences:
                break
            selected.append(i)

        selected.sort()
        summary = " ".join(sentences[i].strip() for i in selected).strip()
        return summary, selected


