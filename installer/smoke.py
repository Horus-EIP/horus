from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import profiles
from common import (
    EXIT_SMOKE_FAILED,
    InstallError,
    Log,
    elapsed,
    find_repo,
    infra_dir,
)

DEFAULT_BASE_URLS = {
    "mas": "http://127.0.0.1:8000",
    "ks": "http://127.0.0.1:8080",
}

DEFAULT_TIMEOUT = 1200
HTTP_TIMEOUT = 30
UPLOAD_TIMEOUT = 300
AGENT_WAIT_SECONDS = 300
AGENT_POLL_INTERVAL = 5.0
TASK_POLL_INTERVAL = 15.0
WS_RECV_SLICE = 5.0

DEMO_DOC = "1_Q4_2025_Financial_Report.md"

QUESTION = "What was our Q4 2025 revenue?"
ANSWER_RE = re.compile(r"4\.2\s*(million|m)|4,200,000", re.IGNORECASE)
QUARTER_RE = re.compile(r"\bq4\b", re.IGNORECASE)
SUBJECT_RE = re.compile(r"revenue|fincorp", re.IGNORECASE)

NEGATIVE_QUESTION = "What is the capital of Peru?"
NEGATIVE_RE = re.compile(r"\blima\b", re.IGNORECASE)

MANAGER_NAMES = {"manager"}
PLANNING_SKILLS = {"planning", "orchestration"}
TASK_ACCEPTED_STATUSES = (200, 202)

def _sanitise_filename(name: str) -> str:
    return name.replace("\r", "").replace("\n", "").replace('"', "%22")

def build_multipart(
    files: list[tuple[str, str, str, bytes]],
    boundary: str | None = None,
) -> tuple[str, bytes]:
    boundary = boundary or ("----horus-smoke-" + uuid.uuid4().hex)
    marker = ("--" + boundary).encode("ascii")
    body = bytearray()
    for field, filename, ctype, data in files:
        body += marker + b"\r\n"
        body += (
            'Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
            % (_sanitise_filename(field), _sanitise_filename(filename))
        ).encode("utf-8")
        body += ("Content-Type: %s\r\n\r\n" % ctype).encode("ascii")
        body += data
        body += b"\r\n"
    body += marker + b"--\r\n"
    return "multipart/form-data; boundary=" + boundary, bytes(body)

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

class WebSocketError(Exception):
    pass

