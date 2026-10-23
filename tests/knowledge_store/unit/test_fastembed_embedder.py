from __future__ import annotations

import logging
from importlib import metadata
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.chroma_db import setup
from app.chroma_db.services import reindex

CPU_ONLY = ["CPUExecutionProvider"]
WITH_CUDA = ["CUDAExecutionProvider", "CPUExecutionProvider"]


@pytest.fixture
def embedder(monkeypatch):
    model = MagicMock()
    model.embed.side_effect = lambda texts: [np.array([float(len(text)), 1.0]) for text in texts]
    monkeypatch.setattr(setup, "model", model)
    return model


class TestBgeQueryPrefix:
    def test_a_question_is_embedded_with_the_bge_prefix_exactly_once(self, embedder):
        setup.get_embedding("What was Q4 revenue?", is_query=True)

        (texts,), _ = embedder.embed.call_args
        assert texts == [setup.BGE_QUERY_PREFIX + "What was Q4 revenue?"]
        assert texts[0].count(setup.BGE_QUERY_PREFIX) == 1

    def test_a_passage_is_embedded_without_the_prefix(self, embedder):
        setup.get_embedding("Q4 revenue was $4.2M.")
        setup.get_embeddings(["Q4 revenue was $4.2M.", "Operating costs were $3.1M."])

        embedded = [text for call in embedder.embed.call_args_list for text in call.args[0]]
        assert embedded == [
            "Q4 revenue was $4.2M.",
            "Q4 revenue was $4.2M.",
            "Operating costs were $3.1M.",
        ]
        assert not any(setup.BGE_QUERY_PREFIX in text for text in embedded)

    def test_vectors_come_back_as_float_lists_in_the_order_given(self, embedder):
        vectors = setup.get_embeddings(["ab", "abcd"])

        assert vectors == [[2.0, 1.0], [4.0, 1.0]]
        assert all(isinstance(value, float) for vector in vectors for value in vector)


class TestEmbedderIdentity:
    def test_the_embed_model_names_the_runtime_its_version_and_the_model(self):
        assert setup.EMBED_MODEL == (
            f"fastembed-{metadata.version('fastembed')}:BAAI/bge-base-en-v1.5"
        )

    def test_a_missing_distribution_has_an_unknown_version(self):
        assert setup.installed_version("no-such-distribution-for-horus") == "unknown"

    def test_the_collection_metadata_records_the_model_id_and_the_runtime_version(self):
        assert setup.COLLECTION_METADATA == {
            "embedding_model": "BAAI/bge-base-en-v1.5",
            "embed_model": setup.EMBED_MODEL,
            "embedding_runtime": "fastembed",
            "embedding_runtime_version": metadata.version("fastembed"),
            "dimensions": 768,
        }


class TestDevice:
    @pytest.mark.parametrize(
        ("requested", "providers", "expected"),
        [
            ("auto", CPU_ONLY, False),
            ("auto", WITH_CUDA, True),
            ("", WITH_CUDA, True),
            ("cpu", WITH_CUDA, False),
            ("cuda", WITH_CUDA, True),
            ("cuda:0", WITH_CUDA, True),
        ],
    )
    def test_the_requested_device_picks_the_onnxruntime_provider(
        self, requested, providers, expected
    ):
        assert setup.wants_cuda(requested, providers) is expected

    def test_cuda_without_a_cuda_provider_falls_back_to_cpu_and_says_so(self, caplog):
        with caplog.at_level(logging.WARNING, logger="Embedder"):
            assert setup.wants_cuda("cuda", CPU_ONLY) is False

        assert "embedding on CPU" in caplog.text


class TestThreads:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(None, None), ("", None), ("4", 4), (" 2 ", 2), ("0", None), ("-1", None), ("x", None)],
    )
    def test_the_thread_setting_is_a_positive_whole_number_or_left_to_onnxruntime(
        self, raw, expected
    ):
        assert setup.embed_threads(raw) == expected


class TestCollectionRecordsTheEmbedder:
    def test_an_older_collection_is_brought_up_to_date_and_keeps_its_other_keys(
        self, fake_collection
    ):
        fake_collection.metadata = {
            "embedding_model": "BAAI/bge-base-en-v1.5",
            "dimensions": 768,
            "owner": "horus",
        }

        assert reindex.record_embedder_in_collection() is True

        assert fake_collection.metadata == {**setup.COLLECTION_METADATA, "owner": "horus"}

    def test_a_collection_already_up_to_date_is_left_alone(self, fake_collection):
        fake_collection.metadata = dict(setup.COLLECTION_METADATA)

        assert reindex.record_embedder_in_collection() is False

        assert fake_collection.metadata_updates == []

    def test_a_collection_without_metadata_gets_it(self, fake_collection):
        assert reindex.record_embedder_in_collection() is True

        assert fake_collection.metadata == setup.COLLECTION_METADATA
