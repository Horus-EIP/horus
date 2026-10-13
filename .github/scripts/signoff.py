# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

TRAILER = re.compile(r"^Signed-off-by:\s*(.*?)\s*<([^<>]+)>\s*$", re.MULTILINE)
FIELD = "\x1f"
RECORD = "\x1e"
HOW_TO_FIX = """Every commit needs a Signed-off-by line with its author's name and email
(the Developer Certificate of Origin, see CONTRIBUTING.md). To add it:

  only the last commit:   git commit --amend --signoff --no-edit
  every commit:           git rebase --signoff {fork}

where {fork} is the commit your branch starts from, then push the branch
again: git push --force-with-lease"""


@dataclass(frozen=True)
class Commit:
    sha: str
    author: str
    email: str
    message: str


def git_log(base: str, head: str, run: Callable = subprocess.run) -> str:
    done = run(
        ["git", "log", "--no-merges", f"--format=%H{FIELD}%an{FIELD}%ae{FIELD}%B{RECORD}", f"{base}..{head}"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return done.stdout


def fork_point(base: str, head: str, run: Callable = subprocess.run) -> str:
    done = run(["git", "merge-base", base, head], capture_output=True, text=True, encoding="utf-8", check=True)
    return done.stdout.strip()


def parse(log: str) -> list[Commit]:
    commits = []
    for record in log.split(RECORD):
        record = record.strip("\n")
        if not record:
            continue
        sha, author, email, message = record.split(FIELD, 3)
        commits.append(Commit(sha, author, email, message))
    return commits


def signed_by_author(commit: Commit) -> bool:
    return any(name.strip() == commit.author.strip() and address.strip().lower() == commit.email.strip().lower()
               for name, address in TRAILER.findall(commit.message))


def problems(commits: list[Commit]) -> list[str]:
    return [f"{commit.sha[:12]} by {commit.author} <{commit.email}> has no matching Signed-off-by line"
            for commit in commits if not signed_by_author(commit)]


def main(argv: list[str] | None = None, run: Callable = subprocess.run) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: signoff.py BASE HEAD", file=sys.stderr)
        return 2
    base, head = argv
    commits = parse(git_log(base, head, run))
    found = problems(commits)
    for problem in found:
        print(f"::error::{problem}")
    if found:
        print(HOW_TO_FIX.format(fork=fork_point(base, head, run)[:12]))
        return 1
    print(f"Every commit is signed off by its author ({len(commits)} checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
