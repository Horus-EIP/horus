#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGING = REPO / "packaging"
SIZE_LIMIT = 50 * 1024 * 1024

VERSION_FILE = REPO / "VERSION"

def read_version() -> str:
    try:
        text = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return text or "0.0.0"

SOURCE_INCLUDE = [
    "src/services/mas",
    "src/services/agent",
    "src/services/web-client",
    "src/services/knowledge-store",
    "src/services/llm-mock",
    "src/infra",
    "demo_assets",
    "models",
    "LICENSES",
    "NOTICES",
]

SOURCE_FILES = [
    "stack-up.sh",
    "LICENSE",
    "THIRD_PARTY_NOTICES",
]

PRUNE_DIRS = {
    ".git", ".github", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".next", ".turbo", ".ruff_cache", ".pytest_cache", ".mypy_cache",
    "htmlcov", ".idea", ".vscode", "offload", "__tests__",
    "ks_chroma_backup", "ks_documents_backup",
    "grafana",
}

PRUNE_GLOBS = [
    ".env", ".env.bak.*", "*.pyc", "*.pyo", "*.log", "*.tmp", "*.swp",
    ".DS_Store", "Thumbs.db", "*.sqlite3", "*.db",
    "install-log.txt", "horus-profile.json",
    "*.gguf", "*.part", "*.gguf.sha256",
    "registry-token.txt",
]

PRUNE_PATHS = (
    "src/services/mas/logs/",
    "src/services/agent/logs/",
    "src/services/knowledge-store/logs/",
    "src/infra/license/",
    "installer/tests/",
    "src/services/knowledge-store/tests/",
    "src/services/agent/app/models/",
)

EXECUTABLE = {".sh", ".command"}
LF_ONLY = {".sh", ".command", ".bash", ".dockerfile"}
LF_ONLY_NAMES = {"Dockerfile"}
CRLF_ONLY = {".bat", ".cmd"}
NORMALISED: list[str] = []

def line_endings(arcname: str, data: bytes) -> bytes:
    name = arcname.rsplit("/", 1)[-1]
    suffix = Path(name).suffix.lower()
    if suffix in LF_ONLY or name in LF_ONLY_NAMES:
        if b"\r\n" in data:
            NORMALISED.append(f"{arcname}  (CRLF -> LF)")
            return data.replace(b"\r\n", b"\n")
    elif suffix in CRLF_ONLY:
        if b"\n" in data.replace(b"\r\n", b""):
            NORMALISED.append(f"{arcname}  (LF -> CRLF)")
            return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data

def is_executable_on_disk(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & 0o111)
    except OSError:
        return False

def pruned(path: Path) -> bool:
    if any(part in PRUNE_DIRS for part in path.parts):
        return True
    posix = path.as_posix()
    if any(posix.startswith(prefix) for prefix in PRUNE_PATHS):
        return True
    return any(path.match(pattern) for pattern in PRUNE_GLOBS)

def _git_tracked(root: Path, rel: str) -> list[Path] | None:
    if shutil.which("git") is None:
        return None
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others",
             "--exclude-standard", "--", rel],
            cwd=str(root), capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    names = [n for n in proc.stdout.decode("utf-8", "replace").split("\0") if n]
    return [root / n for n in names]

def collect(root: Path, rel: str) -> list[Path]:
    base = root / rel
    if base.is_file():
        return [] if pruned(base.relative_to(root)) else [base]

    tracked = _git_tracked(root, rel)
    if tracked is not None:
        found = [p for p in tracked if p.is_file() and not pruned(p.relative_to(root))]
        if found or base.is_dir():
            return found
        print(f"  warning: {rel} does not exist, skipping")
        return []

    if not base.is_dir():
        print(f"  warning: {rel} does not exist, skipping")
        return []
    out = []
    for item in base.rglob("*"):
        if not item.is_file():
            continue
        if pruned(item.relative_to(root)):
            continue
        out.append(item)
    return out