class Frame:

    __slots__ = ("fin", "opcode", "payload")

    def __init__(self, fin: bool, opcode: int, payload: bytes):
        self.fin = fin
        self.opcode = opcode
        self.payload = payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Frame(fin={self.fin}, opcode={self.opcode:#x}, len={len(self.payload)})"

def _apply_mask(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % 4] for i, b in enumerate(data))

def encode_frame(opcode: int, payload: bytes = b"", mask_key: bytes | None = None) -> bytes:
    if mask_key is None:
        mask_key = os.urandom(4)
    if len(mask_key) != 4:
        raise ValueError("mask key must be exactly 4 bytes")

    head = bytearray()
    head.append(0x80 | (opcode & 0x0F))
    n = len(payload)
    if n < 126:
        head.append(0x80 | n)
    elif n < (1 << 16):
        head.append(0x80 | 126)
        head += struct.pack("!H", n)
    else:
        head.append(0x80 | 127)
        head += struct.pack("!Q", n)
    return bytes(head) + mask_key + _apply_mask(payload, mask_key)

def decode_frame(buf: bytes) -> tuple[Frame | None, int]:
    if len(buf) < 2:
        return None, 0
    b0, b1 = buf[0], buf[1]
    fin = bool(b0 & 0x80)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    off = 2

    if length == 126:
        if len(buf) < off + 2:
            return None, 0
        length = struct.unpack("!H", buf[off:off + 2])[0]
        off += 2
    elif length == 127:
        if len(buf) < off + 8:
            return None, 0
        length = struct.unpack("!Q", buf[off:off + 8])[0]
        off += 8

    key = b""
    if masked:
        if len(buf) < off + 4:
            return None, 0
        key = buf[off:off + 4]
        off += 4

    if len(buf) < off + length:
        return None, 0
    payload = buf[off:off + length]
    if masked:
        payload = _apply_mask(payload, key)
    return Frame(fin, opcode, bytes(payload)), off + length

class MessageAssembler:

    def __init__(self) -> None:
        self._opcode: int | None = None
        self._parts: list[bytes] = []

    def push(self, frame: Frame) -> tuple[int, bytes] | None:
        if frame.opcode >= 0x8:
            return frame.opcode, frame.payload

        if frame.opcode == OP_CONT:
            if self._opcode is None:
                raise WebSocketError("continuation frame with nothing to continue")
            self._parts.append(frame.payload)
        else:
            if self._opcode is not None:
                raise WebSocketError("new data frame while a fragmented message was open")
            self._opcode = frame.opcode
            self._parts = [frame.payload]

        if not frame.fin:
            return None
        opcode, payload = self._opcode, b"".join(self._parts)
        self._opcode, self._parts = None, []
        return opcode, payload

def expected_accept(key: str) -> str:
    digest = hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")

def build_handshake(host_header: str, path: str, key: str) -> bytes:
    return (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "User-Agent: horus-installer-smoke\r\n"
        "\r\n"
    ).encode("ascii")

def is_bare_figure(text: str) -> bool:
    remainder = ANSWER_RE.sub(" ", text or "")
    return len(re.sub(r"[^a-z]", "", remainder.lower())) < 6


def check_answer(text: str) -> tuple[bool, str]:
    t = text or ""
    if not ANSWER_RE.search(t):
        return False, "the answer does not contain 4.2M / 4.2 million / 4,200,000"
    if is_bare_figure(t):
        return True, "the figure, stated bare"
    if QUARTER_RE.search(t) or SUBJECT_RE.search(t):
        return True, "figure and grounding both present"
    return False, ("the answer contains 4.2 million but says nothing about Q4, "
                   "revenue or FinCorp, so the number looks coincidental")

def _redact_token(url: str) -> str:
    return re.sub(r"(token=)[^&\s]+", r"\1<redacted>", url)

class Unreachable(Exception):
    pass

class Response:
    __slots__ = ("status", "body")

    def __init__(self, status: int, body: bytes):
        self.status = status
        self.body = body

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return None

    def text(self, limit: int = 300) -> str:
        return self.body.decode("utf-8", "replace")[:limit].replace("\n", " ")

def http(
    method: str,
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT,
) -> Response:
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", "horus-installer-smoke")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, timeout)) as resp:
            return Response(resp.status, resp.read())
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:  # noqa: BLE001 - body is diagnostics only
            body = b""
        return Response(exc.code, body)
    except urllib.error.URLError as exc:
        raise Unreachable(str(exc.reason)) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise Unreachable(f"timed out after {timeout:.0f}s") from exc
    except OSError as exc:
        raise Unreachable(str(exc)) from exc

def _json_post(url: str, payload: dict, token: str | None, timeout: float) -> Response:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(payload).encode("utf-8")
    return http("POST", url, data=body, headers=headers, timeout=timeout)

def _auth_get(url: str, token: str, timeout: float) -> Response:
    return http("GET", url, headers={"Authorization": "Bearer " + token}, timeout=timeout)

class WSClient:

    def __init__(self, url: str, connect_timeout: float = 20.0):
        self.url = url
        self.connect_timeout = connect_timeout
        self._sock: socket.socket | None = None
        self._buf = b""
        self._assembler = MessageAssembler()

    def connect(self) -> None:
        parts = urllib.parse.urlsplit(self.url)
        secure = parts.scheme == "wss"
        host = parts.hostname or "localhost"
        port = parts.port or (443 if secure else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        try:
            sock = socket.create_connection((host, port), timeout=self.connect_timeout)
        except OSError as exc:
            raise WebSocketError(f"cannot connect to {host}:{port}: {exc}") from exc
        if secure:
            try:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            except OSError as exc:
                sock.close()
                raise WebSocketError(f"TLS handshake failed: {exc}") from exc

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        host_header = host if port in (80, 443) else f"{host}:{port}"
        try:
            sock.settimeout(self.connect_timeout)
            sock.sendall(build_handshake(host_header, path, key))
            head = self._read_until_headers(sock)
        except OSError as exc:
            sock.close()
            raise WebSocketError(f"handshake failed: {exc}") from exc

        status_line = head.split("\r\n", 1)[0]
        if " 101" not in status_line:
            sock.close()
            raise WebSocketError(f"server refused the upgrade: {status_line.strip()}")
        accept = ""
        for line in head.split("\r\n")[1:]:
            name, _, value = line.partition(":")
            if name.strip().lower() == "sec-websocket-accept":
                accept = value.strip()
        if accept != expected_accept(key):
            sock.close()
            raise WebSocketError(
                "the server did not return a valid Sec-WebSocket-Accept, "
                "so this is not a WebSocket endpoint"
            )
        self._sock = sock

    def _read_until_headers(self, sock: socket.socket) -> str:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                raise WebSocketError("connection closed during the handshake")
            data += chunk
            if len(data) > 64 * 1024:
                raise WebSocketError("handshake response is implausibly large")
        head, _, rest = data.partition(b"\r\n\r\n")
        self._buf = rest
        return head.decode("latin-1")

    def send(self, opcode: int, payload: bytes = b"") -> None:
        if self._sock is None:
            raise WebSocketError("socket is not connected")
        self._sock.sendall(encode_frame(opcode, payload))

    def recv_message(self, timeout: float) -> tuple[int, bytes] | None:
        if self._sock is None:
            raise WebSocketError("socket is not connected")
        deadline = time.monotonic() + timeout
        while True:
            frame, used = decode_frame(self._buf)
            if frame is not None:
                self._buf = self._buf[used:]
                message = self._assembler.push(frame)
                if message is None:
                    continue
                opcode, payload = message
                if opcode == OP_PING:
                    self.send(OP_PONG, payload)
                    continue
                if opcode == OP_PONG:
                    continue
                if opcode == OP_CLOSE:
                    raise WebSocketError("server closed the chat socket")
                return opcode, payload

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                self._sock.settimeout(min(remaining, WS_RECV_SLICE))
                chunk = self._sock.recv(65536)
            except (socket.timeout, TimeoutError):
                continue
            except OSError as exc:
                raise WebSocketError(f"read failed: {exc}") from exc
            if not chunk:
                raise WebSocketError("server closed the chat socket")
            self._buf += chunk

    def close(self) -> None:
        if self._sock is None:
            return
        try:
            self.send(OP_CLOSE, struct.pack("!H", 1000))
        except Exception:  # noqa: BLE001 - teardown is best effort
            pass
        try:
            self._sock.close()
        except OSError:
            pass
        self._sock = None

class Steps:

    def __init__(self, log: Log):
        self.log = log
        self.entries: list[dict] = []
        self._t0 = 0.0
        self._current: dict | None = None

    def start(self, name: str) -> None:
        self.log.say("")
        self.log.say("  " + name)
        self._current = {"name": name, "ok": False, "detail": "", "seconds": 0.0}
        self.entries.append(self._current)
        self._t0 = time.monotonic()

    def _stamp(self) -> float:
        seconds = round(time.monotonic() - self._t0, 2)
        if self._current is not None:
            self._current["seconds"] = seconds
        return seconds

    def passed(self, detail: str) -> None:
        seconds = self._stamp()
        if self._current is not None:
            self._current["ok"] = True
            self._current["detail"] = detail
        self.log.ok(f"{detail}  [{elapsed(seconds)}]")

    def warned(self, detail: str) -> None:
        seconds = self._stamp()
        if self._current is not None:
            self._current["detail"] = detail
            self._current["warning"] = True
        self.log.warn(f"{detail}  [{elapsed(seconds)}]")

    def failed(self, detail: str) -> None:
        self._stamp()
        if self._current is not None:
            self._current["detail"] = detail
        self.log.fail(detail)

def _fail(steps: Steps, headline: str, detail: str, fix: str) -> InstallError:
    steps.failed(headline)
    return InstallError(EXIT_SMOKE_FAILED, headline, detail, fix)

def _remaining(deadline: float, steps: Steps, what: str) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise _fail(
            steps,
            f"Verification ran out of time during: {what}",
            "The stack did not finish the check within the time budget. On a\n"
            "CPU-only profile a single answer can take several minutes, and the\n"
            "very first one also pays for loading the model.",
            "Give it longer and run the verification on its own:\n"
            "  python installer/smoke.py --timeout 2400\n"
            "Watch what it is doing meanwhile:\n"
            "  docker compose -f src/infra/docker-compose.yml logs -f agent mas",
        )
    return left

def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key] = val
    return values

def model_server_of(infra: Path) -> str:
    compose_file = read_env(infra / ".env").get("COMPOSE_FILE", "")
    return profiles.model_server_for_compose_file(compose_file)

MODEL_SERVER_HINTS = {
    profiles.GPU_MODEL_SERVER: (
        "On a machine without a usable GPU, reinstall with --profile cpu-standard."
    ),
    profiles.CPU_MODEL_SERVER: (
        "On a CPU profile llm is llama-server. If its log shows it was killed\n"
        "for memory, raise LLM_SERVER_MEM_LIMIT in src/infra/.env. If it never\n"
        "started, its model file is missing or damaged: START-HERE (your\n"
        "platform) --start downloads and checks it again. Then read:\n"
        "  docker compose logs llm-model llm"
    ),
}

def admin_credentials(infra: Path, steps: Steps) -> tuple[str, str]:
    env_path = infra / ".env"
    if not env_path.is_file():
        raise _fail(
            steps,
            "No .env file was generated for the stack.",
            f"Expected: {env_path}\n"
            "The verification step reads the seeded admin credentials from it.",
            "Run the installer again from the start so it writes the .env:\n"
            "  START-HERE (your platform)",
        )
    env = read_env(env_path)
    return (
        env.get("SUPER_USER_USERNAME") or "admin",
        env.get("SUPER_USER_PASSWORD") or "admin",
    )

def step_knowledge_health(steps: Steps, ks: str, deadline: float) -> None:
    steps.start("1/9  Knowledge store health")
    budget = min(HTTP_TIMEOUT, _remaining(deadline, steps, "knowledge store health"))
    try:
        resp = http("GET", ks + "/health", timeout=budget)
    except Unreachable as exc:
        raise _fail(
            steps,
            "The knowledge store is not answering on port 8080.",
            f"GET {ks}/health -> {exc}",
            "Check whether the container is up and what it said:\n"
            "  docker compose -f src/infra/docker-compose.yml ps knowledge_store\n"
            "  docker compose -f src/infra/docker-compose.yml logs --tail 50 knowledge_store\n"
            "On first start it downloads the embedding model, which can take a\n"
            "few minutes - wait, then run this again.",
        ) from exc

    body = resp.json() or {}
    if resp.status != 200 or body.get("status") != "healthy":
        raise _fail(
            steps,
            f"The knowledge store answered but is not healthy (HTTP {resp.status}).",
            f"GET {ks}/health returned: {resp.text()}",
            "Read its log for the real error:\n"
            "  docker compose -f src/infra/docker-compose.yml logs --tail 100 knowledge_store",
        )
    steps.passed(f"{ks}/health -> healthy")

def step_unauthenticated_ping(steps: Steps, mas: str, deadline: float) -> None:
    steps.start("2/9  API rejects unauthenticated requests")
    budget = min(HTTP_TIMEOUT, _remaining(deadline, steps, "unauthenticated ping"))
    try:
        resp = http("GET", mas + "/", timeout=budget)
    except Unreachable as exc:
        raise _fail(
            steps,
            "The Horus API is not answering on port 8000.",
            f"GET {mas}/ -> {exc}",
            "Check the API container:\n"
            "  docker compose -f src/infra/docker-compose.yml ps mas\n"
            "  docker compose -f src/infra/docker-compose.yml logs --tail 80 mas\n"
            "If it is restarting in a loop, the database migration usually failed.",
        ) from exc

    if resp.status == 200:
        raise _fail(
            steps,
            "The API served a protected route WITHOUT a login. Refusing to pass.",
            f"GET {mas}/ returned HTTP 200 with no Authorization header.\n"
            "That route is guarded by OAuth2 and must return 401. A 200 means\n"
            "authentication is not being enforced, so anything reachable on\n"
            "port 8000 is open to anyone on this machine or network.",
            "Do not expose this stack. Take it down:\n"
            "  START-HERE (your platform) --stop\n"
            "and report this, with install-log.txt, to the Horus team.",
        )
    if resp.status != 401:
        raise _fail(
            steps,
            f"The API answered its ping with HTTP {resp.status}, expected 401.",
            f"GET {mas}/ returned: {resp.text()}",
            "A 5xx here usually means the API started but its database is not\n"
            "ready. Check:\n"
            "  docker compose -f src/infra/docker-compose.yml logs --tail 80 mas postgres",
        )
    steps.passed("GET / without a token -> 401 as expected")

def step_login(steps: Steps, mas: str, username: str, password: str, deadline: float) -> str:
    steps.start("3/9  Log in as the seeded admin")
    budget = min(HTTP_TIMEOUT, _remaining(deadline, steps, "login"))
    form = urllib.parse.urlencode(
        {"username": username, "password": password, "grant_type": "password"}
    ).encode("utf-8")
    try:
        resp = http(
            "POST",
            mas + "/auth/token",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=budget,
        )
    except Unreachable as exc:
        raise _fail(
            steps,
            "The API stopped answering while logging in.",
            f"POST {mas}/auth/token -> {exc}",
            "  docker compose -f src/infra/docker-compose.yml logs --tail 80 mas",
        ) from exc

    if resp.status != 200:
        raise _fail(
            steps,
            f"Login failed for user '{username}' (HTTP {resp.status}).",
            "The admin account is created by the API on first start from\n"
            "SUPER_USER_USERNAME / SUPER_USER_PASSWORD in src/infra/.env, and\n"
            "an account still on the shipped 'admin' gets that password when\n"
            "the API starts. A 401 here means the account's password is not the\n"
            "one in src/infra/.env: it was changed in Horus, or SUPER_USER_PASSWORD\n"
            "is empty or 'admin', which the API refuses.",
            "Put the admin account's password in SUPER_USER_PASSWORD in\n"
            "src/infra/.env, then run:\n"
            "  START-HERE (your platform) --start\n"
            "Or wipe the data and reinstall:\n"
            "  START-HERE (your platform) --uninstall\n"
            "  START-HERE (your platform)",
        )
    token = (resp.json() or {}).get("access_token")
    if not token:
        raise _fail(
            steps,
            "Login returned HTTP 200 but no access token.",
            "The response did not contain an 'access_token' field.",
            "Report this with install-log.txt; it points at a version mismatch\n"
            "between the installer and the API image.",
        )
    steps.passed(f"obtained token ({len(token)} chars)")
    return token

def step_authenticated_ping(steps: Steps, mas: str, token: str, deadline: float) -> None:
    steps.start("4/9  API accepts the token")
    budget = min(HTTP_TIMEOUT, _remaining(deadline, steps, "authenticated ping"))
    try:
        resp = _auth_get(mas + "/", token, budget)
    except Unreachable as exc:
        raise _fail(
            steps,
            "The API stopped answering after login.",
            f"GET {mas}/ -> {exc}",
            "  docker compose -f src/infra/docker-compose.yml logs --tail 80 mas",
        ) from exc
    if resp.status != 200:
        raise _fail(
            steps,
            f"A valid token was rejected (HTTP {resp.status}).",
            f"GET {mas}/ with a Bearer token returned: {resp.text()}\n"
            "Login succeeded, so the credentials are right; the token itself is\n"
            "not being accepted.",
            "This is usually a clock skew or a SECRET_KEY that changed between\n"
            "container restarts. Restart the stack:\n"
            "  START-HERE (your platform) --restart",
        )
    steps.passed("GET / with a token -> 200")

def _list_agents(mas: str, token: str, timeout: float) -> tuple[int, list[dict]]:
    resp = _auth_get(mas + "/agents/details/", token, timeout)
    data = resp.json()
    if isinstance(data, dict):
        data = data.get("agents") or list(data.values())
    if not isinstance(data, list):
        data = []
    return resp.status, [a for a in data if isinstance(a, dict)]

def _worker_agents(agents: list[dict]) -> list[str]:
    names = []
    for agent in agents:
        name = (agent.get("name") or "").strip()
        if name and name.lower() not in MANAGER_NAMES:
            names.append(name)
    return names

def step_wait_for_agents(steps: Steps, mas: str, token: str, deadline: float) -> list[str]:
    steps.start("5/9  Wait for a worker agent to register")
    budget = min(AGENT_WAIT_SECONDS, _remaining(deadline, steps, "waiting for agents"))
    stop_at = time.monotonic() + budget
    last = "no response yet"
    while time.monotonic() < stop_at:
        try:
            status, agents = _list_agents(mas, token, min(15.0, HTTP_TIMEOUT))
        except Unreachable as exc:
            last = str(exc)
        else:
            if status == 200:
                workers = _worker_agents(agents)
                if workers:
                    shown = ", ".join(sorted(workers)[:5])
                    steps.passed(f"{len(workers)} worker agent(s) registered: {shown}")
                    return workers
                last = f"{len(agents)} agent(s) registered, none of them workers"
            else:
                last = f"HTTP {status}"
        time.sleep(AGENT_POLL_INTERVAL)

    probe_name = "Horus-Installer-Probe-" + uuid.uuid4().hex[:8]
    try:
        probe = _json_post(
            mas + "/agents/register",
            {
                "name": probe_name,
                "skills": ["research"],
                "description": "Temporary agent created by the Horus installer smoke test.",
            },
            token,
            min(20.0, HTTP_TIMEOUT),
        )
    except Unreachable as exc:
        probe = Response(0, str(exc).encode())

    if probe.status == 200:
        probe_id = (probe.json() or {}).get("agent_id")
        if probe_id:
            try:
                http(
                    "DELETE",
                    f"{mas}/agents/unregister/{urllib.parse.quote(str(probe_id))}",
                    headers={"Authorization": "Bearer " + token},
                    timeout=15.0,
                )
            except Unreachable:
                pass
        raise _fail(
            steps,
            "The AI worker never started, although the API itself is fine.",
            f"After {elapsed(budget)} no worker agent had registered "
            f"({last}), but the API accepted a test registration - so the\n"
            "registry works and it is the 'agent' container that has not come\n"
            "up. On first start it downloads several GB of model weights.",
            "Watch it finish, then run the check again:\n"
            "  docker compose -f src/infra/docker-compose.yml logs -f agent\n"
            "  python installer/smoke.py\n"
            "If the log shows an out-of-memory kill, use the CPU profile or a\n"
            "machine with more RAM.",
        )

    raise _fail(
        steps,
        "The API's agent registry is not working.",
        f"No worker agent registered within {elapsed(budget)} ({last}), and\n"
        f"registering a test agent also failed (HTTP {probe.status}).\n"
        "So this is the API, not the worker.",
        "Read the API log - a failed database migration is the usual cause:\n"
        "  docker compose -f src/infra/docker-compose.yml logs --tail 120 mas",
    )

def step_upload_document(steps: Steps, ks: str, repo: Path, deadline: float) -> str | None:
    steps.start("6/9  Ingest the demo document")
    doc = repo / "demo_assets" / DEMO_DOC
    if not doc.is_file():
        raise _fail(
            steps,
            f"The demo document is missing: {DEMO_DOC}",
            f"Expected it at: {doc}",
            "Re-extract the ZIP without moving files out of it, then run the\n"
            "START-HERE launcher again.",
        )

    budget = min(HTTP_TIMEOUT, _remaining(deadline, steps, "listing documents"))
    try:
        listed = http("GET", ks + "/file", timeout=budget)
    except Unreachable as exc:
        raise _fail(
            steps,
            "The knowledge store stopped answering while listing documents.",
            f"GET {ks}/file -> {exc}",
            "  docker compose -f src/infra/docker-compose.yml logs --tail 80 knowledge_store",
        ) from exc

    def titles(resp: Response) -> list[str]:
        data = resp.json() or {}
        return [
            str(d.get("title") or "")
            for d in (data.get("documents") or [])
            if isinstance(d, dict)
        ]

    if DEMO_DOC in titles(listed):
        steps.passed(f"'{DEMO_DOC}' is already indexed (upload skipped)")
        return None

    content_type, body = build_multipart(
        [("files", DEMO_DOC, "text/markdown", doc.read_bytes())]
    )
    budget = min(UPLOAD_TIMEOUT, _remaining(deadline, steps, "uploading the demo document"))
    try:
        up = http(
            "POST",
            ks + "/file",
            data=body,
            headers={"Content-Type": content_type},
            timeout=budget,
        )
    except Unreachable as exc:
        raise _fail(
            steps,
            "Uploading the demo document to the knowledge store failed.",
            f"POST {ks}/file -> {exc}\n"
            "Indexing a document also embeds it, which is slow the first time\n"
            "because the embedding model is loaded on demand.",
            "  docker compose -f src/infra/docker-compose.yml logs --tail 80 knowledge_store",
        ) from exc
    if up.status != 200:
        raise _fail(
            steps,
            f"The knowledge store rejected the demo document (HTTP {up.status}).",
            f"POST {ks}/file returned: {up.text()}",
            "  docker compose -f src/infra/docker-compose.yml logs --tail 80 knowledge_store",
        )

    budget = min(HTTP_TIMEOUT, _remaining(deadline, steps, "verifying the upload"))
    try:
        listed = http("GET", ks + "/file", timeout=budget)
    except Unreachable as exc:
        raise _fail(
            steps,
            "The knowledge store stopped answering after the upload.",
            f"GET {ks}/file -> {exc}",
            "  docker compose -f src/infra/docker-compose.yml logs --tail 80 knowledge_store",
        ) from exc
    if DEMO_DOC not in titles(listed):
        raise _fail(
            steps,
            "The demo document was uploaded but is not in the index.",
            f"POST {ks}/file reported success, but '{DEMO_DOC}' is not listed by\n"
            f"GET {ks}/file. The document store and the vector index have gone\n"
            "out of sync, so retrieval would return nothing.",
            "Reset the knowledge store's data and reinstall:\n"
            "  START-HERE (your platform) --uninstall --delete-data\n"
            "  START-HERE (your platform)",
        )
    steps.passed(f"'{DEMO_DOC}' uploaded and indexed")
    return uploaded_doc_id(up)

def uploaded_doc_id(up: Response) -> str | None:
    for entry in up.json() or []:
        if isinstance(entry, dict) and entry.get("filename") == DEMO_DOC and entry.get("doc_id"):
            return str(entry["doc_id"])
    return None

def remove_uploaded_document(log: Log, ks: str, doc_id: str) -> None:
    try:
        removed = http("DELETE", f"{ks}/{urllib.parse.quote(doc_id)}", timeout=HTTP_TIMEOUT)
    except Unreachable as exc:
        log.info(f"smoke: could not remove the uploaded demo document {doc_id}: {exc}")
        return
    log.info(f"smoke: removed the uploaded demo document {doc_id} (HTTP {removed.status})")

def _create_conversation(mas: str, token: str, name: str, timeout: float) -> int | None:
    resp = _json_post(
        mas + "/conversations/create-conversation/", {"name": name}, token, timeout
    )
    if resp.status not in (200, 201):
        return None
    body = resp.json() or {}
    conv = body.get("conversation_id")
    return conv if isinstance(conv, int) else None

def _extract_text(value) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return _extract_text(json.loads(text))
            except ValueError:
                return text
        return text
    if isinstance(value, dict):
        for key in ("output", "result", "content", "answer", "message", "text"):
            found = _extract_text(value.get(key))
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _extract_text(item)
            if found:
                return found
    return ""

def _is_answer_frame(event: dict) -> bool:
    if event.get("type") not in ("task_complete", "agent"):
        return False
    if (event.get("skill_used") or "").lower() in PLANNING_SKILLS:
        return False
    if (event.get("agent_name") or "").strip().lower() in MANAGER_NAMES:
        return False
    return bool((event.get("content") or "").strip())

def _failed_task_note(event: dict) -> str | None:
    if event.get("event") != "error":
        return None
    reason = (event.get("content") or event.get("detail") or "").strip()
    return f"the task ended without an answer: {reason}" if reason else "the task ended without an answer"

def _poll_task(mas: str, token: str, task_id, timeout: float) -> str:
    try:
        resp = _auth_get(f"{mas}/tasks/{urllib.parse.quote(str(task_id))}", token, timeout)
    except Unreachable:
        return ""
    if resp.status != 200:
        return ""
    body = resp.json() or {}
    if str(body.get("status", "")).lower() not in ("completed", "complete", "done", "success"):
        return ""
    return _extract_text(body.get("result"))

def ask(
    log: Log,
    mas: str,
    token: str,
    question: str,
    conversation_name: str,
    answer_budget: float,
) -> tuple[str, str]:
    try:
        conv = _create_conversation(mas, token, conversation_name, min(20.0, HTTP_TIMEOUT))
    except Unreachable as exc:
        return "", f"the API stopped answering while opening a conversation: {exc}"
    if conv is None:
        return "", "could not create a conversation"

    ws_url = (
        mas.replace("https://", "wss://").replace("http://", "ws://")
        + f"/chat/{conv}/?token={urllib.parse.quote(token)}"
    )
    log.debug(f"chat socket: {_redact_token(ws_url)}")
    client = WSClient(ws_url)
    try:
        client.connect()
    except WebSocketError as exc:
        return "", f"could not open the chat socket: {exc}"

    try:
        try:
            resp = _json_post(
                mas + "/tasks/new_task/",
                {"demand": question, "conversation_id": conv, "skills_required": []},
                token,
                min(60.0, answer_budget),
            )
        except Unreachable as exc:
            return "", f"the API stopped answering while submitting the task: {exc}"
        if resp.status not in TASK_ACCEPTED_STATUSES:
            return "", f"the task was rejected: HTTP {resp.status} {resp.text(200)}"

        body = resp.json() or {}
        direct = _extract_text(body.get("result"))
        if direct:
            return direct, "answered directly by the router"

        task_id = body.get("task_id")
        if task_id is None:
            refusal = str(body.get("message") or "").strip()
            return "", (
                f"the API returned no answer and no task to wait for: {refusal}"
                if refusal
                else "the API accepted the question but no task_id was returned"
            )

        stop_at = time.monotonic() + answer_budget
        next_poll = time.monotonic() + TASK_POLL_INTERVAL
        while True:
            left = stop_at - time.monotonic()
            if left <= 0:
                return "", f"no answer within {elapsed(answer_budget)}"
            try:
                message = client.recv_message(min(left, WS_RECV_SLICE))
            except WebSocketError as exc:
                log.debug(f"chat socket dropped ({exc}); polling the task record instead")
                while time.monotonic() < stop_at:
                    late = _poll_task(mas, token, task_id, 20.0)
                    if late:
                        return late, "chat socket dropped; answer read from the task record"
                    time.sleep(min(TASK_POLL_INTERVAL, max(0.0, stop_at - time.monotonic())))
                return "", f"the chat socket failed ({exc}) and no answer within {elapsed(answer_budget)}"

            if message is not None:
                _opcode, payload = message
                try:
                    event = json.loads(payload.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                log.debug(
                    "ws frame: type=%s agent=%s skill=%s"
                    % (event.get("type"), event.get("agent_name"), event.get("skill_used"))
                )
                failure = _failed_task_note(event)
                if failure:
                    return "", failure
                if _is_answer_frame(event):
                    return event["content"].strip(), "answered over the chat socket"
                continue

            if time.monotonic() >= next_poll:
                next_poll = time.monotonic() + TASK_POLL_INTERVAL
                late = _poll_task(mas, token, task_id, 15.0)
                if late:
                    return late, "answer read from the task record"
    finally:
        client.close()

def step_chat(steps: Steps, log: Log, mas: str, deadline: float, token: str,
              model_server: str = profiles.GPU_MODEL_SERVER) -> str:
    steps.start("7/9  Ask a question about the demo document")
    budget = _remaining(deadline, steps, "asking the demo question")
    answer, note = ask(log, mas, token, QUESTION, "horus-smoke", max(30.0, budget - 120.0))
    if not answer:
        raise _fail(
            steps,
            "The stack never produced an answer.",
            f"Asked: {QUESTION!r}\nResult: {note}",
            "Almost always the AI worker: it is either still starting, or the\n"
            f"model server it calls, the {model_server} container, is not healthy.\n"
            "There is no automatic fallback. From src/infra:\n"
            "  docker compose logs -f agent\n"
            f"  docker compose ps {model_server}\n"
            f"  docker compose logs --tail 80 {model_server}\n"
            + MODEL_SERVER_HINTS.get(model_server, ""),
        )
    steps.passed(f"{note} ({len(answer)} chars)")
    log.debug("answer: " + answer[:1000].replace("\n", " "))
    return answer

def step_check_answer(steps: Steps, answer: str, require_quality: bool = True) -> None:
    steps.start("8/9  Check the answer is grounded in the document")
    ok, why = check_answer(answer)
    if not ok and not require_quality:
        steps.warned(
            f"{why} - EXPECTED on a CPU profile, and not an install failure. "
            "Everything else works; the model is simply too slow on a CPU to "
            "finish a useful answer. ATP scenarios F41, F42 and F43 need an "
            "NVIDIA GPU; the other 65 scenarios do not."
        )
        return
    if not ok:
        raise _fail(
            steps,
            "The stack answered, but the answer is wrong.",
            f"Asked: {QUESTION!r}\n"
            f"Problem: {why}\n"
            f"Got: {answer[:400]}\n\n"
            "The document says Q4 2025 revenue was $4.2M, and that figure appears\n"
            "nowhere else, so an answer without it means the model did not have\n"
            "the document. Everything up to this point worked.",
            "There are two causes and the search below tells them apart.\n"
            "\n"
            "Check the document is indexed and findable:\n"
            "  curl http://127.0.0.1:8080/file\n"
            '  curl "http://127.0.0.1:8080/?query=Q4%202025%20revenue&n_results=5"\n'
            "\n"
            "If the search returns NOTHING, retrieval is the problem. Reset the\n"
            "store and reinstall:\n"
            "  START-HERE (your platform) --uninstall --delete-data\n"
            "\n"
            "If the search DOES return the report, retrieval is fine and the model\n"
            "is at fault - it was given the document and did not use it. On a CPU\n"
            "profile that is expected: generation is too slow to finish and the\n"
            "anti-spiral guard replaces the answer. Send us the log.",
        )
    steps.passed(why)

def step_negative_control(steps: Steps, log: Log, mas: str, token: str, deadline: float) -> None:
    steps.start("9/9  Negative control (should not answer from memory)")
    left = deadline - time.monotonic()
    if left <= 60:
        steps.warned("skipped: not enough time left in the budget")
        return
    answer, note = ask(
        log, mas, token, NEGATIVE_QUESTION, "horus-smoke-negative", max(30.0, left - 30.0)
    )
    if not answer:
        steps.warned(f"no answer to the control question ({note})")
        return
    if NEGATIVE_RE.search(answer):
        steps.warned(
            "the model answered a question the documents do not cover "
            "(said 'Lima') - answers may not be grounded in your documents"
        )
        return
    steps.passed("declined to answer outside the document set")

def run(log: Log, repo: Path, base_urls: dict | None = None,
        timeout: int = DEFAULT_TIMEOUT, require_answer_quality: bool = True,
        model_server: str | None = None) -> dict:
    urls = dict(DEFAULT_BASE_URLS)
    urls.update(base_urls or {})
    mas = urls["mas"].rstrip("/")
    ks = urls["ks"].rstrip("/")

    log.step("Verifying the installation")
    log.say(f"  budget: {elapsed(timeout)} (a CPU-only profile uses most of it)")
    started = time.monotonic()
    deadline = started + timeout
    steps = Steps(log)

    try:
        username, password = admin_credentials(infra_dir(repo), steps)
        step_knowledge_health(steps, ks, deadline)
        step_unauthenticated_ping(steps, mas, deadline)
        token = step_login(steps, mas, username, password, deadline)
        step_authenticated_ping(steps, mas, token, deadline)
        workers = step_wait_for_agents(steps, mas, token, deadline)
        uploaded = step_upload_document(steps, ks, repo, deadline)
        try:
            answer = step_chat(steps, log, mas, deadline, token,
                               model_server or model_server_of(infra_dir(repo)))
            step_check_answer(steps, answer, require_answer_quality)
            step_negative_control(steps, log, mas, token, deadline)
        finally:
            if uploaded:
                remove_uploaded_document(log, ks, uploaded)
    except InstallError:
        log.info("smoke steps: " + json.dumps(steps.entries))
        raise
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 - never let a bug here look like a pass
        steps.failed(f"unexpected error: {type(exc).__name__}: {exc}")
        log.info("smoke steps: " + json.dumps(steps.entries))
        raise InstallError(
            EXIT_SMOKE_FAILED,
            "The verification step hit an unexpected error.",
            f"{type(exc).__name__}: {exc}",
            "This is a bug in the installer, not in your machine.\n"
            f"Please send install-log.txt ({log.path}) to the Horus team.",
        ) from exc

    total = time.monotonic() - started
    log.say("")
    log.say(f"  Verification passed in {elapsed(total)}.")
    log.info("smoke steps: " + json.dumps(steps.entries))
    return {
        "passed": True,
        "steps": steps.entries,
        "answer": answer,
        "agents": sorted(workers),
    }

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify a running Horus stack.")
    parser.add_argument("--repo", default=None, help="path to the Horus source tree")
    parser.add_argument("--mas", default=DEFAULT_BASE_URLS["mas"], help="API base URL")
    parser.add_argument("--ks", default=DEFAULT_BASE_URLS["ks"], help="knowledge store base URL")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="global budget, seconds")
    parser.add_argument("--log", default=None, help="where to write the log")
    args = parser.parse_args()

    from common import BUNDLE_DIR

    log = Log(Path(args.log) if args.log else BUNDLE_DIR / "install-log.txt")
    try:
        repo = find_repo(args.repo)
        result = run(log, repo, {"mas": args.mas, "ks": args.ks}, timeout=args.timeout)
    except InstallError as exc:
        exc.report(log)
        log.close(exc.code)
        return exc.code
    except KeyboardInterrupt:
        log.say("")
        log.warn("interrupted")
        log.close(130)
        return 130

    log.say("")
    for entry in result["steps"]:
        mark = "ok  " if entry["ok"] else ("warn" if entry.get("warning") else "FAIL")
        log.say(f"  {mark}  {entry['name']:<52} {elapsed(entry['seconds'])}")
    log.close(0)
    return 0

if __name__ == "__main__":
    sys.exit(main())
