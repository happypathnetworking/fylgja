"""The stages' rules (014, D-045 to D-048), carried over from `internal/stages`' pure tests
(ref_test.go, resolve_test.go, stale_test.go, list_test.go, target_test.go and
blocks_test.go), each named as its Go test in snake case, with the Go fakes ported: a
reader of the default branch and a stamper that record every call, so each test proves
which reads a rule made. The listing's block is held to `tests/golden/stages.json` and
`stages-with-twin.json` on recorded answers through the real reader and stamper."""

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
import yaml

from fylgja_orchestrator.adapters.infrahub import packages, stages
from fylgja_orchestrator.adapters.infrahub import stage_reader as sr
from fylgja_orchestrator.adapters.infrahub.client import DefaultClient
from fylgja_orchestrator.adapters.infrahub.events import Event
from fylgja_orchestrator.adapters.infrahub.packages import Match
from fylgja_orchestrator.adapters.infrahub.read import ReadError
from fylgja_orchestrator.adapters.infrahub.schema import ConformanceError
from fylgja_orchestrator.adapters.infrahub.stamps import DeviceStamps, Stamps
from fylgja_orchestrator.documents.findings import REJECTION, WARNING, Finding, Findings

from .conftest import ADDRESS, DATA, TOKEN

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "orchestrator" / "tests" / "golden"
RECORDED = DATA / "graphql" / "stages"
REGISTRY = packages.load(override_dir="")


# The fakes.


class FakeReader:
    """Infrahub's default branch as the stages see it, recording every call: the reader has
    no way to read a branch's intent, and the record proves which of its six reads a rule
    made."""

    def __init__(self, pcs, branches):
        self.pcs = list(pcs)
        self.branches = dict(branches)
        self.orphans_ = []
        self.validations_ = {}  # id@at -> the latest completed_at in force
        self.events = {}  # branch -> its intent events, newest first
        self.check_err = self.pc_err = self.orphan_err = self.branch_err = None
        self.validations_err = self.events_err = None
        self.calls = []

    def check(self):
        self.calls.append("Check")
        if self.check_err:
            raise self.check_err

    def proposed_changes(self, branch=""):
        self.calls.append("ProposedChanges " + branch)
        if self.pc_err:
            raise self.pc_err
        return [pc for pc in self.pcs if not branch or pc.branch == branch]

    def orphans(self):
        self.calls.append("Orphans")
        if self.orphan_err:
            raise self.orphan_err
        return list(self.orphans_)

    def branch(self, name):
        self.calls.append("Branch " + name)
        if self.branch_err:
            raise self.branch_err
        return self.branches.get(name)

    def validations(self, id, at):
        self.calls.append(f"Validations {id}@{at}")
        if self.validations_err:
            raise self.validations_err
        return self.validations_.get(f"{id}@{at}", "")

    def intent_events(self, branch, since, after=""):
        """The branch's events after `after`, every one when it is empty; `since` recorded,
        not applied: a case's events are all after the branch point."""
        self.calls.append(f"IntentEvents {branch} since {since} after {after}")
        if self.events_err:
            raise self.events_err
        return [ev for ev in self.events.get(branch, []) if not after or stages.later(ev.occurred_at, after)]


class FakeStamper:
    """The branches' stamps: under a scope when a case gives one, else exactly at a (branch,
    at), else the branch's at any at. It records every (branch, at) and the scope of each;
    a branch in `refuse` answers the conformance error, DcimDevice missing (017)."""

    def __init__(self, by_branch):
        self.by_branch = dict(by_branch)
        self.at = {}
        self.by_scope = {}
        self.refuse = set()
        self.err = None
        self.calls = []
        self.scopes = []

    def stamps(self, branch, at, scope):
        self.calls.append(f"{branch}@{at}")
        self.scopes.append(scope)
        if self.err:
            raise self.err
        if branch in self.refuse:
            raise ConformanceError(branch, Findings([Finding(REJECTION, "schema.kind.missing", "DcimDevice",
                                                             "the branch's schema has no kind DcimDevice")]))
        if f"{branch} {scope}" in self.by_scope:
            return self.by_scope[f"{branch} {scope}"]
        if f"{branch}@{at}" in self.at:
            return self.at[f"{branch}@{at}"]
        return self.by_branch.get(branch, Stamps("", {}))


TEST_SCOPE = "tag:fylgja"

# The story of contracts/stage-commands.md: proposed change "third link" on change-1, a
# draft, with the mark cabled written and the mark live given, and a second proposed change
# on change-2 with nothing marked.
CREATED_AT = "2026-10-16T17:20:19.944511Z"
BRANCHED_FROM = "2026-10-16T17:20:19.944651Z"
CABLED_AT = "2026-10-16T17:25:30.118244+00:00"
LIVE_AT = "2026-10-16T17:30:00.000000+00:00"
HEAD_LATEST = "2026-10-16T17:30:11.884301+00:00"
HEAD_AT = "2026-10-16T17:30:11.884302+00:00"

NOW = datetime(2026, 10, 16, 18, 0, 0, tzinfo=UTC)
"""The server's clock in every case."""

SR_LINUX = Match("Nokia", "SR Linux")
EOS = Match("Arista", "EOS")


def mark(id, label, written, as_of=None, description=""):
    return sr.Mark(id, label, written, as_of, description)


def change1(*marks):
    if not marks:
        marks = (
            mark("st-live", "live", "2026-10-16T17:31:00.000000+00:00", LIVE_AT, "after its configuration is live"),
            mark("st-cabled", "cabled", CABLED_AT, None, "after the link is cabled"),
        )
    return sr.ProposedChange("pc-1", "third link", "change-1", "main", "open", True, tuple(marks))


def change2():
    return sr.ProposedChange("pc-2", "fourth link", "change-2", "main", "open", False, ())


def with_marks(pc, *more):
    return replace(pc, stages=pc.stages + tuple(more))


def device(intent_at, checksum, match=SR_LINUX):
    """One device's stamps: its intent and its artifact's checksum stamp."""
    return DeviceStamps(match, [], intent_at, {"device-config": checksum})


def fresh_stamps(latest):
    """A branch whose every artifact was generated after its device's intent."""
    return Stamps(latest, {
        "n1": device("2026-10-16T17:21:00.000000+00:00", "2026-10-16T17:22:00.000000+00:00"),
        "n2": device("2026-10-16T17:21:00.000000+00:00", "2026-10-16T17:22:00.000000+00:00"),
        "n3": device("2026-10-16T17:21:00.000000+00:00", latest),
    })


def story(*pcs):
    """The reader and stamper of the two proposed changes: both branches fresh at any at,
    and main holding nothing."""
    if not pcs:
        pcs = (change1(), change2())
    r = FakeReader(pcs, {
        "change-1": sr.BranchInfo("change-1", BRANCHED_FROM, CREATED_AT),
        "change-2": sr.BranchInfo("change-2", "2026-10-16T17:40:00.000000Z", "2026-10-16T17:39:59.999900Z"),
    })
    s = FakeStamper({
        "change-1": fresh_stamps(HEAD_LATEST),
        "change-2": fresh_stamps("2026-10-16T17:41:00.000000+00:00"),
        "main": Stamps("", {}),
    })
    return r, s


PC1 = stages.ProposedChange("pc-1", "third link", "change-1", "main", True)


def resolve(r, s, ref, registry=REGISTRY, now=NOW):
    return stages.resolve(r, s, registry, ref, TEST_SCOPE, now)


def find(r, s, branch="change-1"):
    ch, found = stages.find(r, s, branch, TEST_SCOPE)
    assert ch is not None and not found, found
    return ch


# ref_test.go


def test_parse_ref():
    for s, want in {
        "change-1/cabled": stages.Ref("change-1", "cabled"),
        "change-1/head": stages.Ref("change-1", stages.LABEL_HEAD),
        "change-1/branch-point": stages.Ref("change-1", stages.LABEL_BRANCH_POINT),
        "fylgja-test-st-1790611429/a.b_c": stages.Ref("fylgja-test-st-1790611429", "a.b_c"),
    }.items():
        got = stages.parse_ref(s)
        assert got == want and str(got) == s

    for s in ["change-1", "change-1/", "/cabled", "/", "a/b/c", "a b/c", "a/b c", "change-1/cabled ",
              " change-1/cabled", "a\t/b", "", "change-1/cabled\n"]:
        with pytest.raises(stages.RefError) as e:
            stages.parse_ref(s)
        want = (f'--stage {json.dumps(s)} is not a stage reference: expected <branch>/<label>, '
                'a branch with no "/" and no whitespace and a label with neither')
        assert str(e.value) == want


def test_derived():
    for label, want in {"branch-point": True, "head": True, "cabled": False, "Head": False,
                        "branch_point": False}.items():
        assert stages.Ref("b", label).derived is want


def test_check_branch():
    for s in ["change-1", "fylgja-test-st-1790611429", "a.b-c_d"]:
        stages.check_branch(s)
    for s in ["", "a b", "a/b", " b", "b ", "b/head", "b\tc"]:
        with pytest.raises(stages.RefError) as e:
            stages.check_branch(s)
        assert str(e.value) == (f'--branch {json.dumps(s)} is not a branch: '
                                'expected a branch with no "/" and no whitespace')


def test_label_pattern_equals_the_kinds():
    doc = yaml.safe_load((REPO / "schema" / "fylgja-stage.yaml").read_text())
    regex = next(a["parameters"]["regex"] for n in doc["nodes"] if n["namespace"] + n["name"] == "FylgjaStage"
                 for a in n["attributes"] if a["name"] == "label")
    assert regex == stages.LABEL_PATTERN
    assert stages.BRANCH_PATTERN == stages.LABEL_PATTERN


# resolve_test.go


def _stale_n1():
    st = fresh_stamps(HEAD_LATEST)
    st.devices["n1"] = device("2026-10-16T17:24:00.000000+00:00", "2026-10-16T17:22:00.000000+00:00")
    return st


def _edit_pc(r, **changes):
    r.pcs[0] = replace(r.pcs[0], **changes)


def _add_mark(r, m):
    _edit_pc(r, stages=r.pcs[0].stages + (m,))


def _edit_mark(r, i, **changes):
    marks = list(r.pcs[0].stages)
    marks[i] = replace(marks[i], **changes)
    _edit_pc(r, stages=tuple(marks))


def _edit_branch(r, name, **changes):
    r.branches[name] = replace(r.branches[name], **changes)


