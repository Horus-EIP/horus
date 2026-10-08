#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import tomllib
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import licence_files  # noqa: E402
import system_packages  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NOTICES = REPO / "THIRD_PARTY_NOTICES"
PYTHON_DATA = HERE / "python-packages.json"
RUST_DATA = HERE / "rust-crates.json"
COMPONENTS = HERE / "components.yaml"
FILES_DATA = HERE / "licence-files.json"
SYSTEM_DATA = HERE / "system-packages.json"
LICENCE = REPO / "LICENSE"
LICENSES_DIR = REPO / "LICENSES"
COMPONENT_LICENCES = LICENSES_DIR / "components"
NOTICES_DIR = REPO / "NOTICES"
NODE_MODULES = REPO / "src" / "services" / "web-client" / "node_modules"
CARGO_REGISTRY = Path.home() / ".cargo" / "registry"
ECOSYSTEMS = ("python", "web", "rust")
VERSION_FILE = REPO / "VERSION"
WEB_LOCK = REPO / "src" / "services" / "web-client" / "package-lock.json"
CARGO_MANIFEST = REPO / "desktop" / "src-tauri" / "Cargo.toml"
CARGO_LOCK = CARGO_MANIFEST.with_name("Cargo.lock")
MODEL_MANIFEST = REPO / "models" / "manifest.json"
WEB_RUNTIME_ROOTS = ("next",)
WEB_IMAGE_PLATFORM = {"os": "linux", "cpu": "x64"}
COMPOSE_FILES = sorted((REPO / "src" / "infra").glob("docker-compose*.yml"))
SERVICES = {
    "mas": REPO / "src" / "services" / "mas",
    "agent": REPO / "src" / "services" / "agent",
    "knowledge-store": REPO / "src" / "services" / "knowledge-store",
}
TEST_REQUIREMENTS = "requirements-test.txt"
IMAGE_SOURCES = {**SERVICES, "web-client": REPO / "src" / "services" / "web-client"}
OFFER_LIBRARIES = ("psycopg2-binary", "@img/sharp-libvips-")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IMAGE_PYTHON = "3.11"
IMAGE_PLATFORM = "x86_64-manylinux_2_28"
OWN_IMAGES = re.compile(r"(^|/)horus-[a-z-]+(:|$)")
VARIABLE_DEFAULT = re.compile(r"\$\{[A-Z0-9_]+:-([^}]+)\}")
REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
PINNED = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)")
DIRECT_URL = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*@\s*(\S+)")
URL_VERSION = re.compile(r"-(\d+(?:\.\d+)+)-py")
CLASSIFIER_PREFIX = "License :: "
OSI_PREFIX = "OSI Approved :: "
LONG_LICENCE = 80

DUMP_DISTRIBUTIONS = r"""
import importlib.metadata as m, json, sys
rows = []
for dist in m.distributions():
    meta = dist.metadata
    rows.append({
        "name": meta.get("Name") or "",
        "version": dist.version,
        "expression": meta.get("License-Expression") or "",
        "license": (meta.get("License") or "")[:400],
        "classifiers": [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")],
        "home": meta.get("Home-page") or "",
        "urls": meta.get_all("Project-URL") or [],
    })
json.dump(rows, sys.stdout)
"""


