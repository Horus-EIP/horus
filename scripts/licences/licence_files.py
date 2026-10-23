from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

SPDX_LIST_VERSION = "v3.29.0"
SPDX_TEXT_URL = "https://raw.githubusercontent.com/spdx/license-list-data/{version}/text/{id}.txt"
PYPI_RELEASE = "https://pypi.org/pypi/{name}/{version}/json"
CRATE_URL = "https://static.crates.io/crates/{name}/{name}-{version}.crate"
USER_AGENT = "horus-licence-notices/1.0"
BLOCK = 256 * 1024
CACHE = Path.home() / ".cache" / "horus-licences"

LICENCE_FILE = re.compile(
    r"^(?:licen[cs]e|copying|copyright|unlicense|licen[cs]e[-_.][a-z0-9.-]+|copying[-_.][a-z0-9.-]+)"
    r"(?:\.(?:txt|md|rst|markdown))?$",
    re.IGNORECASE,
)
NOTICE_FILE = re.compile(
    r"^(?:notice|notices|third[-_ ]?party[-_ ]?notices?|thirdpartynotices?(?:text)?)"
    r"(?:\.(?:txt|md|rst))?$",
    re.IGNORECASE,
)
CODE_SUFFIXES = (
    ".py",
    ".pyi",
    ".pyc",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".rs",
    ".json",
    ".html",
    ".h",
    ".c",
)
METADATA_LICENCE_DIRS = {"licenses", "license_files"}
SKIPPED_FOLDERS = {
    "test",
    "tests",
    "testing",
    "__tests__",
    "fixtures",
    "examples",
    "example",
    "docs",
    "doc",
}

COPYRIGHT_LICENCES = {
    "MIT",
    "MIT-0",
    "X11",
    "ISC",
    "0BSD",
    "Zlib",
    "PSF-2.0",
    "Python-2.0",
    "HPND",
    "NCSA",
    "curl",
    "Unicode-3.0",
    "Unicode-DFS-2016",
    "CC-BY-4.0",
    "BlueOak-1.0.0",
}
SPDX_IDS_URL = "https://raw.githubusercontent.com/spdx/license-list-data/{version}/json/{kind}.json"
SPDX_TOKEN = re.compile(r"[A-Za-z0-9.+-]+")
OPERATORS = {"AND", "OR", "WITH"}

TEXT_SIGNS = (
    ("Apache-2.0", ("apache license", "version 2.0")),
    ("MPL-2.0", ("mozilla public license", "version 2.0")),
    ("BSD-3-Clause", ("redistribution and use in source and binary forms", "neither the name")),
    (
        "BSD-3-Clause",
        ("redistribution and use in source and binary forms", "names of its contributors"),
    ),
    ("BSD-2-Clause", ("redistribution and use in source and binary forms",)),
    ("ISC", ("permission to use, copy, modify, and/or distribute this software for any purpose",)),
    ("ISC", ("permission to use, copy, modify, and distribute this software for any purpose",)),
    ("MIT", ("permission is hereby granted, free of charge",)),
    ("PSF-2.0", ("python software foundation license",)),
    ("Unlicense", ("this is free and unencumbered software released into the public domain",)),
)


