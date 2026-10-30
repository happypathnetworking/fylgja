"""The `stages` block's text, as `fylgja stage list` printed it (`internal/server/stages.go`'s
`printList` and `heading`), and the line a resolved stage prints (`findings.StageBlock`'s
`Line` and `Resolution`). Each renders from the block as `contracts/stages.schema.json`
shapes it, so the JSON and the text of one listing cannot disagree. The block itself is
built by the adapter (`adapters/infrahub/stages.py`); this module renders it alone and
imports nothing of the adapter's.
"""

from .findings import quote

AT_GIVEN = "given"
AT_WRITTEN = "written"
AT_BRANCH_POINT = "branch_point"
AT_HEAD = "head"

STATE_DIVERGED = "diverged"


def at_source_text(source: str) -> str:
    """Where an at came from as the text names it: the identifier, but for the branch point,
    which reads as two words (`AtSourceText`)."""
    return "branch point" if source == AT_BRANCH_POINT else source


def resolution(stage: dict) -> str:
    """A resolved stage's block after its reference (`StageBlock.Resolution`): the branch it
    is read on, its at and where the at came from, and a mark's description quoted, `""`
    when none was written; a derived stage prints none."""
    where = stage["branch"] if stage["at_source"] == AT_BRANCH_POINT else "branch " + stage["branch"]
    line = f"{where} at {stage['at']} ({at_source_text(stage['at_source'])})"
    if stage["at_source"] in (AT_GIVEN, AT_WRITTEN):
        line += ", " + quote(stage["description"])
    return line


def line(stage: dict) -> str:
    """The one line printed wherever a reference resolved (`StageBlock.Line`):
    `stage change-1/cabled: branch change-1 at … (written), "after the link is cabled"`."""
    return f"stage {stage['ref']}: {resolution(stage)}"


def plural(n: int, noun: str) -> str:
    """n and noun, with an s unless n is one."""
    return f"1 {noun}" if n == 1 else f"{n} {noun}s"


def heading(proposed_change: dict, n: int, destination: str = "", scope: str = "") -> str:
    """One proposed change as the list and the plan head its stages (`heading`): its name
    quoted, its id, its source branch, the destination when given (the plan's), whether it
    is a draft, how many stages it has, and the scope every stage was read under when given
    (the plan's)."""
    pc = proposed_change
    out = f"proposed change {quote(pc['name'])} ({pc['id']}) on branch {pc['branch']}"
    if destination:
        out += " → " + destination
    if pc.get("draft"):
        out += ", draft"
    out += f" ({plural(n, 'stage')})"
    if scope:
        out += ", scope " + scope
    return out


def _width(text: str) -> int:
    # Go's len, which the widths are taken by, counts bytes; its %-*s pads by runes, which
    # str.ljust does.
    return len(text.encode("utf-8"))


def _at_text(at: str) -> str:
    return at or "unresolved"


def _source(at_source: str) -> str:
    return f"({at_source_text(at_source)})"


def list_lines(block: dict) -> list[str]:
    """The listing's text, one line each (`printList`): a heading per proposed change, then
    one line per stage, its reference, branch, at and source padded so the ats and the
    descriptions line up within the proposed change whatever each at's width, the
    description quoted and the twin's row marked, beside a diverged record with the stage
    its step was going to; a stage with no at shows it unresolved. The orphans follow."""
    rows = block.get("rows") or []
    record = block.get("record")
    twin_mark = "  ← twin"
    if record and record.get("state") == STATE_DIVERGED and record.get("towards"):
        twin_mark = f"  ← twin (diverged towards {record['towards']['ref']})"
    out = []
    if not rows:
        out.append(f"branch {block['branch']}: no open proposed change" if block.get("branch")
                   else "no open proposed change")
    start = 0
    while start < len(rows):
        end = start
        while end < len(rows) and rows[end]["proposed_change"]["id"] == rows[start]["proposed_change"]["id"]:
            end += 1
        group = rows[start:end]
        ref_w = max(_width(r["ref"]) for r in group)
        branch_w = max(_width(r["branch"]) for r in group)
        at_w = max(_width(_at_text(r.get("at", ""))) for r in group)
        source_w = max(_width(_source(r["at_source"])) for r in group)
        out.append(heading(group[0]["proposed_change"], len(group)))
        for r in group:
            mark = twin_mark if r.get("twin") else ""
            out.append(
                f"  {r['ref'].ljust(ref_w)}  {r['branch'].ljust(branch_w)}  at {_at_text(r.get('at', '')).ljust(at_w)} "
                f"{_source(r['at_source']).ljust(source_w)}  {quote(r['description'])}{mark}"
            )
        start = end
    for o in block.get("orphans") or []:
        out.append(f"orphaned: stage {quote(o['label'])} ({o['id']}) names no proposed change")
    return out


def list_text(block: dict) -> str:
    """The listing as stdout carries it, each line ended."""
    return "".join(line + "\n" for line in list_lines(block))
