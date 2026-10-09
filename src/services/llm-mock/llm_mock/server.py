import json
import logging
import signal
import sys
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llm_mock import completions
from llm_mock.call import BadRequest, Call
from llm_mock.replies import delay_seconds, reply_to
from llm_mock.settings import DEFAULT_PORT, Settings

PURPOSE_HEADER = "X-Horus-Purpose"
COMPLETIONS_PATH = "/v1/chat/completions"
MAX_BODY_BYTES = 16 * 1024 * 1024

logger = logging.getLogger("llm_mock")


class MockServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], settings: Settings,
                 sleep: Callable[[float], None] = time.sleep):
        super().__init__(address, Handler)
        self.settings = settings
        self.sleep = sleep


class Handler(BaseHTTPRequestHandler):
    server: MockServer
    server_version = "llm-mock"
    sys_version = ""

    def do_GET(self) -> None:
        path = self.route()
        if path == "/health":
            self.send_json(200, {"status": "ok"})
        elif path == "/v1/models":
            self.send_json(200, completions.models(self.server.settings.model))
        else:
            self.send_json(404, completions.error_body(f"No route for GET {path}", 404))

    def do_POST(self) -> None:
        path = self.route()
        if path != COMPLETIONS_PATH:
            self.send_json(404, completions.error_body(f"No route for POST {path}", 404))
            return
        try:
            call = Call.from_request(self.read_json(), self.headers.get(PURPOSE_HEADER, ""))
        except BadRequest as error:
            self.send_json(400, completions.error_body(str(error), 400))
            return
        settings = self.server.settings
        reply = reply_to(call, settings)
        self.server.sleep(delay_seconds(call, settings))
        logger.info(
            "chat completion: purpose=%s schema=%s stream=%s status=%d",
            call.purpose or "-", call.schema_name or "-", call.stream, reply.status,
        )
        model = call.model or settings.model
        if reply.error:
            self.send_json(reply.status, completions.error_body(reply.error, reply.status))
        elif call.stream:
            self.send_stream(completions.stream_events(call, model, reply.content))
        else:
            self.send_json(200, completions.completion(call, model, reply.content))

    def route(self) -> str:
        return self.path.split("?", 1)[0].rstrip("/") or "/"

    def read_json(self) -> object:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise BadRequest("Content-Length is not a number")
        if length <= 0:
            raise BadRequest("the request has no body")
        if length > MAX_BODY_BYTES:
            raise BadRequest("the request body is too large")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise BadRequest("the request body is not JSON")

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_stream(self, events: list[bytes]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for event in events:
                self.wfile.write(event)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            logger.info("The client closed the stream early")

    def log_message(self, message_format: str, *args: object) -> None:
        logger.debug("%s %s", self.address_string(), message_format % args)


def serve(settings: Settings, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
    server = MockServer((host, port), settings)
    logger.warning(
        "Mock AI mode: llm-mock answers every language-model call with simulated, "
        "deterministic text (scenario %s, latency %d ms, model %s). Answers are not "
        "produced by a language model.",
        settings.scenario, settings.latency_ms, settings.model,
    )
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    serve(Settings.from_env())
