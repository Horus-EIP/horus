#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
KNOWLEDGE_STORE = REPO / "src" / "services" / "knowledge-store"
DEFAULT_CORPUS = REPO / "demo_assets"
DEFAULT_EVAL_TESTSET = REPO / "tests" / "eval" / "testset.yaml"
DEFAULT_ROUTER_TESTSET = REPO / "tests" / "mas" / "data" / "router_testset.yaml"
DEFAULT_ROUTER_EXAMPLES = REPO / "src" / "services" / "mas" / "tasks" / "router_examples.yaml"

TARGET_TEXTS = 500
REINDEX_BELOW = 0.99
TOP_K = 3
SINGLE_QUESTIONS_TIMED = 30
CORPUS_SUFFIXES = (".md", ".txt")
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

PASSAGE = "passage"
QUESTION = "question"

Embed = Callable[[list[str]], np.ndarray]


@dataclass(frozen=True)
class Sample:
    kind: str
    text: str
    origin: str
    expected_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class Embedder:
    service: str
    model_id: str
    query_prefix: str = ""

    def model_input(self, sample: Sample) -> str:
        return self.query_prefix + sample.text if sample.kind == QUESTION else sample.text


EMBEDDERS = {
    "knowledge-store": Embedder("knowledge-store", "BAAI/bge-base-en-v1.5", BGE_QUERY_PREFIX),
    "mas": Embedder("mas", "sentence-transformers/all-MiniLM-L6-v2"),
}


