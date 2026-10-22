from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from packaging.requirements import Requirement

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "compare-embeddings.py"
KNOWLEDGE_STORE_REQUIREMENTS = REPO / "src" / "services" / "knowledge-store" / "requirements.txt"
spec = importlib.util.spec_from_file_location("compare_embeddings", SCRIPT)
compare_embeddings = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = compare_embeddings
spec.loader.exec_module(compare_embeddings)

Sample = compare_embeddings.Sample
PASSAGE = compare_embeddings.PASSAGE
QUESTION = compare_embeddings.QUESTION

EVAL_TESTSET = """
version: 1.0.0
items:
  - id: fin-01
    question: "What was Q4 revenue?"
    expected_source: q4.md
  - id: multi-01
    question: "What do the handbook and the expense policy say about travel?"
    expected_source:
      - handbook.md
      - expenses.md
  - id: none-01
    question: "Who won the 1998 World Cup?"
    expected_source: null
"""

ROUTER_TESTSET = """
version: 1.0.0
items:
  - id: direct-01
    question: "Hey Horus!"
"""

ROUTER_EXAMPLES = """
version: 1
agents:
  - agent: Finance-Analyst
    examples:
      - "How much revenue did FinCorp book last quarter?"
"""


def keyword_embedder(keywords: tuple[str, ...]):
    def embed(texts: list[str]) -> np.ndarray:
        return np.array(
            [[1.0 + text.lower().count(keyword) for keyword in keywords] for text in texts]
        )

    return embed


@pytest.fixture
def corpus(tmp_path):
    folder = tmp_path / "corpus"
    folder.mkdir()
    (folder / "q4.md").write_text("Revenue was 4.2M.\n\nCosts were 3.1M.", encoding="utf-8")
    (folder / "handbook.md").write_text("Travel needs approval.", encoding="utf-8")
    (folder / "stress_test.sh").write_text("echo not a document", encoding="utf-8")
    return folder


@pytest.fixture
def question_files(tmp_path):
    eval_testset = tmp_path / "testset.yaml"
    eval_testset.write_text(EVAL_TESTSET, encoding="utf-8")
    router_testset = tmp_path / "router_testset.yaml"
    router_testset.write_text(ROUTER_TESTSET, encoding="utf-8")
    router_examples = tmp_path / "router_examples.yaml"
    router_examples.write_text(ROUTER_EXAMPLES, encoding="utf-8")
    return eval_testset, router_testset, router_examples


def paragraphs(text: str) -> list[str]:
    return [part for part in text.split("\n\n") if part]


def listed_requirements(path: Path) -> dict[str, Requirement]:
    lines = (raw.split(" #", 1)[0].strip() for raw in path.read_text(encoding="utf-8").splitlines())
    parsed = (Requirement(line) for line in lines if line and not line.startswith(("#", "-")))
    return {requirement.name.lower(): requirement for requirement in parsed}


def test_the_knowledge_store_requirements_install_the_yaml_loader_of_this_script():
    pyyaml = listed_requirements(KNOWLEDGE_STORE_REQUIREMENTS)["pyyaml"]

    assert pyyaml.specifier.contains(yaml.__version__), (str(pyyaml.specifier), yaml.__version__)
    assert any(spec.operator in ("<", "<=", "==", "~=") for spec in pyyaml.specifier)


class TestSamples:
    def test_corpus_documents_are_split_into_passages_that_know_their_file(self, corpus):
        passages = compare_embeddings.corpus_passages(corpus, paragraphs)

        assert [(sample.origin, sample.text) for sample in passages] == [
            ("handbook.md", "Travel needs approval."),
            ("q4.md", "Revenue was 4.2M."),
            ("q4.md", "Costs were 3.1M."),
        ]
        assert {sample.kind for sample in passages} == {PASSAGE}

    def test_eval_questions_keep_every_expected_source(self, question_files):
        questions = compare_embeddings.eval_questions(question_files[0])

        assert [sample.expected_sources for sample in questions] == [
            ("q4.md",),
            ("handbook.md", "expenses.md"),
            (),
        ]
        assert [sample.origin for sample in questions] == [
            "eval:fin-01",
            "eval:multi-01",
            "eval:none-01",
        ]

    def test_router_questions_come_from_the_test_set_and_the_examples(self, question_files):
        _, router_testset, router_examples = question_files

        questions = compare_embeddings.router_questions(router_testset, router_examples)

        assert [(sample.origin, sample.text) for sample in questions] == [
            ("router-testset:direct-01", "Hey Horus!"),
            ("router-examples:Finance-Analyst", "How much revenue did FinCorp book last quarter?"),
        ]

    def test_duplicates_are_embedded_once_and_the_total_is_capped(self):
        passages = [Sample(PASSAGE, "a", "x.md"), Sample(PASSAGE, "a", "y.md")]
        questions = [Sample(QUESTION, "a", "q1"), Sample(QUESTION, "b", "q2")]

        assert [
            sample.origin
            for sample in compare_embeddings.collect_samples(passages, questions, limit=10)
        ] == ["x.md", "q1", "q2"]
        assert len(compare_embeddings.collect_samples(passages, questions, limit=2)) == 2

    def test_only_questions_get_the_query_prefix(self):
        embedder = compare_embeddings.EMBEDDERS["knowledge-store"]

        assert embedder.model_input(Sample(QUESTION, "revenue?", "q")) == (
            compare_embeddings.BGE_QUERY_PREFIX + "revenue?"
        )
        assert embedder.model_input(Sample(PASSAGE, "Revenue was 4.2M.", "q4.md")) == (
            "Revenue was 4.2M."
        )
        assert (
            compare_embeddings.EMBEDDERS["mas"].model_input(Sample(QUESTION, "revenue?", "q"))
            == "revenue?"
        )


