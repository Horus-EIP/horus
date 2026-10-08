# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from horus_bench_kit.eval_compare import compare_markdown, compare_reports, load_eval_report
from horus_bench_kit.files import write_json
from horus_bench_kit.report import Profile, blank_review, build_report, question_record


@pytest.fixture
def items(make_item):
    return [
        make_item(id="t-01"),
        make_item(
            id="t-02",
            question="Who is the harbour master?",
            expected_answer="Odile Brandt.",
            expected_source="harbour-rules.md",
            answer_patterns=["Brandt"],
        ),
        make_item(
            id="t-03",
            category="direct",
            question="What is 3 + 4?",
            expected_answer="7",
            expected_source=None,
            answer_patterns=[r"\b7\b"],
        ),
    ]


def outcome(answer, total_s=2.0, ttft_s=0.5, status="ok", cited=None):
    return {
        "mode": "chat",
        "status": status,
        "answer": answer,
        "timing_source": "http",
        "total_s": total_s,
        "ttft_s": ttft_s,
        "models": ["harbour-7b"],
        "cited_sources": cited,
    }


def make_report(items, answers, label="run", sha256="a" * 64, completed=True, **outcome_overrides):
    records = [
        question_record(item, outcome(answers[item["id"]], **outcome_overrides.get(item["id"], {})))
        for item in items
    ]
    return build_report(
        label=label,
        run={
            "target": "openai",
            "model": "harbour-7b",
            "started_at": "2026-10-08T09:00:00Z",
            "finished_at": "2026-10-08T09:05:00Z" if completed else None,
            "completed": completed,
        },
        testset={"path": "harbour.json", "version": "1.0.0", "sha256": sha256, "items_total": 3, "items_run": 3},
        records=records,
    )


@pytest.fixture
def before(items):
    return make_report(items, {"t-01": "Fourteen.", "t-02": "Nobody.", "t-03": "7"}, label="small")


@pytest.fixture
def after(items):
    answers = {"t-01": "Twelve.", "t-02": "Odile Brandt.", "t-03": "7"}
    return make_report(items, answers, label="large", **{"t-01": {"total_s": 4.0}})


class TestOneReport:
    def test_header_metrics_and_categories_without_a_change_column(self, before):
        markdown = compare_reports([before])
        lines = markdown.splitlines()
        assert lines[0] == "# Evaluation"
        assert "| Label | small |" in lines
        assert "| Report | horus-bench-kit-eval v1 |" in lines
        assert "| Model | harbour-7b |" in lines
        assert "| Test set | 1.0.0 (sha256 aaaaaaaaaaaa…), 3 of 3 questions |" in lines
        assert "| Answers correct, automatic (%) | every answer pattern matches | 66.7% (n=3) |" in lines
        assert "| Questions answered | status ok | 3 (n=3) |" in lines
        assert "| lookup | 50.0% (n=2) |" in lines
        assert "| direct | 100.0% (n=1) |" in lines
        assert "Change" not in markdown
        assert "## Questions that changed" not in markdown
        assert markdown.endswith("\n")

    def test_pending_reviews_are_flagged(self, before):
        assert "- run: 3 of 3 answers are not reviewed yet" in compare_reports([before])

    def test_reviewed_answers_fill_the_reviewed_rate(self, before):
        for question in before["questions"]:
            question["review"] = blank_review()
            for slot in question["review"]:
                slot.update(reviewer="ana", answer_correct=True)
        markdown = compare_reports([before])
        assert "| Answers correct, reviewed (%) | both reviewers marked it correct | 100.0% (n=3) |" in markdown
        assert "not reviewed yet" not in markdown

    def test_an_unfinished_run_is_flagged(self, items):
        report = make_report(items, {"t-01": "14", "t-02": "Brandt", "t-03": "7"}, completed=False)
        report["questions"] = report["questions"][:2]
        markdown = compare_reports([report])
        assert "| Finished | not finished |" in markdown
        assert "- run did not finish: 2 of 3 questions recorded." in markdown

    def test_table_cells_escape_pipes(self, before):
        before["label"] = "a|b"
        assert "| Label | a\\|b |" in compare_reports([before])


