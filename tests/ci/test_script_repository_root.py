from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = (
    "scripts/test/run-all.sh",
    "scripts/test/run-mas.sh",
    "scripts/test/run-agent.sh",
    "scripts/test/run-knowledge-store.sh",
    "scripts/test/migrations.sh",
    "scripts/dev/run-mas.sh",
)
ROOT_ASSIGNMENT = re.compile(r"(?m)^REPO_ROOT=.*$")


class ScriptRepositoryRoot(unittest.TestCase):
    def resolve_root(self, relative_script: str, cwd: Path) -> Path:
        script = REPO / relative_script
        text = script.read_text(encoding="utf-8")
        match = ROOT_ASSIGNMENT.search(text)
        self.assertIsNotNone(match, f"{relative_script} does not define REPO_ROOT")

        result = subprocess.run(
            [
                "bash",
                "-c",
                f'{match.group()}\nprintf "%s\\n" "$REPO_ROOT"',
            ],
            cwd=cwd,
            env={**os.environ, "SCRIPT_DIR": str(script.parent)},
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return Path(result.stdout.strip())

    def test_scripts_resolve_the_repository_root_from_an_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            for relative_script in SCRIPTS:
                with self.subTest(script=relative_script):
                    self.assertEqual(self.resolve_root(relative_script, cwd), REPO)

    def test_test_scripts_run_from_the_resolved_repository_root(self):
        for relative_script in SCRIPTS[:4]:
            with self.subTest(script=relative_script):
                text = (REPO / relative_script).read_text(encoding="utf-8")
                self.assertIn('cd "$REPO_ROOT"', text)
                self.assertTrue((REPO / "tests").is_dir())

    def test_migration_and_development_scripts_use_paths_under_the_repository_root(self):
        migrations = (REPO / "scripts/test/migrations.sh").read_text(encoding="utf-8")
        self.assertIn('cd "$REPO_ROOT/src/services/mas/db"', migrations)

        run_mas = (REPO / "scripts/dev/run-mas.sh").read_text(encoding="utf-8")
        self.assertIn('MAS_DIR="$REPO_ROOT/src/services/mas"', run_mas)
        self.assertIn('cd "$MAS_DIR"', run_mas)


if __name__ == "__main__":
    unittest.main()
