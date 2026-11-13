"""The report (D-087), rendered from a rehearsal 1 document alone: the verdict as its heading and the cause as its first
sentence, the check's message and the summary's first lines; a table of a row a stage saying what changed in words;
each failure with its message; what the twin does not model and what was already failing, in plain words; a wait
only where it expired, and no loss. The detail holds the twin, the runs, every id and every finding whole. Each part
is within the bytes a source's comment takes, cut at a line and never inside a character. The report is held to
what it says, never byte for byte."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from drafts import (
    CHANGED,
    EARLIER,
    LABELS,
    PUSH,
    ROOM,
    RUN,
    TWIN,
    UNREAD,
    failed_at,
    failed_at_four,
    headed,
    held,
    no_room,
    passed,
    plan,
    rehearsal,
    run,
    stopped,
    unreached,
)

from fylgja_orchestrator.rehearsal import Report, rules
from fylgja_orchestrator.rehearsal.documents import finding
from fylgja_orchestrator.rehearsal.report import headline, render

# Infrahub's comment, the bound the report is written for.
LIMIT = 4092
# The tightest bound the report is held to, measured: the summary's parts kept whatever else goes fit it for each
# document at the limit (1,079 bytes for the labels of 40 é, the most), and the detail of none of them does (1,783
# bytes for those labels, the least).
TIGHT = 1100
FAILED = (
    "The step to stage 4, third-link, failed and left the twin diverged: n2: At line 1: n2 refused the configuration "
    "(push.refused). Stages 2 and 3 passed. Stage 5 was not reached."
)
FIDELITY = "Fidelity is asserted, not measured."
DRAFTS: dict[str, Callable[[], dict[str, Any]]] = {
    "passed": passed,
    "failed at four": failed_at_four,
    "no room": no_room,
    "stopped": stopped,
    "held": held,
}


def lines(text: str) -> list[str]:
    return text.split("\n")


def in_order(found: list[str], expected: list[str]) -> bool:
    """Whether every line of `expected` is among `found`, in that order."""
    remaining = iter(found)
    return all(line in remaining for line in expected)


def test_the_heading_is_the_verdict_and_the_first_sentence_the_cause() -> None:
    assert headline(failed_at_four()) == f"Rehearsal failed at stage 4 of 5: third-link\n{FAILED}"
    assert headline(passed()).splitlines()[0] == "Rehearsal passed: 5 stages"
    assert headline(no_room()).splitlines()[0] == "Not rehearsed: the runtime has no room"
    assert headline(stopped()).splitlines()[0] == "Rehearsal stopped at stage 3 of 5: third-node"
    for made in DRAFTS.values():
        d = made()
        r = render(d, limit=LIMIT)
        assert isinstance(r, Report)
        assert (r.headline, r.status) == (d["headline"], d["status"])
        heading, sentence = d["headline"].split("\n")
        assert lines(r.summary)[:3] == [f"## {heading}", "", sentence]
        assert d["status"] == "passed" or sentence.startswith(d["findings"][0]["message"])
        assert "**" not in sentence and "`" not in sentence

    limited = held() | {"status": "stopped"}
    limited["findings"] = [finding(rules.LIMIT_PASSED, "error", "The rehearsal passed its time limit of 3600 s, and "
                                   "was stopped. Nothing is said about the change: run the checks again, or raise "
                                   "the limit.")]
    assert headline(limited).splitlines()[0] == "Rehearsal stopped"
    # Stopped while its stages were read: stage 2 built, but no stage was in progress on the twin.
    unfinished = plan() | {"status": "unfinished", "headline": "Plan not finished"}
    unfinished["stages"][3:] = [{"label": s["label"], "where": s["where"], "outcome": "not_read"}
                                for s in unfinished["stages"][3:]]
    reading = rehearsal("stopped", unfinished, [{"result": "empty"}, *unreached(4)], limited["findings"])
    assert headline(reading).splitlines()[0] == "Rehearsal stopped"

    long = failed_at(4, labels=[*LABELS[:3], "x" * 70, LABELS[4]])
    assert headline(long).splitlines()[0] == f"Rehearsal failed at stage 4 of 5: {'x' * 59}…"


def test_each_cause_not_rehearsed_gives_its_why_in_the_catalogues_order() -> None:
    causes = [rule for rule, status in rules.STATUS.items() if status == "not_rehearsed"]
    whys = []
    for rule in causes:
        d = held()
        d["findings"] = [finding(rule, "error", "The cause.")]
        whys.append(headline(d).splitlines()[0].removeprefix("Not rehearsed: "))
    assert whys == [
        "no stage to build",
        "the runtime has no room",
        "an image is absent",
        "the runtime refused the twin",
        "the core could not be used",
        "the core refused the request",
        "the source could not be read",
        "an earlier twin is still there",
    ]


def test_a_passed_rehearsals_first_sentence_says_what_was_verified_and_a_twin_left_is_said_on_any_status() -> None:
    assert headline(passed()).splitlines()[1] == "Every stage was built on the twin and verified."

    d = passed()
    d["already_failing"] = [UNREAD]
    assert headline(d).splitlines()[1] == (
        "Every stage was built on the twin, and verify found nothing the baseline did not already have."
    )

    only = "Only stage 2, seeded, builds, so the twin was created and verified there and no step was rehearsed."
    d["findings"].append(finding(rules.STEPS_NONE, "warning", only))
    assert headline(d).splitlines()[1] == only

    left = (f"The twin {TWIN}'s deletion was asked and not waited for: fylgja-core twin show {TWIN} says whether it "
            "is gone.")
    for made in DRAFTS.values():
        d = made()
        before = headline(d)
        d["findings"].append(finding(rules.TWIN_LEFT, "warning", left))
        assert headline(d) == f"{before} {left}"


def test_the_summary_is_the_form_the_maintainer_was_shown() -> None:
    summary = render(failed_at_four(), limit=LIMIT).summary
    assert in_order(lines(summary), [
        "## Rehearsal failed at stage 4 of 5: third-link",
        FAILED,
        "| # | stage | what changed | result | checks |",
        "|---|---|---|---|---|",
        "| 1 | branch-point | | no devices | |",
        "| 2 | seeded | baseline: 2 nodes, 1 link | created | 9 hold |",
        "| 3 | third-node | 1 node added (n3); 1 link added (n1 to n3) | passed | 9 hold |",
        "| 4 | third-link | 1 link added (n2 to n3) | **failed** | not run |",
        "| 5 | head | nothing | not reached | |",
        "**What failed**",
        "- `push.refused` n2: At line 1: n2 refused the configuration",
        "**Not modelled on the twin:** none",
        "**Already failing before this change:** none",
        'Change "third link", scope `tag:fylgja`. The rehearsal read its stages at 2026-11-09T10:15:11Z; one taken '
        "earlier is as it was then, at the time its line in the detail gives; later edits are not rehearsed. Took "
        "1m 15s.",
        FIDELITY,
    ])
    assert lines(summary)[-1] == FIDELITY
    # The empty stage's read keeps its finding, which failed nothing; and no room was read.
    assert "scope.empty" not in summary
    assert "The room" not in summary
    # Ids, the twin and the runs are the detail's.
    assert [held for held in (TWIN, RUN, run(2), plan()["stages"][1]["bundle_id"][:12]) if held in summary] == []

    others = render(passed(), limit=LIMIT).summary
    assert in_order(lines(others), [
        "| 4 | third-link | 1 link added (n2 to n3) | passed | 9 hold |",
        "| 5 | head | nothing | unchanged | not run again |",
    ])
    assert "**What failed**" not in others


def test_a_stage_taken_earlier_gives_its_time_in_the_detail() -> None:
    taken = "2026-11-12T09:00:00.000000Z"
    d = passed()
    d["plan"]["stages"][1]["where"] = f"the mark third-link of branch change-1, read at {taken}"
    r = render(headed(d), limit=LIMIT)
    numbered = [line for line in lines(r.detail) if re.match(r"\d+\. ", line)]
    assert numbered[1].startswith("2. ") and taken in numbered[1]
    where = lines(r.summary)[-2]
    assert "one taken earlier is as it was then" in where and "later edits are not rehearsed" in where


def test_what_failed_is_listed_only_where_the_change_failed() -> None:
    assert "**What failed**" in lines(render(failed_at_four(), limit=LIMIT).summary)
    # Not rehearsed or stopped, nothing of the change failed: the first sentence says the cause, and the detail gives
    # it whole.
    for d in (no_room(), stopped(), held()):
        r = render(d, limit=LIMIT)
        assert "What failed" not in r.summary, d["status"]
        cause = d["findings"][0]
        assert f"- `{cause['rule']}` error: {cause['message']}" in lines(r.detail), d["status"]


def test_what_the_twin_does_not_model_is_said_once_with_its_stages() -> None:
    d = failed_at_four()
    stages = d["plan"]["stages"]
    for stage in stages[2:4]:
        stage["omitted"] = [{"device": "n1", "interface": "ethernet-1/99", "omission": "no_rule"}]
    stages[1]["omitted"] = [
        {"device": "n2", "interface": "ethernet-1/50", "omission": "out_of_range"},
        {"device": "n2", "interface": "mgmt1", "omission": "extra_management"},
        {"device": "n2", "interface": "ethernet-1/1.1", "omission": "shared"},
    ]
    moved = finding("stage.main.moved", "warning", "The main branch moved after the branch point.")
    for stage in stages[1:4]:
        stage["findings"] = [moved]
    stages[4]["findings"] = [finding("link.speed.assumed", "info", "Its speed is assumed.", "n1:ethernet-1/1")]
    summary = render(headed(d), limit=LIMIT).summary
    assert in_order(lines(summary), [
        "**Not modelled on the twin**",
        "- n2 `ethernet-1/50`: the twin's node has no such port, so it is left out (stage 2).",
        "- n2 `mgmt1`: the twin's node has one management port, so it is left out (stage 2).",
        "- n2 `ethernet-1/1.1`: its port on the twin is taken by a cabled interface, so it is left out (stage 2).",
        "- n1 `ethernet-1/99`: the twin's node has no such port, so it is left out (stages 3 and 4).",
        "- The main branch moved after the branch point (stages 2 to 4).",
        "- n1:ethernet-1/1: Its speed is assumed (stage 5).",
        "**Already failing before this change:** none",
    ])
    assert sum("ethernet-1/99" in line for line in lines(summary)) == 1
    assert "**Not modelled on the twin:** none" not in summary


def test_what_was_already_failing_is_listed() -> None:
    d = passed()
    d["already_failing"] = [UNREAD]
    r = render(headed(d), limit=LIMIT)
    assert in_order(lines(r.summary), [
        "Every stage was built on the twin, and verify found nothing the baseline did not already have.",
        "**Not modelled on the twin:** none",
        "**Already failing before this change**",
        "- `verify.node.unread` n1: n1 could not be read over gNMI.",
        FIDELITY,
    ])
    assert "**Already failing before this change:** none" not in r.summary
    assert "- stage 2 `verify.node.unread` error n1: n1 could not be read over gNMI." in lines(r.detail)


def test_the_wait_is_said_only_when_it_expired() -> None:
    for made in DRAFTS.values():
        r = render(made(), limit=LIMIT)
        said = lines(r.summary) + lines(r.detail)
        assert [line for line in said if "did not hold" in line or "expired" in line] == []

    d = failed_at_four()
    d["stages"][1]["wait"] = {"budget_s": 180, "after_s": 180.4}
    summary = lines(render(headed(d), limit=LIMIT).summary)
    assert in_order(summary, [
        "**Already failing before this change:** none",
        "Verify did not hold within 180 s at stage 2.",
        FIDELITY,
    ])
    assert sum("did not hold" in line for line in summary) == 1


def test_loss_is_never_reported() -> None:
    d = failed_at_four()
    d["stages"][1]["wait"] = {"budget_s": 180, "after_s": 180.4}
    for doc in [made() for made in DRAFTS.values()] + [headed(d)]:
        r = render(doc, limit=LIMIT)
        assert [line for line in lines(r.summary) + lines(r.detail) if "loss" in line.lower()] == []


def test_not_rehearsed_shows_the_room() -> None:
    r = render(no_room(), limit=LIMIT)
    assert in_order(lines(r.summary), [
        "## Not rehearsed: the runtime has no room",
        "| 2 | seeded | baseline: 2 nodes, 1 link | not reached | |",
        "**The room when it was refused**",
        *(f"- {line}" for line in ROOM),
        "**Not modelled on the twin:** none",
    ])

    # A refusal for room whose capacity read itself failed has no room to show.
    d = no_room()
    del d["room"]
    assert "The room" not in render(headed(d), limit=LIMIT).summary


def test_the_detail_holds_the_ids_the_twin_the_run_and_every_finding_whole() -> None:
    d = failed_at_four()
    detail = lines(render(d, limit=LIMIT).detail)
    assert detail[0] == f"**Rehearsal detail**: twin `{TWIN}`, run `{RUN}`, change `pc-1`."
    numbered = [line for line in detail if re.match(r"\d+\. ", line)]
    assert len(numbered) == 5
    for k, (line, planned, ran) in enumerate(zip(numbered, d["plan"]["stages"], d["stages"], strict=True), 1):
        assert line.startswith(f"{k}. {planned['label']}: {planned['where']}")
        for key, name in (("blueprint_id", "blueprint"), ("bundle_id", "bundle")):
            assert (f"{name} `" in line) == (key in planned)
            assert key not in planned or f"{name} `{planned[key][:12]}`" in line
        assert ("run `" in line) == ("run_id" in ran) and ran.get("run_id", "") in line
    assert "1m 15s" not in "\n".join(numbered) and "41s" in numbered[1] and "13s" in numbered[3]
    assert in_order(detail, [
        "**Every finding**",
        f"- `rehearsal.stage.failed` error: {d['findings'][0]['message']}",
        "- stage 1 `scope.empty` error tag:fylgja: The scope selects no device.",
        "- stage 4 `push.refused` error n2: At line 1: n2 refused the configuration",
        "**Approximations**",
        "- `nokia_srlinux`: No linecard model",
    ])
    assert detail.count("- `nokia_srlinux`: No linecard model") == 1
    assert "**Notes**" not in detail and not [line for line in detail if line.startswith("Reclaimed")]

    whole = failed_at(4, failure=PUSH | {"message": "x" * 5000})
    assert f"- stage 4 `push.refused` error n2: {'x' * 5000}" in lines(render(whole, limit=None).detail)

    notes = lines(render(passed(), limit=LIMIT).detail)
    assert in_order(notes, ["**Notes**", f"- {passed()['findings'][0]['message']}"])


def test_the_detail_gives_the_wait_the_checks_skipped_and_the_twins_reclaimed() -> None:
    d = passed()
    d["stages"][1]["counts"] = {"held": 9, "failed": 1, "skipped": 2}
    d["stages"][1]["wait"] = {"budget_s": 180, "after_s": 180.4}
    detail = lines(render(headed(d), limit=LIMIT).detail)
    assert detail[1] == f"Reclaimed: `{EARLIER}`."
    numbered = [line for line in detail if re.match(r"\d+\. ", line)]
    assert numbered[1].endswith("; 9 hold, 1 fail, 2 skipped; verify's wait expired after 180.4 s of 180")
    assert numbered[2].endswith("; 9 hold")
    assert "Reclaimed" not in render(failed_at_four(), limit=LIMIT).detail


def test_a_rehearsal_that_ended_before_its_plan_says_the_stages_were_not_read() -> None:
    d = held()
    r = render(d, limit=LIMIT)
    summary = lines(r.summary)
    assert summary[0] == "## Not rehearsed: an earlier twin is still there"
    assert summary[-2:] == ["The stages were not read. Took 2m 0s.", FIDELITY]
    assert [line for line in summary if line.startswith("|")] == []
    assert in_order(summary, [
        "**Not modelled on the twin:** none",
        "**Already failing before this change:** none",
    ])

    detail = lines(r.detail)
    assert detail[0] == f"**Rehearsal detail**: twin `{TWIN}`, run `{RUN}`."
    assert [line for line in detail if line in ("**Stages**", "**Approximations**", "**Not modelled on the twin**")
            or re.match(r"(\d+\. |- stage )", line)] == []
    assert f"- `rehearsal.twin.held` error: {d['findings'][0]['message']}" in detail


def test_a_stage_the_plan_refused_is_the_stage_that_failed() -> None:
    planned = plan()
    stale = finding("artifact.stale", "error", "n1's configuration is older than its intent.", "n1")
    refused = planned["stages"][2]
    planned["stages"][2] = {"label": refused["label"], "where": refused["where"], "outcome": "refused",
                            "findings": [stale]}
    planned["stages"][3:] = [{"label": s["label"], "where": s["where"], "outcome": "not_read"}
                             for s in planned["stages"][3:]]
    sentence = ("Stage 3, third-node, could not be built: n1: n1's configuration is older than its intent "
                "(artifact.stale). Nothing was rehearsed.")
    cause = finding(rules.STAGE_REFUSED, "error", sentence, "third-node")
    planned |= {"status": "refused", "headline": f"Plan refused at stage 3 of 5: third-node\n{sentence}",
                "findings": [cause]}
    d = rehearsal("failed", planned, [{"result": "empty"}, *unreached(4)], [cause])
    assert d["headline"] == f"Rehearsal failed at stage 3 of 5: third-node\n{sentence}"
    assert in_order(lines(render(d, limit=LIMIT).summary), [
        "| 2 | seeded | baseline: 2 nodes, 1 link | not reached | |",
        "| 3 | third-node | | **failed** | not run |",
        "| 4 | third-link | | not reached | |",
        "**What failed**",
        "- `artifact.stale` n1: n1's configuration is older than its intent.",
        f"- `stage.refused` third-node: {sentence}",
    ])


def test_how_long_it_took_is_said_in_seconds_minutes_or_hours() -> None:
    for took, said in ((44.6, "45s"), (75.2, "1m 15s"), (60.0, "1m 0s"), (3725.0, "1h 2m")):
        d = passed()
        d["took_s"] = took
        assert lines(render(d, limit=LIMIT).summary)[-2].endswith(f" Took {said}.")


def sixty() -> dict[str, Any]:
    """A change of sixty stages that failed at the thirtieth, each built stage leaving an interface of its own out."""
    labels = ["branch-point", *(f"step-{k}" for k in range(2, 61))]
    d = failed_at(30, labels, [*CHANGED[:2], *("1 link added (n2 to n3)" for _ in range(3, 61))])
    for k, stage in enumerate(d["plan"]["stages"][1:], 2):
        stage["omitted"] = [{"device": "n1", "interface": f"ethernet-1/{k}", "omission": "out_of_range"}]
    return headed(d)


def five_thousand() -> dict[str, Any]:
    """The change the maintainer was shown, its failure's message 5,000 bytes."""
    return failed_at(4, failure=PUSH | {"message": "x" * 5000})


