"""The checks /feature-open runs before a feature's chain starts (docs/development.md, "The
feature chain"). Reads only; prints one line per check and exits 1 when any fails.

    python3 -I .claude/skills/feature-open/check.py specs/NNN-slug
"""
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                                   text=True, check=True).stdout.strip())
ENV_NAMES = ("INFRAHUB_ADDRESS", "INFRAHUB_API_TOKEN", "FYLGJA_SRLINUX_USERNAME", "FYLGJA_SRLINUX_PASSWORD",
             "FYLGJA_EOS_USERNAME", "FYLGJA_EOS_PASSWORD", "FYLGJA_API_TOKEN", "FYLGJA_DEFAULT_SCOPE")
SPECKIT_PATHS = (".claude/skills/speckit-specify", ".claude/skills/speckit-clarify", ".claude/skills/speckit-plan",
                 ".claude/skills/speckit-tasks", ".claude/skills/speckit-analyze", ".claude/skills/speckit-implement",
                 ".claude/skills/speckit-converge", ".specify/scripts/bash/check-prerequisites.sh",
                 ".specify/templates/spec-template.md", ".specify/extensions/git", ".specify/init-options.json")


def run(*args):
    try:
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def section(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: check.py specs/NNN-slug", file=sys.stderr)
        sys.exit(2)
    feature = args[0].rstrip("/")
    name = os.path.basename(feature)
    rows = []

    def check(label, ok, detail=""):
        rows.append((label, ok, detail))

    # The previous feature closed.
    try:
        prev = json.loads((ROOT / ".specify/feature.json").read_text())["feature_directory"]
    except (OSError, ValueError, KeyError):
        prev = None
    if prev and prev != feature and (ROOT / prev / "tasks.md").exists():
        open_tasks = re.findall(r"^\s*- \[ \] (T\d+)\b", (ROOT / prev / "tasks.md").read_text(), re.M)
        check(f"previous feature {prev}: every task ticked", not open_tasks, " ".join(open_tasks))
    else:
        check("previous feature: none to check", True, prev or "no feature.json")
    status = run("git", "status", "--porcelain").strip()
    check("tree clean", not status, status.replace("\n", "; ")[:120])
    pending = ROOT / "local/command-log/pending.jsonl"
    check("command log: nothing pending", not pending.exists() or pending.stat().st_size == 0,
          "run: python3 .claude/hooks/command-log.py flush")
    clab = run("clab", "inspect", "--all", "--format", "json").strip()
    check("no twin (clab inspect --all is {})", clab in ("", "{}") or clab.startswith("{}"), clab[:80])
    check("no local/twin", not (ROOT / "local/twin").exists())
    deleted = []
    for pid in run("pgrep", "-x", "fylgja").split():
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
            if exe.endswith("(deleted)"):
                deleted.append(pid)
        except OSError:
            pass
    check("worker and server binaries not (deleted)", not deleted, " ".join(deleted))

    # Spec Kit.
    try:
        want = json.loads((ROOT / ".specify/init-options.json").read_text()).get("speckit_version")
    except (OSError, ValueError):
        want = None
    have = run("specify", "--version").strip().split()[-1] if run("specify", "--version").strip() else ""
    check(f"Spec Kit {want} installed", bool(want) and have.endswith(str(want)), f"specify --version: {have or 'not found'}")
    missing = [p for p in SPECKIT_PATHS if not (ROOT / p).exists()]
    check("Spec Kit's git-ignored files present", not missing, " ".join(missing))

    # The credentials file, by name alone.
    env_text = (ROOT / "local/.env").read_text() if (ROOT / "local/.env").exists() else ""
    absent = [n for n in ENV_NAMES if not re.search(rf"^\s*(export\s+)?{n}=", env_text, re.M)]
    check("local/.env names every variable", not absent, " ".join(absent))

    # The brief.
    brief_path = ROOT / feature / "brief.md"
    brief = brief_path.read_text() if brief_path.exists() else ""
    check(f"{feature}/brief.md exists", bool(brief))
    const = (ROOT / ".specify/memory/constitution.md").read_text()
    cv = re.search(r"\*\*Version\*\*: (\d+\.\d+\.\d+)", const)
    cur = cv.group(1) if cv else "?"
    named = sorted(set(re.findall(r"Constitution(?: version)? (\d+\.\d+\.\d+)", brief)))
    check(f"brief names the current constitution {cur}", bool(brief) and named == [cur], f"named: {', '.join(named) or 'none'}")
    open_sec = section(brief, "Open, for clarify")
    check("brief's Open, for clarify reads none", open_sec is not None and open_sec.strip().lower().rstrip(".") == "none",
          (open_sec or "section missing").strip().splitlines()[0][:80] if (open_sec or "").strip() else "section missing")
    steps = section(brief, "Operator steps")
    open_steps = re.findall(r"^- \[ \] (.*)$", steps or "", re.M)
    check("brief's Operator steps has no open box", steps is not None and not open_steps,
          "; ".join(s[:40] for s in open_steps) if steps is not None else "section missing")

    # The remote and the branch.
    fetch_head = ROOT / ".git/FETCH_HEAD"
    check("origin fetched", fetch_head.exists(), "run: git fetch origin")
    exists = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{name}"], cwd=ROOT).returncode == 0
    check(f"branch {name} does not exist", not exists)

    width = max(len(r[0]) for r in rows)
    for label, ok, detail in rows:
        print(f"{'ok  ' if ok else 'FAIL'}  {label.ljust(width)}  {detail}".rstrip())
    sys.exit(0 if all(ok for _, ok, _ in rows) else 1)


main()
