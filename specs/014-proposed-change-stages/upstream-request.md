# Upstream request: named points in time

**Feature**: `014-proposed-change-stages` · **Requirement**: FR-032 · **Drafted**:
2026-10-17, by the loop's Run 17 (T054), through OpsMill's
`infrahub:infrahub-reporting-issues` skill · **Status**: a draft for the operator's
approval (T056). **Never filed by a session.**

- **Target**: [`opsmill/infrahub`](https://github.com/opsmill/infrahub), a feature request.
  The skill's routing: the behaviour is the platform's (GraphQL's `at`, the branch, the
  rebase, the proposed change's view), so no sub-repository owns it.
- **Template**: the repository's `feature_request.yml` (title prefix `feature: `, label
  `type/feature`, fields Component, Describe the Feature Request, Describe the Use Case,
  Additional Information), read from `.github/ISSUE_TEMPLATE/` on 2026-10-17. The body
  below follows its fields.
- **Duplicates**: none. Searched on 2026-10-17 with `gh search issues`, on
  `opsmill/infrahub` for "named point in time", "named timestamp branch", "bookmark
  time", "snapshot name branch", "tag point in time", "rebase history at", "time travel
  rebase", "checkpoint proposed change", "label timestamp", "named diff", "snapshot",
  "tag", "milestone", "time travel", "rebase timestamp", "historical query rebase",
  "branch history", "query at time", "point in time", "release tag" and "version tag",
  and across every `opsmill` repository for "named point in time", "checkpoint", "branch
  tag" and "rebase history". No issue asks for a named point in time, as the brief found.
  The nearest, cited in the body: #9412 (a query-ready timestamp in webhook payloads, the
  same boundary from the other side), #10593 (a diagram of what merge, rebase and delete
  leave queryable) and #7154 (a named diff whose `from_time` precedes the branch cannot be
  retrieved). So this is a new issue, not a comment.
- **The brief's three issues**, read on 2026-10-17, all open: #10592 "the name argument on
  DiffTree and DiffTreeSummary is advertised but unusable"; #10589 "a future at timestamp
  is accepted and silently returns current data"; #1045 "Add ability to change the
  description of a branch". The body says what each has to do with this request.
