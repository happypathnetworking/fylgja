# Design: an OSPF adjacency check in the example orchestrator, over Nornir 3.7.0a1's asyncio runner

Private, 2026-11-16. Test code on a private branch of this repository; never pushed to the public
remote. This document lives on that branch, `private/nornir-ospf`.

## Intent

Try Nornir 3.7.0a1's async support against a fylgja twin, by giving the example orchestrator's
rehearsal one more judgement after each stage: every link of the blueprint between two
OSPF-speaking devices has a FULL adjacency on both ends. The core and the readers stay as released;
only the orchestrator, the Infrahub demo template and the development set-up change.

## Goals

- A Nornir inventory plugin that builds one host per device node of a twin from API 1 alone
  (the twin record and the bundle) plus the platform package files and the credential variables
  the core itself reads.
- A coroutine task on the asyncio runner, over nornir_scrapli's asyncssh connection, that reads
  each device's OSPF neighbours and their adjacency state.
- The check run in the rehearsal after each stage's verify, its failures recorded in that stage's
  entry and ending the rehearsal there, as a failed verify does.
- The demo network actually running OSPF, so the check has something to judge.

## Non-goals

- Any change to `core/`, `readers/`, or `formats/` (the orchestrator's two document schemas
  included: a stage's failures already carry arbitrary rule ids). The fixtures under `testdata/`
  and the tests that pin them may change, since the seed's rendering changes.
- NetBox. The NetBox template and seed are untouched.
- cEOS. The demo templates render SR Linux only; the check knows SR Linux's CLI alone.
- Defensive programming, exhaustive tests, the public repository's lint and review bar. `make lint`
  should still pass, because it is cheap, but nothing else is owed.
- Publishing anything: no push, no pull request, no decision entry in `design/decisions.md`.

## Anti-goals

- A check that passes when nothing was checked. A twin where no link joins two OSPF speakers must
  fail the check, not pass it.
- A verdict that fails from contention rather than intent. The check runs only after the stage's
  verify held, never during the step's wait, and its concurrency is bounded.
- A credential in a log line, a progress line, a Prefect artifact or the report.

## Constraints found in the repository

- **Infrahub reads this checkout's `.git`.** The task workers mount
  `~/projects/fylgja-core/.git` read-only and `make infrahub-register REF=<branch>` registers a
  branch of it ([infrahub/dev/compose.override.yml](../../../infrahub/dev/compose.override.yml),
  [infrahub/seed/register.py](../../../infrahub/seed/register.py)). A separate clone's branch is
  invisible to Infrahub unless it is pushed into this checkout. So the work is a **worktree of this
  repository on a private branch**, not a clone; the isolation of files is the same.
- **The rehearsal destroys its twin on every path**
  ([rehearsing.py:118-124](../../../orchestrator/src/fylgja_orchestrator/rehearsal/rehearsing.py#L118-L124)).
  The check must run inside `_Rehearsal`, between a stage's verify and the next step.
- **The packages are not served over API 1.** The SR Linux package's credential name (`srlinux`)
  sits in `psp/nokia_srlinux.yaml`; the orchestrator reads that file from disk.
- **The bundle names a node's configuration by path and hash, not by content**, and API 1 does
  not serve the file. So "OSPF-speaking" cannot be read from the configuration through the API; it
  is read from the device's state instead (below).
- **The seed's link ports carry no addresses.** Only the probe ports `ethernet-1/10` and
  `ethernet-1/11` are addressed, one /24 each
  ([infrahub/seed/main/5-devices.yml](../../../infrahub/seed/main/5-devices.yml)); the cabled ports
  `ethernet-1/1` and `ethernet-1/2` have none, so OSPF has nothing to run on. The maintainer's
  decision: **address every device-to-device link as a /31** in the seed, and leave the probe
  ports as they are.
- **The fixtures pin the rendering.** `testdata/blueprint/three-node*.json` carry each device's
  rendered configuration, the reader's contract tier compares Infrahub's artifacts to them,
  `testdata/compiler/three-node-probed.facts.json` carries their hashes, and
  `infrahub/tests/test_tree.py` asserts the exact set of addresses the seed holds. A changed seed
  and template mean those are regenerated on the branch.
- **The alpha's API is partly unstated** in its pull requests: the configuration key that selects
  the runner, `arun`'s signature, what an inventory plugin's `aload` returns, and the exact
  scrapli platform name for SR Linux. The builder reads them from the installed packages and
  records them in this branch's `design/verified-facts.md` under a heading of their own.

## Approaches

Three choices were weighed in conversation; the first was the maintainer's, the others are mine.

**How the adjacencies are read.**
- *A. SSH with nornir_scrapli 1.6.0a1's async tasks.* Chosen. The only route that uses what 3.7.0a1
  adds end to end: async inventory load, asyncio runner, async connection. Stacks an alpha on an
  alpha; host keys accepted blind.
- *B. gNMI with pygnmi wrapped in threads inside Nornir tasks.* The fallback if SR Linux and asyncssh
  fight. The core already proved that transport on these nodes, but the connections stay sync.
  Everything but the task body carries over from A.

**Where the code lives.**
- *A worktree of this repository on branch `private/nornir-ospf`.* Chosen, for the Infrahub mount
  reason above. Never pushed to `origin`.
- *A clone.* The maintainer's first thought; it would need its branch pushed into this checkout for
  Infrahub to read the template, so it adds a step for no gain.

**How the demo network gets OSPF.**
- *Address each device link as a /31 in the seed, and declare OSPF on every cabled, addressed
  port.* Chosen by the maintainer. Touches the seed, the fixtures and the tests that pin them,
  and gives the demo a network that actually routes.
- *Leave the seed alone and run OSPF point-to-point across the probe ports' mismatched /24s.* My
  first proposal; rejected, since it leans on the mask check being skipped rather than on a
  sensible network, and the link ports carry no addresses anyway.

## The design

### 1. The branch and worktree

`git worktree add ~/projects/fylgja-core-wt/nornir-ospf -b private/nornir-ospf main`, then
`make venv` there. All work, this document included, lands there. The branch is registered to the
development Infrahub with `make infrahub-register REF=private/nornir-ospf` and the network
re-seeded with `make infrahub-seed`, which regenerates the artifacts.

### 2. The seed

[infrahub/seed/main/5-devices.yml](../../../infrahub/seed/main/5-devices.yml) gives each cabled port
one /31 address, the pair of a link sharing it:

| Link | A end | B end |
|---|---|---|
| `n1:ethernet-1/1` – `n2:ethernet-1/1` | 10.0.0.0/31 | 10.0.0.1/31 |
| `n2:ethernet-1/2` – `n3:ethernet-1/1` | 10.0.0.2/31 | 10.0.0.3/31 |
| `n1:ethernet-1/2` – `n3:ethernet-1/2` | 10.0.0.4/31 | 10.0.0.5/31 |

The third link's addresses sit on `main` though its cable arrives at stage 1, as the ports do
today. The probe ports keep their /24s and gateways; `7-probes.yml` is untouched. Stage 2 still
adds `192.0.2.1/24` as a second address on `n1:ethernet-1/2`. The seed's header comment names
the /31 plan. `test_tree.py`'s seeded-address list gains the six.

### 3. The template

[infrahub/templates/device_config.j2](../../../infrahub/templates/device_config.j2) gains, after the
network-instance line, one OSPF instance in the default network-instance: admin-state enable,
version ospf-v2, a router-id, and area 0.0.0.0 with each **cabled and addressed** port's
subinterface `.0` as an interface of type point-to-point. The probe ports, addressed but
uncabled, stay out of OSPF. The router-id is the device's lowest address sorted as a string,
prefix dropped (n1: 10.0.0.0). Stage 2's `192.0.2.1/24` sorts after every `10.` address, so no
seeded stage moves a router-id; a stage that did would flap the adjacency and the check would say
so, which is correct. The exact SR Linux `set` lines, and that SR Linux takes a /31 with the
`.0` host address, are verified on a running node first and recorded. The template's header
comment says what was added and why.

Both seeded stages stay meaningful: stage 1 cables `n1`–`n3`, so a third adjacency must appear;
stage 2 adds a second address on `n1`'s `ethernet-1/2`, which must leave all three FULL.

### 3a. The fixtures

After the seed and template are registered and generated, the rendered configurations are read
back from Infrahub's artifacts into `testdata/blueprint/three-node.json` and
`three-node-probed.json` (and any other fixture whose devices render the same way), and
`testdata/compiler/three-node-probed.facts.json` is regenerated, so `make test` and the reader's
contract tier hold on the branch. Whatever else `make test` then names is mended in the same task.

### 4. Dependencies

The orchestrator's `pyproject.toml` adds `nornir==3.7.0a1`, `nornir-scrapli[asyncio]==1.6.0a1` and
`scrapli-community` pinned to the version the venv resolves, for the SR Linux platform. Nothing is
added to the core's or the readers' dependencies.

### 5. The inventory plugin

`orchestrator/src/fylgja_orchestrator/nornir/inventory.py`. A capability inventory plugin,
capabilities `{"asyncio"}`, registered in code with the capability register under the name
`fylgja-twin` (no entry point; this is test code). It takes the twin record and bundle as the
client returns them, the packages directory, and the environment mapping. It emits one host per
device node of the bundle (probe hosts excluded):

| Host field | From |
|---|---|
| name | the node's name |
| hostname | the record's node `address`; `access` is unused, the local driver's addresses being directly reachable |
| platform | the scrapli platform for the node's package id; `nokia_srlinux` for the one package in use |
| username, password | `FYLGJA_CREDENTIAL_<NAME>_USERNAME` / `_PASSWORD`, `<NAME>` from the package's `credentials`, upper-cased |
| connection options `scrapli` | extras: `transport` asyncssh, strict host keys off, a modest operation timeout |
| data | nothing the check needs; the links come from the bundle, not the hosts |

The password is set on the host and nowhere else; the plugin logs nothing.

### 6. The check

`orchestrator/src/fylgja_orchestrator/nornir/ospf.py`, one coroutine
`adjacencies(record, bundle, packages_dir, env, *, timeout_s) -> list[failure]`:

1. `AInitNornir` with the plugin above and the asyncio runner, per-host timeout and overall
   `timeout_s` set through the runner's options.
2. One task per host: `send_command` from `nornir_scrapli.async_tasks` with an `info from state`
   command over `network-instance default protocols ospf`, piped `| as json`, reading every
   neighbour's `adjacency-state` by interface. The exact command and the answer's shape are
   verified on a running node and recorded.
3. **Every device node of the bundle is an expected speaker** in this branch: the template gives
   OSPF to each device with an addressed port, and the demo has one platform. So every link of the
   bundle is in scope, and a device whose answer holds no OSPF instance is a failure in itself,
   not a device dropped from scope. (My call, stricter than "links between two speakers" so that
   a node whose OSPF never loaded cannot hide; a mixed network would need a list of expected
   speakers, which this branch does not need.) For each link end `<device>:<interface>`, the
   answer must hold a neighbour on that interface with state `full`.
4. **The read polls.** An adjacency forms seconds to tens of seconds after a push, and the step's
   verify waits for LLDP, not OSPF. So the coroutine reads every host, and while any failure
   remains and `timeout_s` has not passed, waits `OSPF_POLL_S` (5 s) and reads again; the last
   round's failures are the judgement. Connections stay open across rounds and are closed at the
   end, cancelled or timed-out hosts' included.
5. Failures, each a rehearsal finding `{rule, severity: error, object, message}`:
   - `ospf.instance.absent` on `<device>`, where the answer holds no OSPF instance;
   - `ospf.adjacency.not_full` on `<device>:<interface>`, the message naming the state seen or
     "no neighbour";
   - `ospf.node.unread` on `<device>`, where the host's result failed, timed out or was cancelled;
   - `ospf.links.none` with no object, where the bundle has no link, so that nothing passes
     vacuously.
6. A progress line per round, `ospf: <n> of <m> link ends full`, through the rehearsal's `say`.

The rules go in the orchestrator's [rules.py](../../../orchestrator/src/fylgja_orchestrator/rehearsal/rules.py)
and a row each in [rules.md](../../../orchestrator/rules.md): `orchestrator/tests/test_catalogue.py`
holds the two together and fails on a rule without its row, so the rows are part of the same task.

### 7. The rehearsal hook

In `_Rehearsal`, one method `_ospf(k, label, stage)` called twice: at the end of the baseline
create, once its settle holds (`_create`, after `self.baseline` is set), and at the end of
`_step`, after the verify's `new` is judged empty. It runs the coroutine with `asyncio.run`, the
rehearsal being synchronous, with `timeout_s` the lesser of a setting and the time left under
`limits.limit_s`. Failures mark the stage `failed` with those failures and raise `_Ended` with
`rules.STAGE_FAILED`, exactly as a verify failure does, so the report needs no change. Stages are
judged absolutely, not against the baseline: an adjacency the baseline lacked is still owed. On
the baseline, failures go to `already_failing` and the rehearsal continues, as the baseline's
verify failures do; stage 1 will then most likely fail on the same rules and end the rehearsal
there, with the report naming both, which is the honest outcome. The check is skipped when the
stage was skipped as unchanged.

### 8. Settings

Two variables read by the edge's settings beside the existing ones, neither required when the
check is absent... but the check is always on in this branch, so both have defaults:
`FYLGJA_ORCHESTRATOR_PACKAGES`, the packages directory, default the checkout's `psp/` resolved
from the worktree; `FYLGJA_ORCHESTRATOR_OSPF_TIMEOUT_S`, the polling budget, default 120.

### 9. Verification, in order

1. **Before building the check**, on a twin made from the current main by `fylgja-core twin
   create`: by hand on two cabled nodes, configure a /31 each and OSPF point-to-point, confirm
   FULL on both ends, read the state command's JSON, and note the exact `set` lines. Record all
   of it in `design/verified-facts.md` on the branch. **This is a go/no-go gate:** anything SR
   Linux refuses here comes back to the maintainer with the reading. The same holds for the gNMI
   fallback if asyncssh and SR Linux fight: stop and report, do not switch on your own.
2. **Pure tests**, few: the plugin's hosts from a canned record and bundle; the comparison from a
   canned JSON answer, covering a FULL link, a missing neighbour, a non-FULL state, an unread
   node and no link in scope.
3. **Live**, with `make infrahub-register REF=private/nornir-ospf`, `make infrahub-seed`, the core
   serving locally and `fylgja-orchestrator twin rehearse` on the seeded branch: a report whose
   stages all pass with three links FULL at stage 1 and 2. Then one negative run: disable OSPF on
   one node of a twin by hand between create and the step... which the rehearsal does not allow;
   instead, a throwaway third stage file that removes `n1:ethernet-1/1`'s /31, generated and
   marked as the seed marks its two. The bundle's links come from the cables, not the addresses,
   so the `n1`–`n2` link stays in scope; the core's verify is layer 1 and still passes; the
   template drops OSPF from the now unaddressed port, so `n1` still speaks and both ends report
   `ospf.adjacency.not_full` with "no neighbour", and the rehearsal ends failed at stage 3. The
   third stage is deleted after the run and never committed.

## Left to the builder

- The exact alpha API names (runner config key, plugin registration call, `aload`'s return,
  run options), read from the installed packages.
- The scrapli platform name and the SR Linux state command's precise form.
- How the hosts' connections are closed after a cancel or timeout; the alpha's docs have a page
  on it.
- Whether `scrapli-community` is needed or SR Linux is in core scrapli at that version.
- The pure tests' shape and the fixture files.