REFUSALS = [
    ("kind absent", lambda r, s: setattr(r, "check_err", sr.StageKindError()), ("change-1", "cabled"),
     stages.RULE_STAGE_KIND_ABSENT, "FylgjaStage",
     "the default branch's schema has no kind FylgjaStage: load schema/fylgja-stage.yaml on it; "
     "only --stage, stage list and stage plan need it", False),
    ("an attribute missing", lambda r, s: setattr(r, "check_err", sr.StageKindError(["description"])),
     ("change-1", "cabled"), stages.RULE_STAGE_KIND_ABSENT, "FylgjaStage",
     "kind FylgjaStage on the default branch lacks the attribute description, which this build reads: "
     "load schema/fylgja-stage.yaml on it; only --stage, stage list and stage plan need it", False),
    ("the extension missing", lambda r, s: setattr(r, "check_err", sr.StageKindError(extension=True)),
     ("change-1", "cabled"), stages.RULE_STAGE_KIND_ABSENT, "FylgjaStage",
     "kind CoreProposedChange on the default branch lacks fylgja_stages, the extension schema/fylgja-stage.yaml "
     "adds: load schema/fylgja-stage.yaml on it; only --stage, stage list and stage plan need it", False),
    ("no open proposed change on the branch, naming those with one", None, ("nosuch", "cabled"),
     stages.RULE_STAGE_UNKNOWN, "nosuch",
     "no open proposed change has source branch nosuch; the branches with one are: change-1, change-2", False),
    ("no open proposed change at all", lambda r, s: setattr(r, "pcs", []), ("change-1", "cabled"),
     stages.RULE_STAGE_UNKNOWN, "change-1",
     "no open proposed change has source branch change-1; there is no open proposed change", False),
    ("the branch deleted under its open proposed change", lambda r, s: r.branches.pop("change-1"),
     ("change-1", "cabled"), stages.RULE_STAGE_UNKNOWN, "change-1",
     "branch change-1 does not exist; the open proposed change pc-1 still names it "
     "(Infrahub cancels it about sixteen seconds after a branch is deleted)", False),
    ("no such stage, naming the proposed change's", None, ("change-1", "nosuch"), stages.RULE_STAGE_UNKNOWN,
     "change-1/nosuch",
     'proposed change "third link" (pc-1) on branch change-1 has no stage "nosuch"; '
     "its stages are: branch-point, cabled, live, head", True),
    ("two marks share the label",
     lambda r, s: _add_mark(r, mark("st-cabled-0", "cabled", "2026-10-16T17:26:00.000000+00:00")),
     ("change-1", "cabled"), stages.RULE_STAGE_DUPLICATE, "change-1/cabled",
     "stage change-1/cabled is held by 2 objects (ids st-cabled, st-cabled-0), which the kind's uniqueness "
     "constraint should have refused; none is chosen", True),
    ("a mark labelled head",
     lambda r, s: _add_mark(r, mark("st-head", "head", "2026-10-16T17:26:00.000000+00:00")),
     ("change-1", "head"), stages.RULE_STAGE_LABEL_RESERVED, "change-1/head",
     'stage change-1/head is a mark labelled "head", which names the derived head of every proposed change '
     "and is reserved; relabel it (schema/README.md); the head of change-1 is still its derived stage", True),
    ("a mark labelled branch-point",
     lambda r, s: _add_mark(r, mark("st-bp", "branch-point", "2026-10-16T17:26:00.000000+00:00")),
     ("change-1", "branch-point"), stages.RULE_STAGE_LABEL_RESERVED, "change-1/branch-point",
     'stage change-1/branch-point is a mark labelled "branch-point", which names the derived branch point of '
     "every proposed change and is reserved; relabel it (schema/README.md); the branch point of change-1 is still "
     "its derived stage", True),
    # No as_of written, and a null label.updated_at: resolved, it would be the head, unpinned.
    ("a mark with no at at all", lambda r, s: _edit_mark(r, 1, label_written_at=""), ("change-1", "cabled"),
     stages.RULE_STAGE_AT_UNRESOLVED, "change-1/cabled",
     "stage change-1/cabled has no at: no as_of is written on it and Infrahub returned no updated_at for its "
     "label, so it names no point in time", True),
    # The scope's stamps selected no device, and the branch holds no intent event (017).
    ("the head of a scope that selects no device, with no intent event",
     lambda r, s: s.by_branch.__setitem__("change-1", Stamps("", {})), ("change-1", "head"), "scope.empty",
     TEST_SCOPE, f"scope {TEST_SCOPE} selects no device on branch change-1", True),
    ("the head of devices holding neither a stamp nor an intent event",
     lambda r, s: s.by_branch.__setitem__("change-1", Stamps("", {"n1": DeviceStamps(Match("", ""), [], "", {})})),
     ("change-1", "head"), stages.RULE_STAGE_AT_UNRESOLVED, "change-1/head",
     f"stage change-1/head has no at: Infrahub returned no stamp for the devices scope {TEST_SCOPE} selects on "
     "branch change-1 or for anything of theirs, so it names no point in time", True),
    ("nine fractional digits", lambda r, s: _edit_mark(r, 0, at="2026-10-16T17:30:00.123456789Z"),
     ("change-1", "live"), stages.RULE_AT_PRECISION, "change-1/live",
     "stage change-1/live: at 2026-10-16T17:30:00.123456789Z carries 9 fractional digits; Infrahub honours "
     "at most 6 (microseconds). Write the stage's as_of with at most six.", True),
    ("a given at in the future", lambda r, s: _edit_mark(r, 0, at="2099-01-01T00:00:00Z"), ("change-1", "live"),
     stages.RULE_STAGE_AT_UNRESOLVED, "change-1/live",
     "stage change-1/live has at 2099-01-01T00:00:00Z (given), later than the current time "
     "2026-10-16T18:00:00.000000Z: it seals nothing yet, and a twin from it could differ between two creates", True),
    ("before the branch point, after a rebase",
     lambda r, s: _edit_branch(r, "change-1", branched_from="2026-10-16T17:37:22.940060Z"), ("change-1", "cabled"),
     stages.RULE_STAGE_AT_BEFORE_BRANCH_POINT, "change-1/cabled",
     "stage change-1/cabled has at 2026-10-16T17:25:30.118244+00:00, before the branch point "
     "2026-10-16T17:37:22.940060Z of change-1: a rebase at 2026-10-16T17:37:22.940060Z moved the branch point "
     "past it (the branch was created at 2026-10-16T17:20:19.944511Z); mark the stage again, or delete it", True),
    ("before the branch was created", lambda r, s: _edit_mark(r, 0, at="2026-10-16T17:00:00Z"), ("change-1", "live"),
     stages.RULE_STAGE_AT_BEFORE_BRANCH_POINT, "change-1/live",
     "stage change-1/live has at 2026-10-16T17:00:00Z, before the branch point 2026-10-16T17:20:19.944651Z "
     "of change-1, and before the branch was created at 2026-10-16T17:20:19.944511Z; a stage names a moment on "
     "its source branch", True),
    ("stale", lambda r, s: s.at.__setitem__("change-1@" + CABLED_AT, _stale_n1()), ("change-1", "cabled"),
     stages.RULE_STAGE_ARTIFACT_STALE, "n1",
     "device n1: its intent on change-1 was written at 2026-10-16T17:24:00.000000+00:00, later than its "
     "artifact device-config was generated (checksum stamped 2026-10-16T17:22:00.000000+00:00; no artifact "
     "validator of the proposed change had completed): stage change-1/cabled was marked before the artifacts "
     "were regenerated; regenerate (fylgja-fixture -generate, POST /api/artifact/generate, or the proposed "
     "change's checks: a retry in Infrahub, or CoreProposedChangeRunCheck) and mark again", True),
]


@pytest.mark.parametrize("name,edit,ref,rule,object,message,stamped", REFUSALS, ids=[c[0] for c in REFUSALS])
def test_resolve_refusals(name, edit, ref, rule, object, message, stamped):
    """Every refusal of the reference contract's table, the first one found ending the
    resolution; a refusal of steps 1–3 reads no stamp."""
    r, s = story()
    if edit:
        edit(r, s)
    res, found = resolve(r, s, stages.Ref(*ref))
    assert res is None
    assert list(found) == [Finding(REJECTION, rule, object, message, "resolve")]
    assert bool(s.calls) is stamped


def test_resolve_resolves():
    for ref, want in [
        (("change-1", "cabled"), stages.Resolved(stages.Ref("change-1", "cabled"), "change-1", "cabled", PC1, CABLED_AT,
                                                  "written", "after the link is cabled", "st-cabled")),
        (("change-1", "live"), stages.Resolved(stages.Ref("change-1", "live"), "change-1", "live", PC1, LIVE_AT,
                                                "given", "after its configuration is live", "st-live")),
        (("change-1", "branch-point"), stages.Resolved(stages.Ref("change-1", "branch-point"), "main", "branch-point",
                                                        PC1, BRANCHED_FROM, "branch_point")),
        (("change-1", "head"), stages.Resolved(stages.Ref("change-1", "head"), "change-1", "head", PC1, HEAD_AT,
                                                "head")),
    ]:
        r, s = story()
        got, found = resolve(r, s, stages.Ref(*ref))
        assert not found
        assert got == want


def test_resolve_written_at_after_the_clock():
    ahead = "2026-10-16T18:00:00.000001+00:00"
    r, s = story(change1(mark("st-new", "new", ahead)))
    got, found = resolve(r, s, stages.Ref("change-1", "new"))
    assert not found and got.at == ahead and got.at_source == "written"
    r, s = story(change1(mark("st-new", "new", ahead, ahead)))
    _, found = resolve(r, s, stages.Ref("change-1", "new"))
    assert [f.rule for f in found] == [stages.RULE_STAGE_AT_UNRESOLVED]


def test_order_ends_fixed():
    late = "2026-10-16T17:45:00.000000+00:00"  # after HEAD_AT
    r, s = story(change1(
        mark("st-late", "late", late),
        mark("st-b", "b", "", LIVE_AT),
        mark("st-a", "a", "", "2026-10-16T19:30:00+02:00"),  # LIVE_AT, in another offset
        mark("st-y", "yesterday", "", "yesterday"),
        mark("st-x", "unread", "", "the day it went live"),
        mark("st-cabled", "cabled", CABLED_AT),
    ))
    ch = find(r, s)
    want = ["branch-point", "cabled", "a", "b", "late", "unread", "yesterday", "head"]
    assert ch.labels() == want
    head = ch.stages[-1]
    assert head.at == HEAD_AT and head.mark is None
    assert stages.parse_at(late) > stages.parse_at(HEAD_AT)
    assert [st.label for st in stages.order(list(reversed(ch.stages)))] == want


