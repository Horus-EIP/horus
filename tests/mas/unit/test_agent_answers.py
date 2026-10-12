from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.schemas import MAX_ANSWER_SOURCES, TaskResultForm, TaskResultStatus
from tasks.agent_answers import (
    MAX_ANSWER_ATTEMPTS,
    alternative_retrieval_query,
    keyword_query,
    merge_sources,
    retry_plan,
)

Q4 = {"doc_id": "doc-q4", "chunk_id": "doc-q4:3", "title": "q4.md", "page": 2}
Q4_OTHER_PASSAGE = {"doc_id": "doc-q4", "chunk_id": "doc-q4:5", "title": "q4.md", "page": 3}
EXPENSES = {"doc_id": "doc-expense", "chunk_id": "doc-expense:0", "title": "expenses.md", "page": None}
ATTACHED = {"doc_id": "doc-notes", "chunk_id": None, "title": "notes.txt", "page": None}


def _record(attempt=1, **payload):
    return {
        "attempt": attempt,
        "payload": {"task_id": "t1", "demand": "What was the Q4 2025 revenue?", **payload},
    }


class TestMergeSources:
    def test_every_source_is_kept_once_in_the_order_it_was_first_cited(self):
        merged = merge_sources([[Q4, EXPENSES], [EXPENSES, Q4_OTHER_PASSAGE], [Q4]])

        assert merged == [Q4, EXPENSES, Q4_OTHER_PASSAGE]

    def test_a_document_without_chunks_is_kept_once_by_its_id(self):
        assert merge_sources([[ATTACHED], [dict(ATTACHED)]]) == [ATTACHED]

    def test_steps_that_sent_no_sources_are_skipped(self):
        assert merge_sources([None, [Q4], None]) == [Q4]

    def test_no_step_with_sources_gives_none(self):
        assert merge_sources([None, None]) is None

    def test_steps_that_cited_nothing_give_an_empty_list(self):
        assert merge_sources([[], None]) == []


class TestOtherQuery:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("What was the Q4 2025 revenue?", "Q4 2025 revenue"),
            ("Can you tell me the hotel cap in the Expense Policy?", "hotel cap Expense Policy"),
            ("What is the $250 cap, and is it per night?", "$250 cap per night"),
            ("What is it?", None),
        ],
    )
    def test_the_keyword_query_keeps_the_words_that_carry_meaning(self, text, expected):
        assert keyword_query(text) == expected

    def test_a_chain_step_tries_the_question_the_user_asked(self):
        payload = {"demand": "transcript", "retrieval_query": "find the Q4 revenue"}

        assert alternative_retrieval_query(payload, "How did Q4 compare?") == "How did Q4 compare?"

    def test_a_single_question_tries_its_keywords(self):
        payload = {"demand": "What was the Q4 2025 revenue?"}

        assert alternative_retrieval_query(payload, None) == "Q4 2025 revenue"

    def test_a_query_that_is_already_its_keywords_has_no_other(self):
        assert alternative_retrieval_query({"demand": "Q4 2025 revenue"}, None) is None

    def test_the_same_question_in_other_case_or_punctuation_is_not_another_query(self):
        payload = {"demand": "x", "retrieval_query": "Q4 2025 revenue?"}

        assert alternative_retrieval_query(payload, "q4 2025 REVENUE") is None


class TestRetryPlan:
    def test_a_not_found_answer_is_tried_once_more_with_another_query(self):
        plan = retry_plan(_record(), TaskResultStatus.NOT_FOUND, "not_in_documents", None)

        assert plan.attempt == 2
        assert plan.payload["retrieval_query"] == "Q4 2025 revenue"
        assert plan.payload["demand"] == "What was the Q4 2025 revenue?"
        assert "another query" in plan.detail

    def test_the_last_attempt_is_not_tried_again(self):
        record = _record(attempt=MAX_ANSWER_ATTEMPTS)

        assert retry_plan(record, TaskResultStatus.NOT_FOUND, None, None) is None
        assert retry_plan(record, TaskResultStatus.FAILED, "invalid_output", None) is None

    def test_a_failed_answer_without_another_query_is_tried_once_more_as_it_was(self):
        plan = retry_plan(
            _record(demand="Q4 revenue"), TaskResultStatus.FAILED, "retrieval_error", None
        )

        assert plan.payload == {"task_id": "t1", "demand": "Q4 revenue", "attempt": 2}
        assert "once more" in plan.detail

    def test_a_timed_out_answer_is_not_tried_again(self):
        assert retry_plan(_record(), TaskResultStatus.FAILED, "timeout", None) is None

    def test_a_completed_answer_is_never_tried_again(self):
        assert retry_plan(_record(), TaskResultStatus.COMPLETED, None, None) is None

    def test_a_dispatch_that_cannot_be_replayed_is_not_tried_again(self):
        assert retry_plan(None, TaskResultStatus.NOT_FOUND, None, None) is None
        assert (
            retry_plan({"attempt": 1, "payload": None}, TaskResultStatus.NOT_FOUND, None, None)
            is None
        )


class TestTaskResultForm:
    def _form(self, **over):
        body = {"task_id": "t1", "agent_id": "a1", "result": "Revenue was $4.2M.", **over}
        return TaskResultForm(**body)

    def test_a_not_found_answer_is_accepted(self):
        assert self._form(status="not_found").status is TaskResultStatus.NOT_FOUND

    def test_sources_are_structured(self):
        form = self._form(sources=[{**Q4, "page": "2"}, {"title": "notes.txt"}])

        assert [source.model_dump() for source in form.sources] == [
            Q4,
            {"doc_id": None, "chunk_id": None, "title": "notes.txt", "page": None},
        ]

    def test_a_page_that_is_not_a_number_is_rejected(self):
        with pytest.raises(ValidationError):
            self._form(sources=[{**Q4, "page": "two"}])

    def test_too_many_sources_are_rejected(self):
        with pytest.raises(ValidationError):
            self._form(sources=[Q4] * (MAX_ANSWER_SOURCES + 1))