def accented() -> dict[str, Any]:
    """The change the maintainer was shown, every label 40 `é`, each two bytes."""
    return failed_at(4, labels=["é" * 40] * 5)


AT_THE_LIMIT: dict[str, tuple[Callable[[], dict[str, Any]], int]] = {
    "sixty stages": (sixty, 30),
    "a 5,000-byte message": (five_thousand, 4),
    "labels of 40 é": (accented, 4),
}
CUT = re.compile(r"… cut here: \d+ more lines did not fit\.")
MORE = re.compile(r"- and \d+ more(, in the detail)?")
GAP = re.compile(r"\| … \| \d+ more stages? \| \| \| \|")


def ended(summary: list[str], title: str) -> str | None:
    """The line that ends the list `title` of a summary, where the list was cut; None where it was not, or is not
    there."""
    if f"**{title}**" not in summary:
        return None
    at = summary.index(f"**{title}**") + 1
    while at < len(summary) and summary[at].startswith("- "):
        at += 1
    return summary[at - 1] if MORE.fullmatch(summary[at - 1]) else None


def listed(d: dict[str, Any], k: int) -> dict[str, list[tuple[str, str]]]:
    """Each line of the lists the summary of `d`, failed at stage `k`, may cut, with the detail's line that holds it
    whole."""
    failure, cause = d["stages"][k - 1]["failures"][0], d["findings"][0]
    omitted = [(j, o) for j, stage in enumerate(d["plan"]["stages"], 1) for o in stage.get("omitted", [])]
    return {
        "What failed": [
            (f"- `{failure['rule']}` {failure['object']}: {failure['message']}",
             f"- stage {k} `{failure['rule']}` error {failure['object']}: {failure['message']}"),
            (f"- `{cause['rule']}`: {cause['message']}", f"- `{cause['rule']}` error: {cause['message']}"),
        ],
        "Not modelled on the twin": [
            (f"- {o['device']} `{o['interface']}`: the twin's node has no such port, so it is left out (stage {j}).",
             f"- stage {j} {o['device']} `{o['interface']}`: `{o['omission']}`")
            for j, o in omitted
        ],
    }