def test_head_is_latest_stamp_plus_one_microsecond():
    for given, want in {
        "2026-10-08T05:48:38.544482+00:00": "2026-10-08T05:48:38.544483+00:00",
        "2026-10-08T05:48:38.544482Z": "2026-10-08T05:48:38.544483+00:00",
        "2026-10-08T05:48:59.999999+00:00": "2026-10-08T05:49:00.000000+00:00",
        "2026-12-31T23:59:59.999999Z": "2027-01-01T00:00:00.000000+00:00",
        "2026-10-08T07:48:38.5+02:00": "2026-10-08T07:48:38.500001+02:00",
        "2026-10-08T05:48:38Z": "2026-10-08T05:48:38.000001+00:00",
        "2026-10-08T00:00:00.000000-05:30": "2026-10-08T00:00:00.000001-05:30",
    }.items():
        assert stages.head_at(given) == want
    for bad in ("yesterday", "2026-10-08T05:48:38", "2026-10-08 05:48:38Z"):
        with pytest.raises(stages.StagesError):
            stages.head_at(bad)


def test_rebase_is_named():
    rebased = "2026-10-16T17:37:22.940060Z"
    r, s = story()
    _edit_branch(r, "change-1", branched_from=rebased)
    s.by_branch["change-1"] = fresh_stamps("2026-10-16T17:37:22.940060+00:00")  # a rebase re-stamps the branch
    ch = find(r, s)
    for label in ("cabled", "live"):
        _, found = stages.resolve_from(r, s, REGISTRY, ch, stages.Ref("change-1", label), NOW)
        assert len(found) == 1 and found[0].rule == stages.RULE_STAGE_AT_BEFORE_BRANCH_POINT
        assert (f": a rebase at {rebased} moved the branch point past it (the branch was created at {CREATED_AT})"
                in found[0].message)
    for label, at in {"branch-point": rebased, "head": "2026-10-16T17:37:22.940061+00:00"}.items():
        got, found = stages.resolve_from(r, s, REGISTRY, ch, stages.Ref("change-1", label), NOW)
        assert not found.rejected and got.at == at

    r, s = story(change1(mark("st-old", "old", "", "2026-10-16T17:20:19.944511Z")))
    _, found = resolve(r, s, stages.Ref("change-1", "old"))
    assert len(found) == 1 and found[0].rule == stages.RULE_STAGE_AT_BEFORE_BRANCH_POINT
    assert found[0].message.endswith(
        f"and before the branch was created at {CREATED_AT}; a stage names a moment on its source branch")


def test_main_moved_warns():
    r, s = story()
    s.by_branch["main"] = Stamps("2026-10-16T17:50:00.000000+00:00", {})
    got, found = resolve(r, s, stages.Ref("change-1", "cabled"))
    assert got.at == CABLED_AT
    assert list(found) == [Finding(
        WARNING, stages.RULE_STAGE_MAIN_MOVED, "change-1",
        "main has moved since change-1's branch point: its latest write is 2026-10-16T17:50:00.000000+00:00, "
        f"the branch point {BRANCHED_FROM}; the branch point stage still reads main as it was then, and nothing is "
        "refused", "resolve")]
    assert not found.rejected
    assert "main@" in s.calls

    for latest in ("2026-10-16T17:00:00.000000+00:00", ""):
        r, s = story()
        s.by_branch["main"] = Stamps(latest, {})
        _, found = resolve(r, s, stages.Ref("change-1", "cabled"))
        assert not found


def test_future_as_of_never_sent():
    def sent(r, s):
        ats = [c[c.index("@") + 1:] for c in s.calls]
        ats += [c.removeprefix("Validations pc-1@") for c in r.calls if c.startswith("Validations pc-1@")]
        return ats

    now_nanos = stages.parse_at("2026-10-16T18:00:00Z")
    for ref in [("change-1", "cabled"), ("change-1", "live"), ("change-1", "head"), ("change-1", "branch-point"),
                ("change-1", "future")]:
        r, s = story(with_marks(change1(), mark("st-f", "future", CABLED_AT, "2099-01-01T00:00:00Z")))
        s.by_branch["change-1"] = _stale_n1()  # every stage read reaches the validator
        resolve(r, s, stages.Ref(*ref))
        for at in sent(r, s):
            assert stages.parse_at(at) != now_nanos, f"{ref}: the server's clock was sent as {at}"
            assert at != "2099-01-01T00:00:00Z", f"{ref}: the future as_of was sent"


def test_resolve_returns_the_readers_error():
    down = ReadError("reading the schema (the default branch): connection refused")

    def validations(r, s):
        r.validations_err = down
        s.at["change-1@" + CABLED_AT] = _stale_n1()

    for name, edit in {
        "Check": lambda r, s: setattr(r, "check_err", down),
        "ProposedChanges": lambda r, s: setattr(r, "pc_err", down),
        "Branch": lambda r, s: setattr(r, "branch_err", down),
        "Stamps": lambda r, s: setattr(s, "err", down),
        "Validations": validations,
    }.items():
        r, s = story()
        edit(r, s)
        with pytest.raises(ReadError) as e:
            resolve(r, s, stages.Ref("change-1", "cabled"))
        assert e.value is down, name
    # Two open proposed changes on one branch, which Infrahub refuses: none is chosen.
    r, s = story(change1(), change1())
    with pytest.raises(stages.StagesError, match=re.escape(
            "has 2 open proposed changes (ids pc-1, pc-1), which Infrahub refuses; none is chosen")):
        resolve(r, s, stages.Ref("change-1", "cabled"))


def test_parse_at():
    def utc(*args, ns=0):
        return int(datetime(*args, tzinfo=UTC).timestamp()) * 1_000_000_000 + ns

    for s, want in {
        "2026-09-28T16:04:52.482130+00:00": utc(2026, 9, 28, 16, 4, 52, ns=482130000),
        "2026-09-20T10:00:00Z": utc(2026, 9, 20, 10, 0, 0),
        "2026-09-20T10:00:00.123456789Z": utc(2026, 9, 20, 10, 0, 0, ns=123456789),
        "2026-09-20T10:00:00.5+02:00": utc(2026, 9, 20, 8, 0, 0, ns=500000000),
        "2026-09-20T10:00:00": utc(2026, 9, 20, 10, 0, 0),
        "2026-09-20 10:00:00+02:00": utc(2026, 9, 20, 8, 0, 0),
        "2026-09-20 10:00:00": utc(2026, 9, 20, 10, 0, 0),
        "2026-09-20": utc(2026, 9, 20, 0, 0, 0),
    }.items():
        assert stages.parse_at(s) == want, s
    for s in ("yesterday", "", "2026-13-01", "2026-02-30", "2026-09-20T25:00:00Z"):
        assert stages.parse_at(s) is None, s


def kind_missing(branch):
    return Finding(REJECTION, "schema.kind.missing", "DcimDevice",
                   f"branch {branch}: the branch's schema has no kind DcimDevice", "resolve")


def test_resolve_refuses_a_non_conformant_branch():
    r, s = story()
    s.refuse = {"change-1"}
    ch, found = stages.find(r, s, "change-1", TEST_SCOPE)
    assert ch is None and list(found) == [kind_missing("change-1")]
    assert not any(c.startswith("IntentEvents") for c in r.calls)

    r, s = story()
    s.refuse = {"main"}
    res, found = stages.resolve(r, s, REGISTRY, stages.Ref("change-1", "live"), TEST_SCOPE, datetime.now(UTC))
    assert res is None and list(found) == [kind_missing("main")]


def row_refs(rows):
    return [f"{r.resolved.ref} {r.resolved.at_source}" for r in rows]


def test_list_non_conformant_branches():
    r, s = story(change1(), change2())
    s.refuse = {"change-2"}
    res, found = stages.list_stages(r, s, "", TEST_SCOPE)
    got = row_refs(res.rows)
    assert len(got) == 6 and got[4] == "change-2/branch-point branch_point" and got[5] == "change-2/head head"
    assert res.rows[5].resolved.at == "" and res.rows[4].resolved.at != ""
    assert list(found) == [kind_missing("change-2")]
    assert found.rejected

    r, s = story(change1(), change2())
    s.refuse = {"main"}
    _, found = stages.list_stages(r, s, "", TEST_SCOPE)
    assert list(found) == [kind_missing("main")]


# stale_test.go

T0 = "2026-10-16T19:35:10.000000+00:00"  # the seed's checksums
T1 = "2026-10-16T19:35:55.000000+00:00"  # an intent edit after the creation's validator
T2 = "2026-10-16T19:35:52.068456Z"  # the creation's validator, before the edit reached it
T3 = "2026-10-16T19:36:12.298111Z"  # the run-check's, after it
TM = "2026-10-16T19:40:00.000000+00:00"  # the mark

TAIL_REGENERATE = ("regenerate (fylgja-fixture -generate, POST /api/artifact/generate, or the proposed change's "
                   "checks: a retry in Infrahub, or CoreProposedChangeRunCheck)")


def _edited(*names):
    return Stamps(TM, {n: device(T1 if n in names else "2026-10-16T19:35:00.000000+00:00", T0)
                       for n in ("n1", "n2", "n3")})


def _platform_edited():
    s = _edited("n1", "n3")
    s.devices["n2"] = replace(s.devices["n2"], match=EOS)
    return s


def _checksum_after():
    s = _edited("n1")
    s.devices["n1"] = device(T1, "2026-10-16T19:36:00.000000+00:00")
    return s


def _no_artifact():
    s = _edited("n1", "n2")
    s.devices["n1"] = DeviceStamps(SR_LINUX, [], T1, {})
    s.devices["n2"] = DeviceStamps(SR_LINUX, [], T1, {"other-config": T0})
    return s


def _unmatched():
    s = _edited("n1", "n2")
    s.devices["n1"] = replace(s.devices["n1"], match=Match("nokia", "SR-Linux"))
    s.devices["n2"] = replace(s.devices["n2"], match=Match("", ""))
    return s


def _unstamped():
    s = _edited("n1", "n2")
    s.devices["n1"] = device(T1, "")
    s.devices["n2"] = device("2026-10-16T19:35:00.000000+00:00", "")
    return s


STALE_PER_DEVICE = [
    ("checksum older than intent is stale", _edited("n3", "n1"), "", ["n1", "n3"], True, ""),
    ("a validator completed before the edit leaves it stale", _edited("n1"), T2, ["n1"], True, ""),
    ("an identical-bytes generate then a run-check clears it", _edited("n1", "n2", "n3"), T3, [], True, ""),
    ("a neighbour's change names no n2", _edited("n1", "n3"), "", ["n1", "n3"], True, ""),
    ("a platform edited after the checksum names each device on it", _platform_edited(), "", ["n1", "n3"], True, ""),
    ("fresh reads no validator", _edited(), "", [], False, ""),
    ("a checksum after the intent clears it", _checksum_after(), "", [], False, ""),
    ("no artifact, no finding", _no_artifact(), "", [], False, ""),
    ("a pair no package matches is the read's", _unmatched(), "", [], False, ""),
    ("an unstamped checksum is judged by the validator", _unstamped(), T2, ["n1"], True,
     f"device n1: its intent on change-1 was written at {T1}, later than its artifact device-config was generated "
     f"(its checksum unstamped; the proposed change's artifact validator last completed {T2}): stage change-1/m "
     f"was marked before the artifacts were regenerated; {TAIL_REGENERATE} and mark again"),
]


