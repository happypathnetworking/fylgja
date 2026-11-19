# OSPF adjacency check over Nornir 3.7.0a1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After each stage of a rehearsal is stepped and verified, read every device's OSPF neighbours over Nornir's asyncio runner and fail the stage unless every link of the bundle is FULL on both ends.

**Architecture:** A private branch of this repository, worked in a worktree. The seed gives each device link a /31 and the Infrahub template declares OSPF point-to-point on cabled, addressed ports. A new package `fylgja_orchestrator.nornir` holds an inventory plugin that builds hosts from a twin record and its bundle, and a check that polls the hosts' OSPF state over nornir_scrapli's async tasks and judges it against the bundle's links. The rehearsal takes an optional stage check and calls it after the baseline's settle and after each step's verify.

**Tech Stack:** Python 3.14, nornir 3.7.0a1 (asyncio runner, `AInitNornir`, capability inventory plugins), nornir-scrapli 1.6.0a1 with asyncssh, SR Linux 24.7.1 on containerlab, Infrahub 1.11.11, pytest.

**Spec:** `docs/superpowers/specs/2026-11-16-nornir-ospf-check-design.md` on the branch (written at `local/nornir-ospf/design.md` until Task 1 moves it).

## Global Constraints

- Nothing under `core/`, `readers/` or `formats/` changes. `testdata/` fixtures and the tests that pin them may.
- Branch `nornir-ospf`, worktree `~/projects/fylgja-core-wt/nornir-ospf`. Never commit `local/`.
- Conventional-commit messages whose body says why; each ends `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
- Pins: `nornir==3.7.0a1`, `nornir-scrapli[asyncio]==1.6.0a1`; `scrapli-community` at the version the venv resolves, if needed.
- No password reaches a log line, a progress line, a repr, a finding or the report.
- A fact about SR Linux, Infrahub or the alpha's API is read from the running system or the installed package and recorded in `design/verified-facts.md` on the branch before code relies on it.
- Every live tier runs one at a time on this host; `make live` and friends are not run by this plan.
- Two gates stop the work and report to the maintainer instead of choosing a fallback: SR Linux refusing a /31 or point-to-point FULL (Task 2), and asyncssh failing against SR Linux (Task 2).
- `make lint` and `make test` pass at the end of every task that touches code.

## Amendments from Tasks 1 and 2 (read before Tasks 3 to 7; they override the task text)

1. **Two reads, not one.** The adjacency read answers `{}` both for a node with no OSPF and for one
   with no neighbour (`design/verified-facts.md`, SR Linux, "OSPF point-to-point on /31s"). Task 5
   therefore has `COMMANDS: tuple[str, str]`, the oper-state read then the adjacency read, sent with
   `nornir_scrapli.async_tasks.send_commands(commands=list(COMMANDS))`, and
   `parse(oper_text: str, adjacency_text: str) -> dict[str, str] | None`: `None` when the oper-state
   answer holds no instance, else interface → state, the interface name with its `.0` dropped. The
   texts are `result[host][0].scrapli_response[i].result`.
2. **Fixtures as captured** in `orchestrator/tests/nornir/answers/`: `oper.json` and `full.json`
   (a speaking node, one FULL neighbour on `ethernet-1/1.0`), `absent.json` (oper-state of a node
   with no OSPF), `no-neighbour.json` (adjacency of a node with an instance and no neighbour).
3. **The connection needs an `on_open`.** Task 4's `scrapli` extras are `{"transport": "asyncssh",
   "auth_strict_key": False, "timeout_ops": 30, "on_open": inventory.on_open}`, where
   `async def on_open(conn)` writes `"\x1b[80;256R"` with `conn.channel.write(channel_input=...)`
   and then awaits `scrapli_community.nokia.srlinux.async_driver.default_async_on_open(conn)`.
   Without it every open times out at the prompt. Task 4's connection test asserts the key is there.
4. **A timed-out or failed host joins `nr.data.failed_hosts`.** Task 5's poll calls
   `nr.arun(..., on_failed=True)` every round, and closes with
   `nr.aclose_connections(on_failed=True)`.
5. **The plugin's capabilities are a `frozenset`**: `frozenset({"asyncio"})`, with `async def aload`.
   It is registered by `CapabilityInventoryPluginRegister.register(PLUGIN, TwinInventory)`; guard a
   second registration with a module flag. The runner is `{"plugin": "asyncio", "options":
   {"num_workers": ..., "per_host_timeout": ..., "timeout": ...}}`. `scrapli_community` came with
   the `asyncio` extra and needs no pin.
6. **This host's core listens where `FYLGJA_LISTEN` says**, port 7651 on 2026-11-16, not 7650: set
   `FYLGJA_API_ADDRESS` from it. The server is started from the main checkout as CONTRIBUTING has it
   (`FYLGJA_DRIVER=containerlab FYLGJA_STORE=local/store FYLGJA_PACKAGES=psp:probes`); `FYLGJA_PACKAGES`
   must name the worktree's `psp` only if a package changes, which this plan does not do.
7. **The template's lines are Task 2's**, verbatim in `design/verified-facts.md`; the template also
   needs `subinterface 0 ipv4 admin-state enable`, which it already renders for an addressed port.

8. **One pure test is red until Task 3's seed lands.**
   `infrahub/tests/test_tree.py::test_the_tree_names_no_address` lets a document quote only the
   fixtures' own addresses, and the design, this plan and `design/verified-facts.md` quote the six
   /31 addresses before the seed holds them (28 hits on 2026-11-16, every one `10.0.0.x` in those
   three files). Task 3 Step 2 puts them in `infrahub/seed/main/5-devices.yml`, a fixture, after
   which the test must pass; if it still names a file, mend it in Task 3. Every other pure test
   passed at Task 2's commit.

## Review Focus

Inputs the design implies but no test would otherwise pin; each has its test in the owning task.

1. A node whose answer holds no OSPF instance at all must fail `ospf.instance.absent`, not drop its links from scope (Task 5).
2. A neighbour in a state other than FULL (`exchange`, `two-way`, `init`) must fail with that state named, never pass as "a neighbour exists" (Task 5).
3. A host whose Nornir result failed, timed out or was cancelled must be `ospf.node.unread`, and the link ends on the other device must still be judged (Task 5).
4. A bundle with no links must fail `ospf.links.none` even when every host answers (Task 5).
5. A stage skipped as unchanged must not run the check, and a check on the baseline must land in `already_failing`, not fail the rehearsal (Task 6).

---

### Task 1: Branch, worktree, dependencies and the alpha's API facts

**Files:**
- Create: worktree `~/projects/fylgja-core-wt/nornir-ospf` on branch `nornir-ospf` from `main`
- Create: `docs/superpowers/specs/2026-11-16-nornir-ospf-check-design.md`, `docs/superpowers/plans/2026-11-16-nornir-ospf-check.md` (moved from `local/nornir-ospf/`)
- Modify: `orchestrator/pyproject.toml:15` (dependencies)
- Modify: `design/verified-facts.md` (new section at the end)

**Interfaces:**
- Produces: a venv at `core/.venv` in the worktree with the pins installed; a recorded list of the alpha's names every later task uses.

- [ ] **Step 1: Cut the worktree**

```bash
cd ~/projects/fylgja-core && git worktree add ~/projects/fylgja-core-wt/nornir-ospf -b nornir-ospf main
cd ~/projects/fylgja-core-wt/nornir-ospf && mkdir -p docs/superpowers/specs docs/superpowers/plans
cp ~/projects/fylgja-core/local/nornir-ospf/design.md docs/superpowers/specs/2026-11-16-nornir-ospf-check-design.md
cp ~/projects/fylgja-core/local/nornir-ospf/plan.md docs/superpowers/plans/2026-11-16-nornir-ospf-check.md
```
Edit the design's first paragraph: it now lives on the branch (drop the `local/` sentence).

- [ ] **Step 2: Pin the dependencies**

In `orchestrator/pyproject.toml`, append to `dependencies`: `"nornir==3.7.0a1"`, `"nornir-scrapli[asyncio]==1.6.0a1"`. Add a comment line above saying these are the private branch's, for the OSPF check. Run `make venv`. Expected: pip resolves both without `--pre` since the pins are exact. If `scrapli_community` is a separate distribution and the SR Linux platform lives there, add it pinned to what resolved.

- [ ] **Step 3: Read the alpha's API from the installed packages**

From the worktree's venv, with `python -c` and `inspect`, read and note:
- the import path of `AInitNornir` and the `runner` config key and plugin name that selects the asyncio runner (`nornir/init_nornir.py`, `nornir/plugins/runners/`);
- `CapabilityInventoryPlugin` and `CapabilityInventoryPluginRegister`: import path, `get_capabilities()`, whether `aload` is `async def`, and what `load`/`aload` return (`nornir/core/plugins/inventory.py`);
- the runner options for per-host and overall time limits and how `Nornir.arun` is called (`nornir/core/__init__.py`, `nornir/plugins/runners/asyncio.py` or wherever the class is);
- `nornir_scrapli.async_tasks.send_command`'s signature and how a timed-out host's connection is closed (`nornir_scrapli/async_tasks/`, and the `docs/user_guide/asyncio.md` shipped with the wheel if present);
- the scrapli platform name for SR Linux and which package provides it (`scrapli.factory` / `scrapli_community`).

- [ ] **Step 4: Record the facts**

Append a section `## Nornir 3.7.0a1 and nornir_scrapli 1.6.0a1 (private branch)` to `design/verified-facts.md`: one bullet per item above, each with the file it was read from, dated 2026-11-16. Nothing inferred: what the code says.

