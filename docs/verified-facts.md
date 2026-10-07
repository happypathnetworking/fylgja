# Fylgja — Verified facts

A **verified fact** is something about a dependency that was checked against the running
system, not taken from its documentation or from memory: how Infrahub, containerlab, a
network operating system, Temporal or the host actually behaves. Each fact below names the
version it was verified against and the date. Re-verify a fact on any upgrade of the
system it names, and before a change depends on one that is not here, verify it and add
it, as the [development guide](development.md#verification-is-just-in-time) says. A fact a
session needs in every task is also in `CLAUDE.md`; this document holds the rest, read on
demand.

Terms are the [glossary](glossary.md)'s. Dates are 2026.

---

## Infrahub 1.11.2

**Reading intent**

- Infrahub filters on `created_at <= at`, so a read pinned to a second-granularity local
  "now" hides objects written in that second: send no `at` unless the operator supplied
  one. *(09-14)*
- GraphQL takes the branch in the path, `POST /graphql/<branch>`; a `?branch=` parameter
  there is ignored and answers for `main` with no error. *(09-30)*
- `POST /graphql` and `GET /api/schema` with no branch answer for the default branch.
  *(09-28)*
- A pinned `at` carries at most six fractional digits: Infrahub takes nine, and Fylgja
  refuses more than six (`intent.at.precision`). *(09-16)*
- On a host where Infrahub runs in Docker beside Fylgja, a local clock read after a seed
  returns sees the whole seed, since both share the kernel's clock (verified under WSL2).
  *(09-16)*
- This Infrahub reads anonymously: no token is 200 on GraphQL, the schema and storage,
  and a wrong token is 401, so no token exists that reads intent and cannot read content.
  *(09-18)*

**The schema**

- `POST /api/schema/load` rebuilds the branch's GraphQL schema asynchronously: poll for
  the new mutations before seeding. *(09-14)*
- Attribute names `class` and `type` are refused, descriptions are capped at 128
  characters, and strict mode is on; check a candidate with `POST /api/schema/check`.
  *(09-14)*
- An attribute name is 3–64 characters of `[a-z0-9_]`, so `at` is refused by the JSON
  schema before it reaches the server; the waypoint's attribute is `as_of`. *(09-28)*
- On a branch without the Fylgja schema the generics are not GraphQL types at all: read
  `GET /api/schema` first, whose `used_by` is the conformance check. *(09-14)*
- The IPAM core generic is `BuiltinIPAddress`; `IpamIPAddress` is a demo-schema name.
  *(09-14)*
- The SDL is at `GET /schema.graphql?branch=`, and its field order is not stable between
  two fetches of one branch: compare two SDLs structurally, never with `diff`. *(09-28)*
- `GET /api/schema/summary?branch=` returns the branch's schema hash as `main`; the hash
  covers the branch's whole schema, so two branches whose schemas differ, and two installs,
  have different hashes. *(09-14)*
- A branch sees `main` as it was when the branch was created, so a branch made before the
  schema, the group or the template existed on `main` cannot render. *(09-18)*

**Branch-agnostic kinds (the waypoint)**

- A branch-agnostic kind loads with a uniqueness constraint over two attributes, and a
  duplicate is refused from any branch as `Violates uniqueness constraint
  'series-sequence'`: HTTP 200 on the wire, with `http_status: 422` in the extensions.
  *(09-28)*
- A branch-agnostic object is read from every branch whose schema has its kind, and
  outlives the branch it names. *(09-28)*
- A branch whose schema lacks the kind cannot query it at all: `Cannot query field
  'FylgjaWaypoint' on type 'Query'`, HTTP 200 with a 500 in the extensions that names
  nothing, so read the kind's presence from `GET /api/schema` first. *(09-28)*
- At creation every attribute carries one `updated_at` (six fractional digits, `+00:00`),
  and only a real change of its value moves it: a description edit leaves `branch`'s
  stamp, and re-pointing `branch` moves it. No node-level `_updated_at` is queryable on a
  Fylgja kind. *(09-28)*
- A DateTime attribute keeps a written value character for character and refuses only
  nonsense; GraphQL types it as text, so an unwritten one reads `""`. A Number attribute's
  value is a `BigInt`, which genqlient binds to `int`. *(09-28)*
- An object file's top-level `kind` is `Object`, with the node's kind under `spec.kind`;
  `infrahubctl object validate` checks one without writing. *(09-28)*

**Artifacts and repositories**

- Infrahub regenerates no artifact on its own: not on a data change, a group join or a
  commit import. Generation is `POST /api/artifact/generate/<definition id>?branch=`,
  which returns `null` in about 0.1s; three artifacts were `Pending` at 6.4s and `Ready`
  at 7.6s. *(09-18)*
- Nothing marks an artifact stale. A regeneration to identical bytes writes nothing, not
  even a storage id; one that changes bytes returns before the rewrite, and the artifact
  stays `Ready` throughout, so wait for its checksum to move. *(09-18)*
- `CoreArtifact.checksum` is the MD5 hex of the bytes `GET /api/storage/object/<storage_id>`
  serves. A listing pinned to `at` gives the storage id as of `at`, and the older object
  is still served. *(09-18)*
- A branch created with `sync_with_git: false`, as every test branch is, keeps the
  repository commit it forked with: a template commit reaches it only by `BranchRebase`,
  then a generate. *(09-18)*
- A `BranchCreate` straight after a `BranchDelete` of the same name can fail with
  `graphql: None`; run it again. *(09-18)*
- The repository sync (Prefect's `git_repositories_sync`) runs every minute with one
  concurrency slot, so one run stuck `PENDING` blocks every import until it is cancelled.
  *(09-18)*
- `CoreRepository` and `CoreReadOnlyRepository` are both branch-agnostic and take an
  optional credential. A public HTTPS repository registers as a `CoreReadOnlyRepository`
  on `main` with no credential: the clone and the connectivity check pass, and the import
  then reads the repository's `.infrahub.yml`. *(10-06)*
- A `CoreReadOnlyRepository` imports at its creation, its `commit` the head of its `ref`,
  and afterwards only when asked: a commit pushed to `ref` is not picked up by the minute
  sync (three minutes on, `commit` unmoved and `sync_status in-sync`), nor by a
  `CoreReadOnlyRepositoryUpdate` writing `ref`'s own value (`ok: true`, nothing written).
  `InfrahubReadOnlyRepositoryImportLastCommit(data: {id})` imports the head of `ref`:
  `commit` moved 8s after the call. *(10-07)*
- Deleting a `CoreRepository` deletes the query, the transform and the artifact
  definition its import made; a later registration's import makes them anew, with new
  ids. *(10-07)*

---

## containerlab 0.79.0

- `clab deploy` creates `clab-<lab>/` beside the topology file, or under
  `CLAB_LABDIR_BASE` when it is set, mostly root-owned; `clab destroy --cleanup` removes
  it without sudo in about 1s. *(09-15)*
- containerlab applies an SR Linux `.cli` startup snippet over the default configuration
  and commits it itself, so the snippet carries no `commit` line; LLDP and gNMI are on by
  default. *(0.77, 09-15)*
- `inspect --all --format json` gives each container's `absLabPath`, always absolute;
  `labPath` is relative to the caller's directory when the topology file is under it, so
  decode `absLabPath`. *(09-16)*
- `inspect` reports an exited container's address as `N/A`. *(10-03)*
- `/usr/bin/containerlab` is setuid root, so the kernel clears `Pdeathsig` when it starts,
  and a `clab deploy` outlives a worker killed with `kill -9`: stop a stray `clab` before
  acting. *(09-15)*
- A plain re-deploy of a partial lab skips containerlab's post-deploy and leaves the
  bootstrap unapplied; deploy over a partial lab with `--reconfigure`. *(09-15)*
- `clab deploy --dry-run --format json` prints a plan on stdout (`added-nodes`,
  `deleted-nodes`, `recreated-nodes`, `restarted-nodes`, `added-links`,
  `deleted-endpoints`, `node-change-reasons`) and writes nothing. *(10-01)*
- That dry run must run with `CLAB_LABDIR_BASE` at the running lab's directory:
  containerlab decides a recreate from `.state.clab.yaml` there, so from any other base an
  image or kind change is invisible, and with no running lab under the base it answers
  `deployed-lab: true` with every list `null`. *(10-01)*
- `clab deploy` without `--reconfigure` reconciles a running lab: a link added or removed
  re-cables SR Linux live and restarts a cEOS node in place (3.5–14.6s for the apply); a
  node added is created with containerlab's post-deploy (31.3s); an image or kind change
  is a recreate (20.3s, 58.7s with a far cEOS end's restart); a node removed is deleted
  (0.85s); nothing to do takes 0.39s. *(10-01)*
- A changed SR Linux `.cli` is never applied to a running node by a reconcile. *(10-01)*
- Disabling one end of a containerlab link takes the link down at both ends: both are
  oper `down`, neither has a neighbour, and the far end's admin-state stays `enable`.
  *(09-19)*

---

## SR Linux 24.7.1

**Booting** (one node, Infrahub idle)

- From deploy start the container runs at 0.6s and `sr_cli` answers at 2s, which is
  **not** readiness; `clab deploy` returns at 12.4s, and gNMI `:57400` opens and completes
  a TLS handshake at 15.2–15.4s. *(09-15)*
- One booted node holds about 1.57 GiB (cgroup `memory.current`, steady over a minute).
  *(09-15)*
- The chassis is the `7220 IXR-D2L`, containerlab's default `type` for `nokia_srlinux`.
  Its front ports are `ethernet-1/1` to `ethernet-1/58`, beside `lo0` and `mgmt0`: a push
  naming `ethernet-1/99` is refused `invalid port 99, max is 58`, and one naming
  `ethernet-2/1` `invalid slot 2`. *(09-19)*
- The node's name for a port is `ethernet-1/1`, not containerlab's endpoint name `e1-1`:
  `set / interface e1-1 admin-state enable` is refused. *(09-15)*
- Every LLDP adjacency forms before `clab deploy` returns, so a read after the twin is
  `ready` never waits for a neighbour. *(09-19)*
- SR Linux writes to containerlab's node directory on its own
  (`clab-fylgja/<node>/config/gnoi/healthz/events/events.data` moves on every node), so a
  digest of the whole twin directory moves with nothing read. *(10-03)*
- It boots on Ubuntu only once AppArmor allows its `rsyslogd` ([the host](#the-host)).
  *(09-30)*

**gNMI**

- gNMI listens in the management namespace: reach it from the host at the node's
  management address, or by name through containerlab's `/etc/hosts` entry, not from
  inside the container. *(09-15)*
- The encoding must be set: gnmic's default JSON gets `Unimplemented` ("Only ASCII,
  PROTO/TYPED_VAL, JSON_IETF, … supported"), so a probe on the default never succeeds;
  `json_ietf` works. *(09-15)*
- The paths: `/system/name/host-name`; `/system/information/version`
  (`v24.7.1-330-g38f237abfe`); `/interface[name=X]/admin-state`;
  `/system/lldp/interface[name=X]/admin-state`; and `…/neighbor`, whose `system-name` is
  the far node and whose `port-id` is the far port under the far node's own name
  (`port-id-type INTERFACE_NAME`). *(09-19)*
- A leaf comes back as one update at the leaf; a subtree comes back as one update at the
  list entry, with the subtree inside its value, the update path's elements carrying
  module prefixes and the keys inside the value carrying none. *(09-19)*
- An absent value is no update and no error: an uncabled port's neighbour, or a port the
  node lacks, gives `updates: []` with exit 0. *(09-19)*

**The push (JSON-RPC)**

- The push is JSON-RPC `cli` over HTTPS 443 with basic auth: `enter candidate private`,
  the lines, `commit now`. Without the candidate, `set` is refused. It takes 0.62–0.96s
  for an 839-byte artifact, and is idempotent. *(09-18)*
- A refused line comes back as HTTP 200 with a JSON-RPC error that echoes every command
  sent, the artifact included, so keep only the reason. *(09-18)*
- A refused line stays in the login's private candidate across requests, and every later
  `commit now` fails on it, until `discard now` or `load startup` clears it. *(09-19,
  10-01)*
- Under a replace, a refusal's message is `At line N: Error: <reason>`, a blank line, then
  the request's output so far, `diff flat`'s `insert /` lines included; the reason ends at
  the first blank line. *(10-01)*
- SR Linux cuts that message at about 1 KiB, inside its echo of the commands, so a real
  replace's reason never arrives. `commit validate` after it recovers a schema
  constraint's reason, but answers `All changes are valid.` for the port-range check,
  which only a commit makes. *(10-02)*
- `delete /` as a replace darkens the management plane under the shipped template;
  `load startup` resets to the baseline containerlab left and does not. *(09-18, 10-01)*

---

## cEOS 4.32.0.2F

- The image is account-gated: downloaded from Arista with an account and imported with
  `docker import`, which leaves one layer and no `Cmd`, and gives each import a new image
  id. containerlab's `ceos` kind boots it with nothing else stated and supplies the
  command. *(09-20)*
- It carries production's names one to one: `Ethernet1` … `Ethernet511`
  (`/interfaces/interface/name`, beside `Loopback0` and `Management0`), and modular and
  breakout forms such as `Ethernet2/1` and `Ethernet3/1/1` are the node's own names. A
  push naming a port beyond 511 is refused at parse; one inside the range that the node
  lacks is accepted with a warning. *(09-20)*
- gNMI is plaintext gRPC on 6030, not TLS on 57400 (containerlab's default is `transport
  grpc default` with no SSL profile), and it answers about a second before eAPI does.
  *(09-20, 09-21)*
- The startup-config is the node's whole configuration, not a part merged over a default.
  The kind's default already sets the host name from the node name and brings every port
  up. *(09-20)*
- The push is eAPI `runCmds` over HTTPS to `/command-api` with basic auth, in a named
  configuration session, since a committed session name cannot be reused; a refused
  session is aborted before the next attempt. *(09-20)*
- `#` is refused at token 0, and `!` is read as a comment. *(09-20)*
- `show session-config diffs` has no JSON model: `format: "json"` fails the whole request
  with code 1003 and leaves the session pending, and `format: "text"` answers. The diff
  carries its own bare `!` separators, never the artifact's `!` comment. *(10-01, 10-02)*
- The paths: `/system/state/hostname`; `/system/state/software-version`
  (`4.32.0.2F-41889544.43202F (engineering build)`);
  `/interfaces/interface[name=X]/state/enabled`; `/lldp/interfaces/interface[name=X]/…`.
  *(09-20)*
- An absent value is not a default: OpenConfig reports nothing where SR Linux reports a
  value. *(09-20)*
- A node restarted in place by a reconcile answers gNMI about 49s and eAPI about 55s
  later, on its startup configuration: its push is lost. *(10-01)*
- A gNMI Set is refused (`Unavailable desc = system not yet initialized`) more than a
  minute after the node is ready, while its Gets answer; shut a port through the node's
  own CLI instead: `docker exec clab-fylgja-<node> Cli -p 15 -c 'configure / interface
  Ethernet1 / shutdown'`. *(10-03)*
- A shut port lists a far end as its LLDP neighbour after that end restarted in place,
  while the far end sees none. *(10-03)*

---

## Temporal Server 1.32 / Go SDK 1.49

- The SDK abandons an activity attempt at the first heartbeat call that fails, not after
  `HeartbeatTimeout`, cancelling its context with that call's error as the cause.
  *(09-15)*
- A heartbeat call fails once it has gone unanswered for about half of
  `MaxHeartbeatThrottleInterval`, unreachable or slow alike: 1.0s at 2s, 2.5s at 5s.
  *(09-15)*
- `context.Cause(ctx)` is a `*temporal.CanceledError` for a cancellation the workflow
  asked for, and the RPC's service error for a lost heartbeat. *(09-15)*
- Under `WaitForCancellation`, an activity that never sees the cancellation (one that
  does not heartbeat, or finishes before its next heartbeat) returns its result with no
  error, so the workflow must check `ctx.Err()` after it. *(09-15)*
- The SDK's `testsuite` ignores `WaitForCancellation` and settles a cancelled activity at
  once; that ordering shows only against a live service, or by replaying a history
  recorded from one with `worker.WorkflowReplayer`. *(09-15)*
- Without `WorkflowExecutionErrorWhenAlreadyStarted` the SDK swallows the server's
  already-started error, so a second start waits on the first run and reports its result
  as its own; the `USE_EXISTING` conflict policy makes a second start attach to the run in
  flight. *(09-15)*
- A worker that stopped stays listed as polling its queue for about five minutes.
  *(09-15)*

---

## The host

Ubuntu 24.04.1, kernel 6.8, Docker 27.5.1, as a QEMU/KVM guest with 32 GiB.

- Ubuntu's `/etc/apparmor.d/usr.sbin.rsyslogd` attaches to the `rsyslogd` inside every
  privileged SR Linux container; unwidened, it fails `log_mgr`, and every `nokia_srlinux`
  deploy fails at containerlab's post-deploy commit (`Applications have failed:
  log_mgr`). Add `/opt/srlinux/** mr,` and `/run/srlinux/** rw,` to
  `/etc/apparmor.d/local/usr.sbin.rsyslogd` and reload it with `apparmor_parser -r`.
  *(09-30)*
- A guest that does not nest has no `/dev/kvm`, which only a `vrnetlab_vm` package would
  need. *(09-30)*
- Infrahub idles at about 5 GiB, and its Neo4j, uncapped, once took the headroom a twin
  needs and killed an end-to-end run; capped at heap 1g/2g and page cache 1g, it does not.
  *(09-21)*
- On a host with little memory to spare, a twin booted beside the contract tier starves
  the worker: it misses heartbeats, its deploys are cut short, and Infrahub times out the
  tier. Read `free -m` before booting a twin. *(09-15)*
- Under memory pressure SR Linux's own `sr_cli` can segfault, or refuse containerlab's
  post-deploy checkpoint, failing the deploy. *(09-16, 09-17)*
