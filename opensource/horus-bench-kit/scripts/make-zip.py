# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import importlib.util
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from types import ModuleType

KIT_ROOT = Path(__file__).resolve().parents[1]
CHECKS_PATH = KIT_ROOT / "src" / "horus_bench_kit" / "publishable.py"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o644 << 16
SCRIPT_MODE = 0o755 << 16
MADE_ON_UNIX = 3


def load_checks(path: Path = CHECKS_PATH) -> ModuleType:
    spec = importlib.util.spec_from_file_location("hbk_publishable", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checks = load_checks()
is_packaged = checks.is_packaged
packaged_files = checks.packaged_files


def kit_version(root: Path = KIT_ROOT) -> str:
    return checks.pyproject_version((root / "pyproject.toml").read_text(encoding="utf-8"))


def packaged_bytes(root: Path, relative: PurePosixPath) -> bytes:
    data = (root / relative).read_bytes()
    return data.replace(b"\r\n", b"\n") if checks.is_text(relative) else data


def build_zip(out_dir: Path, root: Path = KIT_ROOT) -> tuple[Path, int]:
    name = f"horus-bench-kit-{kit_version(root)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"{name}.zip"
    files = packaged_files(root)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for relative in files:
            entry = zipfile.ZipInfo(f"{name}/{relative}", date_time=FIXED_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = MADE_ON_UNIX
            entry.external_attr = SCRIPT_MODE if relative.suffix == ".sh" else FILE_MODE
            bundle.writestr(entry, packaged_bytes(root, relative))
    return archive, len(files)


def main(argv: Sequence[str] | None = None, root: Path = KIT_ROOT) -> int:
    parser = argparse.ArgumentParser(
        description="Check that the horus-bench-kit folder can be published, then zip it."
    )
    parser.add_argument(
        "--out",
        "--out-dir",
        dest="out",
        default=str(root / "dist"),
        help="folder for the .zip (default: dist/)",
    )
    args = parser.parse_args(argv)
    problems = checks.problems(root)
    if problems:
        for problem in problems:
            print(f"[error] {problem}")
        print(f"[error] the zip was not built: {len(problems)} problem(s)")
        return 1
    archive, count = build_zip(Path(args.out), root)
    print(f"[done] wrote {archive} ({count} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