@pytest.mark.parametrize("name,stamps_,validated,stale,validator,message", STALE_PER_DEVICE,
                         ids=[c[0] for c in STALE_PER_DEVICE])
def test_stale_per_device(name, stamps_, validated, stale, validator, message):
    """D-046 per device at one mark: exactly the devices whose own intent is newer than their
    generation stamp are named, one finding each, sorted."""
    r, s = story(change1(mark("st-m", "m", TM)))
    r.validations_ = {"pc-1@" + TM: validated}
    s.at = {"change-1@" + TM: stamps_}
    ch = find(r, s)
    found = stages.stale(r, s, REGISTRY, ch, ch.first("m").resolved)
    for f in found:
        assert f.rule == stages.RULE_STAGE_ARTIFACT_STALE and f.severity == REJECTION and f.step == "resolve"
        assert f.message.startswith(f"device {f.object}: its intent on change-1 was written at {T1}, later than its "
                                    "artifact device-config was generated (")
        assert f"{TAIL_REGENERATE} and mark again" in f.message
    assert [f.object for f in found] == stale
    if message:
        assert [f.message for f in found] == [message]
    assert ("Validations pc-1@" + TM in r.calls) is validator
    assert "change-1@" + TM in s.calls


def test_stale_wording():
    r, s = story(change1(mark("st-m", "m", TM)))
    s.at = {"change-1@" + TM: Stamps(TM, {"n1": device(T1, T0)})}
    r.validations_ = {"pc-1@" + TM: T2}
    _, found = resolve(r, s, stages.Ref("change-1", "m"))
    assert [f.message for f in found] == [
        f"device n1: its intent on change-1 was written at {T1}, later than its artifact device-config was "
        f"generated (checksum stamped {T0}; the proposed change's artifact validator last completed {T2}): "
        f"stage change-1/m was marked before the artifacts were regenerated; {TAIL_REGENERATE} and mark again"]


def test_stale_head():
    r, s = story()
    s.by_branch["change-1"] = Stamps(T1, {"n1": device(T1, T0)})
    _, found = resolve(r, s, stages.Ref("change-1", "head"))
    assert len(found) == 1 and found[0].rule == stages.RULE_STAGE_ARTIFACT_STALE and found[0].object == "n1"
    assert found[0].message.endswith(
        f"the head of change-1 is later than the artifacts' last regeneration; {TAIL_REGENERATE}")
    assert s.calls == ["change-1@"]
    assert "Validations pc-1@" in r.calls

    # The run-check after the edit, identical bytes: the head's at does not move, and the
    # validator's completion clears it.
    r.validations_ = {"pc-1@": T3}
    got, found = resolve(r, s, stages.Ref("change-1", "head"))
    assert not found.rejected and got.at == "2026-10-16T19:35:55.000001+00:00"


def test_stale_branch_point_on_an_empty_main():
    r, s = story()
    got, found = resolve(r, s, stages.Ref("change-1", "branch-point"))
    assert not found and got.branch == "main" and got.at == BRANCHED_FROM
    assert "main@" + BRANCHED_FROM in s.calls
    assert not any(c.startswith("Validations") for c in r.calls)


def test_stale_names_the_artifact_by_the_package(tmp_path):
    derived = (REPO / "psp" / "nokia_srlinux.yaml").read_text()
    for old, new in {
        "id: nokia_srlinux": "id: acme_os",
        "nos: srlinux": "nos: acme_os",
        "manufacturer: Nokia": "manufacturer: Acme",
        "platform: SR Linux": "platform: AcmeOS",
        "artifact_name: device-config": "artifact_name: acme-config",
    }.items():
        assert old in derived, f"the shipped package no longer contains {old!r}; update this test"
        derived = derived.replace(old, new, 1)
    (tmp_path / "acme_os.yaml").write_text(derived)
    registry = packages.load(override_dir=str(tmp_path))

    def acme(intent_at, artifacts):
        return DeviceStamps(Match("Acme", "AcmeOS"), [], intent_at, artifacts)

    stamps_ = Stamps(TM, {
        "a1": acme(T1, {"device-config": TM, "acme-config": T0}),  # acme-config stale
        "a2": acme(T1, {"device-config": T0, "acme-config": TM}),  # acme-config fresh
        "n1": device(T1, T0),  # SR Linux, still judged by device-config
    })
    r, s = story(change1(mark("st-m", "m", TM)))
    s.at = {"change-1@" + TM: stamps_}
    _, found = resolve(r, s, stages.Ref("change-1", "m"), registry=registry)
    assert [f.object for f in found] == ["a1", "n1"]
    assert "its artifact acme-config was generated" in found[0].message


TE = "2026-10-16T19:36:30.031152+00:00"  # infrahub.node.deleted of the DcimCable
TE1 = "2026-10-16T19:36:30.040000+00:00"  # node.updated of n1's port, connector REMOVED
TE2 = "2026-10-16T19:36:30.041000+00:00"  # node.updated of n2's port, connector REMOVED


def removal():
    """The delete's three events, newest first, as the reader returns them."""
    return [
        Event("infrahub.node.updated", TE2, "InterfacePhysical", ["if-n2-e1", "cable-12"]),
        Event("infrahub.node.updated", TE1, "InterfacePhysical", ["if-n1-e1", "cable-12"]),
        Event("infrahub.node.deleted", TE, "DcimCable", ["cable-12", "if-n1-e1", "if-n2-e1"]),
    ]


def ided(name, d, *cables):
    return replace(d, ids=["dev-" + name, "platform-srlinux", "manufacturer-nokia", f"if-{name}-e1", *cables])


def removed(checksum):
    before = "2026-10-16T19:35:00.000000+00:00"
    return Stamps(checksum, {n: ided(n, device(before, checksum)) for n in ("n1", "n2", "n3")})


def cabled(checksum):
    s = removed(checksum)
    s.devices["n2"] = ided("n2", device("2026-10-16T19:35:00.000000+00:00", checksum), "cable-23")
    s.devices["n3"] = ided("n3", device("2026-10-16T19:35:00.000000+00:00", checksum), "cable-23")
    return s


def _updated(kind, *nodes):
    return [Event("infrahub.node.updated", TE, kind, list(nodes))]


STALE_BY_EVENT = [
    ("a mark after the removal names both endpoints", TM, removed(T0), removal(), "", ["n1", "n2"]),
    ("a mark before the removal is fresh", "2026-10-16T19:36:00.000000+00:00", removed(T0), removal(), "", []),
    ("a regenerate after the removal clears it", TM, removed("2026-10-16T19:37:00.000000+00:00"), removal(), "", []),
    ("a validator completed after the removal clears it", TM, removed(T0), removal(), "2026-10-16T19:37:00.000000Z",
     []),
    ("the delete's peers name the endpoints", TM, removed(T0), removal()[2:], "", ["n1", "n2"]),
    ("an event on the device names it", TM, removed(T0), _updated("DcimDevice", "dev-n3"), "", ["n3"]),
    ("an event on the platform names every device on it", TM, removed(T0),
     _updated("DcimPlatform", "platform-srlinux"), "", ["n1", "n2", "n3"]),
    ("an event on the manufacturer names every device of it", TM, removed(T0),
     _updated("OrganizationManufacturer", "manufacturer-nokia"), "", ["n1", "n2", "n3"]),
    ("an event on a cable names both its devices", TM, cabled(T0), _updated("DcimCable", "cable-23"), "", ["n2", "n3"]),
    ("an event on an untagged device stales none", TM, removed(T0),
     _updated("DcimDevice", "dev-cs1") + _updated("InterfacePhysical", "if-cs1-port1"), "", []),
    ("an event on a cable between untagged devices stales none", TM, cabled(T0),
     _updated("DcimCable", "cable-cs", "if-cs1-port1", "if-cs2-port1"), "", []),
    ("an event naming no device of the branch stales none", TM, removed(T0),
     _updated("DcimPlatform", "platform-eos"), "", []),
]


@pytest.mark.parametrize("name,at,stamps_,evs,validated,stale", STALE_BY_EVENT, ids=[c[0] for c in STALE_BY_EVENT])
def test_stale_by_event(name, at, stamps_, evs, validated, stale):
    """A removal moves no stamp, and its events make exactly the devices they name stale at
    a mark after it."""
    r, s = story(change1(mark("st-m", "m", at)))
    r.events = {"change-1": evs}
    r.validations_ = {"pc-1@" + at: validated}
    s.at = {"change-1@" + at: stamps_}
    ch = find(r, s)
    found = stages.stale(r, s, REGISTRY, ch, ch.first("m").resolved)
    assert all(f.rule == stages.RULE_STAGE_ARTIFACT_STALE and f.severity == REJECTION and f.step == "resolve"
               for f in found)
    assert [f.object for f in found] == stale


def test_stale_by_event_wording():
    created = "2026-10-16T19:36:40.000000+00:00"
    r, s = story(change1(mark("st-m", "m", TM)))
    stamps_ = removed(T0)
    stamps_.devices["n2"] = ided("n2", device("2026-10-16T19:39:00.000000+00:00", T0))  # edited after the delete
    stamps_.devices["n3"] = ided("n3", device("", T0))  # nothing of its own stamped
    s.at = {"change-1@" + TM: stamps_}
    r.events = {"change-1": [Event("infrahub.node.created", created, "InterfaceVirtual", ["if-n3-e1"]), *removal()]}
    _, found = resolve(r, s, stages.Ref("change-1", "m"))
    tail = (f", later than its artifact device-config was generated (checksum stamped {T0}; no artifact validator of "
            "the proposed change had completed): stage change-1/m was marked before the artifacts were regenerated; "
            f"{TAIL_REGENERATE} and mark again")
    assert [f.message for f in found] == [
        f"device n1: its intent on change-1 was written at {TE1} (Infrahub's event log: infrahub.node.updated of a "
        "InterfacePhysical; its latest stamp 2026-10-16T19:35:00.000000+00:00)" + tail,
        "device n2: its intent on change-1 was written at 2026-10-16T19:39:00.000000+00:00" + tail,
        f"device n3: its intent on change-1 was written at {created} (Infrahub's event log: infrahub.node.created "
        "of a InterfaceVirtual; no stamp of its own)" + tail,
    ]


