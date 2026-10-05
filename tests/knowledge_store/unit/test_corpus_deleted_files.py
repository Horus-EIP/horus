from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.api.routes import corpus
from app.chroma_db.services import deleted_sources, file_service

Q4_TEXT = "Q4 2025 revenue was 4.2M."


@pytest.fixture
def corpus_root(tmp_path, monkeypatch, fake_collection, deleted_sources_file):
    root = tmp_path / "corpus"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "q4.md").write_text(Q4_TEXT, encoding="utf-8")
    monkeypatch.setattr(corpus, "CORPUS_ROOT", root.resolve())
    monkeypatch.setattr(
        corpus._ANALYZER, "analyze", MagicMock(return_value={"auto_category": "finance"})
    )
    return root.resolve()


async def _scan(root, rel: str, **job_options) -> dict:
    job = corpus._new_job(**{"dry_run": False, **job_options})
    candidates = {label: cand for _path, label, cand in corpus.walk_corpus(root)}
    candidate = candidates[rel]
    await corpus._ingest_one(job, candidate.resolved, rel, candidate)
    return job


def _decision(job: dict) -> str:
    return job["files"][-1]["decision"]


class TestCorpusScanAfterDelete:
    async def test_scan_does_not_re_add_a_file_deleted_from_the_store(
        self, corpus_root, fake_collection
    ):
        first = await _scan(corpus_root, "reports/q4.md")
        await file_service.delete_document(first["files"][-1]["doc_id"])

        second = await _scan(corpus_root, "reports/q4.md")

        assert _decision(second) == "skipped_deleted"
        assert second["totals"]["skipped_deleted"] == 1
        assert second["totals"]["ingested"] == 0
        assert fake_collection.rows == {}

    async def test_an_edited_deleted_file_stays_out(self, corpus_root, fake_collection):
        first = await _scan(corpus_root, "reports/q4.md")
        await file_service.delete_document(first["files"][-1]["doc_id"])
        (corpus_root / "reports" / "q4.md").write_text("Q4 2025 revenue was 4.3M.", encoding="utf-8")

        second = await _scan(corpus_root, "reports/q4.md")

        assert _decision(second) == "skipped_deleted"
        assert fake_collection.rows == {}

    async def test_an_identical_copy_elsewhere_in_the_folder_stays_out(
        self, corpus_root, fake_collection
    ):
        (corpus_root / "archive").mkdir()
        (corpus_root / "archive" / "q4-copy.md").write_text(Q4_TEXT, encoding="utf-8")
        first = await _scan(corpus_root, "reports/q4.md")
        await file_service.delete_document(first["files"][-1]["doc_id"])

        copy = await _scan(corpus_root, "archive/q4-copy.md")

        assert _decision(copy) == "skipped_deleted"
        assert fake_collection.rows == {}

    async def test_a_file_that_was_never_deleted_is_still_ingested(
        self, corpus_root, fake_collection
    ):
        (corpus_root / "reports" / "q3.md").write_text("Q3 2025 revenue was 3.9M.", encoding="utf-8")
        first = await _scan(corpus_root, "reports/q4.md")
        await file_service.delete_document(first["files"][-1]["doc_id"])

        other = await _scan(corpus_root, "reports/q3.md")

        assert _decision(other) == "ingested"
        assert len(fake_collection.rows) == 1

    async def test_include_deleted_re_adds_the_file_and_takes_it_off_the_list(
        self, corpus_root, fake_collection
    ):
        digest = corpus.sha256_of_file(corpus_root / "reports" / "q4.md")
        first = await _scan(corpus_root, "reports/q4.md")
        doc_id = first["files"][-1]["doc_id"]
        await file_service.delete_document(doc_id)

        restored = await _scan(corpus_root, "reports/q4.md", include_deleted=True)

        assert _decision(restored) == "ingested"
        assert list(fake_collection.rows) == [doc_id]
        assert not deleted_sources.was_deleted("reports/q4.md", digest)
        assert _decision(await _scan(corpus_root, "reports/q4.md")) == "skipped_unchanged"

    async def test_dry_run_reports_a_deleted_file_and_changes_nothing(
        self, corpus_root, fake_collection
    ):
        digest = corpus.sha256_of_file(corpus_root / "reports" / "q4.md")
        first = await _scan(corpus_root, "reports/q4.md")
        await file_service.delete_document(first["files"][-1]["doc_id"])

        preview = await _scan(corpus_root, "reports/q4.md", dry_run=True)
        restore_preview = await _scan(
            corpus_root, "reports/q4.md", dry_run=True, include_deleted=True
        )

        assert _decision(preview) == "skipped_deleted"
        assert _decision(restore_preview) == "would_ingest"
        assert fake_collection.rows == {}
        assert deleted_sources.was_deleted("reports/q4.md", digest)

    def test_a_new_job_does_not_include_deleted_files_by_default(self):
        assert corpus._new_job(dry_run=False)["include_deleted"] is False
        assert corpus._new_job(dry_run=False)["totals"]["skipped_deleted"] == 0
