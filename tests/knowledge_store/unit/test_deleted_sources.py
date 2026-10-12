from __future__ import annotations

import json

from app.chroma_db.services import deleted_sources
from app.chroma_db.setup import CHROMA_DATA_DIR

Q4 = {"doc_id": "corpus-aaa", "source_path": "reports/q4.md", "content_sha256": "aaa"}


class TestDeletedSources:
    def test_nothing_counts_as_deleted_before_the_list_exists(self, deleted_sources_file):
        assert not deleted_sources_file.exists()
        assert not deleted_sources.was_deleted("reports/q4.md", "aaa")

    def test_a_remembered_path_counts_as_deleted_whatever_its_content(
        self, deleted_sources_file
    ):
        deleted_sources.remember_deleted([Q4])

        assert deleted_sources.was_deleted("reports/q4.md", "edited")

    def test_the_same_content_at_another_path_counts_as_deleted(self, deleted_sources_file):
        deleted_sources.remember_deleted([Q4])

        assert deleted_sources.was_deleted("archive/q4-copy.md", "aaa")

    def test_an_unrelated_file_does_not_count_as_deleted(self, deleted_sources_file):
        deleted_sources.remember_deleted([Q4])

        assert not deleted_sources.was_deleted("reports/q3.md", "ccc")

    def test_an_empty_digest_never_matches(self, deleted_sources_file):
        deleted_sources.remember_deleted([{**Q4, "content_sha256": ""}])

        assert not deleted_sources.was_deleted("reports/q3.md", "")

    def test_the_list_is_written_to_disk(self, deleted_sources_file):
        deleted_sources.remember_deleted([Q4])

        saved = json.loads(deleted_sources_file.read_text(encoding="utf-8"))
        assert len(saved["deleted"]) == 1
        entry = saved["deleted"][0]
        assert entry["doc_id"] == "corpus-aaa"
        assert entry["source_path"] == "reports/q4.md"
        assert entry["content_sha256"] == "aaa"
        assert entry["deleted_at"]

    def test_remembering_the_same_source_twice_keeps_one_entry(self, deleted_sources_file):
        assert deleted_sources.remember_deleted([Q4, dict(Q4)]) == 1
        assert deleted_sources.remember_deleted([Q4]) == 0

        saved = json.loads(deleted_sources_file.read_text(encoding="utf-8"))
        assert len(saved["deleted"]) == 1

    def test_forget_drops_entries_matching_the_path_or_the_content(self, deleted_sources_file):
        deleted_sources.remember_deleted([
            Q4,
            {"doc_id": "corpus-aaa", "source_path": "archive/q4-copy.md", "content_sha256": "aaa"},
            {"doc_id": "corpus-ccc", "source_path": "reports/q3.md", "content_sha256": "ccc"},
        ])

        assert deleted_sources.forget_deleted("reports/q4.md", "aaa") == 2

        assert not deleted_sources.was_deleted("archive/q4-copy.md", "zzz")
        assert deleted_sources.was_deleted("reports/q3.md", "ccc")

    def test_an_unreadable_list_counts_as_empty_and_is_replaced(self, deleted_sources_file):
        deleted_sources_file.parent.mkdir(parents=True)
        deleted_sources_file.write_text("{not json", encoding="utf-8")

        assert not deleted_sources.was_deleted("reports/q4.md", "aaa")

        deleted_sources.remember_deleted([Q4])
        assert deleted_sources.was_deleted("reports/q4.md", "aaa")

    def test_the_list_lives_with_the_chroma_index(self):
        assert deleted_sources.DELETED_SOURCES_FILE.parent == CHROMA_DATA_DIR