- [ ] **Step 5: Lint and commit**

Run: `make lint` → passes (the docs change nothing lint reads).
```bash
git add docs orchestrator/pyproject.toml design/verified-facts.md
git commit -m "chore(private): branch for the OSPF check over Nornir 3.7.0a1

Pins the alpha and nornir_scrapli's async line for the example orchestrator alone, and
records the alpha's API as the installed packages state it, so the check is written
against what is there and not against the pull requests' prose."
```

---

### Task 2: Gate — SR Linux takes a /31, forms a point-to-point FULL adjacency, and answers scrapli over asyncssh

**Files:**
- Modify: `design/verified-facts.md`, under `## SR Linux 24.7.1`, a new `### OSPF point-to-point on /31s, and the state read` subsection.

**Interfaces:**
- Produces: the exact `set` lines Task 3's template emits; the exact state command and a verbatim JSON answer Task 5's parser and tests use; proof the asyncssh transport works for Task 4.

- [ ] **Step 1: A twin to test on**

With the core server running as CONTRIBUTING's "Running the core" says and `local/.env` loaded:
```bash
export FYLGJA_API_ADDRESS=127.0.0.1:7650
core/.venv/bin/fylgja-core twin create ospf-gate --blueprint testdata/blueprint/three-node.json
core/.venv/bin/fylgja-core twin show ospf-gate
```
Note `n1`'s and `n2`'s addresses. The login is `FYLGJA_CREDENTIAL_SRLINUX_USERNAME` / `_PASSWORD` from `local/.env`; never print the password.

