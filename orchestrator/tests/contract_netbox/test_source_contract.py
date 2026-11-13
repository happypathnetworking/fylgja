"""The NetBox change source against the running development NetBox, through a core of the module's own on its fake
runtime (`harness.serving`), never a recording (D-034, D-096, D-097).

A change is a ready branch found by its name; a branch asked before it is ready, and one merged, is refused by its
status. Each of the seeded change's two steps is written on a branch of the test's own by the superuser and then
marked by the source, the example's account writing the mark's journal entry; the marks are read back through the
core, and every stage through the reader or the core to one state, one id. A mark read under another scope, through
another core, or written malformed by hand, is refused by its name. `main` edited after the branch was made is said at
the first stage, by a count held to one worked out here from the changelog's rows, and the marks, a claim and the
trigger's own webhook and event rule count for nothing. The tag is taken off and the others left; a report is one
journal entry whose kind is its status, its text the library's with an empty line before each list, which NetBox's
page then renders as a list; and the example's account may write nothing else.
"""

from __future__ import annotations

import base64
import contextlib
import html
import os
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import drafts
import pytest
from fylgja_core.blueprint import blueprint_id
from fylgja_core.findings import Finding
from fylgja_netbox import ReaderDocument
from harness import ALICE, Served, serving

from fylgja_orchestrator.edge import cli
from fylgja_orchestrator.netbox import (
    HEAD,
    MAIN,
    MARK_PREFIX,
    TAG,
    NetBoxSource,
    NoChange,
    SourceError,
    Unready,
    mark_text,
    marks_of,
    spaced,
)
from fylgja_orchestrator.netbox.source import UNCOUNTED
from fylgja_orchestrator.rehearsal import Change, Report, render

from .conftest import (
    ADDRESS,
    BRANCH_WAIT_S,
    BRANCHES,
    CA,
    CHANGE,
    CHANGES,
    ENTRIES,
    EXAMPLE_TOKEN,
    HOOK,
    PASSWORD,
    POLL_S,
    PREFIX,
    READER_DOCUMENT,
    READER_TOKEN,
    SCOPE,
    TAGS,
    BoxError,
    Secret,
    Writes,
    ca,
    delete,
    edge_port_free,
    entries,
    hide,
    on_main,
    refuse,
    scratch_name,
    secret,
    set_tags,
    settled,
    signed_in,
    tags_of,
    writer,
)

WEBHOOKS = "extras/webhooks/"
RULES = "extras/event-rules/"
TYPES = "core/object-types/"
NOWHERE = "http://" + "192.0.2.1" + "/"
"""Where a scratch webhook would send, an address of the documentation range: its rule is never enabled."""

BIG = 100_000
"""The bytes of the detail a report is posted with, read back whole: NetBox kept an entry whole at a megabyte
(D-097)."""


def kind_of(entry: Mapping[str, Any]) -> str:
    """A journal entry's kind, which NetBox answers as a row of its value and its label."""
    kind = entry["kind"]
    return str(kind["value"] if isinstance(kind, dict) else kind)


