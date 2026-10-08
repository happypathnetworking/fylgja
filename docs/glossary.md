# Glossary

Terms Fylgja coins or uses with a specific meaning. Links go to the section or
decision that defines the concept. Temporal's vocabulary is included where Fylgja
leans on it. A bare milestone marker (`M7`) names the milestone that built a thing;
`CLAUDE.md`'s table says what each built.

**Activity (Temporal)** — A unit of work with side effects, run by a worker, retried
by Temporal. Every Fylgja activity is idempotent and passes paths and hashes, never
bundle bytes ([§4.4](architecture.md#44-provisioner--temporal)).

**API** — From M13 ([D-040](decisions.md#d-040), [D-041](decisions.md#d-041),
the constitution's XI): the boundary of Fylgja's core. Its *server*, `fylgja serve`,
answers HTTP requests with the documents Fylgja already versions. A user-facing *client*,
the CLI first, reaches the core through it alone, for every command, and holds the *API
token* and no other credential. Version `1` is the first element of every path. There are
twelve operations, one per command, each `POST /v1/<noun>/<verb>` (`/v1/twin/create` …
`/v1/psp/validate`), and one more call, the interrupt of a *stream*. Each is answered in
*frames*, the last always the *findings document*. There is no health check, no listing of
runs and no fetch of a filed bundle. Test code and test tools are excepted: they call the
core, and read the nodes, the containers and the record, directly, and no shipped client
carries a second path for them ([contracts/api.md](../contracts/api.md)).

**API token** — From M13 ([D-042](decisions.md#d-042)): the one shared secret between a
*client* and the *server*, `FYLGJA_API_TOKEN` in each one's process environment, sent as
`Authorization: Bearer <token>` with every request. The server holds only its SHA-256 and
compares digests in constant time, before the route, the body, a guard or a dial. A
request without it, or with another, is `401`, and a client whose variable is unset, or
holds a character no request header can carry, or ends in a space or a tab, sends nothing
(`api.token.refused`). The server refuses to start without one. It is never printed,
logged or persisted. There is one token, with no roles and no TLS.

**Artifact** — From M5: a device's configuration as Infrahub rendered it for the branch,
through the *artifacts template*, and stored as a `CoreArtifact` with a status, a content
type, a checksum (the MD5 of the content) and a storage id. The device's *PSP* names the
one artifact that is its configuration (`config.artifact_name`, `device-config` for both
shipped packages). The read fetches it, requires it `Ready` and verifies its bytes; the
CTM and the bundle carry it unchanged, and the *push* delivers it. Fylgja never renders
one and never asks Infrahub to generate one. Infrahub 1.11.2 does not regenerate on its
own either, so whoever changes the branch generates: an intent change nobody generated
for leaves the artifact `Ready` with its old bytes, and neither Fylgja nor Infrahub marks
it stale ([§4.1](architecture.md#41-intent-reader), [D-009](decisions.md#d-009),
[D-028](decisions.md#d-028)).

**Artifacts template** — The Jinja2 transform, its GraphQL query and the `.infrahub.yml`
that declares them with the artifact definition, carried in this repository
(`.infrahub.yml`, `infrahub/`). One transform, `srlinux_device_config`, renders every
device's `device-config` *artifact* for the devices in the *target group*, branching on
the device's platform, so one definition serves both vendors. Infrahub renders from it
once this repository is registered there, read-only on `main` with no credential
([D-028](decisions.md#d-028), [D-044](decisions.md#d-044);
[development.md](development.md#local-environment)).

**Assertion (of verify)** — From M12: one fact `twin verify` expects of a running twin,
derived from the staged bundle's manifest by a pure function (`verify.Derive`) and never
written by an operator ([D-038](decisions.md#d-038)). Three kinds: each node's host name
is its node name (`host_name`); each cabled port intent enables is enabled
(`port_enabled`); each link is an LLDP adjacency seen from both ends, each end naming the
far node and the far port under its node name (`neighbor`). It is read once per path over
the node's own package's transport, by the paths of its `conformance` facet, and ends
held, failed, absent (nothing read, and the facet declares no meaning for that), unread
(the node could not be read) or skipped. A port intent disables, and its link at both
ends, is skipped with its reason, never asserted. A failed or absent one is a finding
under its kind's rule (`verify.host_name`, `verify.port.enabled`, `verify.neighbor`).
Not a *record claim*.

**`at` / point in time** — The optional half of an intent reference: an RFC 3339 UTC
timestamp Infrahub applies to every query as a time-travel filter
(`created_at <= at`). Present → the reference is *pinned*. Absent → *unpinned*, and
Fylgja sends no `at` of its own; `observed_at`, recorded on every read either way, is
then the only record of when the intent was seen
([§4.1](architecture.md#41-intent-reader), [D-012](decisions.md#d-012)).

**Attended loop** — See *converge loop*.

**Baseline** — From M11: the configuration containerlab leaves on a node at deploy, which
a *replace* resets the candidate to before it sends the *bootstrap* and the *artifact*.
On SR Linux it is the startup configuration (management plus the deploy's bootstrap),
loaded with `load startup`; on cEOS it is `flash:startup-config` (containerlab's
management), made the session's whole content by `rollback clean-config` and `copy
startup-config session-config`. It is containerlab's: Fylgja never reads, writes or
saves it, and it is re-verified on a containerlab or image upgrade
([D-033](decisions.md#d-033)).

**Bootstrap** — The minimal per-node startup file the compiler emits from the PSP:
hostname, cabled ports enabled, link-layer discovery on, under the package's
`comment_prefix`. Not rendered from intent; not production configuration
([D-009](decisions.md#d-009)). The package says how a deploy delivers it
(`config.bootstrap_via`): `startup_config`, containerlab applies it at boot; or `push`,
its lines go ahead of the *artifact*'s in the same push request, which is what a platform
whose containerlab kind reads a startup file as the node's **whole** configuration needs —
sending a partial bootstrap that way would replace everything else. Under `mode: replace`,
which both shipped packages use, the push sends the bootstrap after the *baseline* reset
whatever `bootstrap_via` says, and the node's *artifact* after it.

**Branch (Infrahub)** — A version of the source of truth; the first half of an intent
reference.

**Bring-up script** — `scripts/bring-up.sh`, the launch's: takes a fresh Ubuntu 26.04
host to tiers 1 and 2 passing and the dev server, the worker and the API's server running.
A preamble, then four parts (`toolchain`, `lab`, `infrahub`, `fylgja`), each item
verified, installed when missing and verified again, so a second run installs nothing.
Without the cEOS tar it sets the host up for SR Linux alone. CI's contract job runs its
*Infrahub part* alone ([development.md](development.md#local-environment)).

**Bundle** — The compiler's output: `topology.clab.yml`, `configs/` (each node's
*bootstrap* and its *artifact*), `manifest.json`. Deterministic, self-describing,
deployable as emitted, content-addressed by `bundle_id`. Format `4`, whose mapping rows
carry intent's `enabled`. A bundle of another format is refused, naming both versions:
a `1` carries no artifacts, a `2` asserts one forwarding value for every node in it, and
a `3` says nothing of what intent enables ([§4.3](architecture.md#43-compiler),
[D-011](decisions.md#d-011)).

**`bundle_id`** — Hash of a bundle's canonical bytes. The same intent compiles to the
same one; a changed `bundle_id` is how *reconcile* knows the branch moved. The
*artifacts* are among the bytes, so a configuration change moves it too
([D-024](decisions.md#d-024)).

**Bundle store** — `bundles/<bundle_id>/` under the *state root*: every bundle ever
compiled or provisioned, by identity, with the CTM a `create` read kept beside it as
`<bundle_id>.ctm.json`, outside the hashed bytes. Behind a small interface (`Put`, `Has`,
`Path`, `Fetch`, `PutCTM`) so object storage can replace the directory at M8
([D-014](decisions.md#d-014)).

**C4 model** — The architecture's diagrams, drawn from one Structurizr model,
`docs/c4/workspace.dsl`: five views (the system context, the containers, the server's and
the worker's components, and the deployment on the lab host), exported to images by `make
diagrams`. A changed package, import or component is redrawn in the same change
([development.md](development.md#keeping-the-documents-true)).

**Check** — One run of *reconcile* for a *following* twin, started by Schedule
`fylgja-follow` every *interval*, under the workflow ID `fylgja-reconcile-<scheduled
time>`. One at a time. It reads the followed branch without `at`, compiles it, and
compares the `bundle_id` with `twin.json`'s. It ends with one of seven outcomes:

- `unchanged`: nothing touched.
- `rebuilt`: destroyed and provisioned again, ready.
- `rejected`: the read, compile or host check refused; nothing touched.
- `error`: a step before the destroy could not run; the next check tries again.
- `rebuild_failed`: the destroy or the provision failed; *following* stops.
- `skipped`: nothing to compare against, a twin that does not follow, or a run in
  flight.
- `cancelled`: `twin destroy` cancelled it.

`twin show` reports the last one ([§4.4](architecture.md#44-provisioner--temporal),
[D-026](decisions.md#d-026)).

**Client** — From M13 ([D-040](decisions.md#d-040)): a program that reaches Fylgja
through the *API* alone. The CLI is the first. Every command but the two *roles*, `fylgja
serve` and `fylgja worker run`, is a client's command: one request to the server, which
prints what comes back and exits by the document's status. Its environment is
`FYLGJA_API_ADDRESS` (default `127.0.0.1:7650`) and the *API token*, and its files are
the operator's own (`--ctm`, `--out`, a bundle directory, a package). It links
`internal/api`, `internal/findings` and `internal/tree` and nothing else of the module
(`TestClientReachesTheCoreThroughTheAPIAlone`). Its own failures are `api.unreachable`,
`api.token.refused`, `api.version.unknown` and `api.transfer.too_large`, each status
`error`, exit 2.

**Command log** — The record of every Spec Kit session: prompt, report, model, effort,
time, context and tokens, written by Claude Code hooks (`.claude/hooks/command-log.py`)
to `local/command-log/pending.jsonl`, and published by `make command-log` into
`commands/` and each feature's `commands/` directory. Both are git-ignored here, so the
log stays on the developer's disk ([development.md](development.md#spec-kit-workflow)).

**Compiler** — The pure function CTM → bundle. No I/O, no clock. Golden-file tested;
exposed as `fylgja twin compile` on the same code path
([D-011](decisions.md#d-011)).

**Conformance suite** — From M6: the test a PSP passes to count as a *supported
package*. It is `go test` in `internal/conformance`, which no product code imports, and
it has two halves. The **pure half** runs in tier 1 on every package meant to load,
shipped or test: the package validates, each *declared mapping* maps as declared and
round-trips to its production name, and bootstrap renders for it. The **boot half** runs
inside tier 3 against a ready twin of each shipped package. It reads each node once over
the *readiness* probe's transport, by the paths the package's `conformance` facet
declares, and checks five things: the node booted, and was ready within the package's
budget; its host name is set; every cabled port is enabled and discovering; every cabled
port's neighbour is the far node and port the bundle's link names (the round trip
through a booted node); and the version is one the package lists. Its readers are
`internal/verify`'s, which `twin verify` and the step's wait share with it
([D-037](decisions.md#d-037)); its checks and wording are its own, and it holds a package
to what it declares where verify holds a twin to intent. It boots, pushes and retries
nothing. Its failures are `go test` failures, not findings
([§4.7](architecture.md#47-platform-support-packages), [psp/README.md](../psp/README.md)).

**Constitution** — `.specify/memory/constitution.md`: the non-negotiables, principles I
to XI, that every plan's Constitution Check cites by number. It is amended only by citing
a *decision log* entry, with a version bump.

**Contract test** — A test against a real Infrahub with the reference schema loaded.
Never a fake ([development.md](development.md#test-architecture)).

**Contract version** — The version of the Fylgja generics a CTM was read against.
Recorded in provenance so a Fylgja upgrade that needs more from the schema fails
loudly. It is `0.2`: conformance demands that a kind implementing `FylgjaDevice` inherit
`CoreArtifactTarget`, so an implementing branch declares the version that demands it. A
branch declaring `0.1` is `contract.version.mismatch`.

**Contracts** — The current formats' JSON schemas and the CLI's and the API's contract
documents, in [contracts/](../contracts/) at the repository root, which the tests read.
A test that validates an older format reads a *frozen copy* instead.

**Converge loop** — `scripts/converge-loop.sh`: runs a Spec Kit *feature* from its tasks
to convergence in headless sessions, one fresh context each, commits as it goes, never
pushes, and stops at the first thing only the operator can answer. **Attended**
(`--attended`, driven by the `/converge-loop` session), an interactive session carries
each such question to the operator while the loop goes on with what does not wait on it,
and a **live session** runs what needs the host: the worker, a twin, tier 3
([development.md](development.md#spec-kit-workflow)).

**CTM — Canonical Topology Model** — The compiler's input: a thin, branch-addressed
projection of intent, and the only place synthesized nodes can live
([§4.2](architecture.md#42-canonical-topology-model-ctm), [D-010](decisions.md#d-010)).

**Cut** — M14's first half: this repository's first commit, of cleaned code and documents
rewritten for its reader, from a private development repository whose record of how
Fylgja was built stays private ([D-043](decisions.md#d-043)). The *launch* is the second.

**Decision log** — [decisions.md](decisions.md): one entry per decision in force, with
the options it rejected and why, cited by `D-0NN`. Append-only from this repository's
first commit: a change is a new entry that supersedes the old one.

**Declared mapping** — From M6: an entry in a PSP's `interfaces.mappings`, the
expectation the *conformance suite* holds the *mapping profile* to, as data. It is either
a production name with the rule expected to decide it and the port and *node name* it
must render, or a production name the profile must refuse (`no_rule`) or find out of
range under a named rule (`out_of_range`). Only the suite reads them, so changing one
moves no `bundle_id`.

**`destroy` (workflow)** — The short Temporal workflow that removes the lab and the
twin directory. Fixed ID; works on an orphan lab too ([D-007](decisions.md#d-007)).

**Development host** — The one machine Fylgja is developed and tested on, and its only
*lab host* until M9 ([D-020](decisions.md#d-020)): Ubuntu 26.04 under QEMU/KVM, set up by
the *bring-up script*; the guest does not nest, so it has no `/dev/kvm`. Until the launch
it ran Ubuntu 24.04, where most *verified facts* were first verified.

**Disconnected context (Temporal)** — A workflow context that keeps running after the
parent is cancelled. Cleanup in `provision` runs on one, and so does the record of a step
that failed or was cancelled after its stage.

**Diverged** — From M11: the state of a twin whose *step* failed or was cancelled after
it touched the host (from the stage on). The twin stays up, part on the waypoint it came
from and part on the one it was going to; `twin.json` keeps the first at its top level,
names the second, the run and the *phase* in its `step` block, records `state:
diverged`, and gives each node the bundle it is last known to hold, or `null` for a node
containerlab restarted whose push did not land. Each push's outcome sits beside it, and
only `refused` is the node's own answer. A `failed` push may have committed (a node the
replace darkened), so a later rollback reads the outcome beside the bundle. `twin step`
exits `4` with status `diverged`, and `twin show` names the kind `diverged` in one line.
A diverged twin accepts only `twin destroy` ([D-036](decisions.md#d-036)). `twin verify`
reads it too, and changes nothing: it is verified against the staged bundle, the target
it was going to, with its divergence on the first line, and each node whose record does
not say it holds that bundle is a failed *record claim* ([D-038](decisions.md#d-038)).

**Dry run** — `--dry-run` on `twin create`, `twin provision` and `twin step`: every
refusal the run would make, and what it would do, with no run started and no lab,
container or twin directory touched. Like a plan, it files the bundle and the CTM it read
in the *bundle store*. The *server* makes it on the lab host, so it needs `docker` and
`containerlab` on the server's `PATH`.

**Fidelity manifest** — Part of every bundle's manifest: modelled exactly,
approximated, stubbed, omitted; software- or hardware-forwarding, asserted per platform
with one `production_forwarding` entry per package in the bundle, so a *mixed twin*
asserts each vendor's own answer ([D-025](decisions.md#d-025)); every synthesized node;
and every *lossy mapping* and *shared port*, as `fidelity.lossy`, `[]` when there is
none. The only trust signal Fylgja has ([D-022](decisions.md#d-022)).

**Finding** — One thing a command found, in the *findings document*: a `rule` (its
identifier, such as `host.image.absent`), a severity (`rejection`, `warning` or `info`),
the `object` it is about, a message, and from a run's steps on the `step` it was raised
at. A rejection is a **refusal**: the command stops, and says what to change. A warning
never stops anything. The rules are listed in [contracts/cli.md](../contracts/cli.md).

**Findings document** — The JSON document every command ends with (findings format `1`,
[contracts/findings.schema.json](../contracts/findings.schema.json)): the operation, a
status, the *findings*, and the operation's own block (`twin`, `show`, `plan`, `step`,
`verify` and others). Its status decides the exit: `ok` 0, `rejected` 1 (before the host
was touched), `error` 2, `failed` 3 (after the host was touched, cleanup complete),
`unclean` or `diverged` 4, `nonconforming` 5. Without `--json` the CLI prints its text
rendering.

**Fixture branch** — `fylgja-fixture`: the three-node SR Linux topology on the reference
schema, written once by `make infrahub-seed` and by no test, which tier 2 reads and tier
3's first case deploys. Tests make their own throwaway `fylgja-test-*` branches.

**Fixture tool** — `cmd/fylgja-fixture`: the only binary that writes to Infrahub. It
seeds and deletes branches (the fixture branch, the mixed one, throwaway ones), changes
them as the tests need (`-add-link`, `-disable-port`, `-set-role`), generates their
artifacts and waits for them, and writes and deletes `fylgja-test-*` waypoint series. With
`-prepare-main` it prepares `main`: the schema, the group `fylgja-devices` and this
repository's read-only registration, each made only when absent.

**Following** — From M4: a twin built from an unpinned reference is checked every
*interval* and rebuilt when its `bundle_id` moves. `twin create` begins it unless `--at`
or `--no-follow` is given. It is Schedule `fylgja-follow`, which holds the branch and the
interval and nothing else. It stops when a rebuild fails, when `twin destroy` runs, and
when a later create or provision replaces it. Contrast *pinned* and *frozen twin*
([§1](architecture.md#1-claims-that-shape-everything), [D-012](decisions.md#d-012),
[D-026](decisions.md#d-026), [D-027](decisions.md#d-027)).

**Frame** — From M13: one line of an *API* answer, a JSON object whose one key names its
kind: `out` and `err` (text for stdout and stderr), `start` (the server begins to start a
run), `run` (the run's identity), `event` (one step boundary, or a notice), `files` (the
CTM or a bundle, base64) and `document` (the findings document, with its text when a
rendering was asked for). The answer is `application/x-ndjson`, and its last frame is
always `document`. One with no `document` frame did not finish. By default an answer is
the `document` frame alone, after the `files` frame of `intent read` and `twin compile`,
and after a run's `start`, `run` and `event` frames (a destroy's `start` and `event` frames,
with no `run`); the CLI asks the server for the text rendering as well
([D-040](decisions.md#d-040)).

**Frozen copy (of a contract)** — A schema of an older format, kept under the package
whose test reads it (`internal/<package>/testdata/contracts/<feature>/`), so that a test
can show a consumer of that format still reads what the code writes. Never edited;
`TestFrozenContractCopiesAgree` holds two copies of one schema equal. The current
schemas are the *contracts*.

**Frozen twin** — A twin built from an unpinned reference that is not *following*:
created with `--no-follow`, one whose following could not begin (`follow.start.failed`)
or was lost, or one of a branch other than the one a Schedule follows. Not reproducible,
unlike a *pinned* twin: its `observed_at` is a local clock reading, and reproducing it
with `--at` is best-effort ([D-027](decisions.md#d-027)).

**Fylgja** — In Norse tradition, a spirit that accompanies a person: a follower, a
fetch. Here, the platform, and the reason the twin *walks*.

**Generics (Infrahub)** — Abstract kinds that concrete node kinds declare they
implement. Fylgja's schema contract is a small set of generics
([D-002](decisions.md#d-002)).

**`genqlient`** — Go GraphQL client generator. Fylgja generates typed queries from the
Infrahub SDL at build time, so a breaking schema change fails the build, not the twin.

**Golden-file test** — Compares a pure function's output against a checked-in expected
artifact. Needs no infrastructure. The compiler's three **golden bundles** (three-node,
lossy and mixed, under `testdata/golden/`) are its expected output;
`go test ./internal/compiler -update` regenerates them, and the diff is reviewed.

**Graduate, don't gate** — Optional generics unlock features rather than being
required; where absent, dependent behaviour skips with a recorded reason. The same
degradation pattern as PSP capabilities.

**Heartbeat (Temporal)** — A progress signal from a long-running activity so Temporal
does not mistake slow for dead. Mandatory on deploy, readiness and the push
([D-030](decisions.md#d-030)).

**Host budget** — The memory, in MiB, the operator allows the twin on this lab host:
`FYLGJA_HOST_MEMORY_MB` in the worker's and the server's environment. Optional: when
unset, the *host check* reports the twin's memory sum as a warning and proceeds. Never
derived from the host's free memory.

**Host check** — The read-only gate a run passes before it stages or deploys anything:
refuses when lab `fylgja` exists in any state, when a twin directory exists, when the
nodes' PSP memory budgets sum to more than the *host budget*, when a *probe login* or
push login variable is unset, when a node's support package is not on the worker, or
when an *imported image* a node needs is not on the host. Names the cause and how to
clear it; changes nothing on the host ([D-013](decisions.md#d-013)).

**`iftype` (interface)** — What an interface *is*: `physical`, `loopback`, `svi`,
`subinterface`. Kind only. Wiring is derived from it and `mgmt_only` by the compiler;
an unimplemented value is a compile-time rejection ([D-003](decisions.md#d-003)).

**Imported image** — From M7: a NOS image whose PSP declares an `image.acquisition`
other than `public_registry` — `account_gated`, `licensed` or `vrnetlab_vm`. Such an
image cannot be fetched, so **Fylgja never pulls or tags it**: the operator obtains it as
the acquisition says and imports it under exactly the reference the package names, and the
*host check* verifies it is present and refuses the run before anything is staged when it
is not (`host.image.absent`). The same image under another tag is absent. The worker names
each one's state at start and serves either way. cEOS (`ceos:4.32.0.2F`) is one;
SR Linux says `public_registry`, so a deploy may pull it and no call is made
([§4.5](architecture.md#45-lab-host-containerlab-and-the-twin-directory)).

**Infrahub part** — The *bring-up script*'s `infrahub` part, which CI's contract job runs
alone (`--part infrahub`): Infrahub 1.11.2 from its published Compose file with this
repository's override, under `local/infrahub/`; `main` prepared by the *fixture tool*'s
`-prepare-main`, this repository registered read-only with no credential and its import
awaited; and the *fixture branch* seeded ([development.md](development.md#local-environment)).

**Intent** — What Infrahub says the network should be, on a branch, at a time.

**Intent conformance report** — From M12: what `fylgja twin verify` prints, and the
findings document it writes under operation `twin.verify` with a `verify` block
([D-039](decisions.md#d-039)). It reads the running twin against the intent it was built
from, with no run and no worker, and changes nothing: one finding per failed *assertion*
and per *record claim* not held, the held ones counted, the skips named. It ends `ok`
(exit 0), `nonconforming` (exit 5) when every node was read and something failed, or
`operation.failed` (exit 2) when a node could not be read. `--wait` reads again every
second until the twin is *settled* or the budget (2m0s bare) expires. Advisory: no Fylgja
operation reads it. It measures conformance to intent, never fidelity to production,
which the *fidelity manifest* still asserts. Also called **verify**.

**Intent reference** — `(branch, at?)`: the address of intent as the operator gives
it; the provenance of every CTM, bundle and twin ([§3](architecture.md#3-core-objects),
[D-012](decisions.md#d-012)). The operator may also name one by a *waypoint*, which the
*server* resolves to a pinned `(branch, at)` before any run starts; the waypoint's name
is not part of the reference and enters no CTM or bundle ([D-032](decisions.md#d-032)).

**Interval** — How often a *following* twin is *checked*: `twin create --interval`,
in Go duration syntax. Default 5 minutes, floor 10 seconds. Held only by the Schedule,
and refused with `--at` or `--no-follow`.

**Kind (of a twin)** — What `twin show` calls the twin on the host: `following`,
`pinned` (built from an `at` or a waypoint, stepped or not), `frozen`, from a bundle
(`twin provision`), `diverged`, or `none`.

**Lab host** — A machine with Docker, containerlab, NOS images, one `fylgja worker run`
process and one `fylgja serve` process beside it ([D-041](decisions.md#d-041)). The
*development host* is the only one until M9 ([D-020](decisions.md#d-020)).

**Lab name** — `fylgja`: the fixed containerlab lab name, written into every bundle.
One twin at a time ([D-013](decisions.md#d-013)).

**Launch** — M14's second half, after the *cut*: the repository made public at its
start, before the *bring-up script* and CI are built ([D-043](decisions.md#d-043)); then
the script, CI with a real Infrahub, Infrahub rendering from this repository's
*artifacts template*, the *recording*, the *write-up* and the release `v0.1.0`
([roadmap](roadmap.md#built)).

**Link-change fidelity** — From M11: what containerlab's reconcile does to a node of a
platform when a link of its is added or removed, declared by the PSP as
`fidelity.link_change`: `restart` (restarted in place, back on its startup configuration
about a minute later, its *push* lost; cEOS) or `live` (re-cabled with no lifecycle
action, its push kept; SR Linux). Asserted by the package and measured by containerlab's
plan at each *step*; both are recorded, a difference is warned
(`step.restart.undeclared`), and the step acts on containerlab's plan.

**Live session** — See *converge loop*.

**Lossy mapping** — From M6: a mapping whose *mapping rule* drops a placeholder of the
production name from the port it renders, so several production names can reach one port
(`chassisos`'s `linecard` rule sends `Ethernet{slot}/{port}` to `eth{port}`, dropping the
slot). The rule must say `lossy: true`, and validation checks the flag against what `port`
drops. A rule that only renames (`Ethernet1/{port}` → `eth{port}`) is not lossy: it
inverts. Every interface a lossy rule decides, and every interface on a *shared port*,
is recorded in the manifest's `fidelity.lossy` with its rule and what it shares with,
even when nothing was lost in that intent. Neither shipped platform is lossy: cEOS
carries production's names one to one, so the lossy paths are proved by the test-only
`chassisos` package alone ([D-021](decisions.md#d-021)).

**Mapping profile** — From M6: a PSP's Interfaces facet. An ordered list
of *mapping rules*, exactly one management rule, and the *declared mappings* the suite
checks it against. The first rule whose `match` fits a production name decides it. A
value outside that rule's range makes the name out of range under it, never a match for
a later rule. The management rule decides the `mgmt_only` interface whatever its name.
The compiler applies the profile and branches on nothing a package is
([§4.3](architecture.md#43-compiler)).

**Mapping rule** — One entry of a *mapping profile*. It has a unique `name`, a `match`
pattern over the production name (`{x}` captures one path segment), per-placeholder
`ranges`, and the containerlab `port` and the *node name* it renders. `lossy` must say
whether `port` drops a placeholder. An optional `breakout.parent` renders a breakout
child's parent from the child's values. Findings and the fidelity record name the rule
that decided an interface.

**Mechanism** — From M7 ([D-031](decisions.md#d-031)): one of the fixed, named ways
Fylgja's code reaches a node, selected by a value in a *PSP* and by nothing else about the
platform. The set is the push mechanisms (`json_rpc`, `eapi`), the probe's transport
(`readiness.tls`), the *bootstrap*'s route (`config.bootstrap_via`) and the image-presence
check (`image.acquisition`). **A mechanism is code; a platform is data; the format is the
seam.** No code may branch on a platform's id, vendor, NOS, containerlab kind or image
reference, and a test greps every non-test source for the platform names the tree knows,
comments included. A package naming a value this build has no mechanism for is refused at
load, naming the ones there are — never skipped at the moment of use. A platform needing
something new is a format change and a new mechanism, available to every package.

**`mgmt_only` (interface)** — Boolean marking the out-of-band management port: maps
onto the node's containerlab management interface, never cabled. Not set on an in-band
loopback ([D-003](decisions.md#d-003)).

**Milestones M1–M14** — Fylgja's units of planned work; `CLAUDE.md`'s table says in one
line each what each built, and the roadmap's [Built](roadmap.md#built) table what each
delivers.

**Mixed twin** — From M7: a *walking twin* whose nodes span more than one *PSP*, the
proof that "a twin is heterogeneous" (the constitution's II) is more than a sentence. It
is one *bundle*, one lab, one `bundle_id`, one readiness, one push and one *`twin.json`*:
what makes it mixed is where each value comes from, not that anything is duplicated.
Every per-platform value — the deploy, destroy and push budgets, the *readiness* probe
and its transport, the login's variable names, the push *mechanism*, the *bootstrap*'s
route and the *mapping profile* — is looked up by the node's own `psp.id` from its
manifest entry, while a whole step's budget is the largest over the bundle's packages.
Its *fidelity manifest* carries one `production_forwarding` entry per platform
([D-025](decisions.md#d-025)). Its compiled form is a **mixed bundle**; the mixed
fixture (`testdata/ctm/mixed.json`, its shuffled copy and `testdata/golden/mixed/`) and
`fylgja-fixture -mixed`'s seeded branch are what produce one in tiers 1, 2 and 3.

**Node name (of a port)** — What the node's own operating system calls a port, as the
deciding *mapping rule*'s `node_name` renders it. On SR Linux it is the production name,
`ethernet-1/1`. For `chassisos`'s `Ethernet1/1` it is `Ethernet1`, whose containerlab
port is `eth1`. Bootstrap's `{interface}` renders it and the boot half reads a port by it.
The manifest's mapping row carries it as `node_name` on every row, `null` on a row with
no port at all. Not containerlab's port name (`{port}`, `e1-1`).

**NSoT** — Network Source of Truth. Here, Infrahub ([D-001](decisions.md#d-001)).

**Observe (step)** — From M12: the findings step of `twin verify` (`observe`), and the
step a *step (of a twin)* takes after its record, in which `VerifyTwin` waits for the twin
to be *settled* (the **wait**). It is not the findings step `verify`, which checks a
bundle's integrity before a run. The wait runs on the run's own context under the
operator's budget, after every record, writes how it ended into `twin.json`'s
`step.wait`, and never changes the step's outcome; one that did not settle is the warning
`verify.wait.unsettled`. `twin show` lists a step at `observe` under `in flight:` alone.

**Observed fact** — From M12 ([D-037](decisions.md#d-037)): a fact read from a running
node in Fylgja's own vocabulary (a host name, a port's enabled state, an LLDP neighbour),
which each package maps to its platform's paths in its `conformance` facet. *Assertions*
are held against them.

**`observed_at`** — UTC time a read began, from the local clock. Recorded on **every**
read, pinned or not: when the read is pinned it governs nothing, but a CTM that cannot
say when it was read is worth less than one that can. Informational provenance, not a
transaction marker. Recorded in the CTM envelope and `twin.json`, never in the bundle,
so it cannot disturb `bundle_id` ([D-023](decisions.md#d-023), constitution VI).

**Operator** — The person who runs Fylgja: who writes intent and waypoints in Infrahub,
holds the credentials, starts the worker and the server, and gives each command.

**Orphan lab** — Lab `fylgja` present on the host without a readable `twin.json`: no
twin directory, no record, or a record that does not open or parse. Detected at `create`
and at worker start; cleared by `fylgja twin destroy` ([D-013](decisions.md#d-013)).

**Package override directory** — `--psp-dir` on `fylgja serve` and `fylgja worker run`,
or `FYLGJA_PSP_DIR`: a directory of support packages loaded after the embedded ones,
each shadowing an embedded package with the same NOS identifier, by the server and the
worker alike. An override package `psp validate` rejects is refused at load. How an
operator boots another NOS version without a rebuild. A client's command has no
`--psp-dir`.

**Partial pass** — The end of a tier-3 run narrowed by a *platform list* that skipped a
case and passed every case it ran: `E2E-PARTIAL: platforms <list>; ran <cases>; skipped
<case> (<why>) …`, exit 0. Such a run never prints `E2E-OK`, which means every case ran
([development.md](development.md#test-architecture)).

**Phase (of a step)** — From M11: where a *step* that failed or was cancelled after it
touched the host stopped: `reconcile` (the stage swap or containerlab's apply),
`readiness`, `push` or `record`. A *diverged* record names it, and `step.diverged`
carries it. A step that ended `stepped` or `unchanged` has none.

**Pinned** — Of a reference: has an `at`. Of a twin: built from one, and therefore
frozen and reproducible. A twin built from a *waypoint* is always pinned: the waypoint
resolves to the `at` written on it, or to the moment Infrahub recorded its writing, and
the twin never follows.

**Platform list** — `PLATFORMS=<list> make test-e2e`: shipped package names
(`nokia_srlinux`, `arista_eos`) that narrow tier 3 to the cases they can run. It selects
by package, never by image: a case runs when the list names every package it needs and
each account-gated image among them is present, and is skipped, saying why, otherwise.
Unset, every case runs and every image is required. A run that skipped a case ends on a
*partial pass* ([development.md](development.md#test-architecture)).

**Probe login** — The username and password the *readiness* probe authenticates with.
A PSP names the environment variables that carry them (`readiness.login`) and never
the values; the worker reads them from its process environment; no bundle, finding,
`twin.json` or log carries them (constitution X). The *push* has a login of its own under
the same rules (`config.push.login`); each shipped package names the same two variables
for both.

**Provenance** — Per-object tag in the CTM (`intent`, `observed`, `synthesized`), and
the block in every manifest recording branch, `at`, schema hash and contract
version; the CTM envelope and `twin.json` add `observed_at`.

**`provision` (workflow)** — The short Temporal workflow that turns an intent
reference into a ready twin: read, compile, check host, stage, deploy, await
readiness, push, record. The twin is ready only once every node's *push* succeeded.
Fixed ID; cleans up after itself ([D-007](decisions.md#d-007)).

**PSP — Platform Support Package** — The declarative bundle that makes one NOS
supported. Format `0.6`; [psp/README.md](../psp/README.md) records each field under the
version it arrived in. Adding a platform is a data change, never a code change: what a
package can ask for is the set of *mechanisms*
([§4.7](architecture.md#47-platform-support-packages), [D-016](decisions.md#d-016),
[D-031](decisions.md#d-031)).

**Push** — From M5: the step of a run that delivers each node its *artifact* after
readiness and before the record, all nodes at once, by the mechanism, commit style, mode
and budget the node's *PSP* declares. Two *mechanisms* deliver it: `json_rpc`, one
JSON-RPC `cli` request over HTTPS that sets the artifact's lines in a private candidate
and commits (SR Linux); and `eapi`, one eAPI `runCmds` request over HTTPS in a named
configuration session, aborted before the next attempt if a line is refused (EOS). Where
the package says so, the *bootstrap*'s lines go first in the same request. Both shipped
packages push by *replace*, at create and at every *step*, and the push's result carries
the device's diff, which lives in the run's history alone; a package on `merge` (the
artifact over the bootstrap) still creates but cannot step. The activity takes the staged
file's path and checksum, never the bytes; its login is named by environment variables,
as the *probe login* is. A refusal by the node is `push.refused`, a push that could not be
made `push.failed`; either fails the run at step `push` and cleanup follows
([§4.4](architecture.md#44-provisioner--temporal)).

**Push plan** — From M11: which nodes a *step (of a twin)* pushes, each with its reasons
(its artifact or bootstrap changed; containerlab restarted, recreated or created it),
printed by `twin step` and its dry run before anything runs.

**Readiness** — Per-platform detection, declared in the PSP (transport, path,
encoding, port, *probe login* variable names, timeout), that a node has booted far
enough to answer on its management plane; probed from the lab host against the
address containerlab assigned, per node, each under its own package's timeout from
the moment deploy returns. For SR Linux the probe is a gNMI Get of
`/system/information` with JSON_IETF encoding: it shows the management plane
answering, not routing readiness. A package may declare `await_push_transport`: its node
is ready only once the endpoint its *push* uses also accepts a connection, because a
platform can answer its probe while that transport is still shut and the *bootstrap*
itself may travel over it. Both waits share the one timeout, and `ready_after_s` covers
both ([D-029](decisions.md#d-029)). The conformance suite's boot half reads more of a
ready node, once, in tier 3.

**Rebuild** — What a *check* does when its branch's `bundle_id` moved: the `destroy` and
`provision` workflows as children, under their fixed IDs, to the newly compiled bundle. A
failed rebuild stops *following*.

**Reconcile** — From M11: containerlab applying a changed topology to a running lab,
`clab deploy` without `--reconfigure`, the third phase of a *step*. It re-cables, restarts,
recreates, creates or removes each node as its plan says; what it will do is read first
from `clab deploy --dry-run --format json`, with `CLAB_LABDIR_BASE` at the twin directory
so that containerlab sees the state it stored there, and that read writes nothing. Not to
be confused with the `reconcile` workflow below, whose *rebuild* destroys and provisions.

**`reconcile` (workflow)** — M4: the short workflow a *check* runs. Inspect the host
and the runs in flight, read, compile, compare `bundle_id` with `twin.json`'s. If it
changed, check the host for the new bundle, then *rebuild*. Stop following when the
rebuild fails. Started only by Schedule `fylgja-follow`
([§4.4](architecture.md#44-provisioner--temporal)).

**Record claim** — From M12: what `twin.json` says a node holds (`nodes[].holds`, or for
a record before version `4` its `bundle_id`), held against the staged bundle by `twin
verify`. It is the record's word, never a read: verify does not read a node's
configuration back, so its report labels each claim as the record's. A claim not held is
a finding, `verify.record.holds`, and counts toward `nonconforming`; a *diverged* twin's
unpushed nodes fail it. The step's wait never waits on a claim
([D-038](decisions.md#d-038)).

**Recording** — The README's recorded session: `docs/recording/session.cast`, an
asciinema cast of `twin create --waypoint`, `twin step` and `twin verify` run through the
*API* from a shell holding the *API token* alone, and `session.gif`, rendered from it.
Every frame was read for a credential before it was committed ([README](../README.md)).

**Reference schema** — The concrete Infrahub schema Fylgja ships implementing its
generics, so a greenfield install has something to populate.

**Replace** — From M11 ([D-033](decisions.md#d-033)): the *push* under `mode: replace`.
One request with one atomic commit resets the candidate to the node's *baseline*, sends
the *bootstrap*, then the *artifact*, asks the device for its diff and commits; the device
computes the difference, and Fylgja reads none of the node's configuration back. On SR
Linux (**S1**): `load startup` … `diff flat`, `commit now`. On EOS (**E1′**): `rollback
clean-config`, `copy startup-config session-config` … `show session-config diffs`,
`commit`, sent as `format: text`. It is what lets a step remove what the previous
artifact added. No package sends `delete /`, which takes the management plane dark under
the shipped template.

**Role** — One of the three things the one binary does: a *client*'s commands, the
*worker* (`fylgja worker run`) and the *server* (`fylgja serve`). The two roles run on the
lab host; each reads its own environment ([D-018](decisions.md#d-018),
[D-040](decisions.md#d-040)).

**Schedule (Temporal)** — A server-side cron that starts a workflow on an interval.
How following runs without a long-lived workflow.

**Series** — From M10: the *waypoints* that share one series name, ordered by sequence.
It tells a story about one branch, or about several in turn, since each waypoint names
its own branch. `waypoint plan --series` reads and compiles the waypoints in order and
prints the *step (of a series)* between each consecutive pair. A series named
`fylgja-test-*` belongs to a test, and the test that wrote it deletes it
([D-032](decisions.md#d-032)).

**Server** — From M13 ([D-041](decisions.md#d-041)): `fylgja serve [--listen <host:port>]
[--psp-dir <dir>]`, the *API*'s side, a third *role* of the one binary. It runs on the
*lab host* beside the worker as a process of its own, with the worker's state root and
environment plus the *API token*, and listens on `127.0.0.1:7650` unless `--listen` says
otherwise. Its handlers hold the commands' logic: it makes every refusal, reads the host
in its own process, and starts, follows and cancels runs through the *workflow service*.
It loads the packages, dials the workflow service and reads Infrahub per request, and
keeps nothing between two requests but the channel of each open *stream*
([D-014](decisions.md#d-014)). It logs one line a request (operation, outcome,
duration). Stopped, it closes every connection at once, and runs go on.

**Settled** — From M12: of a twin, every *assertion* read from a node held, in one read.
The *record claims* are not counted. `twin verify --wait` reads until the twin is settled
or the budget expires, and the step's wait records `settled` with the reads it took and
`after_s`, the seconds from the record to the end of the read that settled. A wait that
did not settle ends `expired` (every node read, something failing), `incomplete` (a node
still unread, or the activity's own failure) or `cancelled`.

**Shared port** — From M6: a containerlab port that two or more interfaces of one device
render to under the *mapping profile*, from one rule or several. With one of them cabled,
that one holds the port and the others are omitted (`omit.interface.shared`). With none
cabled, all keep it. Two cabled is `interface.port.collision`, a refusal. Every member is
recorded in `fidelity.lossy` with the others it shares with.

**Spec Kit** — The specification-driven workflow Fylgja is built under: each piece of
work is a **feature**, a directory `specs/NNN-<slug>/` taken through `specify`,
`clarify`, `plan`, `tasks`, `analyze`, `implement` and `converge`, each command in a fresh
context reading its inputs from disk ([development.md](development.md#spec-kit-workflow)).

**Stage commands** — `intent read`, `twin compile`, `schema check` and `psp validate`:
each exposes one stage of the pipeline on its own, on the code path a run uses
([D-019](decisions.md#d-019)). Each is a request to the *server* like every command;
`twin compile` and `psp validate` need neither Infrahub nor the workflow service, and are
checked against the server's packages.

**State root** — The one directory under which the *bundle store* and the *twin
directory* live: `FYLGJA_STATE_ROOT`, defaulting to `local/` under the process's
working directory, resolved once at start. The worker and the *server* each report their
root, so two roles started from different directories are visibly, not silently, apart.
A *client* has none.

**Step (of a run)** — One idempotent unit of a provisioning or destroy run, implemented
as a Temporal *activity*: read, compile, host check, stage, deploy, readiness (one per
node), push (one per node), record; teardown and unstage. Takes paths and identities,
never bundle bytes; a step that can run for minutes heartbeats under a budget from the
PSP. Host-bound steps run only on the lab host, in `internal/lab`
([D-015](decisions.md#d-015)). A finding names the step it was raised at. `start`,
`verify` and `resolve` are the command's own steps, taken by the *server* before any run
starts. A *step (of a twin)* runs its own: inspect, host check, plan reconcile (findings
step `compare`), stage, reconcile, readiness, push, record, and *observe*, which is also
`twin verify`'s.

**Step (of a series)** — From M10: the difference between two consecutive *waypoints*'
bundles, computed by a pure function of the two (`step.Diff`, `internal/step`). It names
the nodes, links, bootstraps and artifacts that differ, by presence and checksum, and
never quotes content. `provenance` is left out of the comparison. `at` is hashed, so two
waypoints never share a `bundle_id`, and `unchanged` therefore means identical content;
both ids are printed beside every step. `waypoint plan` prints it, and `twin step` prints
it and acts on it ([D-032](decisions.md#d-032)).

**Step (of a twin)** — From M11: `twin step`, which takes a running twin built from a
*waypoint* to another waypoint of its *series*, the next by default, forward or back,
without a rebuild. The *server* reads and compiles the target, computes the *step (of a
series)* between the two bundles and the *push plan*, and reads containerlab's plan,
making every refusal before any connection to the workflow service; the `fylgja-step`
workflow then stages the target, *reconciles* the lab, waits for every node containerlab
restarted, recreated or created, *replaces* every changed or restarted node's
configuration and records. It ends *stepped*, `unchanged`, rejected, cancelled or
*diverged*. A step that would restart or recreate a node needs `--allow-restart`
([D-036](decisions.md#d-036)). It then waits for the twin to be *settled* (*observe*),
under `--wait <duration>` or 2m0s, and records how the wait ended; the wait never changes
its outcome.

**Stepped** — From M11: a twin a *step (of a twin)* took to its target. Its `twin.json`
names the target's waypoint and bundle at the top level, `state: ready`, and the step in
its `step` block (outcome `stepped`, or `unchanged` when the two bundles differ by
provenance alone), and every node holds the target's bundle. `twin show` still calls it
`pinned`, and adds `stepped from demo/1 by run fylgja-step …` to the kind line.

**Stream** — From M13: an *API* answer that is a run's progress. A client names it
(`Fylgja-Stream`, 16 random bytes in hex) on the request of a create, a provision or a
step, and the server holds that request's interrupt channel under the name while the
request is open, and nothing once it ends. From the `start` frame, the operator's
interrupt is `POST /v1/streams/{stream}/interrupt`, delivered to the open request: the
first abandons a start still waiting for a worker or cancels the run, and the second stops
waiting. `204` when delivered, `404` when the stream has ended, `409` for a name already
open. A client that goes away leaves its run running. `twin destroy` has no stream
([D-040](decisions.md#d-040)).

**Supported package** — A shipped PSP that has passed both halves of the *conformance
suite*. It has a row in `psp/README.md`'s Supported packages table naming the image, the
version the node reported, the date and the tier-3 run whose twin the boot half read. A
shipped package without a row is not supported. Both shipped packages, `nokia_srlinux`
and `arista_eos`, have one. The test packages (`chassisos`, `fastos`, `slowos`) pass the
pure half only and are never shipped. Nothing at run time consults the table.

**Synthesized node** — A node in the twin but absent from intent: boundary speakers,
service mocks, later traffic generators. Added to the CTM before compilation; always
in the fidelity manifest.

**Target group** — The Infrahub Standard Group an artifact definition renders for:
`fylgja-devices` for `srlinux_device_config`. A device outside it has no *artifact*,
and the read refuses it as `artifact.missing`. Joining it renders nothing on its own
in Infrahub 1.11.2; a generate must follow. The fixture seed joins its devices and
generates ([D-028](decisions.md#d-028)).

**Task queue (Temporal)** — The named queue a worker polls. One, `fylgja`, until the
host move ([D-015](decisions.md#d-015)).

**Tiers** — The three levels of tests ([development.md](development.md#test-architecture)).
**Tier 1**, `make test`: no infrastructure, under 35 seconds, in CI on every push and pull
request. **Tier 2**, `make test-contract`: the *contract tests*, against a real Infrahub,
in CI on every push to `main` against one the *Infrahub part* brings up. **Tier 3**, `make
test-e2e`: eight cases on booted NOS images through a server and a worker, on demand and
never in CI, narrowed by a *platform list* when asked. A **hand check** is a scenario run by hand on the host, read by someone
present.

**Twin directory** — `twin/` under the *state root*: `bundle/`, a copy of the staged
bundle verified to hash to its `bundle_id` before deploy; `clab-fylgja/`, containerlab's
own working directory; and `twin.json`. Present exactly while a twin is provisioned or
being provisioned; removed whole by unstage. With containerlab, the whole state of the
twin ([D-014](decisions.md#d-014)).

**`twin.json`** — The twin's record, version `5`, written last by the record step and
removed with the *twin directory*
([contracts/twin.schema.json](../contracts/twin.schema.json)): the manifest's provenance
block, `observed_at` (or an explicit statement that it is unknown, when no read took
place), `bundle_id`, the provisioning run's identity, the version of the worker binary
that provisioned it, and each node's management address, *artifact* (name, content type,
checksum, size, never the bytes) and how long its *push* took; the *waypoint* the twin was
built from (series, sequence, description and where its `at` came from), or an explicit
`null`; `state` (`ready` or *diverged*); the last *step* (its sides, run, outcome,
*phase*, containerlab's plan with each package's declaration, each node's push outcome,
the timings, and the step's `wait`, `null` until `VerifyTwin` writes it), or `null`; and
on each node `holds`, the bundle whose content it runs. A step rewrites it whole, on every
path after its stage. Older versions are read where a twin may still carry one.

**Verified fact** — Something about a dependency checked against the running system,
not taken from its documentation: how Infrahub, containerlab, a NOS, Temporal or the
host actually behaves. Each names the version and the date it was verified against, and
is re-verified on any upgrade ([verified-facts.md](verified-facts.md)).

**Verify** — See *intent conformance report*.

**vrnetlab** — Packaging that runs a VM-based NOS inside a container. Needs
`/dev/kvm`.

**Walking twin** — The provisioned environment: a running virtual topology built from
one intent reference. "Twin" and "environment" are synonyms. One at a time. Walking
because a following twin tracks its intent
([§1](architecture.md#1-claims-that-shape-everything), [D-013](decisions.md#d-013)).

**Waypoint** — From M10: a mark the operator writes in Infrahub, a `FylgjaWaypoint`
object with a series, a sequence, a branch, an optional `as_of` and a description. It is
a name for a pinned reference. The kind is branch-agnostic, so a waypoint lands in no
branch's diff, and it is unique on series and sequence. The operator writes waypoints,
and Fylgja only reads them, from the default branch. The attribute is `as_of` because
Infrahub refuses a two-character name; everything Fylgja prints or records says `at`.
Write a waypoint last, after the branch's writes and after generating: one written
before the generate seals the old artifact. Editing a waypoint changes no twin already
built from it ([D-032](decisions.md#d-032); [schema/README.md](../schema/README.md)).

**Waypoint reference** — `<series>/<sequence>`, e.g. `demo/2`: the third way to name an
*intent reference* on the command line, beside `--branch` and `--branch --at`, given as
`--waypoint` to `twin create`, `twin step` and `intent read`. The series has no `/` and
no whitespace; the sequence is a positive integer with no leading zero. It resolves to a
pinned `(branch, at)`. The `at` is `given` when the waypoint carries an `as_of`, and
`written` when it is the `updated_at` Infrahub stamped on the waypoint's `branch`
attribute. The resolved reference is printed before every run and recorded in
`twin.json`.

**Worker (Temporal)** — The process that polls the task queue and runs workflow and
activity code: `fylgja worker run`, one per lab host.

**Workflow (Temporal)** — Durable, deterministic orchestration code. Fylgja has four, each
short: `provision`, `destroy`, `reconcile` (a *check*) and `step` (`fylgja-step`), which
ends with `VerifyTwin` ([D-007](decisions.md#d-007)).

**Workflow service** — The Temporal service the worker polls and the server starts,
follows and cancels runs through: `temporal server start-dev`, file-backed, on `:7233`,
until M8 replaces it with a self-hosted cluster. `FYLGJA_TEMPORAL_ADDRESS` names it.

**Write-up** — `docs/how-it-was-built.md`: one page on how Fylgja was built, saying what
a Spec Kit pass and a convergence pass are and giving the hours and model time per
milestone. Its figures are derived from the private development record, which it does not
cite ([how-it-was-built.md](how-it-was-built.md), [D-043](decisions.md#d-043)).