class RangeFile(io.RawIOBase):
    def __init__(self, url: str) -> None:
        self.position = 0
        self.blocks: dict[int, bytes] = {}
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            self.url = response.geturl()
            self.size = int(response.headers["Content-Length"])

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.position, io.SEEK_END: self.size}[whence]
        self.position = max(0, base + offset)
        return self.position

    def block(self, index: int) -> bytes:
        if index not in self.blocks:
            start = index * BLOCK
            end = min(self.size, start + BLOCK) - 1
            request = urllib.request.Request(
                self.url, headers={"Range": f"bytes={start}-{end}", "User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
            if len(data) != end - start + 1:
                raise OSError(f"{self.url}: range {start}-{end} returned {len(data)} bytes")
            self.blocks[index] = data
        return self.blocks[index]

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self.size - self.position
        size = min(size, self.size - self.position)
        chunks = []
        while size > 0:
            index, offset = divmod(self.position, BLOCK)
            data = self.block(index)[offset : offset + size]
            chunks.append(data)
            self.position += len(data)
            size -= len(data)
        return b"".join(chunks)

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def fetch(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def cached_fetch(url: str, name: str) -> bytes:
    path = CACHE / "downloads" / name
    if path.is_file():
        return path.read_bytes()
    data = fetch(url, timeout=600)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def is_licence_name(name: str) -> bool:
    return bool(LICENCE_FILE.match(name)) and not name.lower().endswith(CODE_SUFFIXES)


def is_notice_name(name: str) -> bool:
    return bool(NOTICE_FILE.match(name)) and not name.lower().endswith(CODE_SUFFIXES)


def classify(path: str) -> str | None:
    parts = path.split("/")
    base = parts[-1]
    if is_notice_name(base):
        return "notice"
    metadata = [
        index for index, part in enumerate(parts[:-1]) if part.endswith((".dist-info", ".egg-info"))
    ]
    if metadata:
        below = parts[metadata[0] + 1 : -1]
        if is_licence_name(base) or (below and below[0] in METADATA_LICENCE_DIRS):
            return "licence"
    if is_licence_name(base) and not any(part.lower() in SKIPPED_FOLDERS for part in parts[:-1]):
        return "licence"
    return None


def zip_files(handle) -> tuple[dict[str, bytes], dict[str, bytes]]:
    found: dict[str, dict[str, bytes]] = {"licence": {}, "notice": {}}
    with zipfile.ZipFile(handle) as archive:
        for info in archive.infolist():
            kind = None if info.is_dir() else classify(info.filename)
            if kind:
                found[kind][info.filename] = archive.read(info)
    return found["licence"], found["notice"]


def tar_files(data: bytes) -> tuple[dict[str, bytes], dict[str, bytes]]:
    found: dict[str, dict[str, bytes]] = {"licence": {}, "notice": {}}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for member in archive.getmembers():
            kind = classify(member.name) if member.isfile() else None
            if kind:
                found[kind][member.name] = archive.extractfile(member).read()
    return found["licence"], found["notice"]


def folder_files(root: Path) -> tuple[dict[str, bytes], dict[str, bytes]]:
    found: dict[str, dict[str, bytes]] = {"licence": {}, "notice": {}}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if "node_modules/" in relative or not path.is_file():
            continue
        kind = classify(f"{root.name}/{relative}")
        if kind:
            found[kind][relative] = path.read_bytes()
    return found["licence"], found["notice"]


def python_files(name: str, version: str, direct_url: str | None) -> tuple[str, dict, dict]:
    if direct_url:
        return direct_url.rsplit("/", 1)[-1], *zip_files(RangeFile(direct_url))
    release = json.loads(fetch(PYPI_RELEASE.format(name=name, version=version), timeout=60))
    files = release.get("urls") or []
    wheels = sorted(
        (item for item in files if item["filename"].endswith(".whl")), key=wheel_preference
    )
    sdists = [item for item in files if item["packagetype"] == "sdist"]
    if wheels:
        label, licences, notices = wheels[0]["filename"], *zip_files(RangeFile(wheels[0]["url"]))
        if licences or not sdists:
            return label, licences, notices
    if not sdists:
        raise OSError(f"{name} {version}: PyPI lists no wheel and no sdist")
    item = sdists[0]
    data = cached_fetch(item["url"], item["filename"])
    if item["filename"].endswith(".zip"):
        licences, notices = zip_files(io.BytesIO(data))
    else:
        licences, notices = tar_files(data)
    if wheels:
        return f"{wheels[0]['filename']}, licence from {item['filename']}", licences, notices
    return item["filename"], licences, notices


def wheel_preference(item: dict) -> tuple[int, str]:
    name = item["filename"]
    if "py3-none-any" in name or "py2.py3-none-any" in name:
        return 0, name
    if "cp311" in name and "x86_64" in name and "manylinux" in name:
        return 1, name
    if "abi3" in name and "x86_64" in name and "manylinux" in name:
        return 2, name
    if "x86_64" in name and "manylinux" in name:
        return 3, name
    return 4, name


def npm_files(package_path: str, info: dict, node_modules: Path) -> tuple[str, dict, dict]:
    local = node_modules.parent / package_path
    manifest = local / "package.json"
    if manifest.is_file() and json.loads(manifest.read_text(encoding="utf-8")).get(
        "version"
    ) == info.get("version"):
        return f"{package_path} (local node_modules)", *folder_files(local)
    url = info["resolved"]
    data = cached_fetch(url, url.rsplit("/", 1)[-1])
    algorithm, _, expected = info.get("integrity", "").partition("-")
    if algorithm:
        digest = base64.b64encode(hashlib.new(algorithm, data).digest()).decode()
        if digest != expected:
            raise OSError(f"{url}: integrity {algorithm} does not match package-lock.json")
    return url.rsplit("/", 1)[-1], *tar_files(data)


def crate_files(name: str, version: str, registry: Path) -> tuple[str, dict, dict]:
    for source in sorted(registry.glob(f"src/*/{name}-{version}")):
        return f"{name}-{version} (cargo registry)", *folder_files(source)
    for cached in sorted(registry.glob(f"cache/*/{name}-{version}.crate")):
        return cached.name, *tar_files(cached.read_bytes())
    data = cached_fetch(CRATE_URL.format(name=name, version=version), f"{name}-{version}.crate")
    return f"{name}-{version}.crate", *tar_files(data)


def tokens(expression: str) -> list[str]:
    return SPDX_TOKEN.findall(expression.replace("(", " ( ").replace(")", " ) "))


def split_expression(expression: str) -> tuple[list[str], list[str]]:
    licences, exceptions = [], []
    previous = ""
    for token in tokens(expression):
        if token.upper() in OPERATORS:
            previous = token.upper()
            continue
        (exceptions if previous == "WITH" else licences).append(token)
        previous = ""
    return licences, exceptions


def needs_own_copy(expression: str) -> bool:
    licences, _ = split_expression(expression)
    return any(
        atom in COPYRIGHT_LICENCES or atom.startswith(("BSD-", "LicenseRef-")) for atom in licences
    )


def generic_licence(data: bytes) -> bool:
    folded = " ".join(data.decode("utf-8", "replace").lower().split())
    names_a_template = identify(folded) in {"Apache-2.0", "MPL-2.0"}
    carries_a_notice = any(
        sign in folded
        for sign in (
            "permission is hereby granted",
            "redistribution and use in source and binary forms",
            "permission to use, copy, modify",
        )
    )
    names_an_owner = re.search(
        r"copyright\s+(?:\(c\)\s*|©\s*)?(?:\d{4}|[a-z][a-z .,-]{2,}\d{4})", folded
    )
    return names_a_template and not carries_a_notice and not names_an_owner


def spdx_ids() -> tuple[set[str], set[str]]:
    licences = json.loads(
        fetch(SPDX_IDS_URL.format(version=SPDX_LIST_VERSION, kind="licenses"), timeout=60)
    )
    exceptions = json.loads(
        fetch(SPDX_IDS_URL.format(version=SPDX_LIST_VERSION, kind="exceptions"), timeout=60)
    )
    return (
        {item["licenseId"] for item in licences["licenses"]},
        {item["licenseExceptionId"] for item in exceptions["exceptions"]},
    )


def valid_expression(expression: str, licence_ids: set[str], exception_ids: set[str]) -> bool:
    words = tokens(expression)
    if not words or any(
        word not in OPERATORS | {"(", ")"} and not SPDX_TOKEN.fullmatch(word) for word in words
    ):
        return False
    licences, exceptions = split_expression(expression)
    return all(atom in licence_ids or atom.startswith("LicenseRef-") for atom in licences) and all(
        atom in exception_ids for atom in exceptions
    )


def identify(text: str) -> str | None:
    folded = " ".join(text.lower().split())
    for spdx, signs in TEXT_SIGNS:
        if all(sign in folded for sign in signs):
            return spdx
    return None


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]", "_", name.lstrip("@").replace("/", "+"))


def distinct(files: dict[str, bytes]) -> list[tuple[str, bytes]]:
    seen, kept = set(), []
    for source, data in sorted(files.items(), key=lambda item: (item[0].count("/"), item[0])):
        digest = hashlib.sha256(data.replace(b"\r\n", b"\n").strip()).hexdigest()
        if digest not in seen:
            seen.add(digest)
            kept.append((source, data))
    return kept


def target_names(stem: str, files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    if len(files) == 1:
        return [(f"{stem}.txt", files[0][1])]
    named, used = [], set()
    for source, data in files:
        parts = source.split("/")
        label = safe_name(parts[-1])
        if label in used and len(parts) > 1:
            label = safe_name(f"{parts[-2]}.{parts[-1]}")
        used.add(label)
        named.append(
            (f"{stem}.{label}.txt" if not label.endswith(".txt") else f"{stem}.{label}", data)
        )
    return named


def text_of(data: bytes) -> bytes:
    text = data.decode("utf-8", "replace")
    if "<html" not in text[:2000].lower() and "<!doctype html" not in text[:2000].lower():
        return data
    text = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>|</div>|</tr>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#39;|&rsquo;", "'", text)
    text = re.sub(r"&quot;|&ldquo;|&rdquo;", '"', text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return ("\n".join(line for line in lines if line) + "\n").encode("utf-8")


def github_repository(url: str) -> str | None:
    match = re.search(r"github\.com[/:]([^/\s]+)/([^/\s#?]+?)(?:\.git)?(?:[/#?].*)?$", url or "")
    return f"{match.group(1)}/{match.group(2)}" if match else None


def github_licence(repository_url: str) -> tuple[str, bytes] | None:
    repository = github_repository(repository_url)
    if repository is None:
        return None
    cached = CACHE / "github" / f"{repository.replace('/', '__')}.json"
    if cached.is_file():
        answer = json.loads(cached.read_text(encoding="utf-8"))
    else:
        try:
            answer = json.loads(
                fetch(f"https://api.github.com/repos/{repository}/license", timeout=60)
            )
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            answer = {}
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(answer), encoding="utf-8")
    if not answer.get("content"):
        return None
    return answer["html_url"], base64.b64decode(answer["content"])


def spdx_text(identifier: str) -> bytes:
    try:
        return fetch(SPDX_TEXT_URL.format(version=SPDX_LIST_VERSION, id=identifier), timeout=60)
    except urllib.error.HTTPError as error:
        raise OSError(
            f"{identifier} is not on the SPDX licence list {SPDX_LIST_VERSION}"
        ) from error