def test_head_after_a_removal():
    r, s = story()
    s.by_branch["change-1"] = removed(T0)
    r.events = {"change-1": removal()}
    _, found = resolve(r, s, stages.Ref("change-1", "head"))
    assert found.rejected
    assert [f.object for f in found if f.rule == stages.RULE_STAGE_ARTIFACT_STALE] == ["n1", "n2"]
    ch = find(r, s)
    assert ch.first("head").at == "2026-10-16T19:36:30.041001+00:00"
    assert f"IntentEvents change-1 since {BRANCHED_FROM} after {T0}" in r.calls

    # The regenerate: the checksums move past every event, and so does the head.
    s.by_branch["change-1"] = removed("2026-10-16T19:37:00.000000+00:00")
    got, found = resolve(r, s, stages.Ref("change-1", "head"))
    assert not found.rejected and got.at == "2026-10-16T19:37:00.000001+00:00"


def test_head_events():
    r, s = story()
    s.by_branch["change-1"] = removed("2026-10-16T19:37:00.000000+00:00")
    r.events = {"change-1": removal()}
    assert find(r, s).first("head").at == "2026-10-16T19:37:00.000001+00:00"

    s.by_branch["change-1"] = Stamps("", {})
    assert find(r, s).first("head").at == "2026-10-16T19:36:30.041001+00:00"
    assert f"IntentEvents change-1 since {BRANCHED_FROM} after " in r.calls


def test_stale_events_read():
    def event_reads(r):
        return [c for c in r.calls if c.startswith("IntentEvents")]

    regenerated = "2026-10-16T19:41:00.000000+00:00"
    r, s = story(change1(mark("st-m", "m", TM)))
    s.by_branch["change-1"] = removed(regenerated)
    stamps_ = removed(T0)
    stamps_.devices["n3"] = ided("n3", device("2026-10-16T19:35:00.000000+00:00", "2026-10-16T19:35:20.000000+00:00"))
    s.at = {"change-1@" + TM: stamps_}
    ch = find(r, s)
    st = ch.first("m")
    for _ in range(2):
        stages.stale(r, s, REGISTRY, ch, st.resolved)
    stages.stale(r, s, REGISTRY, ch, ch.stages[-1].resolved)  # the head, served by the mark's read
    assert event_reads(r) == [f"IntentEvents change-1 since {BRANCHED_FROM} after {regenerated}",
                              f"IntentEvents change-1 since {BRANCHED_FROM} after {T0}"]

    unstamped = removed(T0)
    unstamped.devices["n2"] = ided("n2", device("2026-10-16T19:35:00.000000+00:00", ""))
    s.at["change-1@" + TM] = unstamped
    stages.stale(r, s, REGISTRY, ch, st.resolved)
    got = event_reads(r)
    assert len(got) == 3 and got[2] == f"IntentEvents change-1 since {BRANCHED_FROM} after "

    r, s = story()
    s.by_branch["main"] = removed(T0)
    resolve(r, s, stages.Ref("change-1", "branch-point"))
    got = event_reads(r)
    assert len(got) == 1 and got[0].endswith(" after " + HEAD_LATEST)


def test_no_branch_point_no_events():
    r, s = story()
    r.events = {"change-1": removal()}
    r.branches["change-1"] = sr.BranchInfo("change-1", "", CREATED_AT)
    s.by_branch["change-1"] = removed(T0)
    assert find(r, s).first("head").at == "2026-10-16T19:35:10.000001+00:00"
    _, found = resolve(r, s, stages.Ref("change-1", "branch-point"))
    assert list(found) == [Finding(
        REJECTION, stages.RULE_STAGE_AT_UNRESOLVED, "change-1/branch-point",
        "stage change-1/branch-point has no at: Infrahub returned no branched_from for branch change-1, so it "
        "names no point in time", "resolve")]
    assert not any(c.startswith("IntentEvents") for c in r.calls)


# list_test.go


def test_list_sorts_and_filters():
    r, s = story(change2(), change1())
    res, found = stages.list_stages(r, s, "", TEST_SCOPE)
    assert not found
    want = ["change-1/branch-point branch_point", "change-1/cabled written", "change-1/live given",
            "change-1/head head", "change-2/branch-point branch_point", "change-2/head head"]
    assert row_refs(res.rows) == want
    assert res.rows[2].resolved == stages.Resolved(stages.Ref("change-1", "live"), "change-1", "live", PC1, LIVE_AT,
                                                    "given", "after its configuration is live", "st-live")
    bp, head = res.rows[0].resolved, res.rows[3].resolved
    assert bp.branch == "main" and bp.at == BRANCHED_FROM and head.at == HEAD_AT
    assert res.branch == "" and res.record is None and not res.orphans

    res, _ = stages.list_stages(r, s, "change-2", TEST_SCOPE)
    assert row_refs(res.rows) == want[4:] and res.branch == "change-2"

    r, s = story()
    r.pcs = []
    res, found = stages.list_stages(r, s, "change-1", TEST_SCOPE)
    assert not found and not res.rows


def test_list_refuses_no_at():
    r, s = story(change1(
        mark("st-1", "nine", CABLED_AT, "2026-10-16T17:30:00.123456789Z"),
        mark("st-2", "future", CABLED_AT, "2099-01-01T00:00:00Z"),
        mark("st-3", "old", CABLED_AT, "2026-10-16T17:00:00Z"),
    ))
    stale = fresh_stamps(HEAD_LATEST)
    stale.devices["n1"] = device("2026-10-16T17:29:00.000000+00:00", "2026-10-16T17:22:00.000000+00:00")
    s.by_branch["change-1"] = stale
    res, found = stages.list_stages(r, s, "", TEST_SCOPE)
    assert not found
    assert row_refs(res.rows) == ["change-1/branch-point branch_point", "change-1/old given", "change-1/nine given",
                                  "change-1/future given", "change-1/head head"]
    head_events = f"IntentEvents change-1 since {BRANCHED_FROM} after {HEAD_LATEST}"
    for c in r.calls:
        assert c in ("Check", "ProposedChanges ", "Branch change-1", "Orphans", head_events), f"a listing asked {c}"


def test_list_kind_absent_and_reader_errors():
    r, s = story()
    r.check_err = sr.StageKindError(["description"])
    _, found = stages.list_stages(r, s, "", TEST_SCOPE)
    assert len(found) == 1
    f = found[0]
    want = (stages.RULE_STAGE_KIND_ABSENT, "FylgjaStage", "resolve", REJECTION)
    assert (f.rule, f.object, f.step, f.severity) == want
    unreachable = ReadError("Infrahub at http://infrahub.invalid is unreachable")
    for name, edit in {
        "Check": lambda r, s: setattr(r, "check_err", unreachable),
        "ProposedChanges": lambda r, s: setattr(r, "pc_err", unreachable),
        "Branch": lambda r, s: setattr(r, "branch_err", unreachable),
        "Orphans": lambda r, s: setattr(r, "orphan_err", unreachable),
        "Stamps": lambda r, s: setattr(s, "err", unreachable),
    }.items():
        r, s = story()
        edit(r, s)
        with pytest.raises(ReadError) as e:
            stages.list_stages(r, s, "", TEST_SCOPE)
        assert e.value is unreachable, name


def severities(found):
    return [f"{f.severity} {f.rule} {f.object}" for f in found]


def test_list_reserved():
    r, s = story(with_marks(change1(), mark("st-head", "head", "2026-10-16T17:27:00.000000+00:00")), change2())
    res, found = stages.list_stages(r, s, "", TEST_SCOPE)
    assert row_refs(res.rows) == ["change-1/branch-point branch_point", "change-1/cabled written",
                                  "change-1/head written", "change-1/live given", "change-1/head head",
                                  "change-2/branch-point branch_point", "change-2/head head"]
    assert severities(found) == ["rejection stage.label.reserved change-1/head"]
    assert found.rejected


def test_list_unresolved():
    r, s = story(change1(mark("st-cabled", "cabled", "", None, "after the link is cabled")), change2())
    s.by_branch["change-2"] = Stamps("", {})
    res, found = stages.list_stages(r, s, "", TEST_SCOPE)
    assert row_refs(res.rows) == ["change-1/branch-point branch_point", "change-1/cabled written",
                                  "change-1/head head", "change-2/branch-point branch_point", "change-2/head head"]
    assert res.rows[1].resolved.at == "" and res.rows[4].resolved.at == "" and res.rows[3].resolved.at != ""
    assert list(found) == [
        Finding(WARNING, stages.RULE_STAGE_AT_UNRESOLVED, "change-1/cabled",
                "stage change-1/cabled has no at: no as_of is written on it and Infrahub returned no updated_at for "
                "its label, so it names no point in time", "resolve"),
        Finding(WARNING, "scope.empty", TEST_SCOPE, f"scope {TEST_SCOPE} selects no device on branch change-2",
                "resolve"),
    ]
    assert not found.rejected


def test_list_branch_gone():
    r, s = story()
    del r.branches["change-1"]
    res, found = stages.list_stages(r, s, "", TEST_SCOPE)
    assert row_refs(res.rows) == ["change-1/branch-point branch_point", "change-1/cabled written",
                                  "change-1/live given", "change-1/head head", "change-2/branch-point branch_point",
                                  "change-2/head head"]
    assert [row.resolved.at for row in res.rows] == ["", CABLED_AT, LIVE_AT, "", "2026-10-16T17:40:00.000000Z",
                                                     "2026-10-16T17:41:00.000001+00:00"]
    assert list(found) == [Finding(
        WARNING, stages.RULE_STAGE_UNKNOWN, "change-1",
        "branch change-1 does not exist; the open proposed change pc-1 still names it (Infrahub cancels it about "
        "sixteen seconds after a branch is deleted); until then its branch point and head have no at", "resolve")]
    assert s.calls == ["change-2@", "main@"]
    assert not found.rejected


def test_list_orphans():
    r, s = story()
    r.orphans_ = [mark("st-o1", "cabled", CABLED_AT), mark("st-o2", "live", CABLED_AT, LIVE_AT)]
    res, found = stages.list_stages(r, s, "change-2", TEST_SCOPE)
    assert not found.rejected
    assert res.orphans == [stages.Orphan("st-o1", "cabled", CABLED_AT, "written"),
                           stages.Orphan("st-o2", "live", LIVE_AT, "given")]
    assert list(found) == [
        Finding(WARNING, stages.RULE_STAGE_ORPHANED, "st-o1",
                'stage "cabled" (id st-o1) names no proposed change: it was removed from its proposed change\'s '
                "fylgja_stages; delete the stage"),
        Finding(WARNING, stages.RULE_STAGE_ORPHANED, "st-o2",
                'stage "live" (id st-o2) names no proposed change: it was removed from its proposed change\'s '
                "fylgja_stages; delete the stage"),
    ]


