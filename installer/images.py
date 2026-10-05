from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from common import (
    EXIT_REGISTRY_LOGIN_FAILED,
    InstallError,
    Log,
    run,
)

DEFAULT_REGISTRY = "ghcr.io/epitechpromo2027"

REGISTRY_KEY = "HORUS_REGISTRY"
IMAGE_ENV_KEYS: tuple[str, ...] = (REGISTRY_KEY,)

BUILD_FROM_SOURCE_KEY = "HORUS_BUILD_FROM_SOURCE"
TOKEN_KEY = "HORUS_REGISTRY_TOKEN"
USERNAME_KEY = "HORUS_REGISTRY_USERNAME"
TOKEN_FILE_NAME = "registry-token.txt"

APP_SERVICES: tuple[str, ...] = ("mas", "agent", "knowledge_store", "web-client")
CPU_FLAVOR = "cpu"
GPU_FLAVOR = "gpu"

TRUE_WORDS = frozenset({"1", "true", "yes", "on"})

REFUSALS: tuple[str, ...] = (
    "unauthorized",
    "authentication required",
    "pull access denied",
    "requested access to the resource is denied",
    ": denied",
)

LOGIN_TIMEOUT_SECONDS = 120

@dataclass(frozen=True)
class Credentials:
    username: str
    token: str
    source: str

def build_from_source_requested(flag: bool, environ: Mapping[str, str] | None = None) -> bool:
    environ = os.environ if environ is None else environ
    return bool(flag) or environ.get(BUILD_FROM_SOURCE_KEY, "").strip().lower() in TRUE_WORDS

def registry_to_use(requested: str | None, environ: Mapping[str, str],
                    configured: str | None) -> str:
    for candidate in (requested, environ.get(REGISTRY_KEY), configured):
        cleaned = (candidate or "").strip().rstrip("/").lower()
        if cleaned:
            return cleaned
    return DEFAULT_REGISTRY

def registry_host(registry: str) -> str:
    return registry.split("/", 1)[0]

def image_repository(service: str) -> str:
    return "horus-" + service.replace("_", "-")

def image_name(registry: str, service: str, version: str, flavor: str) -> str:
    return f"{registry}/{image_repository(service)}:{version}-{flavor}"

def split_tag(image: str) -> tuple[str, str]:
    repository, colon, tag = image.rpartition(":")
    if not colon or "/" in tag:
        return image, ""
    return repository, tag

def flavor_for(cpu_profile: bool) -> str:
    return CPU_FLAVOR if cpu_profile else GPU_FLAVOR

def _parse_token_text(text: str, source: str) -> tuple[str | None, str]:
    line = next((raw.strip() for raw in text.splitlines() if raw.strip()), "")
    if not line:
        raise InstallError(
            EXIT_REGISTRY_LOGIN_FAILED,
            f"The registry token in {source} is empty.",
            "The file exists but holds no token.",
            "Write the token you were given on one line, as  USERNAME:TOKEN\n"
            "(or only the token, with the user name in HORUS_REGISTRY_USERNAME),\n"
            "then run the installer again.",
        )
    if ":" in line:
        username, token = line.split(":", 1)
        return username.strip() or None, token.strip()
    return None, line

def _read_token_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise InstallError(
            EXIT_REGISTRY_LOGIN_FAILED,
            f"Could not read the registry token file {path}.",
            str(exc),
            "Check the path given to --registry-token-file, then run the installer again.",
        ) from exc

def read_credentials(token_file: str | None, username: str | None,
                     environ: Mapping[str, str], default_file: Path) -> Credentials | None:
    if token_file:
        path = Path(token_file).expanduser()
        file_user, token = _parse_token_text(_read_token_file(path), path.name)
        source = path.name
    elif environ.get(TOKEN_KEY, "").strip():
        file_user, token = None, environ[TOKEN_KEY].strip()
        source = f"the {TOKEN_KEY} variable"
    elif default_file.is_file():
        file_user, token = _parse_token_text(_read_token_file(default_file), default_file.name)
        source = default_file.name
    else:
        return None
    if not token:
        raise InstallError(
            EXIT_REGISTRY_LOGIN_FAILED,
            f"The registry token from {source} is empty.",
            "A user name was given but no token after it.",
            "Write it as  USERNAME:TOKEN  and run the installer again.",
        )
    name = (username or "").strip() or file_user or environ.get(USERNAME_KEY, "").strip()
    if not name:
        raise InstallError(
            EXIT_REGISTRY_LOGIN_FAILED,
            f"A registry token was found in {source}, but no user name to go with it.",
            "The registry needs both: the user name the token belongs to, and the token.",
            f"Write {TOKEN_FILE_NAME} as  USERNAME:TOKEN  on one line, or pass\n"
            f"--registry-user NAME, or set {USERNAME_KEY}, then run the installer again.",
        )
    return Credentials(username=name, token=token, source=source)

def _without(secret: str, text: str) -> str:
    return text.replace(secret, "***") if secret else text

def sign_in(log: Log, registry: str, credentials: Credentials) -> None:
    host = registry_host(registry)
    log.say(f"  Signing in to {host} as {credentials.username} "
            f"(token from {credentials.source})")
    res = run(
        ["docker", "login", host, "--username", credentials.username, "--password-stdin"],
        log, timeout=LOGIN_TIMEOUT_SECONDS, log_output=False, stdin_text=credentials.token,
    )
    if res.ok:
        log.ok(f"Signed in to {host}")
        return
    reason = _without(credentials.token, res.err.strip() or res.out.strip() or
                      f"docker login exited {res.code}")
    raise InstallError(
        EXIT_REGISTRY_LOGIN_FAILED,
        f"{host} did not accept the registry token.",
        f"`docker login {host} --username {credentials.username}` said:\n  "
        + reason.splitlines()[0][:300],
        "Check the token you were given has not expired and is copied whole,\n"
        f"with the user name it belongs to ({credentials.username} was used).\n"
        f"Fix {credentials.source}, then run START-HERE again.",
    )