def check_app_dir(app_root: Path) -> str:
    for app in sorted(app_root.glob("*.app")):
        macos_dir = app / "Contents" / "MacOS"
        if not macos_dir.is_dir():
            return f"{app.name} has no Contents/MacOS - it is not a macOS bundle"
        binaries = [p for p in macos_dir.iterdir() if p.is_file()]
        if not binaries:
            return f"{app.name}/Contents/MacOS is empty"
        not_executable = [p.name for p in binaries if not is_executable_on_disk(p)]
        if not_executable:
            return (
                f"{app.name}/Contents/MacOS/{not_executable[0]} is not executable.\n"
                "         macOS will refuse to open the app and will not say why.\n"
                "         Fix it before archiving:\n"
                f"           chmod +x {macos_dir}/*\n"
                "         If you are on Windows, build the archive on Linux or "
                "macOS instead:\n"
                "         a Windows filesystem cannot carry the bit at all."
            )
    return ""

def add_symlink(zf: zipfile.ZipFile, src: Path, arcname: str) -> int:
    target = os.readlink(src)
    info = zipfile.ZipInfo(arcname)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    info.create_system = 3
    info.date_time = (2026, 1, 1, 0, 0, 0)
    zf.writestr(info, target)
    return len(target)

def escapes(link: Path, root: Path) -> bool:
    try:
        resolved = (link.parent / os.readlink(link)).resolve()
    except OSError:
        return True
    try:
        return not resolved.is_relative_to(root.resolve())
    except (OSError, ValueError):
        return True

def add(zf: zipfile.ZipFile, src: Path, arcname: str, keep_mode: bool = False) -> int:
    data = line_endings(arcname, src.read_bytes())
    info = zipfile.ZipInfo(arcname)
    info.compress_type = zipfile.ZIP_DEFLATED
    if keep_mode and is_executable_on_disk(src):
        mode = 0o755
    else:
        mode = 0o755 if src.suffix in EXECUTABLE else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.date_time = (2026, 1, 1, 0, 0, 0)
    zf.writestr(info, data)
    return len(data)

def unpack_for_review(archive: Path, dest: Path) -> int:
    if dest.exists():
        shutil.rmtree(dest)
    written = 0
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            target = dest / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            mode = info.external_attr >> 16
            payload = zf.read(info.filename)
            if stat.S_ISLNK(mode):
                os.symlink(payload.decode("utf-8"), target)
            else:
                target.write_bytes(payload)
                if os.name == "posix":
                    os.chmod(target, mode & 0o777)
            written += 1
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="dist", help="output directory (default: dist)")
    ap.add_argument("--app-dir", default=None,
                    help="directory holding the built desktop apps (Horus.exe, "
                         "Horus.app, horus_*.deb). Omitted = build a ZIP without them.")
    ap.add_argument("--stage", nargs="?", const="Beta_Test_Installer", default=None,
                    metavar="NAME",
                    help="also unpack the archive into <out>/NAME so you can browse "
                         "exactly what the tester receives (default name: "
                         "Beta_Test_Installer). Generated output - never edit it, "
                         "and on Windows send the .zip rather than re-zipping the "
                         "folder, because NTFS cannot carry the executable bit that "
                         "Horus.app needs.")
    ap.add_argument("--allow-oversize", action="store_true",
                    help="do not fail when the archive exceeds 50 MB")
    args = ap.parse_args()

    version = read_version()
    out_dir = REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"Horus-Beta-{version}.zip"
    if target.exists():
        target.unlink()

    partial = out_dir / (target.name + ".partial")
    if partial.exists():
        partial.unlink()

    print(f"Building {target.name}")
    print()

    try:
        return _fill(partial, target, args)
    finally:
        if partial.exists():
            partial.unlink()