def test_list_main_moved():
    r, s = story()
    s.by_branch["main"] = Stamps("2026-10-16T17:30:00.000000+00:00", {})  # after change-1's branch point
    _, found = stages.list_stages(r, s, "", TEST_SCOPE)
    assert [(f.rule, f.object) for f in found] == [(stages.RULE_STAGE_MAIN_MOVED, "change-1")]
    assert not found.rejected
    assert s.calls.count("main@") == 1


def record(label, at, source):
    """A record built from one of change-1's stages, at the reference it resolved to then."""
    branch = "main" if source == "branch_point" else "change-1"
    return stages.RecordView(stages.RecordChange("pc-1", "change-1"), label, branch, at, source, state="ready")


SUFFIX = "; the twin is pinned to what it was built from"


def built(rec):
    return f"the twin was built from stage {rec.ref} at branch {rec.branch}, at {rec.at} ({rec.at_source}); "


def moved_of(found):
    return [f for f in found if f.rule == stages.RULE_STAGE_TWIN_MOVED]


def twin_moved_warning(rec, message):
    return [Finding(WARNING, stages.RULE_STAGE_TWIN_MOVED, str(rec.ref), message)] if message else []


LIVE = change1().stages[0]
CABLED = record("cabled", CABLED_AT, "written")
MOVED_HEAD = record("head", "2026-10-16T17:29:00.000001+00:00", "head")

MARKS_THE_RECORD = [
    ("unchanged", None, None, CABLED, "", ["change-1/cabled"], ""),
    ("its description edited", [change1(LIVE, mark("st-cabled", "cabled", CABLED_AT, None, "renamed")), change2()],
     None, CABLED, "", ["change-1/cabled"], ""),
    ("an as_of written on it",
     [change1(LIVE, mark("st-cabled", "cabled", CABLED_AT, "2026-10-16T17:26:00.000000+00:00")), change2()], None,
     CABLED, "", ["change-1/cabled"],
     built(CABLED) + "change-1/cabled now resolves to branch change-1, at 2026-10-16T17:26:00.000000+00:00 (given)"
     + SUFFIX),
    ("the mark deleted", [change1(LIVE), change2()], None, CABLED, "", [],
     built(CABLED) + "change-1/cabled no longer exists" + SUFFIX),
    ("the mark deleted, listing its branch", [change1(LIVE), change2()], None, CABLED, "change-1", [],
     built(CABLED) + "change-1/cabled no longer exists" + SUFFIX),
    ("the mark deleted, listing another branch", [change1(LIVE), change2()], None, CABLED, "change-2", [], ""),
    ("the head unmoved", None, None, record("head", HEAD_AT, "head"), "", ["change-1/head"], ""),
    ("the head moved", None, None, MOVED_HEAD, "", ["change-1/head"],
     built(MOVED_HEAD) + f"change-1/head now resolves to branch change-1, at {HEAD_AT} (head)" + SUFFIX),
    ("a rebase", None, lambda r, s: _edit_branch(r, "change-1", branched_from="2026-10-16T17:37:22.940060Z"),
     record("branch-point", BRANCHED_FROM, "branch_point"), "", ["change-1/branch-point"],
     built(record("branch-point", BRANCHED_FROM, "branch_point"))
     + "change-1/branch-point now resolves to branch main, at 2026-10-16T17:37:22.940060Z (branch_point)" + SUFFIX),
    ("the proposed change closed", [change2()], None, CABLED, "", [],
     built(CABLED) + "proposed change pc-1 is no longer open, so change-1/cabled is gone" + SUFFIX),
    ("a mark labelled head is not the record's derived head",
     [change1(LIVE, mark("st-cabled", "cabled", CABLED_AT),
              mark("st-head", "head", "2026-10-16T17:27:00.000000+00:00")), change2()],
     None, record("head", HEAD_AT, "head"), "", ["change-1/head"], ""),
]


@pytest.mark.parametrize("name,pcs,edit,rec,branch,marked,message", MARKS_THE_RECORD,
                         ids=[c[0] for c in MARKS_THE_RECORD])
def test_list_marks_the_record(name, pcs, edit, rec, branch, marked, message):
    r, s = story(*(pcs or []))
    if edit:
        edit(r, s)
    res, found = stages.list_stages(r, s, branch, TEST_SCOPE, rec)
    got = []
    for row in res.rows:
        if row.twin:
            got.append(str(row.resolved.ref))
            assert (row.resolved.id == "") is rec.derived
    assert got == marked
    assert moved_of(found) == twin_moved_warning(rec, message)
    assert res.record == rec


EDGE = "tag:edge"
EDGE_LATEST = "2026-10-16T17:29:00.000000+00:00"
EDGE_HEAD = "2026-10-16T17:29:00.000001+00:00"


def scoped(label, at, source, scope):
    return replace(record(label, at, source), scope=scope)


RECORDS_HEAD = [
    ("its head unmoved", scoped("head", EDGE_HEAD, "head", EDGE), "", EDGE_LATEST, None, [TEST_SCOPE, EDGE], ""),
    ("its head moved", scoped("head", EDGE_HEAD, "head", EDGE), "", "2026-10-16T17:29:30.000000+00:00", None,
     [TEST_SCOPE, EDGE],
     built(scoped("head", EDGE_HEAD, "head", EDGE))
     + "change-1/head now resolves to branch change-1, at 2026-10-16T17:29:30.000001+00:00 (head)" + SUFFIX),
    ("a removal after its latest stamp", scoped("head", "2026-10-16T17:29:40.000001+00:00", "head", EDGE), "",
     EDGE_LATEST, [Event("infrahub.node.deleted", "2026-10-16T17:29:40.000000+00:00", "DcimDevice", ["n4"])],
     [TEST_SCOPE, EDGE], ""),
    ("a record of the listing's scope", scoped("head", HEAD_AT, "head", TEST_SCOPE), "", EDGE_LATEST, None,
     [TEST_SCOPE], ""),
    ("a mark of another scope", scoped("cabled", CABLED_AT, "written", EDGE), "", EDGE_LATEST, None, [TEST_SCOPE], ""),
    ("a record naming no scope", scoped("head", EDGE_HEAD, "head", ""), "", EDGE_LATEST, None, [TEST_SCOPE],
     built(scoped("head", EDGE_HEAD, "head", "")) + f"change-1/head now resolves to branch change-1, at {HEAD_AT} "
     "(head)" + SUFFIX),
    ("a listing of another branch", scoped("head", EDGE_HEAD, "head", EDGE), "change-2",
     "2026-10-16T17:29:30.000000+00:00", None, [], ""),
]


@pytest.mark.parametrize("name,rec,branch,edge,evs,scopes,message", RECORDS_HEAD, ids=[c[0] for c in RECORDS_HEAD])
def test_list_judges_the_records_head_under_its_scope(name, rec, branch, edge, evs, scopes, message):
    r, s = story()
    s.by_scope = {f"change-1 {EDGE}": fresh_stamps(edge)}
    if evs is not None:
        r.events = {"change-1": evs}
    res, found = stages.list_stages(r, s, branch, TEST_SCOPE, rec)
    assert moved_of(found) == twin_moved_warning(rec, message)
    assert [s.scopes[i] for i, c in enumerate(s.calls) if c == "change-1@"] == scopes
    for row in res.rows:
        if str(row.resolved.ref) == "change-1/head":
            assert row.resolved.at == HEAD_AT and row.twin is (rec.label == "head")


def found_change(branch="change-1", *pcs):
    """The open proposed change on branch, found as twin step finds it among pcs: change-1
    with three marks, cabled, live and wired, and change-2 when pcs is empty."""
    if not pcs:
        pcs = (with_marks(change1(), mark("st-wired", "wired", "2026-10-16T17:30:05.000000+00:00")), change2())
    r, s = story(*pcs)
    return find(r, s, branch)


REOPENED = replace(change1(*change1().stages), id="pc-9")

MOVED_OF_THE_FOUND_CHANGE = [
    ("a mark unmoved", None, False, "", CABLED, ""),
    ("a given mark unmoved", None, False, "", record("live", LIVE_AT, "given"), ""),
    ("the branch point unmoved", None, False, "", record("branch-point", BRANCHED_FROM, "branch_point"), ""),
    ("the head unmoved", None, False, "", record("head", HEAD_AT, "head"), ""),
    ("the head moved", None, False, "", MOVED_HEAD,
     built(MOVED_HEAD) + f"change-1/head now resolves to branch change-1, at {HEAD_AT} (head)" + SUFFIX),
    ("a mark's as_of edited",
     [change1(LIVE, mark("st-cabled", "cabled", CABLED_AT, "2026-10-16T17:26:00.000000+00:00"))], False, "", CABLED,
     built(CABLED) + "change-1/cabled now resolves to branch change-1, at 2026-10-16T17:26:00.000000+00:00 (given)"
     + SUFFIX),
    ("the mark deleted", [change1(LIVE)], False, "", CABLED,
     built(CABLED) + "change-1/cabled no longer exists" + SUFFIX),
    ("another proposed change opened on the branch, the target's", [REOPENED], False, "", CABLED, ""),
    ("another branch's proposed change, the target's", None, False, "change-2", CABLED, ""),
    ("another branch's, the record's head moved", None, False, "change-2", MOVED_HEAD, ""),
    ("no open proposed change", None, True, "", CABLED,
     built(CABLED) + "proposed change pc-1 is no longer open, so change-1/cabled is gone" + SUFFIX),
]


@pytest.mark.parametrize("name,pcs,none,on,rec,message", MOVED_OF_THE_FOUND_CHANGE,
                         ids=[c[0] for c in MOVED_OF_THE_FOUND_CHANGE])
def test_moved_of_the_found_change(name, pcs, none, on, rec, message):
    ch = None if none else found_change(on or "change-1", *(pcs or []))
    assert list(stages.twin_moved(ch, rec)) == twin_moved_warning(rec, message)


def test_list_is_stable():
    rec = record("cabled", "2026-10-16T17:00:00.000000+00:00", "written")

    def run():
        r, s = story(change2(), with_marks(change1(), mark("st-head", "head", CABLED_AT)))
        r.orphans_ = [mark("st-o", "o", CABLED_AT)]
        s.by_branch["main"] = Stamps("2026-10-16T17:50:00.000000+00:00", {})
        res, found = stages.list_stages(r, s, "", TEST_SCOPE, rec)
        return res, list(found)

    first = run()
    for _ in range(5):
        assert run() == first