- [ ] **Step 2: Configure by hand on `n1` and `n2`**

Over SSH to each node's CLI, in a candidate, on the link `n1:ethernet-1/1`–`n2:ethernet-1/1`:
- the subinterface's ipv4 address `10.0.0.0/31` on `n1`, `10.0.0.1/31` on `n2`;
- `network-instance default protocols ospf instance main`: `admin-state enable`, `version ospf-v2`, `router-id <that address>`, `area 0.0.0.0 interface ethernet-1/1.0 interface-type point-to-point`;
- commit. Note any line SR Linux refuses and the exact accepted form.

- [ ] **Step 3: Read the adjacency**

On both nodes: `info from state network-instance default protocols ospf instance main area * interface * neighbor * adjacency-state | as json`. Expected: one neighbour per node, `adjacency-state` `full`, within about 40 s. Also run the same command on `n3`, which has no OSPF, and record what an instance-less answer looks like. Save both JSON answers verbatim (`n1`'s and `n3`'s) into `orchestrator/tests/nornir/answers/` as `full.json` and `absent.json` (Task 5's fixtures).

- [ ] **Step 4: The asyncssh transport**

A throwaway script in the scratchpad, from the worktree's venv: open scrapli's `AsyncScrapli` with `transport="asyncssh"`, `auth_strict_key=False`, the SR Linux platform from Task 1, against `n1`; send the state command; print its result's length and `failed`. Expected: `failed` False, JSON back. If it fails, **stop**: record what failed and report to the maintainer (the gNMI fallback is theirs to choose).

- [ ] **Step 5: Record and clean up**

Write the subsection in `design/verified-facts.md`: the accepted `set` lines, the time to FULL, the state command, the shape of a `full` answer and of an instance-less answer, and the asyncssh reading, dated. Then `fylgja-core twin destroy ospf-gate`.

- [ ] **Step 6: Commit**

```bash
git add design/verified-facts.md orchestrator/tests/nornir/answers
git commit -m "docs(private): SR Linux forms a point-to-point OSPF FULL over a /31, read as JSON over asyncssh

The gate the OSPF check rests on, read on the running node, with the two answers the
check's parser is tested against."
```

---

### Task 3: The seed's /31s, the template's OSPF, and the fixtures that pin them

**Files:**
- Modify: `infrahub/seed/main/5-devices.yml`, `infrahub/templates/device_config.j2`
- Modify: `infrahub/tests/test_tree.py:242-243`, `infrahub/tests/test_fixture.py:72`
- Modify: `testdata/blueprint/three-node.json`, `testdata/blueprint/three-node-probed.json` (each device's `config`), `testdata/compiler/three-node.facts.json`, `testdata/compiler/three-node-probed.facts.json` (config digests)

**Interfaces:**
- Produces: a seeded `main` and branch `third-link` whose devices run OSPF on every cabled port; fixtures whose rendered configurations match Infrahub's artifacts.

- [ ] **Step 1: Make the fixture tests fail first**

In `test_tree.py`, extend the seeded set with the six /31 host addresses: `10.0.0.0` … `10.0.0.5`. In `test_fixture.py`, `assert len(addresses) == 12`. Run: `cd infrahub && ../core/.venv/bin/pytest -q tests/test_tree.py tests/test_fixture.py`. Expected: both fail on the seed as it stands.

- [ ] **Step 2: The seed**

In `5-devices.yml`, give each cabled port an `ip_addresses` block as the probe ports have, per the design's table: `n1:ethernet-1/1` 10.0.0.0/31, `n2:ethernet-1/1` 10.0.0.1/31, `n2:ethernet-1/2` 10.0.0.2/31, `n3:ethernet-1/1` 10.0.0.3/31, `n1:ethernet-1/2` 10.0.0.4/31, `n3:ethernet-1/2` 10.0.0.5/31. Add one sentence to the header: each device link is a /31 so OSPF has a network to run on.

- [ ] **Step 3: The template**

In `device_config.j2`, after the `network-instance default type default` line, render the OSPF instance when the device has at least one cabled port with an address (`port.connector.node` and `port.ip_addresses.edges`): `admin-state enable`, `version ospf-v2`, `router-id` = the lowest such address sorted as a string with its prefix dropped, then for each such port in name order `area 0.0.0.0 interface <name>.0 interface-type point-to-point`, in the exact `set` forms Task 2 recorded. Extend the header comment with what was added and why.

- [ ] **Step 4: Register, seed, read back**

```bash
set -a; . local/.env; set +a
make infrahub-register REF=nornir-ospf
make infrahub-seed
```
Expected: both end 0, every artifact `Ready`. Then read the branch `third-link` at its first stage with the reader's CLI (`readers/infrahub/README.md`, "The CLI") under `infrahub/seed/reader.yaml` and scope `tag:fylgja`, and copy each device's `config` into `three-node.json` and `three-node-probed.json`. Confirm the OSPF lines are in each, and that `n1`'s lists `router-id 10.0.0.0`.

- [ ] **Step 5: The compiler facts**

Run: `make test`. Expected: `core/tests/test_compiler.py` fails on the config digests of the two fixtures. Update each node's digest in the two `.facts.json` files to the SHA-256 the test computes (read the assertion for the field's name). Run `make test` again. Expected: all pass. Anything else that fails names a pin this task missed: mend it here.

- [ ] **Step 6: Lint and commit**

Run: `make lint` → passes.
```bash
git add infrahub testdata
git commit -m "feat(private): the demo network runs OSPF point-to-point over a /31 per link

The seed's cabled ports carried no addresses and the template rendered nothing routed, so
there was nothing for an adjacency check to judge. Each device link is now a /31, the
template declares one OSPF instance with those ports in area 0 as point-to-point, and the
fixtures and the tests that pin the seed and the rendering follow."
```

---

### Task 4: The inventory plugin

**Files:**
- Create: `orchestrator/src/fylgja_orchestrator/nornir/__init__.py` (empty docstring module), `orchestrator/src/fylgja_orchestrator/nornir/inventory.py`
- Test: `orchestrator/tests/nornir/__init__.py`, `orchestrator/tests/nornir/test_inventory.py`

**Interfaces:**
- Produces:
  - `hosts(record: Mapping[str, Any], bundle: Mapping[str, Any], packages_dir: Path, environ: Mapping[str, str]) -> Hosts` — Nornir's `Hosts` (the `Inventory`'s hosts dict), one per node of `bundle["nodes"]` (device nodes only; the record's probe hosts are not in the bundle's `nodes`).
  - `class TwinInventory` — the capability inventory plugin, constructed with the same four arguments, capabilities `{"asyncio"}`, whose load returns an `Inventory` of those hosts.
  - `PLUGIN = "fylgja-twin"` and `register() -> None`, which registers the class under that name with the capability register, idempotent.
  - `SCRAPLI_PLATFORM: dict[str, str]` mapping package id → scrapli platform, `{"nokia_srlinux": <Task 1's name>}`.