def errors(findings: Sequence[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "error"]


def gained(findings: Sequence[Finding]) -> list[Finding]:
    return [f for f in findings if f.rule == "stage.main.gained"]


def counted(box: Writes, since: str) -> int:
    """The rows of `main`'s changelog of the time `since` or later, of any kind but those of `UNCOUNTED`, worked out
    here from the rows: listed by `time_after`, each row's time and kind then judged in code, so that a filter NetBox
    ignored, which answers the whole list, is no count of the source's."""
    floor = datetime.fromisoformat(since)
    rows = box.listed(CHANGES, time_after=since)
    return sum(1 for row in rows
               if datetime.fromisoformat(row["time"]) >= floor and row["changed_object_type"] not in UNCOUNTED)


def test_the_change_is_a_ready_branch_found_by_its_name(
    source: NetBoxSource, branch: dict[str, Any], box: Writes
) -> None:
    """A branch asked at once after its `POST` was read `new` and `provisioning` and the example's writes taken
    (design/verified-facts.md, "A branch is listed by its name at once"); a branch with no change does not merge, so
    the merged leg makes a tag on its branch first, which the merge takes to `main` and the test removes there."""
    name = branch["name"]
    assert source.change(name) == Change(name, branch["schema_id"], name, f"branch {name}")
    with pytest.raises(NoChange) as none:
        source.change(f"{PREFIX}none")
    assert str(none.value) == f"no branch is named {PREFIX}none"

    unwaited = scratch_name()
    try:
        box.post(BRANCHES, {"name": unwaited})
        try:
            source.change(unwaited)
        except Unready as e:
            said = str(e)
            assert re.fullmatch(rf"branch {unwaited} is (new|provisioning), and only a ready branch is rehearsed",
                                said), said
            print(f"a branch asked at once after its POST: {said}")
        else:
            print("the leg of a branch asked before it is ready was skipped: it read ready at once")
    finally:
        delete(box, unwaited)

    slug = scratch_name()
    try:
        box.post(TAGS, {"name": slug, "slug": slug}, branch=branch["schema_id"])
        box.post(f"{BRANCHES}{branch['id']}/merge/", {"commit": True})
        # Waited for by `BRANCH_WAIT_S`, 120 s: a merge read `merged` 1.44 s after its request
        # (design/verified-facts.md, "A merged branch is listed"), 83.3 times that, a derivation.
        merged = settled(box, branch, leave=("ready", "merging"))
        assert merged is not None and merged["status"]["value"] == "merged"
        with pytest.raises(Unready) as raised:
            source.change(name)
        assert str(raised.value) == f"branch {name} is merged, and only a ready branch is rehearsed"
    finally:
        left = box.one(TAGS, slug=slug)
        if left is not None:
            box.delete(f"{TAGS}{left['id']}/")
        assert box.one(TAGS, slug=slug) is None


def test_a_change_is_marked_at_each_step_and_read_back(
    source: NetBoxSource, branch: dict[str, Any], box: Writes, core: Served, example_user: int
) -> None:
    change = source.change(branch["name"])
    marked = []
    for label, _, _ in CHANGE.STEPS:
        CHANGE.step(box, branch["schema_id"], label)
        marked.append(source.mark(change, label, SCOPE))
    ids = [m.blueprint_id for m in marked]
    assert all(isinstance(held, str) and re.fullmatch(r"[0-9a-f]{64}", held) for held in ids), ids
    assert [errors(m.findings) for m in marked] == [[], []]
    kept = [core.client.get_blueprint(str(held)) for held in ids]
    assert [blueprint_id(held) for held in kept] == ids

    written = entries(box, branch)
    assert [(kind_of(entry), entry["created_by"]) for entry in written] == [("info", example_user)] * 2
    for entry, mark, held in zip(written, marked, kept, strict=True):
        assert entry["comments"] == mark_text(mark.label, str(mark.blueprint_id), SCOPE,
                                              held["source"]["observed_at"])

    stages = source.stages(change)
    assert [stage.label for stage in stages] == ["main", "third-link", "n1-address", "head"]
    reads = [source.read(stage, SCOPE) for stage in stages]
    assert [errors(read.findings) for read in reads] == [[]] * 4
    assert all(read.blueprint is not None for read in reads)
    main, first, second, head = (blueprint_id(dict(read.blueprint or {})) for read in reads)
    assert main != ids[0]
    assert (first, second) == (ids[0], ids[1])
    assert head == ids[1], "the head, nothing written since the second mark, is the second mark's state"

    with pytest.raises(SourceError) as again:
        source.mark(change, "third-link", SCOPE)
    assert str(again.value) == (f"branch {change.ref} already has a mark labelled third-link: a label is unique "
                                "within its branch")
    assert len(entries(box, branch)) == 2


def test_stage_mark_takes_a_mark_the_source_reads_back_and_refuses_its_label_again(
    source: NetBoxSource,
    branch: dict[str, Any],
    box: Writes,
    core: Served,
    example_token: Secret,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`stage mark`, the example's command, under the environment the runner is given for the source `netbox`
    (`scripts/edge_dev.py`'s `source_env`): the module's core, NetBox's address, the example's token, the reader
    document and the scope. Its mark is a stage the source reads back to the blueprint the command printed; the same
    label again is exit 2 in the source's sentence, nothing written."""
    environ = {
        "FYLGJA_ORCHESTRATOR_SOURCE": "netbox",
        "FYLGJA_API_ADDRESS": core.address,
        "FYLGJA_API_TOKEN": ALICE,
        ADDRESS: os.environ[ADDRESS],
        "FYLGJA_NETBOX_TOKEN": example_token.value,
        "FYLGJA_ORCHESTRATOR_SCOPE": SCOPE,
        "FYLGJA_ORCHESTRATOR_READER": str(READER_DOCUMENT),
        "FYLGJA_ORCHESTRATOR_ROOT": str(tmp_path),
    }
    if os.environ.get(CA):
        environ[CA] = os.environ[CA]
    CHANGE.step(box, branch["schema_id"], "third-link")
    argv = ["stage", "mark", "--branch", branch["name"], "--label", "third-link"]
    assert cli.main(argv, environ=environ) == 0
    out, _ = capsys.readouterr()
    said = re.fullmatch(rf"{branch['name']} third-link: blueprint ([0-9a-f]{{64}})\n", out)
    assert said is not None, out
    change = source.change(branch["name"])
    stage = next(stage for stage in source.stages(change) if stage.label == "third-link")
    read = source.read(stage, SCOPE)
    assert read.blueprint is not None and blueprint_id(read.blueprint) == said[1]
    [entry] = entries(box, branch)
    assert marks_of([entry])[0].blueprint_id == said[1]

    assert cli.main(argv, environ=environ) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert (f"branch {branch['name']} already has a mark labelled third-link: a label is unique within its "
            "branch") in err
    assert len(entries(box, branch)) == 1


def test_a_mark_under_another_scope_or_through_another_core_is_refused_by_name(
    source: NetBoxSource,
    branch: dict[str, Any],
    box: Writes,
    document: ReaderDocument,
    example_token: Secret,
    tmp_path: Path,
) -> None:
    """Each provoked on the real NetBox as an operator would meet it: a scope that differs, a core that was never
    given the mark, and a mark's entry written malformed by a person, here the superuser. The labels `main` and `head`
    are refused by `mark` with nothing written."""
    change = source.change(branch["name"])
    CHANGE.step(box, branch["schema_id"], "third-link")
    assert source.mark(change, "third-link", SCOPE).blueprint_id is not None
    stage = next(stage for stage in source.stages(change) if stage.label == "third-link")
    [entry] = entries(box, branch)

    other = source.read(stage, "tag:none")
    assert other.blueprint is None
    assert [(f.rule, f.severity, f.object) for f in other.findings] == [("mark.scope", "error", "third-link")]
    assert f"journal entry {entry['id']}, was read under scope {SCOPE}" in other.findings[0].message

    with serving(tmp_path / "other") as elsewhere:
        through = NetBoxSource(os.environ[ADDRESS], example_token.value, document, elsewhere.client, ca=ca())
        try:
            unheld = through.read(next(s for s in through.stages(change) if s.label == "third-link"), SCOPE)
        finally:
            through.close()
    assert unheld.blueprint is None
    assert [(f.rule, f.severity, f.object) for f in unheld.findings] == [("mark.unheld", "error", "third-link")]
    assert unheld.findings[0].message.startswith("The core holds no blueprint ")

    by_hand = box.post(ENTRIES, {
        "assigned_object_type": "netbox_branching.branch",
        "assigned_object_id": branch["id"],
        "kind": "info",
        "comments": f"{MARK_PREFIX}by-hand\n\n- blueprint: not-an-id\n- scope: {SCOPE}\n- read: earlier",
    })
    malformed = next(stage for stage in source.stages(change) if stage.label == "by-hand")
    refused = source.read(malformed, SCOPE)
    assert refused.blueprint is None
    assert [(f.rule, f.object) for f in refused.findings] == [("mark.malformed", "by-hand")]
    assert f"journal entry {by_hand['id']}, is not read" in refused.findings[0].message

    for label in (MAIN, HEAD):
        with pytest.raises(SourceError):
            source.mark(change, label, SCOPE)
    assert len(entries(box, branch)) == 2


def synced(box: Writes, branch: Mapping[str, Any]) -> str:
    """The branch synchronised with `main` by the superuser, as `make netbox-seed` can never do for the example, which
    is refused it (design/verified-facts.md, "The example's token was refused a branch's `sync`"): its `last_sync` once
    it has moved and the branch reads `ready`, read by its name every `POLL_S`, `BRANCH_WAIT_S` at most. A sync read
    `ready` again 1.47 s after its request."""
    before = box.get(f"{BRANCHES}{branch['id']}/")["last_sync"]
    box.post(f"{BRANCHES}{branch['id']}/sync/", {"commit": True})
    began = time.monotonic()
    while True:
        held = box.get(f"{BRANCHES}{branch['id']}/")
        if held["status"]["value"] == "ready" and held["last_sync"] != before:
            return str(held["last_sync"])
        assert time.monotonic() - began < BRANCH_WAIT_S, f"the sync of {branch['name']} did not end"
        time.sleep(POLL_S)


def test_a_branch_behind_main_is_said_at_the_first_stage(
    source: NetBoxSource, branch: dict[str, Any], box: Writes
) -> None:
    """The count `stage.main.gained` gives is held to the rows of `main`'s changelog judged here (`counted`). The
    marks are journal entries, the claim a write of the branch's own, and the scratch webhook and its disabled event
    rule the trigger's kinds: none is a change of `main` (`UNCOUNTED`), and the tag made on `main` is one."""
    edge_port_free()
    change = source.change(branch["name"])
    first = source.stages(change)[0]
    read = source.read(first, SCOPE)
    assert read.blueprint is not None and gained(read.findings) == []

    source.mark(change, "one", SCOPE)
    source.mark(change, "two", SCOPE)
    set_tags(box, branch, TAG)
    source.claim(change)
    assert tags_of(box, branch) == []
    since = box.get(f"{BRANCHES}{branch['id']}/")["last_sync"]
    hook = {"name": scratch_name(), "payload_url": NOWHERE, "http_method": "POST",
            "http_content_type": "application/json"}
    with on_main(box, WEBHOOKS, hook) as webhook:
        rule = {"name": scratch_name(), "object_types": ["netbox_branching.branch"], "event_types": ["object_updated"],
                "enabled": False, "action_type": "webhook", "action_object_type": "extras.webhook",
                "action_object_id": webhook["id"]}
        with on_main(box, RULES, rule):
            read = source.read(source.stages(change)[0], SCOPE)
            assert read.blueprint is not None and gained(read.findings) == []
            assert counted(box, since) == 0

            slug = scratch_name()
            with on_main(box, TAGS, {"name": slug, "slug": slug}):
                read = source.read(source.stages(change)[0], SCOPE)
                n = counted(box, since)
                print(f"main's changelog counted {n} change of main since {since}, judged here")
                assert read.blueprint is not None
                [said] = gained(read.findings)
                assert (said.severity, said.object) == ("warning", branch["name"])
                assert said.message.startswith(
                    f"main has gained {n} change{'' if n == 1 else 's'} since branch {branch['name']} was made or "
                    f"last synchronised, at {since}"
                )
                assert n >= 1

                moved = synced(box, branch)
                read = source.read(source.stages(change)[0], SCOPE)
                assert read.blueprint is not None and gained(read.findings) == []
                assert counted(box, moved) == 0


def test_claim_takes_the_tag_off_and_leaves_the_others(
    source: NetBoxSource, branch: dict[str, Any], box: Writes
) -> None:
    edge_port_free()
    slug = scratch_name()
    with on_main(box, TAGS, {"name": slug, "slug": slug}):
        set_tags(box, branch, TAG, slug)
        assert sorted(tags_of(box, branch)) == sorted([TAG, slug])
        change = source.change(branch["name"])
        source.claim(change)
        assert tags_of(box, branch) == [slug]
        updated = box.get(f"{BRANCHES}{branch['id']}/")["last_updated"]
        source.claim(change)
        assert box.get(f"{BRANCHES}{branch['id']}/")["last_updated"] == updated
        set_tags(box, branch)


def only_empty_lines_added(original: str, filed: str) -> bool:
    """Whether `filed` is `original` with empty lines put in and nothing else changed."""
    lines = iter(filed.split("\n"))
    for line in original.split("\n"):
        for held in lines:
            if held == line:
                break
            if held != "":
                return False
        else:
            return False
    return all(held == "" for held in lines)


ITEM = re.compile(r"^(?:[-*+]|[0-9]+\.) ")
"""What begins an item of a Markdown list, as the library writes one."""


def words(text: str) -> str:
    """Text as a reader sees it, in Markdown or in HTML: its tags, its code's backticks and its bold's stars gone,
    entities read and spaces made one."""
    plain = html.unescape(re.sub(r"<[^>]+>", "", text)).replace("`", "").replace("**", "")
    return " ".join(plain.split())


def test_a_report_is_one_journal_entry_whose_kind_is_its_status(
    source: NetBoxSource, branch: dict[str, Any], box: Writes, example_user: int
) -> None:
    """Each status's report, the library's for a document of each, and one of a detail of `BIG` bytes; and, signed in
    as the superuser, the branch's `journal` page rendering each report's table as a table and each item of its lists
    as an item of a list (design/verified-facts.md, "NetBox renders it as Markdown, but its lists"): the item's words
    as the text of a `<li>`, its code and its bold as NetBox renders them."""
    change = source.change(branch["name"])
    stages = [stage.label for stage in source.stages(change)]
    reports = [render(document, limit=None)
               for document in (drafts.passed(), drafts.failed_at_four(), drafts.no_room(), drafts.stopped())]
    line = "This line is one of many in a detail of a hundred thousand bytes, and holds no list.\n"
    # Ended by a full stop: NetBox keeps an entry with the whitespace at its end stripped.
    big = Report("passed", "Rehearsal passed\nall of it", "## Rehearsal passed: 2 stages",
                 (line * (BIG // len(line) + 1))[: BIG - 1] + ".")
    for report in (*reports, big):
        source.post(change, report)

    written = entries(box, branch)
    assert [kind_of(entry) for entry in written] == ["success", "danger", "warning", "warning", "success"]
    assert [entry["created_by"] for entry in written] == [example_user] * 5
    for entry, report in zip(written, (*reports, big), strict=True):
        original = f"{report.summary}\n\n{report.detail}"
        assert entry["comments"] == spaced(original)
        assert only_empty_lines_added(original, entry["comments"])
    assert len(written[-1]["comments"].encode()) >= BIG
    assert [stage.label for stage in source.stages(change)] == stages == ["main", "head"]

    if not os.environ.get(PASSWORD):
        print(f"the leg of the rendered page was skipped: {PASSWORD} is not set")
        return
    with signed_in(os.environ[ADDRESS], secret(PASSWORD)) as pages:
        page = pages.get(f"/plugins/branching/branches/{branch['id']}/journal/")
    assert page.status_code == 200
    listed = {words(held) for held in re.findall(r"<li>(.*?)</li>", page.text, re.DOTALL)}
    items = [words(ITEM.sub("", line)) for entry in written for line in entry["comments"].split("\n")
             if ITEM.match(line)]
    shown = [item for item in items if item in listed]
    print(f"the branch's journal page: {len(shown)} of the entries' {len(items)} list items each the text of a "
          f"<li>; {page.text.count('<table')} tables")
    assert items != [] and shown == items
    assert "<table" in page.text


def test_the_examples_account_writes_nothing_else(
    source: NetBoxSource, branch: dict[str, Any], box: Writes, example_token: Secret
) -> None:
    change = source.change(branch["name"])
    assert source.mark(change, "only", SCOPE).blueprint_id is not None
    [entry] = entries(box, branch)
    site = scratch_name()
    example = writer(os.environ[ADDRESS], example_token.value)
    try:
        with pytest.raises(BoxError) as made:
            example.post("dcim/sites/", {"name": site, "slug": site})
        with pytest.raises(BoxError) as removed:
            example.delete(f"{ENTRIES}{entry['id']}/")
    finally:
        example.close()
        left = box.one("dcim/sites/", slug=site)
        if left is not None:
            box.delete(f"dcim/sites/{left['id']}/")
    assert (getattr(made.value, "status", None), getattr(removed.value, "status", None)) == (403, 403)
    assert [held["id"] for held in entries(box, branch)] == [entry["id"]]
    assert marks_of(entries(box, branch))[0].label == "only"


def test_a_lesser_account_reads_the_webhooks_headers_in_the_changelog(box: Writes, example_token: Secret) -> None:
    """The example accepts, as a known limit, that an account with `view` on NetBox's changelog reads the installed
    webhook's headers, and so Prefect's basic auth, in `main`'s changelog (docs/integrating.md, "Credentials";
    design/verified-facts.md, "A webhook's rows of `main`'s changelog hold its headers, to either lesser account"). A
    test holds that exposure so that what the documents say of it stays true: a NetBox that masks the header, or a
    grant that hides the rows, fails it, and the documents are corrected. With the reader's token and with the
    example's, the installed webhook's rows are those the superuser reads, and the last holds `additional_headers` as
    the webhook holds it, unmasked. It writes nothing: it reads the webhook, and its rows of `main`'s changelog with
    each token; the header is compared in memory, no message holds it or a part of it, and it, its base64 and the auth
    are hidden from every report besides. Run alone, it needs rows of the webhook that NetBox's changelog retention
    has kept, which `make netbox-hook` writes when it changes the webhook, as the hook's tests here do; a run that
    finds none skips, saying so."""
    reader_token = secret(READER_TOKEN)
    webhook = box.one(WEBHOOKS, name=HOOK.NAME)
    if webhook is None:
        refuse(f"no webhook {HOOK.NAME} is installed: run make netbox-hook, with the development Prefect up")
    header = str(webhook.get("additional_headers") or "")
    encoded = header.removeprefix(HOOK.BASIC)
    hide(Secret("the installed webhook's header", header))
    hide(Secret("the installed webhook's header's base64", encoded))
    with contextlib.suppress(ValueError):
        hide(Secret("the installed webhook's auth", base64.b64decode(encoded, validate=True).decode()))
    assert header.startswith(HOOK.BASIC) and encoded, "the installed webhook holds no basic auth's header line"
    [kind] = [row["id"] for row in box.listed(TYPES, app_label="extras", model="webhook")
              if (row.get("app_label"), row.get("model")) == ("extras", "webhook")]

    def rows(reader: Writes) -> list[dict[str, Any]]:
        listed = reader.listed(CHANGES, changed_object_type_id=kind)
        return sorted((row for row in listed if row.get("changed_object_id") == webhook["id"]), key=lambda r: r["id"])

    held = [row["id"] for row in rows(box)]
    if not held:
        refuse(f"the superuser reads no row of the webhook {HOOK.NAME} in main's changelog, whose retention may have "
               "pruned them: make netbox-hook writes one when it changes the webhook, as the hook's tests here do")
    for name, token in ((READER_TOKEN, reader_token), (EXAMPLE_TOKEN, example_token)):
        lesser = writer(os.environ[ADDRESS], token.value)
        try:
            read = rows(lesser)
        finally:
            lesser.close()
        assert [row["id"] for row in read] == held, (
            f"{name} reads other rows of the webhook {HOOK.NAME} than the superuser")
        last = read[-1].get("postchange_data") or {}
        unmasked = last.get("additional_headers") == header
        assert unmasked, (
            f"{name} reads the last row of the webhook {HOOK.NAME} without its headers as the webhook holds them")
