#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import system_packages  # noqa: E402

COMPONENTS = Path(__file__).resolve().parent / "components.yaml"
SNAPSHOT = "https://snapshot.debian.org"
DEBIAN_ARCHIVES = ("debian", "debian-security")
APORTS = "https://gitlab.alpinelinux.org/alpine/aports"
ALPINE_REPOSITORIES = ("main", "community")
DISTFILES = "https://distfiles.alpinelinux.org/distfiles"
APKBUILD_SOURCES = ('cat > /tmp/APKBUILD && cd /tmp && . ./APKBUILD >/dev/null 2>&1; '
                    'for s in $source; do echo "$s"; done; echo "--"; echo "$sha512sums"')


def overrides() -> dict[str, dict]:
    import yaml

    return (yaml.safe_load(COMPONENTS.read_text(encoding="utf-8")) or {}).get("system_overrides") or {}


def request(url: str, method: str = "GET"):
    return urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=600)


def fetch(url: str, attempts: int = 4) -> bytes:
    for attempt in range(attempts):
        try:
            with request(url) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)
    raise OSError(url)


def download(url: str, folder: Path, digest: str = "", algorithm: str = "sha1", attempts: int = 4) -> Path:
    target = folder / hashlib.sha1(url.encode()).hexdigest()
    for attempt in range(attempts):
        hasher = hashlib.new(algorithm)
        try:
            with request(url) as response, target.open("wb") as out:
                while chunk := response.read(1 << 20):
                    hasher.update(chunk)
                    out.write(chunk)
        except urllib.error.HTTPError:
            raise
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)
            continue
        if digest and hasher.hexdigest() != digest:
            raise OSError(f"{url} does not match its {algorithm}")
        return target
    raise OSError(url)


def exists(url: str) -> bool:
    try:
        with request(url, "HEAD") as response:
            return response.status == 200
    except OSError:
        return False


def debian_files(source: str, version: str) -> list[dict]:
    quoted = "/".join(urllib.parse.quote(part, safe="") for part in (source, version))
    listing = json.loads(fetch(f"{SNAPSHOT}/mr/package/{quoted}/srcfiles?fileinfo=1"))
    return choose_debian_files(listing)


def choose_debian_files(listing: dict) -> list[dict]:
    files = []
    for digest, seen in sorted(listing.get("fileinfo", {}).items()):
        best = next((entry for archive in DEBIAN_ARCHIVES for entry in seen if entry["archive_name"] == archive),
                    seen[0])
        files.append({"name": best["name"], "size": best.get("size", 0), "sha1": digest,
                      "url": f"{SNAPSHOT}/file/{digest}"})
    return sorted(files, key=lambda file: file["name"])


def alpine_recipe(origin: str, commit: str) -> tuple[str, bytes]:
    for repository in ALPINE_REPOSITORIES:
        try:
            return repository, fetch(f"{APORTS}/-/raw/{commit}/{repository}/{origin}/APKBUILD")
        except urllib.error.HTTPError:
            continue
    raise OSError(f"{origin}: no APKBUILD at aports commit {commit}")


def apkbuild_sources(image: str, apkbuild: bytes) -> list[dict]:
    out = subprocess.run(
        ["docker", "run", "--rm", "-i", "--user", "0", "--network", "none", "--entrypoint", "sh", image,
         "-c", APKBUILD_SOURCES],
        input=apkbuild, capture_output=True, check=True,
    ).stdout.decode("utf-8", "replace")
    return parse_apkbuild_sources(out)


def parse_apkbuild_sources(out: str) -> list[dict]:
    listed, _, sums = out.partition("--\n")
    digests = {}
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2:
            digests[parts[1]] = parts[0]
    found = []
    for entry in listed.split():
        name, separator, url = entry.partition("::")
        if not separator:
            url, name = entry, entry.rsplit("/", 1)[-1]
        if "://" in url:
            found.append({"name": name, "url": url, "sha512": digests.get(name, "")})
    return found


def alpine_files(image: str, origin: str, commit: str, branch: str) -> list[dict]:
    repository, apkbuild = alpine_recipe(origin, commit)
    files = [{"name": f"aports-{origin}-{commit[:12]}.tar.gz", "sha1": "",
              "url": f"{APORTS}/-/archive/{commit}/aports-{commit}.tar.gz?path={repository}/{origin}"}]
    for source in apkbuild_sources(image, apkbuild):
        mirror = f"{DISTFILES}/{branch}/{source['name']}"
        files.append({"name": source["name"], "sha512": source["sha512"],
                      "url": mirror if exists(mirror) else source["url"]})
    return files


def safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]", "_", text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download the exact source code of every GPL or LGPL operating-system package in one of our "
                    "images into a single tar archive, to answer a request under the written offer in "
                    "THIRD_PARTY_NOTICES.")
    parser.add_argument("image", help="the image, for example ghcr.io/epitechpromo2027/horus-mas:0.1.2-cpu "
                                      "(pulled or built locally)")
    parser.add_argument("--out", type=Path, default=Path("."), help="folder for the archive (default: .)")
    parser.add_argument("--dry-run", action="store_true", help="list the source files without downloading them")
    args = parser.parse_args(argv)

    info, problems = system_packages.image_packages(args.image, overrides())
    branch = "v" + ".".join(info["os_version"].split(".")[:2])
    sources = sorted({(row["source"], row["source_version"], row.get("commit", "")) for row in info["packages"]})
    resolved: dict[tuple[str, str, str], list[dict]] = {}
    for source, version, commit in sources:
        try:
            resolved[(source, version, commit)] = (alpine_files(args.image, source, commit, branch)
                                                   if info["kind"] == "alpine" else debian_files(source, version))
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            problems.append(f"{source} {version}: {error}")
    size = sum(file.get("size", 0) for files in resolved.values() for file in files)
    print(f"{args.image}: {info['os']}, {len(info['packages'])} GPL or LGPL packages from {len(sources)} sources, "
          f"{sum(len(files) for files in resolved.values())} files"
          + (f", {size / 1e6:.1f} MB" if info["kind"] != "alpine" else ""))
    if args.dry_run or problems:
        for problem in problems:
            print(f"error: {problem}")
        return 1 if problems else 0

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"gpl-sources-{safe(args.image)}.tar"
    manifest = ["path\tsha1\tsha512\turl"]
    with tempfile.TemporaryDirectory() as scratch, tarfile.open(target, "w") as archive:
        for (source, version, commit), files in resolved.items():
            folder = f"{safe(source)}_{safe(version)}"
            for file in files:
                try:
                    path = download(file["url"], Path(scratch), file.get("sha1") or file.get("sha512", ""),
                                    "sha1" if file.get("sha1") else "sha512")
                except OSError as error:
                    problems.append(f"{source} {version}: {file['name']}: {error}")
                    continue
                archive.add(path, f"{folder}/{file['name']}")
                path.unlink()
                manifest.append(f"{folder}/{file['name']}\t{file.get('sha1', '')}\t{file.get('sha512', '')}\t"
                                f"{file['url']}")
        packages = ["name\tversion\tsource\tsource_version\tlicence"] + [
            f"{row['name']}\t{row['version']}\t{row['source']}\t{row['source_version']}\t{row['licence']}"
            for row in info["packages"]]
        for name, lines in (("PACKAGES.tsv", packages), ("SOURCES.tsv", manifest)):
            listing = Path(scratch) / name
            listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
            archive.add(listing, name)
    print(f"wrote {target} ({target.stat().st_size / 1e6:.1f} MB)")
    for problem in problems:
        print(f"error: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