# target_test.go

STAGES = "branch-point, cabled, live, wired, head"


def skipped_warning(object, message):
    return [Finding(WARNING, stages.RULE_STEP_STAGE_SKIPPED, object, message, "resolve")]


def target_refusal(rule, object, message):
    return [stages.refusal(rule, object, message)]


WIRED_AT = "2026-10-16T17:30:05.000000+00:00"
REF = stages.Ref

TARGET_BY_POSITION = [
    ("the next, from the branch point", None, record("branch-point", BRANCHED_FROM, "branch_point"), None,
     REF("change-1", "cabled"), None, []),
    ("the next, from a mark", None, CABLED, None, REF("change-1", "live"), None, []),
    ("the head, when no mark follows", None, record("wired", WIRED_AT, "written"), None, REF("change-1", "head"), None,
     []),
    ("a given one forward", None, CABLED, REF("change-1", "live"), REF("change-1", "live"), None, []),
    ("a given one back", None, record("live", LIVE_AT, "given"), REF("change-1", "cabled"), REF("change-1", "cabled"),
     None, []),
    ("the head moved since the record is a target", None, MOVED_HEAD, REF("change-1", "head"), REF("change-1", "head"),
     None, []),
    ("a mark whose as_of was edited is a target", None, record("live", "2026-10-16T17:29:00.000000+00:00", "given"),
     REF("change-1", "live"), REF("change-1", "live"), None, []),
    ("the branch point to the head, skipping every mark", None, record("branch-point", BRANCHED_FROM, "branch_point"),
     REF("change-1", "head"), REF("change-1", "head"), ["cabled", "live", "wired"],
     skipped_warning("change-1/head", "the step from change-1/branch-point to change-1/head skips stages cabled, "
                                      "live, wired; the step is between the two bundles either way")),
    ("back, skipping one", None, record("wired", WIRED_AT, "written"), REF("change-1", "cabled"),
     REF("change-1", "cabled"), ["live"],
     skipped_warning("change-1/cabled", "the step from change-1/wired to change-1/cabled skips stage live; the step "
                                        "is between the two bundles either way")),
    ("another proposed change on the same branch, none given", [REOPENED], CABLED, None, None, None,
     target_refusal(stages.RULE_STEP_TARGET_UNKNOWN, "change-1/cabled",
                    "proposed change pc-1 on branch change-1, the twin's, is no longer open "
                    "(the open proposed change on change-1 is pc-9), so the twin has no next stage; "
                    "give --stage <branch>/<label> or --snapshot <id|file>")),
    ("nothing after the head", None, record("head", HEAD_AT, "head"), None, None, None,
     target_refusal(stages.RULE_STEP_TARGET_UNKNOWN, "change-1/head",
                    f"proposed change pc-1 on change-1 has no stage after change-1/head; its stages are: {STAGES}")),
    ("nothing after the head, which has moved", None, MOVED_HEAD, None, None, None,
     target_refusal(stages.RULE_STEP_TARGET_UNKNOWN, "change-1/head",
                    f"proposed change pc-1 on change-1 has no stage after change-1/head; its stages are: {STAGES}"
                    f"; the head has moved since the twin was built (now at {HEAD_AT}): --stage change-1/head steps "
                    "to it")),
    ("the record's label gone", None, record("deleted", "2026-10-16T17:27:00.000000+00:00", "written"), None, None,
     None, target_refusal(stages.RULE_STEP_TARGET_UNKNOWN, "change-1/deleted",
                          "the twin's stage change-1/deleted is no longer a stage of proposed change pc-1 on branch "
                          f"change-1; its stages are: {STAGES}")),
    ("the record's label gone, a target given", None, record("deleted", "2026-10-16T17:27:00.000000+00:00", "written"),
     REF("change-1", "head"), REF("change-1", "head"), None, []),
    ("a label the proposed change lacks", None, CABLED, REF("change-1", "nosuch"), None, None,
     target_refusal(stages.RULE_STEP_TARGET_UNKNOWN, "change-1/nosuch",
                    f'proposed change pc-1 on change-1 has no stage "nosuch"; its stages are: {STAGES}')),
    ("the record's own stage", None, record("live", LIVE_AT, "given"), REF("change-1", "live"), None, None,
     target_refusal(stages.RULE_STEP_TARGET_CURRENT, "change-1/live",
                    f"the twin is already at stage change-1/live (branch change-1, at {LIVE_AT}); the proposed "
                    f"change's stages are: {STAGES}")),
    ("the record's own head", None, record("head", HEAD_AT, "head"), REF("change-1", "head"), None, None,
     target_refusal(stages.RULE_STEP_TARGET_CURRENT, "change-1/head",
                    f"the twin is already at stage change-1/head (branch change-1, at {HEAD_AT}); the proposed "
                    f"change's stages are: {STAGES}")),
    ("another label at the record's reference", None, record("head", LIVE_AT, "head"), REF("change-1", "live"), None,
     None, target_refusal(stages.RULE_STEP_TARGET_CURRENT, "change-1/live",
                          f"the twin is already at stage change-1/live (branch change-1, at {LIVE_AT}); the proposed "
                          f"change's stages are: {STAGES}")),
    ("the next at the record's reference",
     [with_marks(change1(), mark("st-also", "also", "2026-10-16T17:31:00.000000+00:00", LIVE_AT))],
     record("also", LIVE_AT, "given"), None, None, None,
     target_refusal(stages.RULE_STEP_TARGET_CURRENT, "change-1/live",
                    f"the twin is already at stage change-1/live (branch change-1, at {LIVE_AT}); the proposed "
                    "change's stages are: branch-point, cabled, also, live, head")),
    ("the next with no at is no current", [with_marks(change1(), mark("st-none", "none", ""))],
     record("live", LIVE_AT, "given"), None, REF("change-1", "none"), None, []),
]


@pytest.mark.parametrize("name,pcs,rec,given,want,skipped,found_", TARGET_BY_POSITION,
                         ids=[c[0] for c in TARGET_BY_POSITION])
def test_target_by_position(name, pcs, rec, given, want, skipped, found_):
    got, skip, found = stages.target(found_change("change-1", *(pcs or [])), rec, rec.branch, rec.at, given)
    assert (got, skip, list(found)) == (want, skipped, found_)


def test_target_resolves_under_the_reference_rules():
    """The chosen target resolves under the reference contract's own refusals: a target whose
    label two marks share is refused stage.duplicate. (Go's test plans it by Build, the
    plan's, whose port is not this module's; the resolution it runs is resolve_from.)"""
    pcs = (with_marks(change1(), mark("st-live-0", "live", "2026-10-16T17:31:30.000000+00:00")),)
    ch = found_change("change-1", *pcs)
    rec = record("cabled", CABLED_AT, "written")
    chosen, _, found = stages.target(ch, rec, rec.branch, rec.at, None)
    assert not found and chosen == REF("change-1", "live")
    r, s = story(*pcs)
    res, found = stages.resolve_from(r, s, REGISTRY, ch, chosen, NOW)
    assert res is None and [f.rule for f in found] == [stages.RULE_STAGE_DUPLICATE]


REOPENED_WIRED = replace(with_marks(change1(), mark("st-wired", "wired", WIRED_AT)), id="pc-9")

TARGET_OF_ANY = [
    ("another branch's proposed change", "change-2", None, CABLED, CABLED.branch, CABLED.at, REF("change-2", "head"),
     REF("change-2", "head"), []),
    ("another branch's proposed change, lacking the label", "change-2", None, CABLED, CABLED.branch, CABLED.at,
     REF("change-2", "cabled"), None,
     target_refusal(stages.RULE_STEP_TARGET_UNKNOWN, "change-2/cabled",
                    'proposed change pc-2 on change-2 has no stage "cabled"; its stages are: branch-point, head')),
    ("another proposed change on the record's branch", "", [REOPENED_WIRED], CABLED, CABLED.branch, CABLED.at,
     REF("change-1", "wired"), REF("change-1", "wired"), []),
    ("another proposed change on the record's branch, lacking the label", "", [REOPENED_WIRED], CABLED, CABLED.branch,
     CABLED.at, REF("change-1", "nosuch"), None,
     target_refusal(stages.RULE_STEP_TARGET_UNKNOWN, "change-1/nosuch",
                    f'proposed change pc-9 on change-1 has no stage "nosuch"; its stages are: {STAGES}')),
    ("another proposed change's stage at the record's own reference", "", [REOPENED_WIRED], CABLED, "change-1",
     LIVE_AT, REF("change-1", "live"), None,
     target_refusal(stages.RULE_STEP_TARGET_CURRENT, "change-1/live",
                    f"the twin is already at stage change-1/live (branch change-1, at {LIVE_AT}); the proposed "
                    f"change's stages are: {STAGES}")),
    ("no view, a given stage", "", None, None, "fylgja-fixture", "", REF("change-1", "live"), REF("change-1", "live"),
     []),
    ("no view, a given stage of another branch", "change-2", None, None, "change-1", CABLED_AT,
     REF("change-2", "branch-point"), REF("change-2", "branch-point"), []),
    ("no view, a stage the proposed change lacks", "", None, None, "fylgja-fixture", "", REF("change-1", "nosuch"),
     None, target_refusal(stages.RULE_STEP_TARGET_UNKNOWN, "change-1/nosuch",
                          f'proposed change pc-1 on change-1 has no stage "nosuch"; its stages are: {STAGES}')),
    ("no view, the target at the record's own reference", "", None, None, "change-1", LIVE_AT, REF("change-1", "live"),
     None, target_refusal(stages.RULE_STEP_TARGET_CURRENT, "change-1/live",
                          f"the twin is already at stage change-1/live (branch change-1, at {LIVE_AT}); the proposed "
                          f"change's stages are: {STAGES}")),
    ("no view, the record unpinned", "", None, None, "change-1", "", REF("change-1", "head"), REF("change-1", "head"),
     []),
    ("no view, none given", "", None, None, "fylgja-fixture", LIVE_AT, None, None,
     target_refusal(stages.RULE_STEP_TARGET_UNKNOWN, "fylgja-fixture", stages.NO_TARGET_MESSAGE)),
]


@pytest.mark.parametrize("name,on,pcs,view,branch,at,given,want,found_", TARGET_OF_ANY,
                         ids=[c[0] for c in TARGET_OF_ANY])
def test_target_of_any_proposed_change(name, on, pcs, view, branch, at, given, want, found_):
    got, skip, found = stages.target(found_change(on or "change-1", *(pcs or [])), view, branch, at, given)
    assert (got, skip, list(found)) == (want, None, found_)


