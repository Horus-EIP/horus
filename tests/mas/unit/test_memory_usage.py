from __future__ import annotations

import sys
from types import SimpleNamespace

from core import memory_usage


def _fake_resource(max_rss: int) -> SimpleNamespace:
    return SimpleNamespace(
        RUSAGE_SELF=0,
        getrusage=lambda who: SimpleNamespace(ru_maxrss=max_rss),
    )


class TestPeakRss:
    def test_linux_reports_getrusage_kilobytes_as_bytes(self, monkeypatch):
        monkeypatch.setattr(memory_usage, "resource", _fake_resource(2048))
        monkeypatch.setattr(sys, "platform", "linux")

        assert memory_usage.peak_rss_bytes() == 2048 * 1024

    def test_macos_getrusage_is_already_in_bytes(self, monkeypatch):
        monkeypatch.setattr(memory_usage, "resource", _fake_resource(5_000_000))
        monkeypatch.setattr(sys, "platform", "darwin")

        assert memory_usage.peak_rss_bytes() == 5_000_000

    def test_without_resource_the_peak_working_set_is_used(self, monkeypatch):
        monkeypatch.setattr(memory_usage, "resource", None)
        info = SimpleNamespace(rss=1, peak_wset=3 * 1024**2)
        fake_psutil = SimpleNamespace(Process=lambda: SimpleNamespace(memory_info=lambda: info))
        monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

        assert memory_usage.peak_rss_bytes() == 3 * 1024**2

    def test_without_any_source_the_peak_is_unknown(self, monkeypatch):
        monkeypatch.setattr(memory_usage, "resource", None)
        monkeypatch.setitem(sys.modules, "psutil", None)

        assert memory_usage.peak_rss_bytes() is None
        assert memory_usage.peak_rss_mb() == "unknown"

    def test_the_peak_is_reported_in_whole_megabytes(self, monkeypatch):
        monkeypatch.setattr(memory_usage, "peak_rss_bytes", lambda: int(1.6 * 1024**2))

        assert memory_usage.peak_rss_mb() == "2"