@pytest.mark.parametrize("made", AT_THE_LIMIT)
def test_each_part_is_within_the_limit(made: str) -> None:
    make, k = AT_THE_LIMIT[made]
    d = make()
    whole = render(d, limit=None)
    assert not CUT.search(whole.detail) and not MORE.search(whole.summary) and not GAP.search(whole.summary)

    heading, sentence = d["headline"].split("\n")
    for limit in (LIMIT, TIGHT):
        r = render(d, limit=limit)
        for part in (r.summary, r.detail):
            assert len(part.encode()) <= limit
        summary, detail = lines(r.summary), lines(r.detail)
        assert summary[:3] == [f"## {heading}", "", sentence]
        assert [line for line in summary if line.startswith(f"| {k} |") and "**failed**" in line]
        assert summary[-1] == FIDELITY
        if r.detail != whole.detail:
            assert CUT.fullmatch(detail[-1])
        # A cut list points to the detail exactly where every line it left out is there whole.
        for title, items in listed(d, k).items():
            cut = ended(summary, title)
            dropped = [held for line, held in items if line not in summary]
            if cut is None:
                assert dropped == [] or f"**{title}**" not in summary, title
                continue
            assert cut.startswith(f"- and {len(dropped)} more"), title
            assert cut.endswith(", in the detail") == all(held in detail for held in dropped), title
    assert CUT.fullmatch(lines(render(d, limit=TIGHT).detail)[-1])

    at_limit = render(d, limit=LIMIT)
    summary = lines(at_limit.summary)
    if made == "labels of 40 é":
        assert at_limit == whole
    else:
        assert len(whole.detail.encode()) > LIMIT and CUT.fullmatch(lines(at_limit.detail)[-1])
    if made == "sixty stages":
        # The detail gives what the summary points to before the stages, so at the limit it holds both lists whole.
        assert ended(summary, "What failed") == "- and 2 more, in the detail"
        assert ended(summary, "Not modelled on the twin") == "- and 59 more, in the detail"
        tight = lines(render(d, limit=TIGHT).summary)
        assert len([line for line in tight if GAP.fullmatch(line)]) == 2
        assert len([line for line in tight if line.startswith(("| 1 |", "| 60 |"))]) == 2
    if made == "a 5,000-byte message":
        # The failure's 5,000 bytes fit no comment, so the detail does not hold it, and the summary does not say so.
        assert ended(summary, "What failed") == "- and 2 more"


