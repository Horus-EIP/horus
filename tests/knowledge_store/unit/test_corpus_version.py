from __future__ import annotations

import threading

from app.chroma_db.services.corpus_version import CorpusVersion


class TestCorpusVersion:
    def test_reading_the_version_does_not_change_it(self):
        corpus = CorpusVersion()

        assert corpus.current() == corpus.current()

    def test_a_bump_gives_a_new_version(self):
        corpus = CorpusVersion()
        before = corpus.current()["version"]

        corpus.bump()

        assert corpus.current()["version"] != before

    def test_a_restarted_service_never_reuses_an_earlier_version(self):
        first_run, second_run = CorpusVersion(), CorpusVersion()
        first_run.bump()
        second_run.bump()

        assert first_run.current()["version"] != second_run.current()["version"]

    def test_concurrent_bumps_are_all_counted(self):
        corpus = CorpusVersion()

        def bump_a_hundred_times():
            for _ in range(100):
                corpus.bump()

        workers = [threading.Thread(target=bump_a_hundred_times) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        assert corpus.current()["version"].endswith("-800")
