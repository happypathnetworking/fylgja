"""scripts/converge-loop.sh's pure functions, extracted from the script by name and run
under bash. Run: python3 -I -m unittest discover -s scripts/tests."""
import os
import re
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "converge-loop.sh")


def function(name):
    text = open(SCRIPT, encoding="utf-8").read()
    m = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}", text, re.M | re.S)
    assert m, f"{name} is not a function of the script"
    return m.group(0)


def bash(body, *args):
    return subprocess.run(["bash", "-c", body, "bash", *args], capture_output=True, text=True).stdout


class ReportMarker(unittest.TestCase):
    """The marker a chain stage ends its report with is its last non-empty line, so a
    report that quotes both markers above its end is read by its end alone."""

    def marker(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(text)
        try:
            return bash(function("report_marker") + '\nreport_marker "$1"', f.name).strip()
        finally:
            os.unlink(f.name)

    def test_the_last_non_empty_line_is_the_marker(self):
        self.assertEqual(self.marker("Nothing to ask.\n\nCLARIFY-DONE\n\n"), "CLARIFY-DONE")

    def test_a_wait_at_the_end_wins_over_a_done_quoted_above(self):
        report = "I would end with CLARIFY-DONE, but one point is open:\nCLARIFY-DONE\n\n## Questions\n\n1. Which?\n\nCLARIFY-WAIT\n"
        self.assertEqual(self.marker(report), "CLARIFY-WAIT")

    def test_no_marker_when_the_report_ends_otherwise(self):
        self.assertEqual(self.marker("CLARIFY-DONE\nand then some prose\n"), "and then some prose")


class SeedWorktree(unittest.TestCase):
    """A lane's worktree is seeded with both venvs by symlink, the root's and the
    orchestrator's, so a lane's `make test` and `make lint` find pytest and ruff, and each
    is listed so the lane's dirty check leaves it out."""

    def test_both_venvs_are_linked_and_listed(self):
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.join(d, "repo")
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
            subprocess.run(["git", "init", "-q", repo], check=True)
            for path, text in {
                ".gitignore": "local/\n",
                ".specify/extensions.yml": "hooks: {}\n",
                "orchestrator/pyproject.toml": "[project]\n",
            }.items():
                os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
                with open(os.path.join(repo, path), "w") as f:
                    f.write(text)
            subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
            subprocess.run([*git, "commit", "-qm", "base"], cwd=repo, check=True)
            for venv in (".venv", "orchestrator/.venv"):
                os.makedirs(os.path.join(repo, venv, "bin"))
                with open(os.path.join(repo, venv, ".gitignore"), "w") as f:
                    f.write("*\n")
                open(os.path.join(repo, venv, "bin", "python"), "w").close()
            wt, seeded = os.path.join(d, "wt"), os.path.join(d, "seeded")
            body = function("seed_worktree") + '\nFEATURE_REL=specs/000-x; seed_worktree "$1" lane/x "$2"'
            out = subprocess.run(["bash", "-c", body, "bash", wt, seeded], cwd=repo, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            for venv in (".venv", "orchestrator/.venv"):
                self.assertTrue(os.path.islink(os.path.join(wt, venv)), venv)
                self.assertEqual(os.readlink(os.path.join(wt, venv)), os.path.join(os.path.realpath(repo), venv))
            listed = open(seeded).read().split()
            self.assertIn(".venv", listed)
            self.assertIn("orchestrator/.venv", listed)


if __name__ == "__main__":
    unittest.main()