# blocks_test.go

STAGES_SCHEMA = json.loads((REPO / "contracts" / "stages.schema.json").read_text())


def must_validate(definition, instance):
    """The block validates against one $def of contracts/stages.schema.json."""
    schema = {"$ref": f"{STAGES_SCHEMA['$id']}#/$defs/{definition}"}
    registry = jsonschema.validators.validator_for(STAGES_SCHEMA)
    from referencing import Registry, Resource

    resources = Registry().with_resource(STAGES_SCHEMA["$id"], Resource.from_contents(STAGES_SCHEMA))
    registry(schema, registry=resources).validate(instance)
    return json.dumps(instance, separators=(",", ":"), ensure_ascii=False)


def test_blocks_validate():
    r, s = story()
    r.orphans_ = [mark("st-o1", "lost", CABLED_AT)]
    rec = record("cabled", CABLED_AT, "written")
    res, _ = stages.list_stages(r, s, "", TEST_SCOPE, rec)
    assert len(res.rows) == 6
    for row in res.rows:
        must_validate("resolved", row.resolved.block())
    got = must_validate("list", res.block())
    for want in ['"branch":null', '"twin":true', '"orphans":[{"id":"st-o1","label":"lost"',
                 '"record":{"ref":"change-1/cabled","proposed_change":{"id":"pc-1","branch":"change-1"}',
                 '"towards":null']:
        assert want in got
    assert must_validate("list", stages.ListResult(branch="change-9").block()) == (
        '{"branch":"change-9","rows":[],"orphans":[],"record":null}')
    # A row whose stage has no at carries none: a branch deleted under its proposed change.
    del r.branches["change-1"]
    res, _ = stages.list_stages(r, s, "change-1", TEST_SCOPE)
    got = must_validate("list", res.block())
    assert ('{"ref":"change-1/branch-point","branch":"main","label":"branch-point","proposed_change":{"id":"pc-1",'
            '"name":"third link","branch":"change-1","draft":true},"at_source":"branch_point","description":"",'
            '"twin":false}') in got


def test_record_view_of():
    r, s = story()
    res, _ = stages.list_stages(r, s, "change-1", TEST_SCOPE)
    cabled_ = res.rows[1].resolved
    v = stages.RecordView(stages.RecordChange(cabled_.proposed_change.id, cabled_.proposed_change.branch),
                          cabled_.label, "change-1", cabled_.at, cabled_.at_source, state="diverged", towards="live")
    got = must_validate("record", v.block())
    assert '"state":"diverged","towards":{"ref":"change-1/live"}' in got


# The golden: the listing, through the real reader and stamper, on recorded answers.


def serve_recorded(infrahub, name):
    """The recorded answers of one listing: the default branch's operations by name, each
    branch's stamps by operation and branch, and the branches the schema endpoint knows."""
    recorded = json.loads((RECORDED / name).read_text())
    infrahub.branches.update(recorded["branches"])
    infrahub.default_schema = recorded["default_schema"]

    def default(operation):
        def answer(variables, query, branch, params):
            return recorded["default"][operation]
        return answer

    def branched(operation):
        def answer(variables, query, branch, params):
            return recorded["branches"][branch][operation]
        return answer

    for operation in recorded["default"]:
        infrahub.default_operations[operation] = default(operation)
    for operation in {op for answers in recorded["branches"].values() for op in answers}:
        infrahub.operations[operation] = branched(operation)
    return recorded


def golden(name):
    return json.loads((GOLDEN / name).read_text())


@pytest.mark.parametrize("name,rec", [
    ("stages.json", None),
    ("stages-with-twin.json", stages.RecordView(
        stages.RecordChange("18e3127c-025b-f488-33be-c5158cf576c3", "fylgja-test-golden-41263"), "seeded",
        "fylgja-test-golden-41263", "2026-10-29T18:11:38.471611+00:00", "written", "tag:fylgja")),
])
def test_the_listing_is_the_golden(infrahub, name, rec):
    """The golden's proposed change as Infrahub answered it (its id, its marks' ids, ats and
    descriptions, its branch's branched_from, the branch's latest stamp one microsecond
    before the head, main holding no device): the block equals the Go server's `stages`
    block, and the listing files no finding, as the golden's."""
    recorded = serve_recorded(infrahub, "golden.json")
    default = DefaultClient(ADDRESS, TOKEN, requester=infrahub)
    reader = sr.StageReader(default)

    res, found = stages.list_stages(reader, stages.stamper_of(default), recorded["branch"], "tag:fylgja", rec)

    want = golden(name)
    assert list(found) == want["findings"] == []
    assert res.block() == want["stages"]
    must_validate("list", res.block())


# Infrahub's side: the stamper and the read-and-take.


def test_the_stamper_checks_each_branch_once(infrahub):
    """A branch's conformance is asked once and remembered: a conforming branch's stamps are
    read at each `at` asked, one that does not conform refuses every read with its schema.*
    findings, which the stages file at resolve naming the branch."""
    recorded = serve_recorded(infrahub, "golden.json")
    stamper = stages.Stamper(ADDRESS, TOKEN, infrahub)
    branch = recorded["branch"]

    assert stamper.stamps(branch, "", TEST_SCOPE).latest == "2026-10-29T18:12:10.636974+00:00"
    stamper.stamps(branch, "2026-10-29T18:11:38.471611+00:00", TEST_SCOPE)
    assert infrahub.count("/api/schema") == 1
    pinned = [r for r in infrahub.served("IntentStamps") if r["query"].get("at")]
    assert [r["query"]["at"] for r in pinned] == [["2026-10-29T18:11:38.471611+00:00"]]
    assert all(r["variables"]["tag"] == "fylgja" for r in infrahub.served("IntentStamps"))

    infrahub.schema = {**infrahub.schema, "nodes": [n for n in infrahub.schema["nodes"] if n["kind"] != "DcimDevice"]}
    other = stages.Stamper(ADDRESS, TOKEN, infrahub)
    for _ in range(2):
        with pytest.raises(ConformanceError) as e:
            other.stamps("main", "", TEST_SCOPE)
    assert infrahub.count("/api/schema") == 2
    refused = stages.conformance_refusal(e.value)
    assert refused and all(f.step == "resolve" and f.message.startswith("branch main: ") for f in refused)


def test_read_stage_reads_the_resolved_reference(infrahub, monkeypatch):
    """A stage resolved, then its branch read at its at under the scope and taken: the client
    the read is given names the resolved (branch, at), and the resolution's warnings come
    first. A refused resolution reads nothing."""
    serve_recorded(infrahub, "golden.json")
    default = DefaultClient(ADDRESS, TOKEN, requester=infrahub)
    reads = []

    def read_snapshot(client, scope, registry, probes=None, observed_at=None, out=None):
        reads.append((client.branch, client.at, scope, probes))
        return {"snapshot_id": "s"}, Findings([Finding(WARNING, "omit.cable.kind", "c1", "read")])

    monkeypatch.setattr(stages.reading, "read_snapshot", read_snapshot)
    ref = stages.Ref("fylgja-test-golden-41263", "seeded")
    res, taken, found = stages.read_stage(default, ref, TEST_SCOPE, REGISTRY, [{"name": "p"}],
                                          now=datetime(2026, 10, 29, 19, 0, tzinfo=UTC))
    assert (res.branch, res.at, res.at_source) == ("fylgja-test-golden-41263", "2026-10-29T18:11:38.471611+00:00",
                                                   "written")
    assert taken == {"snapshot_id": "s"} and [f.rule for f in found] == ["omit.cable.kind"]
    assert reads == [("fylgja-test-golden-41263", "2026-10-29T18:11:38.471611+00:00", TEST_SCOPE, [{"name": "p"}])]

    res, taken, found = stages.read_stage(default, stages.Ref("fylgja-test-golden-41263", "nosuch"), TEST_SCOPE,
                                          REGISTRY)
    assert res is None and taken is None and [f.rule for f in found] == [stages.RULE_STAGE_UNKNOWN]
    assert len(reads) == 1


# The live recording: the adapter beside the Go server, on a real Infrahub's answers.


class Replay:
    """Answers each request with the one recorded for its path, query, operation and
    variables; a branch schema answer is the library's recorded schema under the hash the
    branch answered. A request never recorded fails the test."""

    def __init__(self, recorded):
        self.answers = {self.key(a["path"], a["query"], a["operation"], a["variables"]): a
                        for a in recorded["answers"]}

    @staticmethod
    def key(path, query, operation, variables):
        return json.dumps([path, query, operation, variables], sort_keys=True)

    def __call__(self, url, method, headers, timeout, payload=None):
        import httpx
        from urllib.parse import parse_qs, unquote, urlsplit

        assert headers.get("X-INFRAHUB-KEY") == TOKEN
        parts = urlsplit(url)
        body = payload if isinstance(payload, dict) else {}
        key = self.key(unquote(parts.path), parse_qs(parts.query), body.get("operationName"),
                       body.get("variables") or {})
        assert key in self.answers, f"a request never recorded: {key}"
        a = self.answers[key]
        answer = a["body"]
        if "schema_file" in (answer or {}):
            answer = {**json.loads((DATA / "schema" / answer["schema_file"]).read_text()), "main": answer["main"]}
        return httpx.Response(a["status"], content=json.dumps(answer).encode(),
                              request=httpx.Request(method.value, url))


def test_the_recorded_listing_is_the_go_servers():
    """A live proposed change (`tests/data/graphql/stages/live.json`): the listing's block and
    findings equal the Go server's `stage list --json` of the same moment, and each stage
    resolves as its `stage plan` resolved it, at the same at or refused in the same words:
    a nine-digit given as_of `intent.at.precision`, third-link stale on n1 and n3 after the
    link, the branch point, seeded and the head resolved."""
    recorded = json.loads((RECORDED / "live.json").read_text())
    default = DefaultClient(ADDRESS, TOKEN, requester=Replay(recorded))
    reader, stamper = sr.StageReader(default), stages.stamper_of(default)

    res, found = stages.list_stages(reader, stamper, recorded["branch"], TEST_SCOPE)

    assert res.block() == recorded["go"]["stages"]
    assert [vars(f) for f in found] == recorded["go"]["findings"]
    now = datetime.strptime(recorded["now"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    for ref, want in recorded["go"]["resolved"].items():
        got, found = stages.resolve(reader, stamper, REGISTRY, stages.parse_ref(ref), TEST_SCOPE, now)
        assert (got.at if got else None) == want["at"], ref
        assert [{"severity": f.severity, "rule": f.rule, "object": f.object, "message": f.message, "step": f.step}
                for f in found] == want["findings"], ref
