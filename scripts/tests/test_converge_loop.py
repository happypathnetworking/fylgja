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


if __name__ == "__main__":
    unittest.main()
