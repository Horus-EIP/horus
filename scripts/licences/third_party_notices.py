#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NOTICES = REPO / "THIRD_PARTY_NOTICES"
PYTHON_DATA = HERE / "python-packages.json"
RUST_DATA = HERE / "rust-crates.json"
COMPONENTS = HERE / "components.yaml"
VERSION_FILE = REPO / "VERSION"
WEB_LOCK = REPO / "src" / "services" / "web-client" / "package-lock.json"
CARGO_MANIFEST = REPO / "desktop" / "src-tauri" / "Cargo.toml"
CARGO_LOCK = CARGO_MANIFEST.with_name("Cargo.lock")
MODEL_MANIFEST = REPO / "models" / "manifest.json"
WEB_RUNTIME_ROOTS = ("next",)
COMPOSE_FILES = sorted((REPO / "src" / "infra").glob("docker-compose*.yml"))
SERVICES = {
    "mas": REPO / "src" / "services" / "mas",
    "agent": REPO / "src" / "services" / "agent",
    "knowledge-store": REPO / "src" / "services" / "knowledge-store",
}
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
    return sorted(service_dir.glob("requirements*.txt"))


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


def web_runtime_paths(packages: dict) -> set[str]:
    roots = list(packages[""].get("dependencies", {})) + list(WEB_RUNTIME_ROOTS)
    pending = [lock_path(packages, "", name) for name in roots]
    seen: set[str] = set()
    while pending:
        path = pending.pop()
        if path is None or path in seen:
            continue
        seen.add(path)
        info = packages[path]
        for kind in ("dependencies", "optionalDependencies", "peerDependencies"):
            pending.extend(lock_path(packages, path, name) for name in info.get(kind, {}))
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
            f"{note}used by {', '.join(sorted(where))}",
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
        Entry(model_id, model.get("revision", ""), model["licence"], model["url"], model["source"], model.get("note", ""))
        for model_id, model in sorted(models.items())
    ]


def component_entries(components: dict) -> list[Entry]:
    return [
        Entry(name, info.get("version", ""), info["licence"], info["url"], info["source"], info.get("note", ""))
        for name, info in sorted((components.get("components") or {}).items())
    ]


def lines_for(entries: Iterable[Entry]) -> list[str]:
    lines = []
    for entry in entries:
        version = f" {entry.version}" if entry.version else ""
        lines.append(f"- {entry.name}{version}")
        lines.append(f"  Licence: {entry.licence} (source: {entry.source})")
        lines.append(f"  {entry.url}")
        if entry.note:
            lines.append(f"  {entry.note}")
    return lines


def render(report: Report) -> str:
    components = read_components()
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    python = python_entries(report)
    web = web_entries()
    rust = rust_entries(report)
    images = image_entries(components, report)
    models = model_entries(components, report)
    others = component_entries(components)
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
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate THIRD_PARTY_NOTICES at the repository root.")
    parser.add_argument("--check", action="store_true", help="exit 1 if THIRD_PARTY_NOTICES or its data is out of date")
    parser.add_argument("--refresh", nargs="?", const="all", choices=("all", "python", "rust"),
                        help="re-read the Python and/or Rust licence data before writing (default: all)")
    parser.add_argument("--python-env", action="append", default=[], metavar="PYTHON",
                        help="with --refresh: a Python interpreter whose installed packages give licence metadata "
                             "(repeat for each service environment; default: this interpreter)")
    parser.add_argument("--cargo", default=shutil.which("cargo") or "cargo",
                        help="with --refresh: the cargo executable (default: cargo on PATH)")
    args = parser.parse_args(argv)

    if args.refresh in ("all", "python"):
        refresh_python(args.python_env or [sys.executable])
    if args.refresh in ("all", "rust"):
        refresh_rust(args.cargo)

    report = Report()
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
