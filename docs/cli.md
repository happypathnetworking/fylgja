# The `fylgja-core` command

`fylgja-core` is a command-line client of the core's HTTP API. It creates twins, steps them to a
new blueprint, verifies them, reads what the runtime has room for, and files and compares
blueprints and bundles. It holds no rule of its own: every check is the server's, and a refusal
is printed as the server's status, rule and detail. Anything the command does, a program can do
with the same API.

The command is installed with the package `fylgja-core`. The server it talks to is
`fylgja-core-server`, a separate command that needs the package's `server` extra. `-h` and `--help`
print a command's usage and exit; they are not listed below.

## Before a command

The command reads three environment variables.

| Variable | Holds |
|---|---|
| `FYLGJA_API_ADDRESS` | The server's address, as `host:port` or an `http://` or `https://` URL. A server started with no listen address of its own is at `127.0.0.1:7650`. Required. |
| `FYLGJA_API_TOKEN` | The client's token, the one whose hash the server's token file holds. Required. |
| `FYLGJA_API_CA` | A file of CA certificates that an `https://` address is verified against. The system's trust is used when the variable is unset or empty. |

An address that holds a login, a token that is not a bearer token (letters, digits and `-._~+/`,
with trailing `=`) and a CA file that cannot be read are each refused with one line that names the
variable and never its value. All three variables are checked before any request is made, and a
refusal exits with status 2. The command never prints the token: not on success, not in an error,
and not with `--json`.

For a server running on the same host with its default listen address, set the two required
variables in the shell that runs the command, with the token you made for this client in place of
`TOKEN`:

```sh
export FYLGJA_API_ADDRESS=127.0.0.1:7650
export FYLGJA_API_TOKEN=TOKEN
```

