"""Coverage-focused unit tests for the MAS app-wiring modules.

Targets:
    * ``core.app``                  — FastAPI factory + lifespan
    * ``core.correlation_middleware`` — correlation-ID propagation
    * ``core.metrics_middleware``     — Prometheus request metrics
    * ``main``                        — ASGI entrypoint + health endpoint
    * ``bootstrap_llm``               — first-run model download helper

Everything here is hermetic.  All startup side effects (DB init, RabbitMQ
connect/close, background-task spawns, embedding/LLM preload threads, engine
disposal) are patched with auto-reverting mocks, so building or driving the
app never opens a real connection or leaks a thread.  ``core.metrics`` does
not (yet) export the counters ``core.metrics_middleware`` imports, so we
inject them with ``patch(..., create=True)`` *only while importing that
module*; the patch reverts immediately, leaving the shared ``core.metrics``
namespace untouched for the rest of the suite.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

import core.app as app_module
from core.structured_logging import get_correlation_id

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


async def _noop_coro():
    """A finished coroutine used to replace the never-ending watchdog loops."""
    return None


@pytest.fixture
def patched_lifespan_side_effects():
    """Patch every startup/shutdown side effect of ``core.app``.

    All patches auto-revert, so the real DB/broker/thread helpers are restored
    when the test finishes.  ``check_agent_heartbeat`` / ``check_task_timeout``
    are swapped for an already-complete coroutine so ``asyncio.create_task``
    never spins an infinite watchdog loop inside the test event loop.
    """
    with (
        patch.object(app_module, "init_db") as init_db,
        patch.object(app_module, "check_agent_heartbeat", new=_noop_coro),
        patch.object(app_module, "check_task_timeout", new=_noop_coro),
        patch.object(app_module, "rabbitmq_instance") as rabbitmq_instance,
        patch.object(app_module, "start_llm_preload_background_thread") as llm_preload,
        patch.object(
            app_module, "start_embedding_preload_background_thread"
        ) as emb_preload,
        patch.object(app_module, "engine") as engine,
    ):
        yield {
            "init_db": init_db,
            "rabbitmq_instance": rabbitmq_instance,
            "llm_preload": llm_preload,
            "emb_preload": emb_preload,
            "engine": engine,
        }


# --------------------------------------------------------------------------- #
# core.app — factory wiring
# --------------------------------------------------------------------------- #


class TestCreateAppEnvironment:
    def test_factory_returns_configured_fastapi_app(self):
        """``create_app_environment`` builds a titled FastAPI app with our lifespan."""
        app = app_module.create_app_environment()

        assert isinstance(app, FastAPI)
        assert app.title == "MAS - Multi-Agent System"
        assert app.version == "1.0.0"
        # A lifespan context is wired in (FastAPI/Instrumentator wrap ours, so
        # we assert presence rather than identity; TestLifespan proves it runs
        # our boot/teardown hooks).
        assert app.router.lifespan_context is not None
        assert callable(app.router.lifespan_context)

    def test_factory_registers_expected_routes_and_middleware(self):
        """All routers and both custom middlewares are mounted, plus /metrics."""
        app = app_module.create_app_environment()

        paths = {route.path for route in app.routes}
        # Routers from each feature package are included.
        assert "/rabbitmq/heartbeat" in paths
        # Instrumentator.expose() adds the Prometheus scrape endpoint.
        assert "/metrics" in paths

        # CORS + logging middleware both present in the stack.
        middleware_classes = {m.cls.__name__ for m in app.user_middleware}
        assert "LoggingMiddleware" in middleware_classes
        assert "CORSMiddleware" in middleware_classes

    def test_factory_sets_module_level_instrumentator(self):
        """The module-global instrumentator is assigned during wiring."""
        app_module.instrumentator = None
        app_module.create_app_environment()
        assert app_module.instrumentator is not None

    def test_metrics_endpoint_served_through_full_lifespan(
        self, patched_lifespan_side_effects
    ):
        """Driving the app through TestClient exercises startup + a real request."""
        app = app_module.create_app_environment()

        with TestClient(app) as client:
            response = client.get("/metrics")

        assert response.status_code == 200
        # Prometheus exposition format.
        assert "# HELP" in response.text or "# TYPE" in response.text


# --------------------------------------------------------------------------- #
# core.app — lifespan startup / shutdown
# --------------------------------------------------------------------------- #


class TestLifespan:
    def test_startup_and_shutdown_invoke_all_side_effects(
        self, patched_lifespan_side_effects
    ):
        """Happy path: every boot hook runs on enter, teardown hooks on exit."""
        mocks = patched_lifespan_side_effects
        app = app_module.create_app_environment()

        with TestClient(app):
            # startup hooks
            mocks["init_db"].assert_called_once()
            mocks["rabbitmq_instance"].connect.assert_called_once()
            mocks["llm_preload"].assert_called_once()
            mocks["emb_preload"].assert_called_once()

        # shutdown hooks fire when the context manager exits.
        mocks["rabbitmq_instance"].close.assert_called_once()
        mocks["engine"].dispose.assert_called_once()

    def test_startup_propagates_db_init_failure(
        self, patched_lifespan_side_effects
    ):
        """A failing ``init_db`` is logged and re-raised out of the lifespan."""
        mocks = patched_lifespan_side_effects
        mocks["init_db"].side_effect = RuntimeError("db boom")
        app = app_module.create_app_environment()

        with pytest.raises(RuntimeError, match="db boom"):
            with TestClient(app):
                pass  # pragma: no cover - startup raises before body runs

        # We failed before reaching the RabbitMQ connect line.
        mocks["rabbitmq_instance"].connect.assert_not_called()

    def test_startup_propagates_rabbitmq_failure(
        self, patched_lifespan_side_effects
    ):
        """A failing broker connect is logged and re-raised out of the lifespan."""
        mocks = patched_lifespan_side_effects
        mocks["rabbitmq_instance"].connect.side_effect = ConnectionError("no broker")
        app = app_module.create_app_environment()

        with pytest.raises(ConnectionError, match="no broker"):
            with TestClient(app):
                pass  # pragma: no cover - startup raises before body runs

        # DB init ran before the broker step blew up.
        mocks["init_db"].assert_called_once()
        # Preload threads are wired only after the broker connects.
        mocks["llm_preload"].assert_not_called()

    def test_factory_logs_when_tracing_initialized(self):
        """When tracing init reports success, the success-log branch is taken."""
        with patch.object(app_module, "init_tracing", return_value=True) as it:
            app = app_module.create_app_environment()
        assert isinstance(app, FastAPI)
        it.assert_called_once_with(app)

    def test_shutdown_awaits_and_swallows_cancelled_heartbeat(
        self, patched_lifespan_side_effects
    ):
        """A long-lived heartbeat task is cancelled and its CancelledError swallowed."""
        import asyncio

        async def _forever():
            # Runs until cancelled at shutdown, so `await task` raises
            # CancelledError, exercising the try/except cleanup branch.
            await asyncio.Event().wait()

        with patch.object(app_module, "check_agent_heartbeat", new=_forever):
            app = app_module.create_app_environment()
            with TestClient(app):
                pass

        # Clean shutdown still disposed the engine after swallowing the cancel.
        patched_lifespan_side_effects["engine"].dispose.assert_called_once()

    def test_shutdown_skips_close_when_no_rabbitmq_instance(
        self, patched_lifespan_side_effects
    ):
        """A falsy broker handle skips ``close()`` at shutdown (defensive branch)."""
        rmq = patched_lifespan_side_effects["rabbitmq_instance"]
        # Truthy enough to call .connect() at startup, falsy at the shutdown
        # `if rabbitmq_instance:` guard so .close() is skipped.
        rmq.__bool__ = MagicMock(return_value=False)
        app = app_module.create_app_environment()

        with TestClient(app):
            pass

        rmq.connect.assert_called_once()
        rmq.close.assert_not_called()
        patched_lifespan_side_effects["engine"].dispose.assert_called_once()


# --------------------------------------------------------------------------- #
# core.correlation_middleware
# --------------------------------------------------------------------------- #


def _build_correlation_app():
    """Tiny app mounting only the correlation middleware, with probe routes."""
    from core.correlation_middleware import CorrelationIDMiddleware

    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)

    @app.get("/ping")
    async def ping():
        # Surface the contextvar so we can assert it was bound mid-request.
        return PlainTextResponse(get_correlation_id() or "")

    @app.get("/boom")
    async def boom():
        raise ValueError("kaboom")

    @app.get("/metrics")
    async def metrics():
        return PlainTextResponse("metrics-body")

    return app


class TestCorrelationMiddleware:
    def test_generates_correlation_id_when_absent(self):
        """No inbound header -> a fresh UUID is minted and echoed on both headers."""
        client = TestClient(_build_correlation_app())
        response = client.get("/ping")

        assert response.status_code == 200
        cid = response.headers["X-Request-ID"]
        assert cid  # non-empty
        assert response.headers["X-Correlation-ID"] == cid
        # The same id was visible inside the handler via the contextvar.
        assert response.text == cid

    def test_reuses_inbound_request_id_header(self):
        """An incoming X-Request-ID is honoured rather than regenerated."""
        client = TestClient(_build_correlation_app())
        response = client.get("/ping", headers={"X-Request-ID": "abc-123"})

        assert response.headers["X-Request-ID"] == "abc-123"
        assert response.headers["X-Correlation-ID"] == "abc-123"
        assert response.text == "abc-123"

    def test_reuses_inbound_correlation_id_header(self):
        """Falls through to X-Correlation-ID when X-Request-ID is missing."""
        client = TestClient(_build_correlation_app())
        response = client.get("/ping", headers={"X-Correlation-ID": "corr-999"})

        assert response.headers["X-Request-ID"] == "corr-999"
        assert response.headers["X-Correlation-ID"] == "corr-999"

    def test_query_params_branch_is_logged(self):
        """Requests carrying a query string hit the query_params logging branch."""
        client = TestClient(_build_correlation_app())
        response = client.get("/ping", params={"q": "hello", "n": "2"})
        assert response.status_code == 200
        assert response.headers["X-Request-ID"]

    def test_excluded_path_skips_correlation_headers(self):
        """Excluded paths short-circuit before any correlation header is added."""
        client = TestClient(_build_correlation_app())
        response = client.get("/metrics")

        assert response.status_code == 200
        assert response.text == "metrics-body"
        assert "X-Request-ID" not in response.headers
        assert "X-Correlation-ID" not in response.headers

    def test_exception_is_logged_and_reraised(self):
        """A handler exception is logged then propagated (500), id cleared after."""
        client = TestClient(_build_correlation_app(), raise_server_exceptions=False)
        response = client.get("/boom")

        assert response.status_code == 500
        # The finally-block clears the contextvar regardless of the error.
        assert get_correlation_id() is None


# --------------------------------------------------------------------------- #
# core.metrics_middleware
# --------------------------------------------------------------------------- #


@pytest.fixture
def metrics_middleware_module():
    """Import ``core.metrics_middleware`` with the (currently missing) counter
    helpers injected into ``core.metrics`` for the duration of the import.

    The ``create=True`` patches revert as soon as the ``with`` block ends, so
    the real ``core.metrics`` module is left pristine for the rest of the
    suite.  The imported middleware module keeps its own bound references to
    the mocks (frozen at import time), which is exactly what we want for the
    behavioural assertions below.
    """
    import core.metrics as cm

    record_calls = {
        "increment_request_count": MagicMock(),
        "observe_request_latency": MagicMock(),
        "record_error": MagicMock(),
        "track_request_in_progress": MagicMock(),
    }
    with (
        patch.object(
            cm, "increment_request_count", record_calls["increment_request_count"],
            create=True,
        ),
        patch.object(
            cm, "observe_request_latency", record_calls["observe_request_latency"],
            create=True,
        ),
        patch.object(cm, "record_error", record_calls["record_error"], create=True),
        patch.object(
            cm, "track_request_in_progress",
            record_calls["track_request_in_progress"], create=True,
        ),
    ):
        module = importlib.import_module("core.metrics_middleware")
        module = importlib.reload(module)

    return module, record_calls


def _build_metrics_app(mw_module):
    app = FastAPI()
    app.add_middleware(mw_module.MetricsMiddleware)

    @app.get("/tasks/{task_id}")
    async def task(task_id: str):
        return {"task_id": task_id}

    @app.get("/boom")
    async def boom():
        raise ValueError("metrics-kaboom")

    @app.get("/metrics")
    async def metrics():
        return PlainTextResponse("scrape")

    return app


class TestMetricsMiddleware:
    def test_normal_request_records_count_and_latency(self, metrics_middleware_module):
        """A served request increments in-progress, count and latency once each."""
        mw_module, calls = metrics_middleware_module
        client = TestClient(_build_metrics_app(mw_module))

        response = client.get("/tasks/42")
        assert response.status_code == 200

        # Endpoint is normalized: numeric id -> {id}.
        calls["increment_request_count"].assert_called_once_with("GET", "/tasks/{id}", 200)
        assert calls["observe_request_latency"].call_count == 1
        observed_args = calls["observe_request_latency"].call_args.args
        assert observed_args[0] == "GET"
        assert observed_args[1] == "/tasks/{id}"
        assert isinstance(observed_args[2], float)

        # In-progress gauge goes up then down (increment True then False).
        assert calls["track_request_in_progress"].call_count == 2
        increments = [c.kwargs.get("increment") for c in calls["track_request_in_progress"].call_args_list]
        assert increments == [True, False]
        calls["record_error"].assert_not_called()

    def test_excluded_path_records_nothing(self, metrics_middleware_module):
        """Excluded paths bypass all metric instrumentation."""
        mw_module, calls = metrics_middleware_module
        client = TestClient(_build_metrics_app(mw_module))

        response = client.get("/metrics")
        assert response.status_code == 200
        assert response.text == "scrape"

        calls["increment_request_count"].assert_not_called()
        calls["observe_request_latency"].assert_not_called()
        calls["track_request_in_progress"].assert_not_called()
        calls["record_error"].assert_not_called()

    def test_exception_records_error_and_uses_default_status(
        self, metrics_middleware_module
    ):
        """A raised handler records an error and reports the default 500 status."""
        mw_module, calls = metrics_middleware_module
        client = TestClient(
            _build_metrics_app(mw_module), raise_server_exceptions=False
        )

        response = client.get("/boom")
        assert response.status_code == 500

        calls["record_error"].assert_called_once_with(
            error_type="ValueError", component="http"
        )
        # finally-block still records the request with the default status 500.
        calls["increment_request_count"].assert_called_once_with("GET", "/boom", 500)
        assert calls["track_request_in_progress"].call_count == 2

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("/agents/123e4567-e89b-12d3-a456-426614174000", "/agents/{id}"),
            ("/tasks/42", "/tasks/{id}"),
            ("/users/7/tasks/9", "/users/{id}/tasks/{id}"),
            ("/health/", "/health"),
            ("/", "/"),
            ("", "/"),
        ],
    )
    def test_normalize_endpoint(self, metrics_middleware_module, raw, expected):
        """ID/UUID segments collapse to {id}; trailing slashes trimmed; '' -> '/'."""
        mw_module, _ = metrics_middleware_module
        mw = mw_module.MetricsMiddleware(MagicMock())
        assert mw._normalize_endpoint(raw) == expected


# --------------------------------------------------------------------------- #
# main — ASGI entrypoint + health endpoint
# --------------------------------------------------------------------------- #


@pytest.fixture
def main_module(patched_lifespan_side_effects):
    """Import ``main`` (building its app) with startup side effects patched."""
    import main as main_mod

    return importlib.reload(main_mod)


class TestMainEntrypoint:
    def test_app_is_built_at_import(self, main_module):
        """Importing ``main`` exposes a wired FastAPI app and the '/' route."""
        assert isinstance(main_module.app, FastAPI)
        paths = {route.path for route in main_module.app.routes}
        assert "/" in paths

    def test_health_endpoint_authenticated(self, main_module):
        """An authenticated user receives their claims and the success message."""
        from auth.auth_tool_functions import get_current_user
        from db.database import get_db

        app = main_module.app
        user_payload = {"username": "alice", "id": 1, "role": "admin"}
        app.dependency_overrides[get_current_user] = lambda: user_payload
        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app)
            response = client.get("/")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Authentification succeed"
        assert body["User"] == user_payload

    def test_health_endpoint_unauthenticated_returns_401(self, main_module):
        """When the dependency yields ``None`` the handler raises a 401."""
        from auth.auth_tool_functions import get_current_user
        from db.database import get_db

        app = main_module.app
        app.dependency_overrides[get_current_user] = lambda: None
        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 401
        assert response.json()["detail"] == "Not authenticated"

    def test_health_endpoint_user_without_username(self, main_module):
        """A claims dict lacking 'username' still succeeds, defaulting to 'unknown'."""
        from auth.auth_tool_functions import get_current_user
        from db.database import get_db

        app = main_module.app
        user_payload = {"id": 5, "role": "user"}  # no 'username' key
        app.dependency_overrides[get_current_user] = lambda: user_payload
        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app)
            response = client.get("/")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["User"] == user_payload


# --------------------------------------------------------------------------- #
# bootstrap_llm
# --------------------------------------------------------------------------- #


class TestBootstrapLLM:
    def test_default_model_dir_uses_hub_leaf(self):
        import bootstrap_llm

        base = Path("/srv")
        out = bootstrap_llm._default_model_dir(base, "Qwen/Qwen2.5-1.5B-Instruct")
        assert out == base / "models" / "Qwen2.5-1.5B-Instruct"

    def test_default_model_dir_falls_back_to_model_when_trailing_slash(self):
        import bootstrap_llm

        # A trailing slash makes the leaf empty -> fallback name 'model'.
        out = bootstrap_llm._default_model_dir(Path("/srv"), "vendor/")
        assert out == Path("/srv") / "models" / "model"

    def test_required_files_present_false_when_dir_missing(self, tmp_path):
        import bootstrap_llm

        assert bootstrap_llm._required_files_present(tmp_path / "nope") is False

    def test_required_files_present_false_when_files_missing(self, tmp_path):
        import bootstrap_llm

        (tmp_path / "config.json").write_text("{}")  # tokenizer.json absent
        assert bootstrap_llm._required_files_present(tmp_path) is False

    def test_required_files_present_true_when_all_present(self, tmp_path):
        import bootstrap_llm

        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "tokenizer.json").write_text("{}")
        assert bootstrap_llm._required_files_present(tmp_path) is True

    def test_main_noops_when_model_already_present(self, tmp_path, monkeypatch):
        import bootstrap_llm

        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "tokenizer.json").write_text("{}")
        monkeypatch.setenv("LLM_MODEL_DIR", str(tmp_path))
        monkeypatch.setenv("LLM_MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct")

        assert bootstrap_llm.main() == 0

    def test_main_returns_1_when_offline_and_missing(self, tmp_path, monkeypatch):
        import bootstrap_llm

        monkeypatch.setenv("LLM_MODEL_DIR", str(tmp_path / "missing"))
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        assert bootstrap_llm.main() == 1

    def test_main_downloads_when_missing(self, tmp_path, monkeypatch):
        import bootstrap_llm

        target = tmp_path / "dl"
        monkeypatch.setenv("LLM_MODEL_DIR", str(target))
        monkeypatch.setenv("HF_HUB_OFFLINE", "0")

        fake_hub = MagicMock()
        # snapshot_download imported lazily inside main(): inject a fake module.
        monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", fake_hub)

        rc = bootstrap_llm.main()

        assert rc == 0
        assert target.is_dir()  # mkdir(parents=True) ran
        fake_hub.snapshot_download.assert_called_once()
        kwargs = fake_hub.snapshot_download.call_args.kwargs
        assert kwargs["local_dir"] == str(target)
        assert kwargs["local_dir_use_symlinks"] is False

    def test_main_returns_3_on_download_failure(self, tmp_path, monkeypatch):
        import bootstrap_llm

        monkeypatch.setenv("LLM_MODEL_DIR", str(tmp_path / "dl"))
        monkeypatch.setenv("HF_HUB_OFFLINE", "0")

        fake_hub = MagicMock()
        fake_hub.snapshot_download.side_effect = RuntimeError("network down")
        monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", fake_hub)

        assert bootstrap_llm.main() == 3

    def test_main_returns_2_when_hub_import_fails(self, tmp_path, monkeypatch):
        import builtins

        import bootstrap_llm

        monkeypatch.setenv("LLM_MODEL_DIR", str(tmp_path / "dl"))
        monkeypatch.setenv("HF_HUB_OFFLINE", "0")
        # Ensure no cached module so the import statement actually executes.
        monkeypatch.delitem(
            __import__("sys").modules, "huggingface_hub", raising=False
        )

        real_import = builtins.__import__

        def _boom(name, *args, **kwargs):
            if name == "huggingface_hub":
                raise ImportError("no hub")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _boom)
        assert bootstrap_llm.main() == 2
