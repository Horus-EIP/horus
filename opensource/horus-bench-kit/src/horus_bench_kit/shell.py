# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import shlex
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from horus_bench_kit import host

COMMAND_NOT_STARTED = 127


class Shell:
    start_errors: tuple[type[Exception], ...] = (OSError,)

    def run_text(self, argv: Sequence[str], timeout: float = 60.0) -> str | None:
        return host.run_text(list(argv), timeout)

    def run(self, argv: Sequence[str]) -> int:
        command = list(argv)
        try:
            return subprocess.run(command).returncode
        except self.start_errors as exc:
            print(f"[error] could not start {command[0]}: {exc}")
            return COMMAND_NOT_STARTED

    def run_captured(self, argv: Sequence[str]) -> tuple[int, str]:
        command = list(argv)
        try:
            completed = subprocess.run(
                command, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace"
            )
        except self.start_errors as exc:
            print(f"[error] could not start {command[0]}: {exc}")
            return COMMAND_NOT_STARTED, ""
        return completed.returncode, completed.stdout or ""

    def run_and_echo(
        self, argv: Sequence[str], stdin_text: str | None = None
    ) -> tuple[int, list[str]]:
        command = list(argv)
        print("[info] " + shlex.join(command), flush=True)
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE if stdin_text is not None else None,
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            print(f"[error] could not start {command[0]}: {exc}")
            return COMMAND_NOT_STARTED, []
        if stdin_text is not None:
            try:
                process.stdin.write(stdin_text)
                process.stdin.close()
            except self.start_errors:
                pass
        lines = []
        for line in process.stdout:
            lines.append(line.rstrip("\n"))
            if stdin_text is None:
                print(line, end="", flush=True)
        return process.wait(), lines

    def docker_text(self, argv: Sequence[str], timeout: float = 60.0) -> str | None:
        return self.run_text(["docker", *argv], timeout=timeout)

    def docker_output(self, argv: Sequence[str], timeout: float = 60.0) -> str:
        try:
            completed = subprocess.run(
                ["docker", *argv],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return (completed.stdout or "") + (completed.stderr or "")

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def temp_dir(self) -> Path:
        return Path(tempfile.gettempdir())

    def collect_host(self, disk_path: Path | None = None) -> dict[str, tuple[Any, str]]:
        return host.collect_host(disk_path)

    def docker_facts(self) -> dict[str, Any] | None:
        return host.parse_docker_info(self.run_text(["docker", "info", "--format", "{{json .}}"]))

    def git_commit(self, directory: Path | str | None = None) -> str | None:
        folder = Path(directory) if directory is not None else Path.cwd()
        return (
            self.run_text(["git", "-C", str(folder), "rev-parse", "--short", "HEAD"]) or ""
        ).strip() or None