def corpus_passages(corpus_dir: Path, split: Callable[[str], list[str]]) -> list[Sample]:
    passages: list[Sample] = []
    for path in sorted(corpus_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in CORPUS_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            passages.extend(Sample(PASSAGE, chunk, path.name) for chunk in split(text))
    return passages


def expected_sources(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(source) for source in value)


def eval_questions(testset: Path) -> list[Sample]:
    document = yaml.safe_load(testset.read_text(encoding="utf-8")) or {}
    return [
        Sample(
            QUESTION,
            item["question"],
            f"eval:{item['id']}",
            expected_sources(item.get("expected_source")),
        )
        for item in document.get("items") or []
    ]


def router_questions(testset: Path, examples: Path) -> list[Sample]:
    labelled = yaml.safe_load(testset.read_text(encoding="utf-8")) or {}
    taught = yaml.safe_load(examples.read_text(encoding="utf-8")) or {}
    questions = [
        Sample(QUESTION, item["question"], f"router-testset:{item['id']}")
        for item in labelled.get("items") or []
    ]
    questions.extend(
        Sample(QUESTION, example, f"router-examples:{agent['agent']}")
        for agent in taught.get("agents") or []
        for example in agent.get("examples") or []
    )
    return questions


def collect_samples(
    passages: Sequence[Sample],
    questions: Sequence[Sample],
    limit: int = TARGET_TEXTS,
) -> list[Sample]:
    unique: dict[tuple[str, str], Sample] = {}
    for sample in (*passages, *questions):
        unique.setdefault((sample.kind, sample.text), sample)
    return list(unique.values())[:limit]


def normalised(vectors: np.ndarray) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


def rowwise_cosine(old: np.ndarray, new: np.ndarray) -> np.ndarray:
    if old.shape != new.shape:
        raise ValueError(f"the two setups disagree on the shape: {old.shape} vs {new.shape}")
    return np.sum(normalised(old) * normalised(new), axis=1)


def similarity_summary(cosines: np.ndarray, threshold: float = REINDEX_BELOW) -> dict:
    if cosines.size == 0:
        return {"count": 0}
    return {
        "count": int(cosines.size),
        "min": float(np.min(cosines)),
        "p1": float(np.percentile(cosines, 1)),
        "p5": float(np.percentile(cosines, 5)),
        "median": float(np.median(cosines)),
        "mean": float(np.mean(cosines)),
        "max": float(np.max(cosines)),
        "below_threshold": int(np.sum(cosines < threshold)),
    }


def top_passages(questions: np.ndarray, passages: np.ndarray, k: int = TOP_K) -> np.ndarray:
    scores = normalised(questions) @ normalised(passages).T
    return np.argsort(-scores, axis=1, kind="stable")[:, :k]


def retrieval_agreement(
    questions: Sequence[Sample],
    passages: Sequence[Sample],
    old_questions: np.ndarray,
    new_questions: np.ndarray,
    old_passages: np.ndarray,
    new_passages: np.ndarray,
    k: int = TOP_K,
) -> dict:
    graded = [index for index, question in enumerate(questions) if question.expected_sources]
    if not graded or not passages:
        return {"questions": 0}
    rankings = {
        "old": top_passages(old_questions[graded], old_passages, k),
        "new": top_passages(new_questions[graded], new_passages, k),
        "new_question_old_passages": top_passages(new_questions[graded], old_passages, k),
    }
    expected = [set(questions[index].expected_sources) for index in graded]

    def source_hits(ranking: np.ndarray, depth: int) -> int:
        return sum(
            bool(expected[row] & {passages[column].origin for column in ranking[row, :depth]})
            for row in range(len(graded))
        )

    report: dict = {"questions": len(graded), "k": k}
    for name, ranking in rankings.items():
        report[f"{name}_source_hit_at_1"] = source_hits(ranking, 1)
        report[f"{name}_source_hit_at_{k}"] = source_hits(ranking, k)
    report["same_top_passage"] = int(np.sum(rankings["old"][:, 0] == rankings["new"][:, 0]))
    return report


def needs_reindex(summary: dict, threshold: float = REINDEX_BELOW) -> bool:
    return summary.get("count", 0) > 0 and summary["min"] < threshold


def sentence_transformers_embedder(model_id: str) -> Embed:
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    model = SentenceTransformer(model_id, device="cpu")

    def embed(texts: list[str]) -> np.ndarray:
        return np.asarray(
            model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
        )

    return embed


def fastembed_embedder(model_id: str) -> Embed:
    from fastembed import TextEmbedding  # noqa: PLC0415

    model = TextEmbedding(model_id)

    def embed(texts: list[str]) -> np.ndarray:
        return np.stack(list(model.embed(texts)))

    return embed


def timed(embed: Embed, texts: list[str]) -> tuple[np.ndarray, float]:
    started = time.perf_counter()
    vectors = embed(texts)
    return vectors, time.perf_counter() - started


def single_text_p50_ms(embed: Embed, texts: Sequence[str]) -> float | None:
    if not texts:
        return None
    return float(np.median([timed(embed, [text])[1] for text in texts]) * 1000)


def embed_setup(embed: Embed, passages: list[str], questions: list[str]) -> tuple[np.ndarray, dict]:
    embed(["warm up"])
    passage_vectors, passage_seconds = timed(embed, passages)
    question_vectors, question_seconds = timed(embed, questions)
    timing = {
        "passages_seconds": round(passage_seconds, 3),
        "questions_seconds": round(question_seconds, 3),
        "single_question_p50_ms": single_text_p50_ms(embed, questions[:SINGLE_QUESTIONS_TIMED]),
    }
    return np.concatenate([passage_vectors, question_vectors]), timing


def compare(embedder: Embedder, samples: Sequence[Sample], old: Embed, new: Embed) -> dict:
    passages = [sample for sample in samples if sample.kind == PASSAGE]
    questions = [sample for sample in samples if sample.kind == QUESTION]
    ordered = [*passages, *questions]
    passage_texts = [embedder.model_input(sample) for sample in passages]
    question_texts = [embedder.model_input(sample) for sample in questions]
    old_vectors, old_timing = embed_setup(old, passage_texts, question_texts)
    new_vectors, new_timing = embed_setup(new, passage_texts, question_texts)
    cosines = rowwise_cosine(old_vectors, new_vectors)
    passage_rows = slice(0, len(passages))
    question_rows = slice(len(passages), len(ordered))
    overall = similarity_summary(cosines)
    lowest = np.argsort(cosines, kind="stable")[:3]
    return {
        "service": embedder.service,
        "model": embedder.model_id,
        "query_prefix": embedder.query_prefix,
        "texts": len(ordered),
        "dimensions": int(new_vectors.shape[1]),
        "timing": {"sentence_transformers": old_timing, "fastembed": new_timing},
        "cosine": overall,
        "cosine_passages": similarity_summary(cosines[passage_rows]),
        "cosine_questions": similarity_summary(cosines[question_rows]),
        "lowest": [
            {
                "cosine": float(cosines[row]),
                "origin": ordered[row].origin,
                "text": ordered[row].text[:120],
            }
            for row in lowest
        ],
        "retrieval": retrieval_agreement(
            questions,
            passages,
            old_vectors[question_rows],
            new_vectors[question_rows],
            old_vectors[passage_rows],
            new_vectors[passage_rows],
        ),
        "reindex_required": needs_reindex(overall),
    }


def _stats_line(label: str, summary: dict) -> str:
    if not summary.get("count"):
        return f"  {label:<10} no texts"
    return (
        f"  {label:<10} n={summary['count']:<4} min {summary['min']:.6f}  p1 {summary['p1']:.6f}"
        f"  p5 {summary['p5']:.6f}  median {summary['median']:.6f}  mean {summary['mean']:.6f}"
        f"  below {REINDEX_BELOW}: {summary['below_threshold']}"
    )


def _timing_line(label: str, timing: dict) -> str:
    single = timing["single_question_p50_ms"]
    return (
        f"  {label:<22} passages {timing['passages_seconds']:.3f} s, questions "
        f"{timing['questions_seconds']:.3f} s, one question p50 "
        + ("n/a" if single is None else f"{single:.1f} ms")
    )


def format_report(reports: Sequence[dict], sample_count: int) -> str:
    lines = [
        f"{sample_count} texts embedded by each setup"
        + (
            ""
            if sample_count >= TARGET_TEXTS
            else f" (fewer than {TARGET_TEXTS}: the demo corpus and the question sets hold no more)"
        )
    ]
    for report in reports:
        retrieval = report["retrieval"]
        lines += [
            "",
            f"{report['service']}: {report['model']}, {report['dimensions']} dimensions",
            _timing_line("sentence-transformers", report["timing"]["sentence_transformers"]),
            _timing_line("fastembed", report["timing"]["fastembed"]),
            _stats_line("all", report["cosine"]),
            _stats_line("passages", report["cosine_passages"]),
            _stats_line("questions", report["cosine_questions"]),
        ]
        if retrieval.get("questions"):
            k = retrieval["k"]
            lines.append(
                f"  retrieval  {retrieval['questions']} graded questions: source hit@1 "
                f"old {retrieval['old_source_hit_at_1']} new {retrieval['new_source_hit_at_1']} "
                f"mixed {retrieval['new_question_old_passages_source_hit_at_1']}; hit@{k} "
                f"old {retrieval[f'old_source_hit_at_{k}']} new {retrieval[f'new_source_hit_at_{k}']}"
                f" mixed {retrieval[f'new_question_old_passages_source_hit_at_{k}']}; "
                f"same top passage {retrieval['same_top_passage']}"
            )
        lines.append(
            "  verdict    "
            + ("RE-INDEX REQUIRED" if report["reindex_required"] else "no re-index needed")
            + f" (minimum cosine {report['cosine'].get('min', float('nan')):.6f}, "
            f"threshold {REINDEX_BELOW})"
        )
    return "\n".join(lines)


def _chunker_split() -> Callable[[str], list[str]]:
    sys.path.insert(0, str(KNOWLEDGE_STORE))
    from app.services.document_chunker import DocumentChunker  # noqa: PLC0415

    return DocumentChunker().chunk_document


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Embed the demo corpus, chunked like the knowledge store chunks it, and the eval "
            "and router questions with the old sentence-transformers setup and the FastEmbed "
            "one, and report how far apart the vectors are. Exits 1 when a re-index is "
            "required. Needs sentence-transformers, fastembed and network access to download "
            "both models."
        )
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--eval-testset", type=Path, default=DEFAULT_EVAL_TESTSET)
    parser.add_argument("--router-testset", type=Path, default=DEFAULT_ROUTER_TESTSET)
    parser.add_argument("--router-examples", type=Path, default=DEFAULT_ROUTER_EXAMPLES)
    parser.add_argument("--limit", type=int, default=TARGET_TEXTS)
    parser.add_argument(
        "--service",
        choices=sorted(EMBEDDERS),
        action="append",
        help="Compare only this service's embedder (default: both).",
    )
    parser.add_argument("--json", type=Path, help="Also write the report as JSON to this file.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    samples = collect_samples(
        corpus_passages(args.corpus, _chunker_split()),
        [
            *eval_questions(args.eval_testset),
            *router_questions(args.router_testset, args.router_examples),
        ],
        args.limit,
    )
    reports = [
        compare(
            EMBEDDERS[service],
            samples,
            sentence_transformers_embedder(EMBEDDERS[service].model_id),
            fastembed_embedder(EMBEDDERS[service].model_id),
        )
        for service in (args.service or sorted(EMBEDDERS))
    ]
    print(format_report(reports, len(samples)))
    if args.json is not None:
        args.json.write_text(
            json.dumps({"texts": len(samples), "reports": reports}, indent=2), encoding="utf-8"
        )
    return 1 if any(report["reindex_required"] for report in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
