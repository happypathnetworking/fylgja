"""scripts/converge-plan.py: the route planner scripts/converge-loop.sh runs before every
session. Run: python3 -I -m unittest discover -s scripts/tests -p 'test_*.py'."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = os.path.join(HERE, "..", "converge-plan.py")

TASKS = """# Tasks: x

## Phase 1: Setup

- [X] T001 the baseline
- [ ] T002 [operator] the review, which cannot precede the chain

## Phase 2: Core

- [ ] T003 a
- [ ] T004 b
- [ ] T005 c
- [ ] T006 d
- [ ] T007 e, a tier-2 test
- [ ] T008 [live] f
- [ ] T009 g

## Dependencies & Execution Order

## Implementation Strategy

### Recommended route

Each line is one implement run's prompt.

1. **Run 1** — the baseline (T001). Read first: Makefile. Only this; stop and report.
2. **Run 2** — [operator] the review (T002). Stop and report.
3. **Run 3** [∥ Run 4] — a and c, not b (T003, T005). Read first: internal/a/a.go. Only these; stop and report.
4. **Run 4** [∥ Run 3] — b and d (T004, T006). Read first: internal/b/b.go. Only these; stop and report.
5. **Run 5** [∥ Run 6] — the tier-2 test TestX written and run alone (T007). Only this; stop and report.
6. **Run 6** [∥ Run 5] — [live] f on the host (T008). Stop and report.

## Notes

- [ ] T010 a convergence task outside the route
"""


def plan(text, tier2="1", excluded="", only=""):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(text)
    try:
        out = subprocess.run([sys.executable, "-I", PLAN, f.name, tier2, excluded, only],
                             capture_output=True, text=True, check=True).stdout
    finally:
        os.unlink(f.name)
    rows = [line.split("\t") for line in out.splitlines()]
    return {r[0]: {"live": r[1], "ids": r[2].split(), "lane": r[3], "line": r[4]} for r in rows}


class RouteParsing(unittest.TestCase):
    def test_a_checked_run_is_left_out_and_ids_may_be_non_contiguous(self):
        runs = plan(TASKS)
        self.assertNotIn("Run 1", runs)
        self.assertEqual(runs["Run 3"]["ids"], ["T003", "T005"])
        self.assertEqual(runs["Run 4"]["ids"], ["T004", "T006"])

    def test_the_line_is_the_prompt_without_the_lane_mark(self):
        line = plan(TASKS)["Run 3"]["line"]
        self.assertTrue(line.startswith("Run 3 — a and c"), line)
        self.assertNotIn("∥", line)

    def test_an_operator_run_is_live_and_never_laned(self):
        r = plan(TASKS)["Run 2"]
        self.assertEqual(r["live"], "1")
        self.assertEqual(r["lane"], "")

    def test_a_pure_pair_is_laned_both_ways(self):
        runs = plan(TASKS)
        self.assertEqual(runs["Run 3"]["lane"], "Run 4")
        self.assertEqual(runs["Run 4"]["lane"], "Run 3")

    def test_a_tier2_run_and_a_live_run_are_not_laned(self):
        runs = plan(TASKS)
        self.assertEqual(runs["Run 5"]["lane"], "", "tier 2 shares one Infrahub")
        self.assertEqual(runs["Run 5"]["live"], "0")
        self.assertEqual(runs["Run 6"]["lane"], "")
        self.assertEqual(runs["Run 6"]["live"], "1")

    def test_a_task_the_route_does_not_name_is_its_phase_run(self):
        runs = plan(TASKS)
        self.assertIn("Phase 2", runs)
        self.assertEqual(runs["Phase 2"]["ids"], ["T009"])
        self.assertEqual(runs["Phase 2"]["lane"], "")

    def test_excluded_ids_and_only_ids(self):
        runs = plan(TASKS, excluded="T003")
        self.assertEqual(runs["Run 3"]["ids"], ["T005"])
        runs = plan(TASKS, only="T004 T002")
        self.assertEqual(set(runs), {"Run 2", "Run 4"})
        self.assertEqual(runs["Run 2"]["live"], "0", "an answered [operator] task no longer makes its run live")

    def test_without_infrahub_tier2_is_live(self):
        self.assertEqual(plan(TASKS, tier2="0")["Run 5"]["live"], "1")

    def test_a_lane_partner_that_is_not_listed_is_dropped(self):
        text = TASKS.replace("- [ ] T004 b", "- [X] T004 b").replace("- [ ] T006 d", "- [X] T006 d")
        runs = plan(text)
        self.assertNotIn("Run 4", runs)
        self.assertEqual(runs["Run 3"]["lane"], "", "Run 4 is done, so Run 3 has no partner")


if __name__ == "__main__":
    unittest.main()