- **What it rests on**: [research.md](research.md) §2.1 (a read at `branched_from`), §2.6
  (the strict boundary) and §2.7 (a rebase discards history), all verified on Infrahub
  1.11.2 on 2026-10-16 and in [verified-facts.md](../../docs/verified-facts.md);
  [D-045](../../docs/decisions.md#d-045)'s options and its "Revisit if Infrahub gains a
  named point in time or a rebase that keeps history".
- **Sanitised** as the skill's environment rule asks: versions only; no host, address,
  path, log or token. The repro uses symbolic instants (`T`, `t0`), not the development
  host's.
- **For the operator to decide**: whether to name Fylgja and link it (the body does; drop
  the link to keep the request product-neutral), and whether to link D-045, which is not
  on `origin`'s `main` until release 0.2 is pushed.
- **To file, once approved**: the web form at
  <https://github.com/opsmill/infrahub/issues/new?template=feature_request.yml>, pasting
  the title and each field below (the form applies `type/feature`, which an outside
  account cannot set from `gh`); or `gh issue create --repo opsmill/infrahub --title "…"
  --body-file <the body, saved alone>`. Then record the issue's number here and in
  [verified-facts.md](../../docs/verified-facts.md)'s "Reported upstream" style.

---

## Title

```text
feature: named points in time on a branch, kept across a rebase
```

## Component

API Server / GraphQL; Frontend UI

## Describe the Feature Request

A **named point in time**: a name a user gives to an instant of a branch, which Infrahub
stores, lists and accepts wherever it accepts `at`, so that "the state we called
`third-link`" can be read again without the client holding or computing a timestamp.

- **Create** it on a branch with a name and an optional description. The instant is
  Infrahub's own, taken when the mark is made, and placed so that a read at it sees every
  write committed before it.
- **Read** at it by name wherever `at` is taken: GraphQL, REST and the SDK, and the web
  interface's time selector, which would offer the branch's named points.
- **List** a branch's named points in order, and show them in a proposed change's view,
  since the proposed change is where a change is built and reviewed.
- **Keep it across a rebase**: either the history it names stays readable after
  `BranchRebase`, or the point says the rebase invalidated it, rather than reading empty.

Infrahub 1.11.2 has none of this: no branch tag, checkpoint, snapshot or saved
time-travel view. The time selector writes an `at` URL parameter and saves nothing, and
`Branch` is not a schema kind, so a user kind cannot relate to one.

## Describe the Use Case

[Fylgja](https://github.com/happypathnetworking/fylgja) rehearses a proposed change on a
network twin: a containerlab lab built from a branch's intent and the artifacts Infrahub
renders for it. An operator builds a change in stages on a draft proposed change
(`seeded`, then `third-link`, then the head) and steps one twin from stage to stage. Each
stage must name an instant of the branch, reproducibly, for as long as the branch lives.

We built the mark as a user kind: a branch-agnostic `FylgjaStage` with a required
relationship to `CoreProposedChange`, a label unique within it and an optional `as_of`.
Its instant is the stamp Infrahub returns for the mark's own writing. The branch point is
read on the default branch, pinned at the source branch's `branched_from`, and the head is
pinned one microsecond after the later of the latest `updated_at` across the branch's
intent and its artifacts' checksums and the `occurred_at` of the branch's latest intent
event in `InfrahubEvent`, since a removal moves no stamp. It works, but three parts of it
are workarounds a native mark would retire:

1. **The boundary is strict, so a client must offset every stamp it pins.** A read pinned
   at exactly an attribute's `updated_at` returns the node with every attribute `null`;
   one microsecond later it returns the values, and one microsecond earlier no node. The
   comparison is strict on the value's stamp and inclusive on the node's `created_at`, and
   it is not a truncation: a nine-digit `at` one nanosecond after the stamp returns the
   values. The same holds for an artifact: pinned at exactly its `checksum.updated_at`,
   the checksum read is the previous version's. So "the state as of this write" is the
   stamp plus an increment the client chooses; we add one microsecond, the smallest a
   six-digit `at` carries. #9412 meets the same boundary from the webhook side.
2. **A rebase discards a branch's history from pinned reads.** `BranchRebase` moves
   `branched_from` to the rebase's moment and re-stamps every attribute on the branch at
   it (`created_at` does not move). Pinned at any instant before the rebase, a read on the
   branch returns no device and no artifact where it returned three of each before; at
   exactly the new `branched_from`, the nodes with `null` values; one microsecond later,
   everything, with the branch's own values rather than the base's. So every mark made
   before a rebase reads nothing after it, and a read on the branch at its `branched_from`
   is no longer the base, which is why we read the branch point on the default branch.
   We refuse every mark at once after a rebase and ask the operator to mark again.
   #10593 asks for a diagram of what merge, rebase and delete leave queryable; this is
   the rebase's effect on the branch itself.
3. **The proposed change's view does not show the marks.** They are on their own kind's
   page, so a reviewer of the proposed change does not see the stages it was built in.

## Additional Information

- Observed on Infrahub 1.11.2 (Docker Compose), with infrahub-sdk 1.23.2.
- Related issues:
  - #10592: the `name` argument on `DiffTree` and `DiffTreeSummary` is advertised but
    unusable. A named diff is the one named thing over time the API offers today, and it
    cannot be retrieved by its name.
  - #10589: a future `at` is accepted and silently returns current data, so a client
    pinning a set of queries at an instant cannot tell one that was reached from one that
    was not. A point Infrahub stamps itself could never be in the future.
  - #1045: changing a branch's description from the web interface. The description is a
    branch's only free text; there is no other branch metadata a mark could hang from.
  - #9412 (a query-ready timestamp in webhook payloads), #10593 (what history merge,
    rebase and delete leave queryable) and #7154 (a named diff whose `from_time` precedes
    the branch cannot be retrieved).
- To reproduce the boundary: on any branch, take a node whose `name` was written at `T`
  (read `name { updated_at }`). `POST /graphql/<branch>?at=T` returns the node with
  `name.value` `null`; `?at=T+1µs` returns the value; `?at=T-1µs` returns no node.
- To reproduce the rebase: on a branch with nodes of its own, note an instant `t0` at
  which a pinned read returns them. Run `BranchRebase(data: {name: "<branch>"},
  wait_until_completion: true)`. The same read pinned at `t0` on the branch returns none.
- A read pinned at exactly `branched_from` returns the default branch as it then stood,
  back to the default branch's creation, before which `at` is refused with a 422. On the
  default branch, a read pinned at `branched_from` is the base before and after a rebase;
  on the branch after a rebase, the same read returns the branch's re-stamped content.
