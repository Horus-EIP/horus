"""Coverage-focused unit tests for three MAS core modules.

Targets:
- ``core.structured_logging`` — correlation-id contextvars, the JSON
  formatter, the singleton manager, and the convenience emit helpers.
- ``core.skill_cache`` — the in-memory ``(agent, skill)`` embedding cache:
  build / warm / upsert / evict and the cosine-similarity ranking path.
- ``core.log_config`` — module-level logging configuration constants.

Isolation notes (logging tests leak global state easily):
- Convenience emitters are exercised against a ``MagicMock`` logger so no
  real records hit the root handlers / log files installed at import time.
- The one test that calls ``StructuredLogger._configure`` directly snapshots
  and restores the root logger's level + handler list, and patches
  ``FileHandler`` / ``StreamHandler`` / ``Path`` so no files are created.
- ``skill_cache`` keeps a module-global ``_rows`` list; an autouse fixture
  saves and restores it so cache mutations never bleed across tests.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core import skill_cache, structured_logging
from core.structured_logging import (
    JSONFormatter,
    StructuredLogger,
    clear_correlation_id,
    get_correlation_id,
    get_structured_logger,
    log_agent_event,
    log_request,
    log_security_event,
    log_task_event,
    log_with_context,
    set_correlation_id,
)

# --------------------------------------------------------------------------- #
# core.structured_logging — correlation id
# --------------------------------------------------------------------------- #


class TestCorrelationId:
    def teardown_method(self):
        # Never let a correlation id leak into another test's context.
        clear_correlation_id()

    def test_set_correlation_id_generates_uuid_when_none(self):
        returned = set_correlation_id(None)
        assert isinstance(returned, str)
        # UUID4 string form: 8-4-4-4-12 hex groups.
        assert len(returned) == 36
        assert returned.count("-") == 4
        assert get_correlation_id() == returned

    def test_set_correlation_id_uses_explicit_value(self):
        returned = set_correlation_id("corr-123")
        assert returned == "corr-123"
        assert get_correlation_id() == "corr-123"

    def test_clear_correlation_id_resets_to_none(self):
        set_correlation_id("to-be-cleared")
        assert get_correlation_id() == "to-be-cleared"
        clear_correlation_id()
        assert get_correlation_id() is None

    def test_get_correlation_id_default_is_none(self):
        clear_correlation_id()
        assert get_correlation_id() is None


# --------------------------------------------------------------------------- #
# core.structured_logging — JSONFormatter
# --------------------------------------------------------------------------- #


def _make_record(**overrides) -> logging.LogRecord:
    params = {
        "name": "test.logger",
        "level": logging.INFO,
        "pathname": "/some/path.py",
        "lineno": 42,
        "msg": "hello %s",
        "args": ("world",),
        "exc_info": None,
    }
    params.update(overrides)
    return logging.LogRecord(
        name=params["name"],
        level=params["level"],
        pathname=params["pathname"],
        lineno=params["lineno"],
        msg=params["msg"],
        args=params["args"],
        exc_info=params["exc_info"],
    )


class TestJSONFormatter:
    def teardown_method(self):
        clear_correlation_id()

    def test_format_basic_fields(self):
        record = _make_record()
        payload = json.loads(JSONFormatter().format(record))

        assert payload["level"] == "INFO"
        assert payload["logger"] == "test.logger"
        assert payload["message"] == "hello world"  # %-args interpolated
        assert payload["line"] == 42
        assert payload["timestamp"].endswith("Z")
        # Standard LogRecord attributes are present.
        assert "process_id" in payload
        assert "thread_id" in payload
        # No correlation id set -> key omitted entirely.
        assert "correlation_id" not in payload
        # No user-supplied custom attributes. (Python 3.12 adds a stdlib
        # ``taskName`` record attr that is not in the reserved set, so an
        # "extra" block may exist but must not carry our own fields.)
        assert "user_id" not in payload.get("extra", {})

    def test_format_omits_extra_block_when_no_custom_fields(self):
        record = _make_record()
        # Python 3.12 injects a stdlib ``taskName`` attr; drop it so the
        # record carries *no* non-reserved attributes and the formatter takes
        # the "no extra block" branch.
        record.__dict__.pop("taskName", None)
        payload = json.loads(JSONFormatter().format(record))
        assert "extra" not in payload

    def test_format_includes_correlation_id_when_set(self):
        set_correlation_id("trace-xyz")
        payload = json.loads(JSONFormatter().format(_make_record()))
        assert payload["correlation_id"] == "trace-xyz"

    def test_format_includes_exception_info(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = _make_record(msg="failed", args=(), exc_info=sys.exc_info())

        payload = json.loads(JSONFormatter().format(record))
        assert "ValueError" in payload["exception"]
        assert "boom" in payload["exception"]
        assert payload["exception_type"] == "ValueError"

    def test_format_includes_serializable_extra_fields(self):
        record = _make_record()
        # Attributes not in the reserved set become the "extra" block.
        record.user_id = 7
        record.action = "login"
        payload = json.loads(JSONFormatter().format(record))
        assert payload["extra"]["user_id"] == 7
        assert payload["extra"]["action"] == "login"

    def test_format_stringifies_non_serializable_extra_fields(self):
        record = _make_record()

        class Unserializable:
            def __str__(self):
                return "<custom-object>"

        record.weird = Unserializable()
        payload = json.loads(JSONFormatter().format(record))
        # Falls back to str() rather than raising.
        assert payload["extra"]["weird"] == "<custom-object>"


# --------------------------------------------------------------------------- #
# core.structured_logging — StructuredLogger singleton + get_logger
# --------------------------------------------------------------------------- #


class TestStructuredLogger:
    def test_singleton_returns_same_instance(self):
        assert StructuredLogger() is StructuredLogger()

    def test_get_structured_logger_returns_stdlib_logger(self):
        logger = get_structured_logger("coverage.named")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "coverage.named"

    def test_get_logger_caches_by_name(self):
        mgr = StructuredLogger()
        first = mgr.get_logger("coverage.cached")
        second = mgr.get_logger("coverage.cached")
        assert first is second
        assert "coverage.cached" in mgr._loggers

    def test_configure_json_branch_installs_handlers(self):
        """Drive ``_configure`` with JSON_LOGGING=true without touching disk.

        Snapshots and restores root-logger state so handlers added here do
        not leak into other tests.
        """
        root = logging.getLogger()
        saved_handlers = root.handlers[:]
        saved_level = root.level
        try:
            with patch("core.structured_logging.Path") as mock_path, patch(
                "core.structured_logging.logging.FileHandler"
            ) as mock_file_handler, patch(
                "core.structured_logging.logging.StreamHandler"
            ) as mock_stream_handler, patch.dict(
                "os.environ",
                {"LOG_LEVEL": "DEBUG", "JSON_LOGGING": "true"},
                clear=False,
            ):
                mock_stream_handler.return_value = MagicMock()
                mock_file_handler.return_value = MagicMock()

                mgr = StructuredLogger()
                mgr._configure()

                # logs dir creation attempted.
                mock_path.return_value.mkdir.assert_called_with(exist_ok=True)
                # Console (stream) + two file handlers (structured + error).
                assert mock_stream_handler.called
                assert mock_file_handler.call_count == 2
                # JSON branch: console handler gets a JSONFormatter.
                console = mock_stream_handler.return_value
                set_formatter_calls = console.setFormatter.call_args_list
                assert any(
                    isinstance(c.args[0], JSONFormatter) for c in set_formatter_calls
                )
        finally:
            root.handlers[:] = saved_handlers
            root.setLevel(saved_level)

    def test_configure_console_branch_uses_colored_formatter(self):
        """JSON_LOGGING=false -> the dev ``ColoredFormatter`` branch."""
        from core.logger import ColoredFormatter

        root = logging.getLogger()
        saved_handlers = root.handlers[:]
        saved_level = root.level
        try:
            with patch("core.structured_logging.Path") as mock_path, patch(
                "core.structured_logging.logging.FileHandler"
            ) as mock_file_handler, patch(
                "core.structured_logging.logging.StreamHandler"
            ) as mock_stream_handler, patch.dict(
                "os.environ",
                {"LOG_LEVEL": "INFO", "JSON_LOGGING": "false"},
                clear=False,
            ):
                mock_path.return_value.mkdir = MagicMock()
                mock_stream_handler.return_value = MagicMock()
                mock_file_handler.return_value = MagicMock()

                StructuredLogger()._configure()

                console = mock_stream_handler.return_value
                formatters = [c.args[0] for c in console.setFormatter.call_args_list]
                assert any(isinstance(f, ColoredFormatter) for f in formatters)
        finally:
            root.handlers[:] = saved_handlers
            root.setLevel(saved_level)


# --------------------------------------------------------------------------- #
# core.structured_logging — emit helpers
# --------------------------------------------------------------------------- #


class TestLogHelpers:
    def test_log_with_context_forwards_level_and_extra(self):
        mock_logger = MagicMock()
        log_with_context(mock_logger, logging.WARNING, "msg", request_id="r1")
        mock_logger.log.assert_called_once_with(
            logging.WARNING, "msg", extra={"request_id": "r1"}
        )

    def test_log_request_builds_structured_extra(self):
        mock_logger = MagicMock()
        with patch(
            "core.structured_logging.get_structured_logger", return_value=mock_logger
        ) as get_log:
            log_request("GET", "/api/x", 200, 12.345, client_ip="1.2.3.4", user_id=9)

        get_log.assert_called_once_with("http")
        args, kwargs = mock_logger.info.call_args
        assert args[0] == "GET /api/x -> 200"
        extra = kwargs["extra"]
        assert extra["type"] == "http_request"
        assert extra["method"] == "GET"
        assert extra["status_code"] == 200
        assert extra["duration_ms"] == 12.35  # rounded to 2 dp
        assert extra["client_ip"] == "1.2.3.4"
        assert extra["user_id"] == 9

    def test_log_request_passes_through_extra_kwargs(self):
        mock_logger = MagicMock()
        with patch(
            "core.structured_logging.get_structured_logger", return_value=mock_logger
        ):
            log_request("POST", "/p", 201, 1.0, region="eu")
        extra = mock_logger.info.call_args.kwargs["extra"]
        assert extra["region"] == "eu"

    def test_log_task_event_with_duration(self):
        mock_logger = MagicMock()
        with patch(
            "core.structured_logging.get_structured_logger", return_value=mock_logger
        ) as get_log:
            log_task_event(
                "task-1",
                "completed",
                agent_id="a1",
                conversation_id=3,
                duration_ms=8.999,
                attempt=2,
            )
        get_log.assert_called_once_with("task")
        args, kwargs = mock_logger.info.call_args
        assert args[0] == "Task completed: task-1"
        extra = kwargs["extra"]
        assert extra["type"] == "task_event"
        assert extra["task_id"] == "task-1"
        assert extra["event"] == "completed"
        assert extra["agent_id"] == "a1"
        assert extra["conversation_id"] == 3
        assert extra["duration_ms"] == 9.0  # rounded
        assert extra["attempt"] == 2

    def test_log_task_event_without_duration_is_none(self):
        mock_logger = MagicMock()
        with patch(
            "core.structured_logging.get_structured_logger", return_value=mock_logger
        ):
            log_task_event("task-2", "started")
        extra = mock_logger.info.call_args.kwargs["extra"]
        # duration_ms is None -> the rounding branch is skipped.
        assert extra["duration_ms"] is None

    def test_log_agent_event(self):
        mock_logger = MagicMock()
        with patch(
            "core.structured_logging.get_structured_logger", return_value=mock_logger
        ) as get_log:
            log_agent_event("agent-7", "registered", agent_name="Scout", tier="gold")
        get_log.assert_called_once_with("agent")
        args, kwargs = mock_logger.info.call_args
        assert args[0] == "Agent registered: agent-7"
        extra = kwargs["extra"]
        assert extra["type"] == "agent_event"
        assert extra["agent_id"] == "agent-7"
        assert extra["agent_name"] == "Scout"
        assert extra["tier"] == "gold"

    def test_log_security_event_success_uses_info(self):
        mock_logger = MagicMock()
        with patch(
            "core.structured_logging.get_structured_logger", return_value=mock_logger
        ) as get_log:
            log_security_event("login", username="bob", client_ip="9.9.9.9", success=True)
        get_log.assert_called_once_with("security")
        level, message = mock_logger.log.call_args.args
        assert level == logging.INFO
        assert message == "Security login: success"
        extra = mock_logger.log.call_args.kwargs["extra"]
        assert extra["type"] == "security_event"
        assert extra["success"] is True
        assert extra["username"] == "bob"

    def test_log_security_event_failure_uses_warning(self):
        mock_logger = MagicMock()
        with patch(
            "core.structured_logging.get_structured_logger", return_value=mock_logger
        ):
            log_security_event("login", username="mallory", success=False)
        level, message = mock_logger.log.call_args.args
        assert level == logging.WARNING
        assert message == "Security login: failed"
        assert mock_logger.log.call_args.kwargs["extra"]["success"] is False


# --------------------------------------------------------------------------- #
# core.skill_cache
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def restore_skill_cache_rows():
    """Snapshot & restore the module-global ``_rows`` around each test."""
    saved = list(skill_cache._rows)
    skill_cache._rows[:] = []
    yield
    skill_cache._rows[:] = saved


def _unit_vec(values: list[float]) -> np.ndarray:
    v = np.asarray(values, dtype=np.float32)
    n = np.linalg.norm(v)
    return v / n if n else v


class TestSkillCacheText:
    def test_agent_skill_text_with_description(self):
        text = skill_cache._agent_skill_text("Scout", "web_search", "finds pages")
        # Underscores in the skill become spaces; skill leads the string.
        assert text.startswith("web search — used by agent Scout")
        assert text.endswith(": finds pages")

    def test_agent_skill_text_without_description(self):
        text = skill_cache._agent_skill_text("Scout", "web_search", "   ")
        assert text == "web search — used by agent Scout"
        assert ":" not in text

    def test_agent_skill_text_none_description(self):
        text = skill_cache._agent_skill_text("Scout", "summarize", None)
        assert text == "summarize — used by agent Scout"


class TestSkillCacheBuild:
    def test_build_rows_empty_skills_returns_empty(self):
        with patch.object(skill_cache, "embed_texts") as embed:
            rows = skill_cache._build_rows_for_agent("a1", "Scout", [], "desc")
        assert rows == []
        embed.assert_not_called()  # short-circuits before embedding

    def test_build_rows_embeds_and_zips(self):
        vecs = [_unit_vec([1, 0]), _unit_vec([0, 1])]
        with patch.object(skill_cache, "embed_texts", return_value=vecs) as embed:
            rows = skill_cache._build_rows_for_agent(
                "a1", "Scout", ["search", "summarize"], "desc"
            )
        # One embed call for all skill texts.
        embed.assert_called_once()
        assert [r.skill for r in rows] == ["search", "summarize"]
        assert all(r.agent_id == "a1" and r.agent_name == "Scout" for r in rows)
        np.testing.assert_array_equal(rows[0].vector, vecs[0])


class TestSkillCacheWarm:
    def test_warm_skill_cache_loads_agents_and_embeds(self):
        agent_a = MagicMock()
        agent_a.id, agent_a.name = "a1", "Scout"
        agent_a.skills = ["search"]
        agent_a.description = "finds things"

        agent_b = MagicMock()
        agent_b.id, agent_b.name = "a2", "Writer"
        agent_b.skills = ["summarize", "translate"]
        agent_b.description = None  # exercises the ``or ""`` fallback

        fake_db = MagicMock()
        fake_db.query.return_value.all.return_value = [agent_a, agent_b]

        with patch.object(skill_cache, "SessionLocal", return_value=fake_db), patch.object(
            skill_cache, "embed_texts", side_effect=lambda texts: [_unit_vec([1, 0]) for _ in texts]
        ):
            skill_cache.warm_skill_cache()

        # 1 + 2 = 3 (agent, skill) rows.
        assert len(skill_cache._rows) == 3
        assert {r.skill for r in skill_cache._rows} == {"search", "summarize", "translate"}
        fake_db.close.assert_called_once()  # session always closed

    def test_warm_skill_cache_skips_agents_without_skills(self):
        agent = MagicMock()
        agent.id, agent.name, agent.skills, agent.description = "a3", "Idle", None, "d"
        fake_db = MagicMock()
        fake_db.query.return_value.all.return_value = [agent]

        with patch.object(skill_cache, "SessionLocal", return_value=fake_db), patch.object(
            skill_cache, "embed_texts"
        ) as embed:
            skill_cache.warm_skill_cache()

        assert skill_cache._rows == []
        embed.assert_not_called()


class TestSkillCacheUpsertEvict:
    def test_upsert_adds_rows(self):
        with patch.object(
            skill_cache, "embed_texts", return_value=[_unit_vec([1, 0])]
        ):
            skill_cache.upsert_agent("a1", "Scout", ["search"], "desc")
        assert len(skill_cache._rows) == 1
        assert skill_cache._rows[0].agent_id == "a1"

    def test_upsert_replaces_only_target_agent(self):
        # Seed two agents.
        with patch.object(
            skill_cache, "embed_texts", return_value=[_unit_vec([1, 0])]
        ):
            skill_cache.upsert_agent("a1", "Scout", ["search"], "")
        with patch.object(
            skill_cache, "embed_texts", return_value=[_unit_vec([0, 1])]
        ):
            skill_cache.upsert_agent("a2", "Writer", ["summarize"], "")

        # Re-upsert a1 with new skills; a2 must be untouched.
        with patch.object(
            skill_cache,
            "embed_texts",
            return_value=[_unit_vec([1, 1]), _unit_vec([1, 0])],
        ):
            skill_cache.upsert_agent("a1", "Scout", ["search", "scrape"], "")

        a1_skills = {r.skill for r in skill_cache._rows if r.agent_id == "a1"}
        a2_skills = {r.skill for r in skill_cache._rows if r.agent_id == "a2"}
        assert a1_skills == {"search", "scrape"}
        assert a2_skills == {"summarize"}

    def test_upsert_none_description_does_not_raise(self):
        with patch.object(
            skill_cache, "embed_texts", return_value=[_unit_vec([1, 0])]
        ):
            skill_cache.upsert_agent("a9", "Nameless", ["x"], None)
        assert len(skill_cache._rows) == 1

    def test_evict_removes_matching_rows(self):
        with patch.object(
            skill_cache, "embed_texts", return_value=[_unit_vec([1, 0])]
        ):
            skill_cache.upsert_agent("a1", "Scout", ["search"], "")
        skill_cache.evict_agent("a1")
        assert skill_cache._rows == []

    def test_evict_missing_agent_is_noop(self):
        with patch.object(
            skill_cache, "embed_texts", return_value=[_unit_vec([1, 0])]
        ):
            skill_cache.upsert_agent("a1", "Scout", ["search"], "")
        # Evicting an unknown id removes nothing (the ``if removed`` log branch
        # stays false) and leaves existing rows intact.
        skill_cache.evict_agent("does-not-exist")
        assert len(skill_cache._rows) == 1


class TestSkillCacheRank:
    def _seed(self, mapping: dict[str, list[float]], agent_id="a1", agent_name="Scout"):
        """Seed rows directly with deterministic unit vectors."""
        rows = [
            skill_cache._SkillRow(
                agent_id=agent_id,
                agent_name=agent_name,
                skill=skill,
                vector=_unit_vec(vec),
            )
            for skill, vec in mapping.items()
        ]
        skill_cache._rows[:] = rows

    def test_rank_empty_demand_returns_empty(self):
        self._seed({"search": [1, 0]})
        assert skill_cache.rank_skills("") == []
        assert skill_cache.rank_skills("   ") == []

    def test_rank_no_rows_returns_empty(self):
        skill_cache._rows[:] = []
        with patch.object(skill_cache, "embed_text") as embed:
            assert skill_cache.rank_skills("anything") == []
        embed.assert_not_called()  # bails before embedding the query

    def test_rank_orders_by_cosine_similarity(self):
        self._seed({"search": [1, 0], "summarize": [0, 1]})
        # Query aligned with "search".
        with patch.object(skill_cache, "embed_text", return_value=_unit_vec([1, 0])):
            results = skill_cache.rank_skills("find pages", top_k=2, min_score=-1.0)
        assert [r["skill"] for r in results] == ["search", "summarize"]
        assert results[0]["score"] == pytest.approx(1.0)
        assert results[0]["agent_id"] == "a1"
        assert results[0]["agent_name"] == "Scout"
        # Scores are plain floats, not numpy scalars.
        assert isinstance(results[0]["score"], float)

    def test_rank_applies_min_score_cutoff(self):
        self._seed({"search": [1, 0], "summarize": [0, 1]})
        # Query matches "search" (score 1.0); "summarize" scores 0.0 and is
        # dropped by the default-ish cutoff.
        with patch.object(skill_cache, "embed_text", return_value=_unit_vec([1, 0])):
            results = skill_cache.rank_skills("find", top_k=5, min_score=0.5)
        assert [r["skill"] for r in results] == ["search"]

    def test_rank_respects_top_k(self):
        self._seed({"a": [1, 0.1], "b": [1, 0.2], "c": [1, 0.3]})
        with patch.object(skill_cache, "embed_text", return_value=_unit_vec([1, 0])):
            results = skill_cache.rank_skills("q", top_k=1, min_score=-1.0)
        assert len(results) == 1

    def test_rank_dedups_by_skill_name(self):
        # Two agents expose the same skill name; only the best-scoring wins.
        rows = [
            skill_cache._SkillRow("a1", "Scout", "search", _unit_vec([1, 0])),
            skill_cache._SkillRow("a2", "Writer", "search", _unit_vec([0.9, 0.1])),
            skill_cache._SkillRow("a2", "Writer", "summarize", _unit_vec([0, 1])),
        ]
        skill_cache._rows[:] = rows
        with patch.object(skill_cache, "embed_text", return_value=_unit_vec([1, 0])):
            results = skill_cache.rank_skills("q", top_k=5, min_score=-1.0)
        skills = [r["skill"] for r in results]
        # "search" appears once (the a1 row, higher cosine), then "summarize".
        assert skills.count("search") == 1
        assert skills == ["search", "summarize"]
        search_row = next(r for r in results if r["skill"] == "search")
        assert search_row["agent_id"] == "a1"


# --------------------------------------------------------------------------- #
# core.log_config — module-level constants
# --------------------------------------------------------------------------- #


class TestLogConfig:
    def test_constants_importable_and_shaped(self):
        from core import log_config

        # Environment -> level mapping.
        assert log_config.LOG_LEVELS["development"] == logging.DEBUG
        assert log_config.LOG_LEVELS["production"] == logging.WARNING
        assert log_config.DEFAULT_LOG_LEVEL in log_config.LOG_LEVELS.values()

        # Per-module overrides.
        assert log_config.MODULE_LOG_LEVELS["auth"] == logging.INFO
        assert "core" in log_config.MODULE_LOG_LEVELS

        # Misc structured config blocks exist with expected keys.
        assert log_config.LOG_DIR.name == "logs"
        assert set(log_config.LOG_ROTATION) == {"max_files", "max_size_mb"}
        assert set(log_config.LOG_FORMATS) == {"console", "file", "error"}
        assert {"syslog", "email"} <= set(log_config.EXTERNAL_HANDLERS)
        assert log_config.EXTERNAL_HANDLERS["email"]["smtp_port"] == 587
        assert log_config.LOG_FILTERS["exclude_paths"] == [
            "/health",
            "/metrics",
            "/favicon.ico",
        ]
        assert "password" in log_config.SECURITY_CONFIG["sensitive_fields"]
        assert isinstance(log_config.SQL_LOGGING, bool)
