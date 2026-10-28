#!/usr/bin/env python3
"""The route planner of scripts/converge-loop.sh (docs/development.md, "The converge loop").

    python3 -I scripts/converge-plan.py <tasks.md> <tier2: 1|0> "<excluded ids>" "<only ids>"

Prints the runs still to implement, one per line, as TSV: the label (`Run N` or `Phase N`),
1 if the run needs the host (live), its unchecked task ids, its lane partner's label (or
nothing), and its line, which is the run's prompt.

The runs come from tasks.md's "Recommended route", read up to the next heading:

    N. **Run N** [∥ Run M] — <what> (T0xx–T0yy, T0zz). Read first: … Only these; stop and report.

The parenthesised ids are the run's tasks, ranges expanded, contiguous or not. After the
route, each phase's unchecked tasks the route does not name are a run of their own (a phase
added after the route was written, a convergence phase); without a route, each phase is a
run. A run whose tasks are all checked is left out, so a stopped loop resumes where it
stopped. With <excluded ids> (the open and skipped questions' tasks), those tasks are left
out; with <only ids>, only those are listed, and an [operator] tag no longer makes a run
live, since the question that tag raised has been answered.

A run is live when its line names tier 3, the hand scenarios, a quiet host or test-e2e, or
carries [operator] or [live], or one of its tasks does; without Infrahub credentials
(tier2 = 0), tier 2 and test-contract make it live too.

A run is laned when it or its partner carries `[∥ Run M]`, the partner is listed and still
pending, and neither is live or names tier 2: lanes run in separate worktrees, and tier 2
shares one Infrahub. The mark never reaches the prompt.
"""
import re
import sys


def expand(s):
    out = []
    for a, b in re.findall(r"(T\d+)(?:\s*[–-]\s*(T\d+))?", s):
        if b:
            out += [f"T{i:0{len(a) - 1}d}" for i in range(int(a[1:]), int(b[1:]) + 1)]
        else:
            out.append(a)
    return out


def main():
    text = open(sys.argv[1], encoding="utf-8").read()
    tier2 = sys.argv[2] == "1"
    excluded = set(sys.argv[3].split())
    only = set(sys.argv[4].split())
    tasks = {m.group(2): (m.group(1) != " ", m.group(3))
             for m in re.finditer(r"^\s*- \[([ xX])\] (T\d+)\b(.*)$", text, re.M)}
    # With <only ids>, an [operator] on the line no longer counts either: the question that
    # tag raised has been answered, and the answered tasks run as a plain session.
    live_re = (r"\[live\]" if only else r"\[operator\]|\[live\]") + r"|tier 3|hand scenario|quiet host|test-e2e"
    if not tier2:
        live_re += r"|tier[ -]?2|test-contract|-tags contract"
    live_re = re.compile(live_re, re.I)
    tier2_re = re.compile(r"tier[ -]?2|test-contract|-tags contract", re.I)

    phases = []
    for m in re.finditer(r"^## (Phase \d+)[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        title = m.group(0).splitlines()[0][3:]
        phases.append((m.group(1), title, re.findall(r"^\s*- \[[ xX]\] (T\d+)\b", m.group(2), re.M)))

    runs = []  # (label, line, ids, partner mark)
    route = re.search(r"^### Recommended route[^\n]*\n(.*?)(?=^#)", text, re.M | re.S)
    if route:
        for line in route.group(1).splitlines():
            r = re.match(r"\s*\d+\.\s+\*\*(Run \d+)\*\*\s*(?:\[∥\s*(Run \d+)\s*\])?\s*[—-]\s*(.*)", line)
            if r:
                ids = [i for g in re.findall(r"\(([^)]*T\d+[^)]*)\)", r.group(3)) for i in expand(g)]
                runs.append((r.group(1), f"{r.group(1)} — {r.group(3).strip()}", ids, r.group(2)))
    covered = {i for _, _, ids, _ in runs for i in ids}
    for label, title, ids in phases:
        rest = [i for i in ids if i not in covered]
        if rest:
            runs.append((label, title, rest, None))
            covered.update(rest)

    listed = []
    for label, line, ids, mark in runs:
        todo = list(dict.fromkeys(i for i in ids if i in tasks and not tasks[i][0] and i not in excluded
                                  and (not only or i in only)))
        if not todo:
            continue
        tag = r"\s*\[live\]" if only else r"\s*\[(operator|live)\]"
        live = bool(live_re.search(line) or any(re.match(tag, tasks[i][1]) for i in todo))
        laneable = not live and not tier2_re.search(line) and not any(tier2_re.search(tasks[i][1]) for i in todo)
        listed.append({"label": label, "line": line, "ids": todo, "live": live, "mark": mark, "laneable": laneable})

    by_label = {r["label"]: r for r in listed}
    for r in listed:
        r["lane"] = ""
    for r in listed:
        p = by_label.get(r["mark"]) if r["mark"] else None
        if p and r["laneable"] and p["laneable"]:
            r["lane"], p["lane"] = p["label"], r["label"]
    for r in listed:
        print(f"{r['label']}\t{1 if r['live'] else 0}\t{' '.join(r['ids'])}\t{r['lane']}\t{r['line']}")


if __name__ == "__main__":
    main()