- [ ] **Step 1: Write the failing tests**

```python
RECORD = {"status": {"nodes": [{"name": "n1", "address": "192.0.2.11"}, {"name": "n2", "address": "192.0.2.12"},
                               {"name": "n1-loop-a", "address": "192.0.2.21"}]}}   # shape per twin-record-1
BUNDLE = {"nodes": [{"name": "n1", "platform": "nokia_srlinux"}, {"name": "n2", "platform": "nokia_srlinux"}],
          "links": [{"a": {"device": "n1", "interface": "ethernet-1/1"}, "b": {"device": "n2", "interface": "ethernet-1/1"}}]}
ENV = {"FYLGJA_CREDENTIAL_SRLINUX_USERNAME": "admin", "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "s3cret"}

def test_one_host_per_device_node_at_its_address():
    found = hosts(RECORD, BUNDLE, ROOT / "psp", ENV)
    assert sorted(found) == ["n1", "n2"]
    assert found["n1"].hostname == "192.0.2.11"

def test_the_login_is_the_packages_credential_read_from_the_environment():
    h = hosts(RECORD, BUNDLE, ROOT / "psp", ENV)["n1"]
    assert (h.username, h.password) == ("admin", "s3cret")
    assert "s3cret" not in repr(h)   # Nornir's Host repr is its name; this pins that no one changes it

def test_the_connection_is_scrapli_over_asyncssh_with_strict_keys_off():
    h = hosts(RECORD, BUNDLE, ROOT / "psp", ENV)["n1"]
    assert h.platform == SCRAPLI_PLATFORM["nokia_srlinux"]
    extras = h.connection_options["scrapli"].extras
    assert extras["transport"] == "asyncssh" and extras["auth_strict_key"] is False

def test_the_plugin_declares_asyncio_and_loads_the_same_hosts():
    plugin = TwinInventory(RECORD, BUNDLE, ROOT / "psp", ENV)
    assert plugin.get_capabilities() == {"asyncio"}
    inventory = asyncio.run(plugin.aload()) if inspect.iscoroutinefunction(plugin.aload) else plugin.aload()
    assert sorted(inventory.hosts) == ["n1", "n2"]
```
Read the record's node field path from `formats/twin-record-1.schema.json` before fixing `RECORD`'s shape.