class TestTwoReports:
    def test_changes_and_question_flips(self, before, after):
        markdown = compare_reports([before, after])
        lines = markdown.splitlines()
        assert lines[0] == "# Evaluation comparison"
        assert "|  | before | after |" in lines
        assert "| Answers correct, automatic (%) | every answer pattern matches | 66.7% (n=3) | 66.7% (n=3) | +0.0 pts |" in lines
        assert "| Total time, median (s) | question sent to full answer | 2.00 s (n=3) | 2.00 s (n=3) | +0.00 s (+0%) |" in lines
        assert "| Total time, sum (s) | every question | 6.00 s (n=3) | 8.00 s (n=3) | +2.00 s (+33%) |" in lines
        assert "| Category | before (answers correct) | after (answers correct) | Change |" in lines
        assert "| Question | Category | Answer (before) | Answer (after) | Source (before) | Source (after) |" in lines
        assert "| t-01 | lookup | yes | no | — | — |" in lines
        assert "| t-02 | lookup | no | yes | — | — |" in lines
        assert not any(line.startswith("| t-03 |") for line in lines)

    def test_identical_runs_have_no_changed_question(self, before):
        assert "No question changed its automatic answer or source score." in compare_reports([before, before])

    def test_different_test_sets_and_question_lists_are_flagged(self, items, before):
        other = make_report(items[:2], {"t-01": "14", "t-02": "Brandt"}, sha256="b" * 64)
        markdown = compare_reports([before, other])
        assert "different test sets (sha256 aaaaaaaaaaaa… and bbbbbbbbbbbb…)" in markdown
        assert "did not ask the same questions: 1 only in before, 0 only in after." in markdown
        assert "| Total time, sum (s) | every question | 6.00 s (n=3) | 4.00 s (n=2) | not comparable: different question counts |" in markdown

    def test_source_flips_are_listed_too(self, items, before):
        cited = {"t-01": {"cited": ["north-pier.md"]}}
        right = make_report(items, {"t-01": "Fourteen.", "t-02": "Nobody.", "t-03": "7"}, **cited)
        assert "| t-01 | lookup | yes | yes | — | yes |" in compare_reports([before, right])

    def test_only_one_or_two_reports_compare(self, before):
        with pytest.raises(ValueError):
            compare_reports([before, before, before])


class TestReportFiles:
    def test_a_product_report_with_more_fields_and_sections_compares(self, tmp_path, items):
        profile = Profile(kind="acme-eval", schema_version=7, outcome_fields=("session", "ttft_s", "total_s"))
        records = [question_record(item, {**outcome("14"), "session": "s"}, profile) for item in items]
        report = build_report(
            label="acme",
            run={"started_at": "2026-10-08T09:00:00Z"},
            testset={},
            records=records,
            sections={"model": {"name": "acme-model"}, "machine": {"cores": 8}},
            profile=profile,
        )
        path = tmp_path / "acme.json"
        write_json(path, report)
        markdown = compare_markdown([path])
        assert "| Report | acme-eval v7 |" in markdown
        assert "| Model | acme-model |" in markdown
        assert "| Target | — |" in markdown

    def test_a_newer_kit_report_is_refused(self, tmp_path, before):
        path = tmp_path / "new.json"
        write_json(path, {**before, "schema_version": 2})
        with pytest.raises(ValueError, match="newer"):
            load_eval_report(path)

    def test_a_file_without_questions_is_refused(self, tmp_path):
        path = tmp_path / "bench.json"
        path.write_text(json.dumps({"kind": "llama-bench", "results": []}), encoding="utf-8")
        with pytest.raises(ValueError, match="bench.json is not an evaluation report"):
            load_eval_report(path)
        path.write_text(json.dumps([{"model": "m"}]), encoding="utf-8")
        with pytest.raises(ValueError, match="no questions list"):
            load_eval_report(path)

    def test_question_records_need_an_id_and_a_category(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text(json.dumps({"questions": [{"id": "x"}]}), encoding="utf-8")
        with pytest.raises(ValueError, match="broken.json: a question record has no category"):
            load_eval_report(path)