def test_a_list_cut_from_the_summary_points_to_the_detail_where_the_detail_is_whole() -> None:
    d = failed_at_four()
    d["plan"]["stages"][1]["omitted"] = [
        {"device": "n1", "interface": f"ethernet-1/{j}", "omission": "no_rule"} for j in range(1, 46)
    ]
    r = render(headed(d), limit=LIMIT)
    assert r.detail == render(d, limit=None).detail
    summary = lines(r.summary)
    left = [j for j in range(1, 46) if not any(f"`ethernet-1/{j}`:" in line for line in summary)]
    assert left and ended(summary, "Not modelled on the twin") == f"- and {len(left)} more, in the detail"


def test_the_detail_gives_first_what_the_summary_points_to_and_the_stages_last() -> None:
    d = no_room()
    d["plan"]["stages"][1]["omitted"] = [{"device": "n1", "interface": "ethernet-1/99", "omission": "no_rule"}]
    d["findings"].append(finding(rules.TWIN_LEFT, "warning", f"The twin {TWIN} may still be there: remove it with "
                                 f"fylgja-core twin destroy {TWIN} once the core answers."))
    detail = lines(render(headed(d), limit=LIMIT).detail)
    assert [line for line in detail if line.startswith("**") and line.endswith("**")] == [
        "**Every finding**",
        "**Not modelled on the twin**",
        "**The room when it was refused**",
        "**Approximations**",
        "**Notes**",
        "**Stages**",
    ]
    assert detail[0].startswith("**Rehearsal detail**: ")


def test_the_first_sentence_is_cut_to_what_fits_beside_what_is_always_kept() -> None:
    d = accented()
    sentence = d["headline"].splitlines()[1]
    # Below what the summary always keeps, the sentence alone is cut: what it keeps beside the sentence is read from
    # one such summary.
    first = lines(render(d, limit=TIGHT - 120).summary)
    assert first[2].endswith("…") and sentence.startswith(first[2][:-1])
    assert [line for line in first if line.startswith("**")] == []
    beside = len("\n".join(first).encode()) - len(first[2].encode())

    # A limit whose byte cut lands inside the eleventh `é` of the label, two bytes each: the ten before it are kept.
    before = sentence.index("é")
    limit = beside + len(sentence[:before].encode()) + 2 * 10 + 1 + len("…".encode())
    r = render(d, limit=limit)
    summary = lines(r.summary)
    assert len(r.summary.encode()) <= limit
    assert summary[2] == sentence[: before + 10] + "…"
    assert sentence.startswith(summary[2][:-1])
    assert summary[0] == first[0] and summary[-2:] == first[-2:]