@dataclass(frozen=True)
class Entry:
    name: str
    version: str
    licence: str
    url: str
    source: str = "metadata"
    note: str = ""
    spdx: str = ""
    copies: tuple[str, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass
class Report:
    stale: list[str] = field(default_factory=list)

    def add(self, problem: str) -> None:
        self.stale.append(problem)


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_yaml(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def read_components() -> dict:
    return read_yaml(COMPONENTS)


def licence_from_metadata(expression: str, licence: str, classifiers: Iterable[str]) -> str:
    if expression.strip():
        return expression.strip()
    text = licence.strip()
    if text and "\n" not in text and len(text) <= LONG_LICENCE and text.upper() not in {"UNKNOWN", "NONE"}:
        return text
    named = []
    for classifier in classifiers:
        value = classifier[len(CLASSIFIER_PREFIX):]
        if value.startswith(OSI_PREFIX):
            value = value[len(OSI_PREFIX):]
        named.append(value)
    return " OR ".join(sorted(set(named)))


def project_url(home: str, urls: Iterable[str], name: str) -> str:
    labelled = {}
    for item in urls:
        label, _, value = item.partition(",")
        labelled[label.strip().lower()] = value.strip()
    for key in ("homepage", "home", "source", "source code", "repository", "github", "documentation"):
        if labelled.get(key):
            return labelled[key]
    if home.strip() and home.strip().upper() != "UNKNOWN":
        return home.strip()
    if labelled:
        return sorted(labelled.items())[0][1]
    return f"https://pypi.org/project/{name}/"


def requirement_files(service_dir: Path) -> list[Path]:
    return sorted(path for path in service_dir.glob("requirements*.txt") if path.name != TEST_REQUIREMENTS)


def lock_file(requirements: Path) -> Path:
    return requirements.with_suffix(".lock")


def parse_locked(text: str) -> dict[str, str]:
    pinned: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", "--")):
            continue
        match = PINNED.match(line)
        if match:
            pinned[normalise(match.group(1))] = match.group(2)
            continue
        match = DIRECT_URL.match(line)
        if match:
            found = URL_VERSION.search(match.group(2))
            pinned[normalise(match.group(1))] = found.group(1) if found else match.group(2)
    return pinned


def resolve(requirements: Path) -> dict[str, str]:
    locked = lock_file(requirements)
    if locked.is_file():
        return parse_locked(locked.read_text(encoding="utf-8"))
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit(f"{requirements}: no lock file and no uv on PATH to resolve it")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "resolved.txt"
        subprocess.run(
            [uv, "pip", "compile", str(requirements), "--python-version", IMAGE_PYTHON,
             "--python-platform", IMAGE_PLATFORM, "--no-header", "--no-annotate", "--quiet",
             "-o", str(out)],
            check=True, cwd=requirements.parent,
        )
        return parse_locked(out.read_text(encoding="utf-8"))


def installed_metadata(pythons: Iterable[str]) -> dict[tuple[str, str], dict]:
    found: dict[tuple[str, str], dict] = {}
    for python in pythons:
        result = subprocess.run(
            [python, "-c", DUMP_DISTRIBUTIONS], capture_output=True, text=True, encoding="utf-8", check=True,
        )
        for row in json.loads(result.stdout):
            key = (normalise(row["name"]), row["version"])
            found.setdefault(key, row)
    return found


def pypi_metadata(name: str, version: str) -> dict | None:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            info = json.load(response)["info"]
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
        return None
    return {
        "name": info.get("name") or name,
        "version": version,
        "expression": info.get("license_expression") or "",
        "license": (info.get("license") or "")[:400],
        "classifiers": [c for c in info.get("classifiers") or [] if c.startswith("License ::")],
        "home": info.get("home_page") or "",
        "urls": [f"{label}, {link}" for label, link in (info.get("project_urls") or {}).items()],
    }


def python_entry(name: str, version: str, installed: dict, overrides: dict) -> dict:
    override = overrides.get(name)
    row = installed.get((name, version))
    source = "metadata, installed environment"
    if row is None:
        row = pypi_metadata(name, version)
        source = "metadata, PyPI"
    licence = ""
    url = f"https://pypi.org/project/{name}/"
    if row is not None:
        licence = licence_from_metadata(row["expression"], row["license"], row["classifiers"])
        url = project_url(row["home"], row["urls"], name)
    if override and (not licence or override.get("force")):
        licence = override["licence"]
        source = override["source"]
        url = override.get("url", url)
    if not licence:
        licence = "UNKNOWN"
        source = "no licence in the metadata"
    return {"name": name, "version": version, "licence": licence, "url": url, "source": source}


def refresh_python(pythons: list[str]) -> None:
    overrides = {normalise(k): v for k, v in (read_components().get("python_overrides") or {}).items()}
    installed = installed_metadata(pythons)
    services: dict[str, dict[str, list[dict]]] = {}
    for service, folder in SERVICES.items():
        services[service] = {}
        for requirements in requirement_files(folder):
            pinned = resolve(requirements)
            services[service][requirements.name] = [
                python_entry(name, version, installed, overrides) for name, version in sorted(pinned.items())
            ]
    data = {
        "how": (
            "Package sets: the service's requirements lock file, or uv pip compile for Python "
            f"{IMAGE_PYTHON} on {IMAGE_PLATFORM} (the images' Python and platform) when there is none. "
            "Licences: each package's own metadata (importlib.metadata of a local environment, "
            "else the PyPI JSON API for that exact version); components.yaml python_overrides "
            "where the metadata has none."
        ),
        "services": services,
    }
    PYTHON_DATA.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def refresh_rust(cargo: str) -> None:
    result = subprocess.run(
        [cargo, "metadata", "--format-version", "1", "--locked", "--manifest-path", str(CARGO_MANIFEST)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    meta = json.loads(result.stdout)
    members = set(meta["workspace_members"])
    crates = [
        {
            "name": package["name"],
            "version": package["version"],
            "licence": package.get("license") or "",
            "url": package.get("repository") or package.get("homepage") or f"https://crates.io/crates/{package['name']}",
        }
        for package in meta["packages"]
        if package["id"] not in members
    ]
    crates.sort(key=lambda crate: (crate["name"], crate["version"]))
    data = {"how": "cargo metadata --locked on desktop/src-tauri; licences from each crate's Cargo.toml.", "crates": crates}
    RUST_DATA.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def python_entries(report: Report) -> dict[str, list[Entry]]:
    data = read_json(PYTHON_DATA)
    grouped: dict[str, list[Entry]] = {}
    for service, files in sorted(data["services"].items()):
        flavours: dict[tuple[str, str], list[str]] = {}
        rows: dict[tuple[str, str], dict] = {}
        for file_name, packages in sorted(files.items()):
            for row in packages:
                key = (row["name"], row["version"])
                flavours.setdefault(key, []).append(file_name)
                rows[key] = row
            requirements = SERVICES[service] / file_name
            locked = lock_file(requirements)
            if locked.is_file():
                expected = parse_locked(locked.read_text(encoding="utf-8"))
                recorded = {row["name"]: row["version"] for row in packages}
                if expected != recorded:
                    report.add(f"{service}/{file_name}: python-packages.json does not match {locked.name}; run --refresh")
        grouped[service] = [
            Entry(row["name"], row["version"], row["licence"], row["url"], row["source"], ", ".join(flavours[key]))
            for key, row in sorted(rows.items())
        ]
    return grouped


def lock_path(packages: dict, start: str, name: str) -> str | None:
    base = start
    while True:
        candidate = f"{base}/node_modules/{name}" if base else f"node_modules/{name}"
        if candidate in packages:
            return candidate
        if not base:
            return None
        cut = base.rfind("/node_modules/")
        base = base[:cut] if cut >= 0 else ""


def runs_in_web_image(info: dict, path: str = "", packages: dict | None = None) -> bool:
    if not all(not info.get(field) or wanted in info[field] for field, wanted in WEB_IMAGE_PLATFORM.items()):
        return False
    musl = (path.replace("-linux-", "-linuxmusl-").replace("-gnu", "-musl"),
            path.replace("-gnu", "-musl"))
    return not (info.get("os") == ["linux"] and "musl" not in path
                and any(other != path and other in (packages or {}) for other in musl))


def web_runtime_paths(packages: dict) -> set[str]:
    roots = list(packages[""].get("dependencies", {})) + list(WEB_RUNTIME_ROOTS)
    pending = [lock_path(packages, "", name) for name in roots]
    seen: set[str] = set()
    while pending:
        path = pending.pop()
        if path is None or path in seen or not runs_in_web_image(packages[path], path, packages):
            continue
        seen.add(path)
        info = packages[path]
        optional_peers = {name for name, meta in (info.get("peerDependenciesMeta") or {}).items()
                          if meta.get("optional")}
        for kind in ("dependencies", "optionalDependencies", "peerDependencies"):
            pending.extend(lock_path(packages, path, name) for name in info.get(kind, {})
                           if not (kind == "peerDependencies" and name in optional_peers))
    return seen


def web_entries() -> list[Entry]:
    lock = read_json(WEB_LOCK)
    entries = []
    for path in web_runtime_paths(lock["packages"]):
        package = lock["packages"][path]
        name = path.split("node_modules/")[-1]
        entries.append(Entry(
            name, package.get("version", ""), package.get("license") or "UNKNOWN",
            f"https://www.npmjs.com/package/{name}", "package.json, through package-lock.json",
        ))
    return sorted(set(entries), key=lambda entry: (entry.name, entry.version))


def cargo_lock_crates() -> set[tuple[str, str]]:
    lock = tomllib.loads(CARGO_LOCK.read_text(encoding="utf-8"))
    return {(package["name"], package["version"]) for package in lock.get("package", []) if "source" in package}


def rust_entries(report: Report) -> list[Entry]:
    data = read_json(RUST_DATA)
    crates = data["crates"]
    recorded = {(crate["name"], crate["version"]) for crate in crates}
    if recorded != cargo_lock_crates():
        report.add("rust-crates.json does not match desktop/src-tauri/Cargo.lock; run --refresh")
    return [
        Entry(crate["name"], crate["version"], crate["licence"] or "UNKNOWN", crate["url"], "Cargo.toml, through cargo metadata")
        for crate in crates
    ]


def resolve_image(raw: str) -> str | None:
    value = raw.strip().strip("'\"")
    if value.startswith("${HORUS_REGISTRY") or OWN_IMAGES.search(value):
        return None
    return VARIABLE_DEFAULT.sub(lambda match: match.group(1), value)


def used_images() -> dict[str, set[str]]:
    images: dict[str, set[str]] = {}
    for compose in COMPOSE_FILES:
        for line in compose.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*image:\s*(\S+)", line)
            if match:
                image = resolve_image(match.group(1))
                if image:
                    images.setdefault(image, set()).add(str(compose.relative_to(REPO)).replace("\\", "/"))
    stages: set[str] = set()
    for dockerfile in sorted((REPO / "src" / "services").glob("*/Dockerfile")):
        for line in dockerfile.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*FROM\s+(\S+)(?:\s+AS\s+(\S+))?", line, re.IGNORECASE)
            if not match:
                continue
            if match.group(2):
                stages.add(match.group(2).lower())
            if match.group(1).lower() in stages:
                continue
            images.setdefault(match.group(1), set()).add(str(dockerfile.relative_to(REPO)).replace("\\", "/"))
    return images


def repository_of(image: str) -> str:
    last = image.rsplit("/", 1)[-1]
    if ":" in last:
        return image[: len(image) - len(last)] + last.split(":", 1)[0]
    return image


def tag_of(image: str) -> str:
    last = image.rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else "latest"


def image_entries(components: dict, report: Report) -> list[Entry]:
    known = components.get("images") or {}
    entries = []
    for image, where in sorted(used_images().items()):
        repository = repository_of(image)
        info = known.get(repository)
        if info is None:
            report.add(f"{image} ({', '.join(sorted(where))}) has no entry in components.yaml images")
            continue
        note = info.get("note", "")
        note = f"{note}; " if note else ""
        entries.append(Entry(
            repository, tag_of(image), info["licence"], info["url"], info["source"],
            f"{note}used by {', '.join(sorted(where))}", info.get("spdx", ""),
        ))
    return entries


def model_entries(components: dict, report: Report) -> list[Entry]:
    models = {model["id"]: model for model in components.get("models") or []}
    manifest = read_json(MODEL_MANIFEST)
    for item in manifest.get("models", []):
        source = item["source"].split("@", 1)[0]
        if source not in models:
            report.add(f"models/manifest.json model {source} has no entry in components.yaml models")
    return [
        Entry(model_id, model.get("revision", ""), model["licence"], model["url"], model["source"],
              model.get("note", ""), model.get("spdx", ""))
        for model_id, model in sorted(models.items())
    ]


def component_entries(components: dict) -> list[Entry]:
    return [
        Entry(name, info.get("version", ""), info["licence"], info["url"], info["source"],
              info.get("note", ""), info.get("spdx", ""))
        for name, info in sorted((components.get("components") or {}).items())
    ]


def key_of(name: str, version: str) -> str:
    return f"{name} {version}"


def locked_urls() -> dict[str, str]:
    urls = {}
    for folder in SERVICES.values():
        for lock in sorted(folder.glob("requirements*.lock")):
            for line in lock.read_text(encoding="utf-8").splitlines():
                match = DIRECT_URL.match(line.strip())
                if match:
                    urls[normalise(match.group(1))] = match.group(2)
    return urls


def python_components() -> dict[str, dict]:
    found = {}
    urls = locked_urls()
    for files in read_json(PYTHON_DATA)["services"].values():
        for rows in files.values():
            for row in rows:
                found[key_of(row["name"], row["version"])] = {
                    "name": row["name"], "version": row["version"], "licence": row["licence"],
                    "url": urls.get(normalise(row["name"])), "repository": row["url"],
                }
    return found


def web_components() -> dict[str, dict]:
    packages = read_json(WEB_LOCK)["packages"]
    found = {}
    for path in sorted(web_runtime_paths(packages)):
        info = packages[path]
        name = path.split("node_modules/")[-1]
        found[key_of(name, info.get("version", ""))] = {
            "name": name, "version": info.get("version", ""), "licence": info.get("license") or "",
            "path": path, "info": info, "repository": npm_repository(path),
        }
    return found


def npm_repository(path: str) -> str:
    manifest = NODE_MODULES.parent / path / "package.json"
    if not manifest.is_file():
        return ""
    repository = json.loads(manifest.read_text(encoding="utf-8")).get("repository") or ""
    if isinstance(repository, dict):
        repository = repository.get("url", "")
    if repository.startswith("github:"):
        repository = "https://github.com/" + repository.split(":", 1)[1]
    elif re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        repository = "https://github.com/" + repository
    return repository


def rust_components() -> dict[str, dict]:
    return {
        key_of(crate["name"], crate["version"]): {
            "name": crate["name"], "version": crate["version"], "licence": crate["licence"],
            "repository": crate["url"]}
        for crate in read_json(RUST_DATA)["crates"]
    }


def component_files(ecosystem: str, item: dict) -> tuple[str, dict, dict]:
    if ecosystem == "python":
        return licence_files.python_files(item["name"], item["version"], item["url"])
    if ecosystem == "web":
        return licence_files.npm_files(item["path"], item["info"], NODE_MODULES)
    return licence_files.crate_files(item["name"], item["version"], CARGO_REGISTRY)


def resolve_spdx(raw: str, override: dict, aliases: dict, texts: list[str], ids: tuple[set, set]) -> str:
    if override.get("spdx"):
        return override["spdx"]
    if raw in aliases:
        return aliases[raw]
    candidate = re.sub(r"\s*/\s*", " OR ", raw.strip())
    if licence_files.valid_expression(candidate, *ids):
        return candidate
    found = {licence_files.identify(text) for text in texts} - {None}
    return found.pop() if len(found) == 1 else ""


def write_files(folder: Path, stem: str, files: dict[str, bytes]) -> list[str]:
    written = []
    for name, data in licence_files.target_names(stem, licence_files.distinct(files)):
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.replace(b"\r\n", b"\n"))
        written.append(target.relative_to(REPO).as_posix())
    return written


def overrides_for(components: dict, ecosystem: str) -> dict[str, dict]:
    key = {"python": "python_overrides", "web": "web_overrides", "rust": "rust_overrides"}[ecosystem]
    return {normalise(name): value for name, value in (components.get(key) or {}).items()}


def override_for(overrides: dict[str, dict], name: str) -> dict:
    exact = overrides.get(normalise(name))
    if exact is not None:
        return exact
    for pattern, value in sorted(overrides.items()):
        if "*" in pattern and fnmatch.fnmatchcase(normalise(name), pattern):
            return value
    return {}


def refresh_files(report: Report) -> None:
    components = read_components()
    aliases = components.get("spdx_aliases") or {}
    ids = licence_files.spdx_ids()
    for folder in (COMPONENT_LICENCES, NOTICES_DIR):
        if folder.exists():
            shutil.rmtree(folder)
    records: dict[str, dict] = {}
    shipped: dict[str, dict[str, bytes]] = {}
    sources = {"python": python_components(), "web": web_components(), "rust": rust_components()}
    for ecosystem in ECOSYSTEMS:
        overrides = overrides_for(components, ecosystem)
        records[ecosystem] = {}
        for key, item in sorted(sources[ecosystem].items()):
            try:
                record, licences = component_record(ecosystem, item, override_for(overrides, item["name"]),
                                                    aliases, ids, report)
            except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as error:
                report.add(f"{ecosystem}: {key}: cannot read its files: {error}")
                continue
            shipped[f"{ecosystem} {key}"] = licences
            records[ecosystem][key] = record
    write_licence_texts(components, records, shipped, report)
    FILES_DATA.write_text(json.dumps({
        "how": ("Licence and NOTICE files read from each component's own distribution: the wheel on PyPI "
                "(only the needed members, by HTTP range requests) or its sdist when the wheel has none, "
                "node_modules or the npm tarball named in package-lock.json for the web client, the cargo "
                "registry for the desktop app. When a component whose licence carries a copyright line "
                "ships no licence file, the licence file of its repository is used, and the file says so. "
                f"Licence texts from the SPDX licence list {licence_files.SPDX_LIST_VERSION}."),
        "spdx_list": licence_files.SPDX_LIST_VERSION,
        **records,
    }, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def component_record(ecosystem: str, item: dict, override: dict, aliases: dict, ids: tuple[set, set],
                     report: Report) -> tuple[dict, dict[str, bytes]]:
    key = key_of(item["name"], item["version"])
    label, licences, notices = component_files(ecosystem, item)
    record = {"spdx": "", "from": label, "copies": [], "notices": []}
    spdx = resolve_spdx(item["licence"], override, aliases, primary_texts(licences), ids)
    if not licences and (override.get("licence_url") or not spdx or licence_files.needs_own_copy(spdx)):
        found = repository_licence(item, override)
        if found:
            source, data = found
            name = f"{item['name']} {item['version']}"
            header = (f"No licence file ships with {name}. This is the licence file of its "
                      f"repository: {source}\n\n").encode("utf-8")
            licences = {source.rsplit("/", 1)[-1]: header + data}
            record["licence_from"] = source
            spdx = spdx or resolve_spdx(item["licence"], override, aliases, [data.decode("utf-8", "replace")], ids)
    record["spdx"] = spdx
    if not spdx:
        report.add(f"{ecosystem}: {key} licence {item['licence']!r} has no SPDX id; add it to "
                   "spdx_aliases or an override in components.yaml")
    stem = f"{licence_files.safe_name(item['name'])}-{item['version']}"
    kept = {source: data for source, data in licences.items() if not licence_files.generic_licence(data)}
    if kept and (licence_files.needs_own_copy(spdx) or override.get("own_copy")):
        record["copies"] = write_files(COMPONENT_LICENCES / ecosystem, stem, kept)
    if override.get("notice_url"):
        url = override["notice_url"].format(version=item["version"])
        header = f"The third-party notices of {item['name']} {item['version']}, from {url}\n\n".encode("utf-8")
        notices = {**notices, url.rsplit("/", 1)[-1]: header + licence_files.fetch(url, timeout=60)}
        record["notice_from"] = url
    if notices:
        record["notices"] = write_files(NOTICES_DIR / ecosystem, stem, notices)
    if not licences:
        record["no_licence_file"] = True
    return record, licences


def primary_texts(licences: dict[str, bytes]) -> list[str]:
    if not licences:
        return []
    depth = min(source.count("/") for source in licences)
    return [data.decode("utf-8", "replace") for source, data in licences.items() if source.count("/") == depth]


def repository_licence(item: dict, override: dict) -> tuple[str, bytes] | None:
    if override.get("licence_url"):
        url = override["licence_url"].format(version=item["version"])
        return url, licence_files.text_of(licence_files.fetch(url, timeout=60))
    return licence_files.github_licence(override.get("repository") or item.get("repository") or "")


def expressions_in_use(components: dict, records: dict) -> set[str]:
    found = set()
    for ecosystem in ECOSYSTEMS:
        found.update(record["spdx"] for record in records.get(ecosystem, {}).values() if record["spdx"])
    for section in ("images", "components"):
        found.update(info.get("spdx", "") for info in (components.get(section) or {}).values())
    found.update(model.get("spdx", "") for model in components.get("models") or [])
    found.update(text for image in system_data().get("images", {}).values()
                 for row in image["packages"] for text in row["texts"])
    return {expression for expression in found if expression}


def write_licence_texts(components: dict, records: dict, shipped: dict, report: Report) -> None:
    refs = components.get("licence_refs") or {}
    wanted = set()
    for expression in expressions_in_use(components, records):
        licences, exceptions = licence_files.split_expression(expression)
        wanted.update(licences + exceptions)
    for old in LICENSES_DIR.glob("*.txt"):
        old.unlink()
    LICENSES_DIR.mkdir(exist_ok=True)
    for identifier in sorted(wanted):
        target = LICENSES_DIR / f"{identifier}.txt"
        if identifier.startswith("LicenseRef-"):
            text = licence_ref_text(identifier, refs.get(identifier), shipped)
            if text is None:
                report.add(f"{identifier} has no source in components.yaml licence_refs")
                continue
            target.write_text(text, encoding="utf-8", newline="\n")
        else:
            target.write_bytes(licence_files.spdx_text(identifier).replace(b"\r\n", b"\n"))


def licence_ref_text(identifier: str, ref: dict | None, shipped: dict) -> str | None:
    if not ref:
        return None
    today = datetime.date.today().isoformat()
    if "component" in ref:
        matches = sorted(key for key, files in shipped.items() if key.startswith(f"{ref['component']} ") and files)
        if not matches:
            return None
        source, data = sorted(shipped[matches[0]].items())[0]
        header = f"{identifier}: the text {matches[0]} ships as {source}.\n\n"
        return header + data.decode("utf-8", "replace").replace("\r\n", "\n")
    if "image" in ref:
        text = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "cat", ref["image"], ref["path"]],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        return f"{identifier}: the text shipped in {ref['image']} at {ref['path']}, read on {today}.\n\n{text}"
    text = licence_files.text_of(licence_files.fetch(ref["url"], timeout=60)).decode("utf-8", "replace")
    return f"{identifier}: text of {ref['url']}, retrieved on {today}.\n\n{text}"


def attach_files(ecosystem: str, entries: list[Entry], records: dict, report: Report) -> list[Entry]:
    attached = []
    for entry in entries:
        record = records.get(ecosystem, {}).get(key_of(entry.name, entry.version))
        if record is None:
            report.add(f"{ecosystem}: {entry.name} {entry.version} has no licence files recorded; "
                       "run --refresh files")
            attached.append(entry)
            continue
        attached.append(replace(entry, spdx=record["spdx"], copies=tuple(record["copies"]),
                                notices=tuple(record["notices"])))
    return attached


def check_licence_files(components: dict, records: dict, report: Report) -> None:
    referenced = set()
    for ecosystem in ECOSYSTEMS:
        for key, record in records.get(ecosystem, {}).items():
            for path in record["copies"] + record["notices"]:
                referenced.add(path)
                if not (REPO / path).is_file():
                    report.add(f"{ecosystem}: {key}: {path} is missing; run --refresh files")
    for expression in sorted(expressions_in_use(components, records)):
        licences, exceptions = licence_files.split_expression(expression)
        for identifier in licences + exceptions:
            if not (LICENSES_DIR / f"{identifier}.txt").is_file():
                report.add(f"licence {identifier} is in use but LICENSES/{identifier}.txt is missing")
    for folder in (COMPONENT_LICENCES, NOTICES_DIR):
        for path in sorted(folder.rglob("*")) if folder.exists() else []:
            relative = path.relative_to(REPO).as_posix()
            if path.is_file() and relative not in referenced:
                report.add(f"{relative} belongs to no listed component; run --refresh files")


def text_paths(spdx: str) -> list[str]:
    licences, exceptions = licence_files.split_expression(spdx)
    return [f"LICENSES/{identifier}.txt" for identifier in dict.fromkeys(licences + exceptions)]


def lines_for(entries: Iterable[Entry]) -> list[str]:
    lines = []
    for entry in entries:
        version = f" {entry.version}" if entry.version else ""
        lines.append(f"- {entry.name}{version}")
        lines.append(f"  Licence: {entry.licence} (source: {entry.source})")
        lines.append(f"  {entry.url}")
        if entry.note:
            lines.append(f"  {entry.note}")
        if entry.spdx:
            lines.append(f"  Licence text ({entry.spdx}): {', '.join(text_paths(entry.spdx))}")
        if entry.copies:
            lines.append(f"  Its own licence file: {', '.join(entry.copies)}")
        if entry.notices:
            lines.append(f"  NOTICE: {', '.join(entry.notices)}")
    return lines


def entries_with_spdx(entries: list[Entry], section: str, report: Report) -> list[Entry]:
    for entry in entries:
        if not entry.spdx:
            report.add(f"{section}: {entry.name} has no spdx in components.yaml")
    return entries


def system_data() -> dict:
    return read_json(SYSTEM_DATA) if SYSTEM_DATA.is_file() else {}


def refresh_system(images: list[str], report: Report) -> None:
    refs = dict(item.split("=", 1) for item in images if "=" in item)
    missing = sorted(set(IMAGE_SOURCES) - set(refs))
    if missing:
        report.add(f"--refresh system reads built images: add --image NAME=IMAGE for {', '.join(missing)}")
        return
    overrides = read_components().get("system_overrides") or {}
    found = {}
    for name, folder in IMAGE_SOURCES.items():
        try:
            info, problems = system_packages.image_packages(refs[name], overrides)
        except (OSError, subprocess.CalledProcessError) as error:
            report.add(f"{name}: cannot read the packages of {refs[name]} with docker: {error}")
            continue
        for problem in problems:
            report.add(problem)
        found[name] = {"os": info["os"], "kind": info["kind"], "packages": info["packages"],
                       "recipe": system_packages.recipe(folder / "Dockerfile")}
    if report.stale:
        return
    SYSTEM_DATA.write_text(json.dumps({
        "how": ("GPL and LGPL operating-system packages of each image, read with dpkg-query and the copyright "
                "files in /usr/share/doc (Debian) or from /lib/apk/db/installed (Alpine). recipe is the base "
                "image and the system packages of the Dockerfile's final stage when the images were read."),
        "read_on": datetime.date.today().isoformat(),
        "images": found,
    }, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    known = licence_files.spdx_ids()[0]
    for identifier in sorted({text for image in found.values() for row in image["packages"] for text in row["texts"]}):
        target = LICENSES_DIR / f"{identifier}.txt"
        if identifier not in known:
            report.add(f"system packages: {identifier} is not an SPDX licence id")
        elif not target.is_file():
            target.write_bytes(licence_files.spdx_text(identifier).replace(b"\r\n", b"\n"))


def check_system(data: dict, report: Report) -> None:
    images = data.get("images", {})
    for name, folder in IMAGE_SOURCES.items():
        if name not in images:
            report.add(f"scripts/licences/system-packages.json has no {name} image; build the images and run "
                       "--refresh system")
        elif images[name]["recipe"] != system_packages.recipe(folder / "Dockerfile"):
            report.add(f"{name}: the final stage of its Dockerfile changed since its system packages were read; "
                       "build the images and run --refresh system")


def offer_addresses(report: Report) -> list[str]:
    text = LICENCE.read_text(encoding="utf-8")
    contact = re.search(r"^16\. CONTACT$(.*?)(?=^\d+\. |\Z)", text, re.M | re.S)
    addresses = EMAIL.findall(contact.group(1)) if contact else []
    if not addresses:
        report.add("LICENSE section 16 names no contact address for the written offer")
    return addresses


def paragraph(text: str) -> list[str]:
    return textwrap.wrap(text, 79, break_on_hyphens=False, break_long_words=False) + [""]


def indented(text: str) -> list[str]:
    return textwrap.wrap(text, 79, initial_indent="  ", subsequent_indent="  ", break_on_hyphens=False,
                         break_long_words=False)


def listed_with(names: list[str]) -> str:
    return ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1]


def system_lines(images: dict, kind: str) -> list[str]:
    grouped: dict[tuple[str, str], tuple[dict, list[str]]] = {}
    for name, image in sorted(images.items()):
        if image["kind"] != kind:
            continue
        for row in image["packages"]:
            grouped.setdefault((row["name"], row["version"]), (row, []))[1].append(name)
    lines = []
    for (name, version), (row, found_in) in sorted(grouped.items()):
        if kind == "alpine":
            origin = f" (aport {row['source']} at commit {row['commit'][:12]})"
        elif (row["source"], row["source_version"]) == (name, version):
            origin = ""
        elif row["source_version"] == version:
            origin = f" (source {row['source']})"
        else:
            origin = f" (source {row['source']} {row['source_version']})"
        lines.append(f"- {name} {version}{origin}")
        lines += indented(f"Licence: {row['licence']}. Images: {', '.join(found_in)}.")
    return lines


def library_lines(python: dict[str, list[Entry]], web: list[Entry]) -> list[str]:
    found: dict[tuple[str, str], tuple[Entry, list[str]]] = {}
    for service, entries in python.items():
        for entry in entries:
            if entry.name == OFFER_LIBRARIES[0]:
                found.setdefault((entry.name, entry.version), (entry, []))[1].append(f"Python, {service}")
    for entry in web:
        if entry.name.startswith(OFFER_LIBRARIES[1]):
            found.setdefault((entry.name, entry.version), (entry, []))[1].append("web client")
    lines = []
    for (name, version), (entry, used_by) in sorted(found.items()):
        if name == OFFER_LIBRARIES[0]:
            source = f"https://pypi.org/project/{name}/{version}/#files"
        else:
            source = (f"https://www.npmjs.com/package/{name}/v/{version}, whose versions.json names the libvips "
                      "release; its source is at https://github.com/libvips/libvips/releases")
        lines.append(f"- {name} {version} ({'; '.join(used_by)})")
        lines += indented(f"Licence: {entry.spdx or entry.licence}. Source: {source}")
    return lines


def offer_section(data: dict, python: dict[str, list[Entry]], web: list[Entry], report: Report) -> list[str]:
    images = data.get("images", {})
    texts = sorted({text for image in images.values() for row in image["packages"] for text in row["texts"]})
    addresses = offer_addresses(report)
    systems = {kind: sorted({image["os"] for image in images.values() if image["kind"] == kind})
               for kind in ("debian", "alpine")}
    out = ["", "", "7. Source code of GPL and LGPL components", ""]
    out += paragraph(
        "Our images, horus-mas, horus-agent, horus-knowledge-store and horus-web-client, contain "
        "operating-system packages from Debian and Alpine Linux licensed under the GNU GPL or the GNU LGPL "
        "(7.1 and 7.2). They run as separate programs, or are system libraries that the Python and Node.js "
        "runtimes load; Horus's own code does not link them. Two libraries among our dependencies are under "
        "the LGPL too (7.3): psycopg2-binary, and the prebuilt libvips that sharp loads.")
    out += ["Where the source is:", ""]
    for item in (
        "Debian packages: the source package of each version listed below (.dsc, original and Debian "
        "tarballs) is on https://snapshot.debian.org/, which keeps every version Debian has published.",
        "Alpine packages: the build recipe and patches at the aports commit listed for each package, in "
        "https://gitlab.alpinelinux.org/alpine/aports, and the upstream archives it names, mirrored at "
        "https://distfiles.alpinelinux.org/distfiles/.",
        "psycopg2-binary: its source distribution on PyPI; sharp's libvips: its package on npm. 7.3 gives "
        "the links.",
    ):
        wrapped = textwrap.wrap(item, 77, break_on_hyphens=False, break_long_words=False)
        out += [f"- {wrapped[0]}"] + [f"  {line}" for line in wrapped[1:]]
    out += [""]
    out += ["Written offer:", ""]
    out += paragraph(
        "For three years from our last distribution of a given version of Horus, we will give anyone who "
        "asks a complete machine-readable copy of the corresponding source code of the GPL and LGPL "
        "components of that version, for no more than our cost of sending it. Write to one of the "
        f"maintainers, at the addresses of section 16 of LICENSE: {listed_with(addresses or ['?'])}. Name "
        "the version of Horus and the image. scripts/licences/fetch-gpl-sources.py gathers the exact sources "
        "of the system packages of any of our images into one archive (docs/operations.md).")
    out += paragraph(
        f"The versions below were read with dpkg-query, and from the apk database, in CPU images built on "
        f"{data.get('read_on', '?')} from this repository; the GPU images install the same system packages. "
        "An image built on another day can carry later Debian or Alpine security updates, and the script "
        "reads the exact list from the image it is given. The licence names are those of each package's "
        "copyright file (Debian) or package database (Alpine). The full texts are in LICENSES/ "
        f"({', '.join(texts)}), and the Debian images also keep each package's copyright file in "
        "/usr/share/doc/<package>/.")
    out += [f"7.1 Debian packages ({', '.join(systems['debian'])})", ""]
    out += system_lines(images, "debian")
    out += ["", "", f"7.2 Alpine packages ({', '.join(systems['alpine'])})", ""]
    out += system_lines(images, "alpine")
    out += ["", "", "7.3 LGPL libraries among our dependencies", ""]
    out += library_lines(python, web)
    return out


def render(report: Report) -> str:
    components = read_components()
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    records = read_json(FILES_DATA) if FILES_DATA.is_file() else {}
    if not records:
        report.add("scripts/licences/licence-files.json is missing; run --refresh files")
    python = {service: attach_files("python", entries, records, report)
              for service, entries in python_entries(report).items()}
    web = attach_files("web", web_entries(), records, report)
    rust = attach_files("rust", rust_entries(report), records, report)
    images = entries_with_spdx(image_entries(components, report), "images", report)
    models = entries_with_spdx(model_entries(components, report), "models", report)
    others = entries_with_spdx(component_entries(components), "components", report)
    system = system_data()
    check_system(system, report)
    check_licence_files(components, records, report)
    out = [
        f"THIRD-PARTY NOTICES FOR HORUS {version}",
        "",
        "Horus is proprietary software (see LICENSE). It includes, links to or runs the",
        "third-party software listed below, each under its own licence. The licences",
        "keep applying to that software; nothing in LICENSE changes them.",
        "",
        "This file is generated by scripts/licences/third_party_notices.py. Do not edit",
        "it by hand: change the dependencies, run the script with --refresh if a",
        "dependency was added or changed, then run it again to rewrite this file.",
        "",
        "Each entry gives the licence and where it was read: the package's own",
        "metadata where it has one, else the licence inventory",
        "(docs/eip/dependency-licence-inventory.xlsx) or the project page.",
        "",
        "The full licence texts are in LICENSES/, one file per licence, named by its",
        f"SPDX id and taken from the SPDX licence list {records.get('spdx_list', licence_files.SPDX_LIST_VERSION)}.",
        "Licences that carry a copyright line (MIT, BSD, ISC and similar) also keep each",
        "component's own licence file in LICENSES/components/. Every NOTICE or",
        "third-party notices file a component ships is in NOTICES/. Each entry names",
        "its files.",
        "",
        "",
        "1. Python packages, per service",
        "",
        read_json(PYTHON_DATA)["how"],
    ]
    for service, entries in python.items():
        out += ["", f"1.{list(python).index(service) + 1} {service} (src/services/{service})", "",
                "The last line of each entry names the requirements files that install it.", ""]
        out += lines_for(entries)
    out += [
        "", "",
        "2. Web client: production dependencies (src/services/web-client/package-lock.json)",
        "",
        "Licences as each package's package.json declares them, copied by npm into",
        "package-lock.json.",
        "",
    ]
    out += lines_for(web)
    out += [
        "", "",
        "3. Desktop app: Rust crates (desktop/src-tauri/Cargo.lock)",
        "",
        read_json(RUST_DATA)["how"],
        "",
    ]
    out += lines_for(rust)
    out += [
        "", "",
        "4. Container images the stacks run as separate processes",
        "",
        "Pulled unmodified and run as their own containers next to Horus's services.",
        "The tag is the one the Compose files or Dockerfiles name.",
        "",
    ]
    out += lines_for(images)
    out += [
        "", "",
        "5. Models",
        "",
        "Downloaded at install or build time, or by the services on first use.",
        "",
    ]
    out += lines_for(models)
    out += [
        "", "",
        "6. Other components",
        "",
    ]
    out += lines_for(others)
    out += offer_section(system, python, web, report)
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate THIRD_PARTY_NOTICES at the repository root.")
    parser.add_argument("--check", action="store_true", help="exit 1 if THIRD_PARTY_NOTICES or its data is out of date")
    parser.add_argument("--refresh", nargs="?", const="all", choices=("all", "python", "rust", "files", "system"),
                        help="re-read the Python and/or Rust licence data, fetch the licence texts and "
                             "NOTICE files (files), or list the GPL and LGPL system packages of the built "
                             "images (system, not part of all), before writing (default: all)")
    parser.add_argument("--python-env", action="append", default=[], metavar="PYTHON",
                        help="with --refresh: a Python interpreter whose installed packages give licence metadata "
                             "(repeat for each service environment; default: this interpreter)")
    parser.add_argument("--cargo", default=shutil.which("cargo") or "cargo",
                        help="with --refresh: the cargo executable (default: cargo on PATH)")
    parser.add_argument("--image", action="append", default=[], metavar="NAME=IMAGE",
                        help="with --refresh system: the built image of mas, agent, knowledge-store and "
                             "web-client (repeat for each)")
    args = parser.parse_args(argv)

    if args.refresh in ("all", "python"):
        refresh_python(args.python_env or [sys.executable])
    if args.refresh in ("all", "rust"):
        refresh_rust(args.cargo)
    report = Report()
    if args.refresh in ("all", "files"):
        refresh_files(report)
    if args.refresh == "system":
        refresh_system(args.image, report)

    text = render(report)
    if args.check:
        current = NOTICES.read_text(encoding="utf-8") if NOTICES.is_file() else ""
        if current != text:
            report.add("THIRD_PARTY_NOTICES is out of date; run scripts/licences/third_party_notices.py")
        for problem in report.stale:
            print(f"error: {problem}")
        return 1 if report.stale else 0
    for problem in report.stale:
        print(f"error: {problem}")
    if report.stale:
        return 1
    NOTICES.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {NOTICES.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
