# SPDX-License-Identifier: Apache-2.0
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "signoff.py"


def load_signoff():
    spec = importlib.util.spec_from_file_location("kit_signoff", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


signoff = load_signoff()


def commit(message, author="Ada Lovelace", email="ada@example.org", sha="a" * 40):
    return signoff.Commit(sha, author, email, message)


def log(*commits):
    return "".join(f"{c.sha}\x1f{c.author}\x1f{c.email}\x1f{c.message}\x1e\n" for c in commits)


class TestSignedByAuthor:
    def test_a_line_with_the_authors_name_and_email(self):
        assert signoff.signed_by_author(commit("[+] Add\n\nSigned-off-by: Ada Lovelace <ada@example.org>"))

    def test_the_email_ignores_case(self):
        assert signoff.signed_by_author(commit("[+] Add\n\nSigned-off-by: Ada Lovelace <Ada@Example.org>"))

    def test_one_matching_line_among_several_is_enough(self):
        message = "[+] Add\n\nSigned-off-by: Grace Hopper <grace@example.org>\nSigned-off-by: Ada Lovelace <ada@example.org>"
        assert signoff.signed_by_author(commit(message))

    @pytest.mark.parametrize(
        "message",
        [
            "[+] Add",
            "[+] Add\n\nSigned-off-by: Ada Lovelace <ada@example.com>",
            "[+] Add\n\nSigned-off-by: A. Lovelace <ada@example.org>",
            "[+] Add\n\nSigned-off-by: Grace Hopper <grace@example.org>",
            "[+] Add\n\nSigned-off-by Ada Lovelace <ada@example.org>",
            "[+] Add, see Signed-off-by: Ada Lovelace <ada@example.org> in the docs",
        ],
    )
    def test_a_missing_or_different_line_fails(self, message):
        assert not signoff.signed_by_author(commit(message))


class TestMain:
    def fake_run(self, text):
        def run(command, **options):
            if command[:2] == ["git", "merge-base"]:
                assert command[2:] == ["base", "head"]
                return subprocess.CompletedProcess(command, 0, stdout="c" * 40 + "\n")
            assert command[:3] == ["git", "log", "--no-merges"]
            assert command[-1] == "base..head"
            return subprocess.CompletedProcess(command, 0, stdout=text)
        return run

    def test_every_commit_signed_off_passes(self, capsys):
        good = commit("[+] Add\n\nSigned-off-by: Ada Lovelace <ada@example.org>")
        assert signoff.main(["base", "head"], run=self.fake_run(log(good, good))) == 0
        assert "(2 checked)" in capsys.readouterr().out

    def test_a_missing_sign_off_fails_and_says_how_to_fix_it(self, capsys):
        good = commit("[+] Add\n\nSigned-off-by: Ada Lovelace <ada@example.org>")
        bad = commit("[x] Fix", sha="b" * 40)
        assert signoff.main(["base", "head"], run=self.fake_run(log(good, bad))) == 1
        out = capsys.readouterr().out
        assert f"::error::{'b' * 12} by Ada Lovelace <ada@example.org> has no matching Signed-off-by line" in out
        for expected in ("git commit --amend --signoff --no-edit", f"git rebase --signoff {'c' * 12}\n",
                         f"where {'c' * 12} is the commit your branch starts from", "git push --force-with-lease"):
            assert expected in out

    def test_it_needs_a_base_and_a_head(self):
        assert signoff.main(["base"]) == 2


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_it_reads_the_commits_of_a_real_repository(tmp_path, capsys):
    def git(*args):
        identity = ["-c", "user.name=Ada Lovelace", "-c", "user.email=ada@example.org", "-c", "commit.gpgsign=false"]
        done = subprocess.run(["git", *identity, *args], cwd=tmp_path, capture_output=True, text=True, check=True)
        return done.stdout.strip()

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "[+] Start")
    base = git("rev-parse", "HEAD")
    git("commit", "-q", "--allow-empty", "-s", "-m", "[+] Signed", "-m", "With a body.")
    signed = git("rev-parse", "HEAD")
    git("commit", "-q", "--allow-empty", "-m", "[x] Not signed")
    head = git("rev-parse", "HEAD")

    def run_here(command, **options):
        return subprocess.run(command, cwd=tmp_path, **options)

    found = signoff.parse(signoff.git_log(base, head, run_here))
    assert [(item.sha, item.author, item.email) for item in found] == [
        (head, "Ada Lovelace", "ada@example.org"),
        (signed, "Ada Lovelace", "ada@example.org"),
    ]
    assert found[1].message.startswith("[+] Signed\n\nWith a body.\n\nSigned-off-by: Ada Lovelace <ada@example.org>")
    assert signoff.main([base, signed], run=run_here) == 0
    assert signoff.main([base, head], run=run_here) == 1
    out = capsys.readouterr().out
    assert f"::error::{head[:12]} by Ada Lovelace" in out
    assert f"git rebase --signoff {base[:12]}" in out