How a token is made and entered in the server's token file is described in
[the token file](server.md#the-token-file).

## Commands

Each command below is `fylgja-core`, then the words in its first column. Every command takes
`--json`, before the noun or after the verb.

| Command | Options | Prints |
|---|---|---|
| `fylgja-core` | `--json`, `--version` | `--version` prints the command's name and version and exits. |
| `fylgja-core twin create NAME` | `--blueprint FILE` or `--bundle ID`, one required; `--driver D`; `--allow-restart`; `--no-wait`; `--json` | The twin's record, then its create run and the run's verdict. |
| `fylgja-core twin step NAME` | `--blueprint FILE` or `--bundle ID`, one required; `--allow-restart`; `--no-wait`; `--dry-run`; `--json` | The twin's record, then the run toward the new spec and its verdict. With `--dry-run`, the deployment, the verdict and each change the step would make. |
| `fylgja-core twin show NAME` | `--json` | The twin's record: generations, conditions, phase, bundle and nodes. |
| `fylgja-core twin list` | `--json` | A line for each twin, or `no twins`. |
| `fylgja-core twin verify NAME` | `--json` | The verdict of reading every node once and judging it against its bundle, with its counts and findings. |
| `fylgja-core twin destroy NAME` | `--no-wait`; `--json` | `twin NAME deleted`, then the destroy run and its verdict. |
| `fylgja-core capacity show` | `--json` | A line for each host with its free CPU and memory, what is pending, and the number of twins. |
| `fylgja-core run get ID` | `--json` | The run and, once it has ended, its verdict. |
| `fylgja-core run watch ID` | `--json` | A line for each event of the run until it ends, then its verdict. |
| `fylgja-core run cancel ID` | `--json` | The run as the server records it after the request. |
| `fylgja-core blueprint push FILE` | `--json` | `blueprint` and the id the blueprint is filed under. |
| `fylgja-core bundle build BLUEPRINT_ID` | `--json` | The bundle's id, blueprint, nodes, links and probes, a count of what was approximated, omitted and synthesized, and each finding. |
| `fylgja-core bundle get ID` | `--json` | The bundle's id, blueprint, nodes, links and probes. |
| `fylgja-core bundle diff FROM TO` | `--json` | What a step from the bundle FROM to the bundle TO changes, or `unchanged`. |

The forms a command takes, with `FILE` a blueprint file and `ID` a filed bundle's id:

```sh
fylgja-core twin create NAME --blueprint FILE [--driver D] [--allow-restart] [--no-wait]
fylgja-core twin create NAME --bundle ID [--driver D] [--allow-restart] [--no-wait]
fylgja-core twin step NAME --blueprint FILE [--allow-restart] [--no-wait]
fylgja-core twin step NAME --bundle ID [--allow-restart] [--no-wait]
fylgja-core twin step NAME --blueprint FILE --dry-run
fylgja-core twin destroy NAME [--no-wait]
fylgja-core --json twin list
fylgja-core run watch ID
```

A blueprint file is JSON or YAML. The command holds it to the blueprint format before it sends
it, and the server refuses the same file the same way. The three-node blueprint used below is
`testdata/blueprint/three-node.json` in a clone of the repository.

### Twins

`twin create` files the blueprint, writes a spec for a twin that must not exist yet, and waits for
the create run to end. `twin step` writes a new spec for a twin that does exist and waits for the
run toward it. Both exit by the run's verdict. A step to the spec the twin already has starts no
run, and the command says so. `--allow-restart` lets the run restart or recreate nodes; without
it, a step that would is refused with a finding that says which node. `--driver` names the driver
the twin runs on; without it the server's default is used, and a step keeps the twin's own driver.

`--no-wait` writes the spec, prints the twin's record and exits 0 without waiting. `twin destroy
--no-wait` asks for the deletion and prints the record in the same way.

`twin step --dry-run` writes nothing. It prints what the step would change, node by node and link
by link, and exits by the verdict of that plan. It cannot be given with `--no-wait`.

`twin destroy` waits until the twin is gone, then prints the destroy run. A teardown that leaves
the twin's record prints it, and the command exits by the destroy run's verdict, 3 when it is
`unclean`.

`twin verify` reads every node once and exits by the verdict it prints.

### Waiting and printing

While a command waits it prints its progress on standard error, a line for each phase the twin
reaches, such as `demo: pushed`. Standard output holds only the result, which is why the examples
below show standard output alone. With `--json` no progress is printed and standard output holds
one JSON value: the document the server answered, as it came. Which document that is depends on
the command:

- `twin create`, `twin step` and `twin destroy` print the run they waited for.
- With `--no-wait` they print the twin's record instead, and a `twin step` to the spec the twin
  already has prints the record too, since no run started.
- `twin step --dry-run` prints the plan: the deployment, the verdict and the changes.
- `twin show` and `twin list` print the record and the list of records, `twin verify` the verdict,
  `run get` and `run cancel` the run, `blueprint push` the blueprint's id, and `bundle build`,
  `bundle get` and `bundle diff` the bundle's document.
- `run watch` prints the list of the run's events, once the run has ended. A run that has ended with
  no verdict prints nothing, and the command exits 2.
- A command the server refuses prints the problem document it answered, and the one-line refusal
  still goes to standard error.

A command that waits rides through a restart of the server. Its watch reconnects for up to about
three minutes, each try given 5 seconds to connect, says so once on standard error, and then exits
with status 2 if the server does not return. A `run watch` begun while the server is away exits 2
at once.

## Examples

Each example is a command and its standard output. The twin is `demo`, and the address and token
come from the variables above. The two bundle ids in the last-but-one example are the compiled ids
of `testdata/blueprint/three-node.json` and of `testdata/blueprint/three-node-probed.json`. A
bundle's id comes from `bundle build`, which compiles a filed blueprint, from the `bundle:` line of
`twin show`.

```console
$ fylgja-core capacity show
host: cpu 10 of 10 free, memory 25907 of 31065 MiB free
pending: 0 nodes, 0 CPU, 0 MiB
twins: 0
```

```console
$ fylgja-core twin create demo --blueprint testdata/blueprint/three-node.json
twin demo: generation 1, observed 1
Ready: True
Stepping: False
phase: pushed
bundle: 6a6f441cad24814b55f082958b9caa2858660aea9d01fa9c6b20ea50f5ac2b31
nodes:
  n1 192.0.2.11
  n2 192.0.2.12 via bastion.example
  n3 192.0.2.13
run 01JB8Z5Y3V4W6X7Y8Z9A0B1C2D: create of twin demo, ended
asked by operator at 2026-11-03T10:00:00.000000Z, ended at 2026-11-03T10:04:30.000000Z
verdict: ok
```

```console
$ fylgja-core twin show demo
twin demo: generation 1, observed 1
Ready: True
Stepping: False
phase: pushed
bundle: 6a6f441cad24814b55f082958b9caa2858660aea9d01fa9c6b20ea50f5ac2b31
nodes:
  n1 192.0.2.11
  n2 192.0.2.12 via bastion.example
  n3 192.0.2.13
```

```console
$ fylgja-core twin step demo --blueprint testdata/blueprint/three-node-probed.json --dry-run
deployment: ea5bec45e47c677a365051ee341e69f4d2d639b630ad786cd5d3f7157d76acda
verdict: ok
changes:
  n1: kept
  n2: kept
  n3: kept
```

```console
$ fylgja-core twin verify demo
verdict: ok
  held 7, failed 0, skipped 0
```

```console
$ fylgja-core bundle diff 6a6f441cad24814b55f082958b9caa2858660aea9d01fa9c6b20ea50f5ac2b31 d45f6b7de1d7d90466cb31aeeb0197a0d2ab5f0beecb2ad69de6e480ebef2c31
diff 6a6f441cad24814b55f082958b9caa2858660aea9d01fa9c6b20ea50f5ac2b31 -> d45f6b7de1d7d90466cb31aeeb0197a0d2ab5f0beecb2ad69de6e480ebef2c31
probes added: n1-loop
```

```console
$ fylgja-core twin destroy demo
twin demo deleted
run 01JB8Z9K3V4W6X7Y8Z9A0B1C2E: destroy of twin demo, ended
asked by operator at 2026-11-03T10:00:00.000000Z, ended at 2026-11-03T10:04:30.000000Z
verdict: ok
```

`twin create` and `twin destroy` printed progress lines on standard error while they waited, here
`demo: compiled`, `demo: pushed` and `demo: destroyed`; they are not part of the output above.
The ids, times and counts depend on the blueprint and the server.

## Exit statuses

| Status | Means |
|---|---|
| 0 | The command succeeded, or the verdict it exits by is `ok`. |
| 1 | The verdict is negative: `rejected`, `failed` or `nonconforming`. |
| 2 | The server answered with a problem, the server could not be reached or its certificate is not trusted, or a write could not be followed to its verdict. The command itself failed: a variable is not set or cannot be used, a file cannot be read, a blueprint is not valid, or the command line is wrong. |
| 3 | The twin is left dirty: the verdict is `unclean` or `diverged`. |

A command exits by a verdict only where it waits for one: `twin create`, `twin step` and `twin destroy`
without `--no-wait`, `twin step --dry-run`, `twin verify` and `run watch`. The others, `--no-wait`
included, exit 0 whatever a run's verdict is. `run watch` on a run with no verdict exits 2, and so does Ctrl-C.

A refusal prints one line on standard error with the server's status, rule and detail, and each
finding under it. The terms are defined in [the glossary](glossary.md).