- [ ] **Step 2: Run them**

Run: `cd orchestrator && ../core/.venv/bin/pytest -q tests/nornir/test_inventory.py`. Expected: FAIL, `fylgja_orchestrator.nornir.inventory` not found.

- [ ] **Step 3: Implement `inventory.py`**

The package's credential name is `yaml.safe_load(packages_dir / f"{platform}.yaml")["credentials"]`; the variables are `FYLGJA_CREDENTIAL_{NAME.upper().replace('-', '_')}_{USERNAME,PASSWORD}` (as `core/src/fylgja_core/credentials.py` reads them). Connection options: `ConnectionOptions(extras={"transport": "asyncssh", "auth_strict_key": False, "timeout_ops": 30})` under the key `"scrapli"`. Use Nornir's `Host`, `Hosts`, `Groups`, `Defaults`, `Inventory`, `ConnectionOptions` from `nornir.core.inventory`. The plugin method names and return are Task 1's facts.

- [ ] **Step 4: Run, lint, commit**

Run: the test file → PASS; `make lint` → passes.
```bash
git add orchestrator/src/fylgja_orchestrator/nornir orchestrator/tests/nornir
git commit -m "feat(private): a Nornir inventory of a twin, from its record and bundle

One host per device node at the record's management address, the login read from the
same credential variables the core reads, the connection scrapli over asyncssh."
```

---

### Task 5: The check — expectation, parsing, judgement, and the polling run

**Files:**
- Create: `orchestrator/src/fylgja_orchestrator/nornir/ospf.py`
- Modify: `orchestrator/rules.md` (a final section `## Findings: the OSPF check`)
- Test: `orchestrator/tests/nornir/test_ospf.py`, `orchestrator/tests/test_catalogue.py` (one test appended)

**Interfaces:**
- Produces, in `ospf.py`:
  - `RULE_NOT_FULL = "ospf.adjacency.not_full"`, `RULE_ABSENT = "ospf.instance.absent"`, `RULE_UNREAD = "ospf.node.unread"`, `RULE_NO_LINKS = "ospf.links.none"`; `SEVERITY: dict[str, str]`, every rule `"error"`.
  - `COMMAND: str` — Task 2's state command.
  - `expected(bundle: Mapping[str, Any]) -> list[tuple[str, str]]` — every link end `(device, interface)`, both ends of each link, sorted.
  - `parse(text: str) -> dict[str, str] | None` — interface name → adjacency state from the JSON answer; `None` when the answer holds no OSPF instance.
  - `judge(ends: Sequence[tuple[str, str]], devices: Iterable[str], answers: Mapping[str, dict[str, str] | None | Unread]) -> list[dict[str, Any]]` — the failures as rehearsal findings (`documents.finding(rule, "error", message, object)`), where `Unread` is a marker class carrying the host's error text (`class Unread: reason: str`).
  - `async def adjacencies(record, bundle, packages_dir, environ, *, timeout_s: float, poll_s: float = 5.0, say: Callable[[str], None] | None = None, clock=time.monotonic, sleep=asyncio.sleep) -> list[dict[str, Any]]`.
  - `StageCheck = Callable[[Mapping[str, Any], Mapping[str, Any], float], list[dict[str, Any]]]` and `def check(packages_dir: Path, environ: Mapping[str, str], *, say=None) -> StageCheck` — the sync closure `(record, bundle, timeout_s) -> failures` that `asyncio.run`s `adjacencies`.

