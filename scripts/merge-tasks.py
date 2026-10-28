#!/usr/bin/env python3
"""git's merge driver for specs/*/tasks.md (.gitattributes: `merge=tasks`), used when
scripts/converge-loop.sh merges a lane's branch back (docs/development.md, "The converge
loop"). Registered by the script: git config merge.tasks.driver "python3 scripts/merge-tasks.py %O %A %B".

    python3 -I scripts/merge-tasks.py <base> <ours> <theirs>

Two lanes that each tick their own tasks conflict whenever the ticks are on adjacent lines,
since git's hunk then spans both, and a `merge=union` driver would keep both sides' copies
of each line. This driver resolves a conflict region mechanically and only when every
difference in it is a tick or a note under a task: each task line in the region keeps its
base text, is ticked when either side ticked it, and keeps the note lines (indented lines
under it) each side added, ours first. Any other difference, a reworded task, a changed
heading, a task on one side alone, is left with its conflict markers, and the driver exits
1, so git reports the conflict and the loop stops at `merge` for the operator. The result
is written to <ours>, as git expects.
"""
import re
import subprocess
import sys

TASK = re.compile(r"^(\s*- \[)([ xX])(\] T\d+\b.*)$")
NOTE = re.compile(r"^\s+\S")


def parse(lines):
    """[(kind, key, text, notes)]: a task with its notes, or a plain line."""
    out = []
    for line in lines:
        m = TASK.match(line)
        if m:
            out.append(["task", re.search(r"T\d+", line).group(0), m.group(1) + " " + m.group(3), m.group(2) != " ", []])
        elif out and out[-1][0] == "task" and NOTE.match(line):
            out[-1][4].append(line)
        else:
            out.append(["line", None, line, False, []])
    return out


def resolve(base, ours, theirs):
    """The merged region, or None when a difference is not a tick or a note."""
    b, o, t = parse(base), parse(ours), parse(theirs)
    if not (len(b) == len(o) == len(t)):
        return None
    merged = []
    for eb, eo, et in zip(b, o, t):
        if not (eb[0] == eo[0] == et[0] and eb[1] == eo[1] == et[1] and eb[2] == eo[2] == et[2]):
            return None
        if eb[0] == "line":
            merged.append(eb[2])
            continue
        for side in (eo, et):
            if side[4][:len(eb[4])] != eb[4]:
                return None  # a note removed or reordered: not a mechanical merge
        ticked = eo[3] or et[3]
        notes = eb[4] + eo[4][len(eb[4]):] + et[4][len(eb[4]):]
        merged.append(eb[2].replace("[ ]", "[X]" if ticked else "[ ]", 1))
        merged += notes
    return merged


def main():
    base, ours, theirs = sys.argv[1:4]
    r = subprocess.run(["git", "merge-file", "-p", "--diff3", "-L", "ours", "-L", "base", "-L", "theirs", ours, base, theirs],
                       capture_output=True, text=True)
    if r.returncode < 0 or r.returncode > 127:
        sys.stderr.write(r.stderr)
        sys.exit(2)
    lines = r.stdout.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out, unresolved, i = [], 0, 0
    while i < len(lines):
        if lines[i] == "<<<<<<< ours":
            j = lines.index("||||||| base", i)
            k = lines.index("=======", j)
            end = lines.index(">>>>>>> theirs", k)
            merged = resolve(lines[j + 1:k], lines[i + 1:j], lines[k + 1:end])
            if merged is None:
                out += lines[i:end + 1]
                unresolved += 1
            else:
                out += merged
            i = end + 1
        else:
            out.append(lines[i])
            i += 1
    with open(ours, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    sys.exit(1 if unresolved else 0)


if __name__ == "__main__":
    main()