def _fill(partial: Path, target: Path, args) -> int:
    totals: dict[str, int] = {}
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        section = 0
        for name in ("START-HERE-Windows.bat", "START-HERE-macOS.command",
                     "START-HERE-Linux.sh", "README-FIRST.txt"):
            src = PACKAGING / name
            if not src.is_file():
                print(f"  ERROR: missing {src}")
                return 1
            section += add(zf, src, name)
        if not VERSION_FILE.is_file():
            print(f"  ERROR: missing {VERSION_FILE}")
            return 1
        section += add(zf, VERSION_FILE, "VERSION")
        totals["launchers + README"] = section

        section = 0
        for item in collect(REPO, "installer"):
            section += add(zf, item, str(item.relative_to(REPO)).replace("\\", "/"))
        totals["installer"] = section

        section = 0
        for rel in SOURCE_INCLUDE:
            for item in collect(REPO, rel):
                arc = "horus/" + str(item.relative_to(REPO)).replace("\\", "/")
                section += add(zf, item, arc)
        for rel in SOURCE_FILES:
            src = REPO / rel
            if src.is_file():
                section += add(zf, src, "horus/" + rel)
            else:
                print(f"  warning: {rel} missing")
        totals["horus source"] = section

        section = 0
        if args.app_dir:
            app_root = Path(args.app_dir).expanduser().resolve()
            if not app_root.is_dir():
                print(f"  ERROR: --app-dir {app_root} is not a directory")
                return 1
            problem = check_app_dir(app_root)
            if problem:
                print(f"  ERROR: {problem}")
                return 1
            for item in app_root.rglob("*"):
                rel = item.relative_to(app_root)
                if item.is_symlink():
                    if pruned(rel):
                        continue
                    if escapes(item, app_root):
                        print(f"  warning: skipping symlink out of the tree: "
                              f"{rel} -> {os.readlink(item)}")
                        continue
                    arc = "app/" + str(rel).replace("\\", "/")
                    section += add_symlink(zf, item, arc)
                    continue
                if item.is_file() and not pruned(item.relative_to(app_root)):
                    arc = "app/" + str(item.relative_to(app_root)).replace("\\", "/")
                    section += add(zf, item, arc, keep_mode=True)
            if section == 0:
                print(f"  warning: {app_root} contained no files")
        else:
            print("  note: --app-dir not given, so the desktop apps are NOT included.")
            print("        Build them in CI (desktop-release.yml) and pass the")
            print("        downloaded artifacts directory here.")
        totals["desktop apps"] = section

    if NORMALISED:
        print()
        print(f"  WARNING: {len(NORMALISED)} file(s) had the wrong line endings in the")
        print("  working tree and were rewritten on the way into the archive:")
        for note in NORMALISED:
            print(f"    {note}")
        print("  The checkout is what is wrong: run `git add --renormalize .` so the")
        print("  .gitattributes rules take effect, then rebuild.")

    size = partial.stat().st_size
    print()
    print("  uncompressed by section:")
    for label, count in totals.items():
        print(f"    {label:<22} {count / 1024 / 1024:6.2f} MB")
    print()
    print(f"  archive:  {size / 1024 / 1024:.2f} MB  ({size:,} bytes)")
    print(f"  budget :  {SIZE_LIMIT / 1024 / 1024:.0f} MB")
    with zipfile.ZipFile(partial) as zf:
        print(f"  files  :  {len(zf.namelist())}")

    if size > SIZE_LIMIT and not args.allow_oversize:
        print()
        print(f"  FAIL: over the 50 MB budget by "
              f"{(size - SIZE_LIMIT) / 1024 / 1024:.2f} MB")
        print("  A Linux AppImage bundles WebKitGTK (70-100 MB) and will not fit;")
        print("  ship the .deb instead, which links the system webkit2gtk.")
        return 1

    partial.replace(target)
    print()
    print(f"  OK -> {target}")

    if args.stage:
        staged = target.parent / args.stage
        count = unpack_for_review(target, staged)
        print(f"  OK -> {staged}{os.sep}  ({count} files, generated - do not edit)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