- [ ] **Step 1: Write the failing tests** (fixtures from Task 2's `answers/`)

```python
ENDS = [("n1", "ethernet-1/1"), ("n2", "ethernet-1/1")]
FULL = parse(ANSWERS / "full.json" text)   # {"ethernet-1/1": "full"}

def test_expected_is_both_ends_of_every_link(): assert expected(BUNDLE) == ENDS
def test_parse_reads_each_interfaces_state(): assert parse(full_text) == {"ethernet-1/1": "full"}
def test_parse_answers_none_for_a_node_without_ospf(): assert parse(absent_text) is None
def test_all_full_is_no_failure(): assert judge(ENDS, ["n1", "n2"], {"n1": FULL, "n2": FULL}) == []
def test_a_missing_neighbour_names_the_end():
    found = judge(ENDS, ["n1", "n2"], {"n1": FULL, "n2": {}})
    assert [(f["rule"], f["object"]) for f in found] == [(RULE_NOT_FULL, "n2:ethernet-1/1")]
    assert "no neighbour" in found[0]["message"]
def test_a_state_short_of_full_names_the_state():            # Review Focus 2
    found = judge(ENDS, ["n1", "n2"], {"n1": FULL, "n2": {"ethernet-1/1": "exchange"}})
    assert found[0]["rule"] == RULE_NOT_FULL and "exchange" in found[0]["message"]
def test_a_node_without_an_instance_fails_itself():          # Review Focus 1
    found = judge(ENDS, ["n1", "n2"], {"n1": FULL, "n2": None})
    assert (found[0]["rule"], found[0]["object"]) == (RULE_ABSENT, "n2")
def test_an_unread_node_is_said_and_the_other_end_still_judged():   # Review Focus 3
    found = judge(ENDS, ["n1", "n2"], {"n1": Unread("timed out"), "n2": {}})
    assert [(f["rule"], f["object"]) for f in found] == [(RULE_UNREAD, "n1"), (RULE_NOT_FULL, "n2:ethernet-1/1")]
def test_no_links_cannot_pass():                              # Review Focus 4
    assert [f["rule"] for f in judge([], ["n1"], {"n1": FULL})] == [RULE_NO_LINKS]
def test_the_catalogue_lists_exactly_the_checks_rules():     # in test_catalogue.py, section "## Findings: the OSPF check"
    rows = _rows("## Findings: the OSPF check")
    assert {row[0] for row in rows} == set(ospf.SEVERITY) == {v for k, v in vars(ospf).items() if k.startswith("RULE_")}
```
Failures are sorted by object. One failure per end, one `RULE_ABSENT` per device (its ends then produce no `RULE_NOT_FULL`), one `RULE_UNREAD` per unread device likewise.

- [ ] **Step 2: Run them** → FAIL, module not found.

- [ ] **Step 3: Implement the pure parts and the catalogue section**

`parse` walks the JSON Task 2 recorded; the key path is that fact. Add the section to `rules.md` after the NetBox section: a table of the four rules, severity `error`, status `none`, one sentence each; note that `rehearsal.stage.failed`'s sentence gains a variant *By the OSPF check:* (Task 6 writes it). `test_catalogue.py`'s `_rows(NETBOX)` stops at the next `## `, so the existing tests hold.

- [ ] **Step 4: Implement `adjacencies` and `check`**

`adjacencies`: `inventory.register()`; `nr = await AInitNornir(inventory={"plugin": PLUGIN, "options": {...}}, runner={"plugin": <asyncio runner name>, "options": {per-host timeout: poll_s * 4, overall: timeout_s}})` per Task 1's facts; then loop: `result = await nr.arun(task=send_command, command=COMMAND)`; per host, `Unread(str(result[host].exception))` where `result[host].failed`, else `parse(result[host][0].result)`; `failures = judge(...)`; `say(f"ospf: {ends - failed_ends} of {len(ends)} link ends full")`; break when `failures == []` or `clock() - started >= timeout_s`; else `await sleep(poll_s)`. Finally close connections with the alpha's async close (Task 1's fact). `check` returns `lambda record, bundle, timeout_s: asyncio.run(adjacencies(...))`. No test beyond the live run (Task 7); keep it under 60 lines.

- [ ] **Step 5: Run, lint, commit**

Run: `cd orchestrator && ../core/.venv/bin/pytest -q tests/nornir tests/test_catalogue.py` → PASS; `make lint` → passes.
```bash
git add orchestrator/src/fylgja_orchestrator/nornir/ospf.py orchestrator/tests/nornir/test_ospf.py orchestrator/tests/test_catalogue.py orchestrator/rules.md
git commit -m "feat(private): the OSPF adjacency check, judged against the bundle's links

Every device node is expected to speak, every link end to be FULL; a silent instance, a
short state, an unread node and a bundle with no links are each a failure of their own, so
nothing passes vacuously. The read polls over the asyncio runner until FULL or its budget."
```

---

### Task 6: The rehearsal hook and the settings

**Files:**
- Modify: `orchestrator/src/fylgja_orchestrator/rehearsal/rehearsing.py` (`rehearse` signature; `_Rehearsal.__init__`; `_create` end; `_step` end; new `_ospf`)
- Modify: `orchestrator/src/fylgja_orchestrator/edge/settings.py` (two fields), `orchestrator/src/fylgja_orchestrator/edge/run.py:88-111` (`rehearse` builds the check)
- Modify: `orchestrator/rules.md:45` (the `rehearsal.stage.failed` row gains *By the OSPF check:*)
- Test: `orchestrator/tests/test_rehearse.py`, `orchestrator/tests/test_edge_run.py` (or the settings test module, whichever holds `from_env` tests)

**Interfaces:**
- Consumes: `StageCheck`, `check` from Task 5.
- Produces: `rehearse(..., check: StageCheck | None = None)` in `rehearsing.py` and re-exported by `fylgja_orchestrator.rehearsal`; `Settings.packages: Path`, `Settings.ospf_timeout_s: float`; variables `FYLGJA_ORCHESTRATOR_PACKAGES` (default `<repo root>/psp`, the root being `Path(__file__).resolve().parents[4]`) and `FYLGJA_ORCHESTRATOR_OSPF_TIMEOUT_S` (default `120`), both optional.

- [ ] **Step 1: Write the failing rehearsal tests** (in `test_rehearse.py`, using `rehearsed`'s pattern; add a `check` keyword to `rehearsed` that it passes through)

```python
def failing(record, bundle, timeout_s): return [documents.finding("ospf.adjacency.not_full", "error", "no neighbour", "n2:ethernet-1/1")]
def passing(record, bundle, timeout_s): return []

def test_a_check_failure_fails_the_stage_as_verify_does(served, c):
    doc, _ = rehearsed(served, [(S1, built(...)), (S2, built(...))], c, check=lambda r, b, t: failing(r, b, t) if <stage 2 is being checked> else [])
    assert results(doc) == ["created", "failed"]
    assert doc["stages"][1]["failures"][0]["rule"] == "ospf.adjacency.not_full"
    assert doc["status"] == "failed" and "OSPF" in doc["headline"] or "OSPF" in doc["findings"][0]["message"]

def test_a_passing_check_leaves_the_stage_passed(served, c): results == ["created", "passed"]

def test_a_baseline_failure_is_already_failing_and_the_rehearsal_goes_on(served, c):   # Review Focus 5
    calls = []
    def once(record, bundle, timeout_s): calls.append(1); return failing(record, bundle, timeout_s) if len(calls) == 1 else []
    doc, _ = rehearsed(served, [(S1, built(...)), (S2, built(...))], c, check=once)
    assert doc["already_failing"][0]["rule"] == "ospf.adjacency.not_full"
    assert results(doc) == ["created", "passed"] and doc["status"] == "passed"

def test_a_skipped_stage_is_not_checked(served, c):   # Review Focus 5
    calls = []
    ... two stages sharing one bundle_id ...; check appends to calls
    assert results(doc)[1] == "skipped" and len(calls) == 1

def test_the_check_is_given_the_time_left(served, c):
    seen = []; check records timeout_s; Limits(limit_s=...) small enough that the second call's budget is less than the setting
```
Distinguish the baseline call from a step call in a fake by counting calls. Write the settings test: `from_env` with neither variable set gives `packages == ROOT / "psp"` and `ospf_timeout_s == 120.0`; with both set, the given values.

- [ ] **Step 2: Run them** → FAIL, `rehearse() got an unexpected keyword 'check'`.

- [ ] **Step 3: Implement**

In `rehearsing.py`: `rehearse(..., check: StageCheck | None = None, ospf_timeout_s: float = 120.0)`; `_Rehearsal` stores both. `_ospf(self, k: int, label: str) -> list[dict[str, Any]]`: returns `[]` when `check is None`; else `record, _ = self.core.get_twin(self.twin)`, `bundle = self.core.get_bundle(record["spec"]["bundle_id"])` (confirm the field path in `twin-record-1.schema.json`), `budget = max(1.0, min(self.ospf_timeout_s, self.limits.limit_s - (self.clock() - self.started)))`, `self.say(f"ospf: stage {k}, {label}, checking")`, returns `self.check(record, bundle, budget)`. In `_create`, after `self.baseline = ...` and the verify judgement: `self.already_failing += self._ospf(k, label)` (append, keeping verify's first). In `_step`, after `if new: ...` and before `self.stages[k - 1] = stage`: `found = self._ospf(k, label)`; if found, `self.stages[k - 1] = stage | {"result": "failed", "failures": found}` and `raise _Ended(_said(rules.STAGE_FAILED, f"The OSPF check found {n} {failure(s)} at stage {k}, {label}, the first {rules.quote(found[0])}."))`. Add that sentence as *By the OSPF check:* in `rules.md`'s `rehearsal.stage.failed` row. In `settings.py`: the two fields and names, read in `from_env` with the defaults, listed in the module docstring's count. In `run.py`'s `rehearse`: `check=ospf.check(settings.packages, os.environ, say=progress)` and `ospf_timeout_s=settings.ospf_timeout_s`; `run.rehearse` gains a `settings: Settings` parameter if it has none — read how `flows.py:106` and `cli.py` call it and thread settings through (they hold a `config`/`Context` already).

- [ ] **Step 4: Run, lint, commit**

Run: `make test` → passes (the existing rehearsal tests pass `check=None`); `make lint` → passes.
```bash
git add orchestrator
git commit -m "feat(private): the rehearsal runs the OSPF check after the baseline settles and after each step

A check failure fails the stage as a verify failure does and ends the rehearsal there; on
the baseline it is already failing. The check is given the lesser of its budget and the
rehearsal's time left, and a stage skipped as unchanged is not checked."
```

---

### Task 7: Live acceptance — the seeded change passes, a broken link fails

**Files:**
- Modify: `design/verified-facts.md` (the Nornir section: the live readings)
- Temporary, never committed: `infrahub/seed/stages/3-n1-unaddressed.yml`

- [ ] **Step 1: Everything up**

`local/.env` loaded; the core server running locally; `make infrahub-up` (if down); `make infrahub-register REF=nornir-ospf` (picks up Task 6's commit on the task workers); `make infrahub-seed`; `make orchestrator-env`. Expected: each ends 0.

- [ ] **Step 2: The positive run**

From the worktree, with the runner's environment as `make orchestrator-serve` would give it (CONTRIBUTING, "Running the example orchestrator"; or simply `export FYLGJA_API_TOKEN=$FYLGJA_ORCHESTRATOR_API_TOKEN FYLGJA_INFRAHUB_TOKEN=$FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`):
```bash
core/.venv/bin/fylgja-orchestrator twin rehearse third-link --json > /tmp/claude-1000/.../rehearsal.json; echo $?
```
Expected: exit 0; `status` `passed`; stage results `["created", "passed", "passed"]`; the progress shows `ospf: 4 of 4 link ends full` at the baseline (two links) and `6 of 6` at stages 1 and 2; `already_failing` empty. Note the seconds each check took.

- [ ] **Step 3: The negative run**

Write `infrahub/seed/stages/3-n1-unaddressed.yml`: an `InterfacePhysical` edit on `n1`'s `ethernet-1/1` that removes its /31 (read how `2-n1-address.yml` sets one and how Infrahub's object loader expresses a removed relationship; if the loader cannot remove, delete the `IpamIPAddress` `10.0.0.0/31` by `infrahubctl` on the branch instead). Add a third `Edit` to `seed.py`'s list for the run only. Re-run `make infrahub-seed`, then the rehearsal. Expected: exit 1; `status` `failed`; stage 3 `failed` with failures `ospf.adjacency.not_full` on `n1:ethernet-1/1` and `n2:ethernet-1/1`, both "no neighbour"; the cause's message begins `The OSPF check found 2 failures at stage 3`. Then `git checkout -- infrahub/seed/seed.py && rm infrahub/seed/stages/3-n1-unaddressed.yml` and `make infrahub-seed` once more so the instance holds the two-stage branch.

- [ ] **Step 4: Record and commit**

Append the two runs' readings to the Nornir section of `design/verified-facts.md`: the counts, the seconds to FULL after each step, the negative run's failures, dated.
```bash
git status --short   # nothing of local/, no stage 3, no seed.py change
git add design/verified-facts.md
git commit -m "docs(private): the OSPF check read on the seeded change, passing, and failing a link without an address"
```
Report to the maintainer with the two documents' headlines and the readings. Do not push.
