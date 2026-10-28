"""scripts/merge-tasks.py: git's merge driver for specs/*/tasks.md, which resolves a
conflict made of ticks alone (two lanes each ticking their own tasks) and leaves any
other conflict for the operator. Run: python3 -I -m unittest discover -s scripts/tests."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, "..", "merge-tasks.py")

BASE = """# Tasks

- [ ] T001 a
- [ ] T002 b
- [ ] T003 c
- [ ] T004 d

## Notes
"""


def merge(base, ours, theirs):
    d = tempfile.mkdtemp()
    paths = []
    for name, text in (("base", base), ("ours", ours), ("theirs", theirs)):
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write(text)
        paths.append(p)
    r = subprocess.run([sys.executable, "-I", DRIVER] + paths, capture_output=True, text=True)
    return r.returncode, open(paths[1]).read()


class TickMerge(unittest.TestCase):
    def test_adjacent_ticks_from_two_lanes_are_both_kept_once(self):
        ours = BASE.replace("- [ ] T001", "- [X] T001")
        theirs = BASE.replace("- [ ] T002", "- [X] T002")
        code, out = merge(BASE, ours, theirs)
        self.assertEqual(code, 0)
        self.assertEqual(out, BASE.replace("- [ ] T001", "- [X] T001").replace("- [ ] T002", "- [X] T002"))

    def test_a_clean_merge_passes_through(self):
        ours = BASE.replace("- [ ] T001", "- [X] T001")
        theirs = BASE.replace("- [ ] T004", "- [X] T004")
        code, out = merge(BASE, ours, theirs)
        self.assertEqual(code, 0)
        self.assertIn("- [X] T001", out)
        self.assertIn("- [X] T004", out)
        self.assertNotIn("<<<<<<<", out)

    def test_a_tick_with_a_note_on_one_side_still_merges(self):
        ours = BASE.replace("- [ ] T001 a", "- [X] T001 a\n  - 2026-10-28: done")
        theirs = BASE.replace("- [ ] T002", "- [X] T002")
        code, out = merge(BASE, ours, theirs)
        self.assertEqual(code, 0, out)
        self.assertIn("- [X] T001 a\n  - 2026-10-28: done\n- [X] T002 b", out)

    def test_a_conflict_that_is_not_ticks_is_left_with_markers(self):
        ours = BASE.replace("- [ ] T002 b", "- [ ] T002 b, reworded by one lane")
        theirs = BASE.replace("- [ ] T002 b", "- [X] T002 b")
        code, out = merge(BASE, ours, theirs)
        self.assertEqual(code, 1)
        self.assertIn("<<<<<<<", out)
        self.assertIn(">>>>>>>", out)


if __name__ == "__main__":
    unittest.main()