class TestSimilarity:
    def test_cosine_is_compared_row_by_row_whatever_the_norm(self):
        old = np.array([[1.0, 0.0], [0.0, 2.0], [3.0, 4.0]])
        new = np.array([[2.0, 0.0], [1.0, 0.0], [3.0, 4.0]])

        np.testing.assert_allclose(compare_embeddings.rowwise_cosine(old, new), [1.0, 0.0, 1.0])

    def test_vectors_of_another_size_are_refused(self):
        with pytest.raises(ValueError, match="shape"):
            compare_embeddings.rowwise_cosine(np.ones((2, 3)), np.ones((2, 4)))

    def test_the_summary_counts_what_falls_under_the_threshold(self):
        summary = compare_embeddings.similarity_summary(np.array([1.0, 0.995, 0.98, 0.5]))

        assert summary["count"] == 4
        assert summary["min"] == 0.5
        assert summary["below_threshold"] == 2
        assert compare_embeddings.needs_reindex(summary) is True

    def test_vectors_that_did_not_move_need_no_reindex(self):
        summary = compare_embeddings.similarity_summary(np.array([1.0, 0.9999, 0.995]))

        assert compare_embeddings.needs_reindex(summary) is False

    def test_an_empty_set_needs_no_reindex(self):
        summary = compare_embeddings.similarity_summary(np.array([]))

        assert summary == {"count": 0}
        assert compare_embeddings.needs_reindex(summary) is False


class TestRetrieval:
    def test_hits_are_counted_against_any_expected_source(self):
        passages = [Sample(PASSAGE, "revenue", "q4.md"), Sample(PASSAGE, "travel", "handbook.md")]
        questions = [
            Sample(QUESTION, "revenue?", "a", ("q4.md",)),
            Sample(QUESTION, "travel?", "b", ("handbook.md", "expenses.md")),
            Sample(QUESTION, "football?", "c"),
        ]
        passage_vectors = np.array([[1.0, 0.0], [0.0, 1.0]])
        question_vectors = np.array([[1.0, 0.1], [0.1, 1.0], [0.5, 0.5]])
        swapped = question_vectors[:, ::-1]

        report = compare_embeddings.retrieval_agreement(
            questions, passages, question_vectors, swapped, passage_vectors, passage_vectors, k=1
        )

        assert report["questions"] == 2
        assert report["old_source_hit_at_1"] == 2
        assert report["new_source_hit_at_1"] == 0
        assert report["same_top_passage"] == 0


class TestCompare:
    def test_the_same_vectors_need_no_reindex_and_agree_on_retrieval(self):
        samples = [
            Sample(PASSAGE, "Revenue was 4.2M.", "q4.md"),
            Sample(PASSAGE, "Travel needs approval.", "handbook.md"),
            Sample(QUESTION, "What was the revenue?", "eval:a", ("q4.md",)),
        ]
        embed = keyword_embedder(("revenue", "travel"))

        report = compare_embeddings.compare(
            compare_embeddings.EMBEDDERS["mas"], samples, embed, embed
        )

        assert report["reindex_required"] is False
        assert report["cosine"]["min"] == pytest.approx(1.0)
        assert report["cosine_passages"]["count"] == 2
        assert report["cosine_questions"]["count"] == 1
        assert report["retrieval"]["same_top_passage"] == 1
        assert set(report["timing"]) == {"sentence_transformers", "fastembed"}

    def test_vectors_that_moved_require_a_reindex(self):
        samples = [
            Sample(PASSAGE, "Revenue was 4.2M.", "q4.md"),
            Sample(QUESTION, "travel?", "eval:a", ("handbook.md",)),
        ]

        report = compare_embeddings.compare(
            compare_embeddings.EMBEDDERS["mas"],
            samples,
            keyword_embedder(("revenue", "travel")),
            keyword_embedder(("travel", "revenue")),
        )

        assert report["reindex_required"] is True
        assert "RE-INDEX REQUIRED" in compare_embeddings.format_report([report], len(samples))


class TestMain:
    def test_the_report_is_printed_written_and_reflected_in_the_exit_code(
        self, corpus, question_files, tmp_path, monkeypatch, capsys
    ):
        eval_testset, router_testset, router_examples = question_files
        embed = keyword_embedder(("revenue", "travel", "costs"))
        monkeypatch.setattr(compare_embeddings, "_chunker_split", lambda: paragraphs)
        monkeypatch.setattr(compare_embeddings, "sentence_transformers_embedder", lambda _: embed)
        monkeypatch.setattr(compare_embeddings, "fastembed_embedder", lambda _: embed)
        written = tmp_path / "report.json"

        code = compare_embeddings.main(
            [
                "--corpus",
                str(corpus),
                "--eval-testset",
                str(eval_testset),
                "--router-testset",
                str(router_testset),
                "--router-examples",
                str(router_examples),
                "--json",
                str(written),
            ]
        )

        out = capsys.readouterr().out
        assert code == 0
        assert "8 texts embedded by each setup (fewer than 500" in out
        assert out.count("no re-index needed") == 2
        report = json.loads(written.read_text(encoding="utf-8"))
        assert report["texts"] == 8
        assert [entry["service"] for entry in report["reports"]] == ["knowledge-store", "mas"]
