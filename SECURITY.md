# Security

Fylgja builds a network twin on one lab host from intent it reads in Infrahub. It is two
deployables ([D-065](docs/decisions.md#d-065)): the **core**, the `fylgja` binary, which
runs a twin from a snapshot and knows no source of truth, and the **orchestrator**, a
Python project on Prefect under `orchestrator/`, which reads Infrahub, plans and rehearses
a proposed change's stages and drives the core through its API. This page says what each
protects, what it leaves to the operator, and how to report a vulnerability.

## The threat model

**The core's API has one token.** Every `fylgja` command but `fylgja serve` and `fylgja
worker run` is a request to the API's server, `fylgja serve`, on the lab host, and so is
every call the orchestrator's flows make to the core. The server reads one token,
`FYLGJA_API_TOKEN`, from its environment and refuses to start without it. A client sends it
as `Authorization: Bearer <token>` on every request, and the server compares it, in
constant time, before it reads anything else. There are no roles and no second token:
whoever holds the token can do everything the operator can do to the twin, from building,
stepping and destroying it to compiling a snapshot ([D-042](docs/decisions.md#d-042)).

**The token is sent in the clear, on loopback.** The server speaks HTTP/1.1 and terminates
no TLS. It listens on `127.0.0.1:7650` unless `--listen`, which may be given more than
once, says otherwise, and for each address off loopback its start-up report says the token
is sent unencrypted on it. The development host starts it on loopback alone (020's
FR-005). Keeping the token confidential is the transport's work, and the transport is the
operator's: loopback, an SSH tunnel (`ssh -N -L 7650:127.0.0.1:7650 <lab host>` from a
client's machine), or a proxy that terminates TLS, which a client addresses by an
`https://` URL. A client follows no redirect, so it never sends the token to an address the
operator did not give. **The core's token never crosses the Docker bridge**: nothing inside
Infrahub's containers holds it or reaches the core.

**The orchestrator's platform is on the bridge.** The orchestrator's flows run on a Prefect
server of its own (`make prefect-server`), which listens on the host's Docker bridge
address (`docker0`, `172.17.0.1` by Docker's default), port 4200, so that Infrahub's task
workers, on their own Compose network, reach it as `host.docker.internal:4200`: the checks
`fylgja-step` and `fylgja-twin` run there and are clients of the platform, never of the
core. Its API takes basic authentication, one `<user>:<password>` string
(`PREFECT_API_AUTH_STRING` for the host's processes, the same value as
`FYLGJA_ORCHESTRATOR_AUTH` for the checks); without it every path is `401` but Prefect's
`/api/health`. There is no TLS on the bridge, so the string is sent in the clear, and any
container on the host can reach that address, the twin's nodes included: the credential is
what guards it. Whoever holds it can start any of the six flows the runner,
`fylgja-orchestrator serve`, serves, with any parameters, and the runner runs them as the
operator's user with the orchestrator's credentials: reading Infrahub, writing a snapshot
file where a read's `out` names, creating, stepping and destroying the twin through the
core, and posting a rehearsal's report on a proposed change. It also reads every flow run
the platform holds, with its parameters, its findings document and its log. It is one
credential with no roles, a client that needs less than everything still deferred as
[D-050](docs/decisions.md#d-050) deferred it for the core's token.

**Who holds what.** `local/.env`, kept at mode `0600`, is the one file that holds a value.
Fylgja reads the process environment only.

- **The core's server** reads the API's token and both node logins. It reads no
  `INFRAHUB_*` and no scope, and the bring-up script starts it without `INFRAHUB_ADDRESS`,
  `INFRAHUB_API_TOKEN` and `FYLGJA_DEFAULT_SCOPE`; it carries the rest of `local/.env`'s
  variables, which it never reads, among them Infrahub's Compose values, whose
  `INFRAHUB_INITIAL_ADMIN_TOKEN` is Infrahub's token, and the platform's auth string.
- **The core's worker** reads both node logins, never the API's token or Infrahub's, and
  carries `local/.env` whole when it is started from it, as the bring-up script starts it.
- **A client of the core**, `fylgja` on any machine, holds the API's token alone.
- **The orchestrator**, `fylgja-cli` and the runner and its flows, reads Infrahub's token,
  for its adapter and for the report it posts, the API's token, since its flows are the
  core's clients, and the platform's auth string; never a node login, which it carries
  unread when started from `local/.env`. Its Prefect server reads the auth string alone,
  as `PREFECT_SERVER_API_AUTH_STRING`.
- **The Infrahub adapter** run as a tool (`python -m fylgja_orchestrator.adapters.infrahub`)
  reads Infrahub's token, never the API's.
- **The checks**, inside Infrahub's task workers, hold the platform's auth string alone, of
  Fylgja's credentials: the Compose override gives it them from `local/.env`, so whoever can
  inspect those containers holds it, and never the API's token.

None of them prints, logs or persists a credential: none is in a snapshot, a bundle, a
finding, an answer, a log line, a start-up report, a flow run's artifact or log, a check's
message or the thread the rehearse flow posts.

### On a shared host

- **The API's port** is on loopback alone, so any local user can reach it, but nothing is
  done without the token.
- **The orchestrator's platform** is on the Docker bridge, so any local user and any
  container on the host can reach it, but nothing is done or read without its auth string.
  Its database, under `local/orchestrator/prefect`, holds every flow run's parameters,
  findings document and log, and the orchestrator's state root, `local/orchestrator`, its
  snapshots, each carrying every device's artifact: both are as readable as the operator
  leaves those directories.
- **The environment and `local/.env` are the credentials.** Anyone who can read the
  environment of the operator's processes (as that user, or as root) or `local/.env` has
  every credential: the API's token, Infrahub's token, the platform's auth string and both
  node logins.
- **The workflow service** is Temporal's dev server (`temporal server start-dev`), on
  `127.0.0.1:7233` with its UI on `:8233`. It checks no credential, so any local user can
  read every run's history and start or cancel runs on the queue the worker serves.
- **The twin's nodes** use their images' published default logins, and sit on
  containerlab's default management network, a bridge on the lab host. Any local user can
  reach them and log in. Treat a twin as open to everyone on the host.
- **Infrahub's published Compose file** publishes port 8000 (the server), 2004 and 6362
  (Neo4j) and 15692 (RabbitMQ's metrics) on every interface, so Infrahub is reachable from
  the host's network, not only from loopback. The same file carries defaults for its admin
  token, agent token, secret key and admin password that anyone can read: set your own.

## Reporting a vulnerability

Report it privately, through GitHub's private vulnerability reporting: the repository's
**Security** tab, then **Report a vulnerability**. Do not open a public issue for it. Say
what you found, how to reproduce it, and the version (`fylgja --version`, `fylgja-cli
--version`) or commit it applies to.

**In scope**: the `fylgja` binary (the API's server, the worker and the client's
commands), the orchestrator under `orchestrator/` (`fylgja-cli`, the runner, its flows and
the Infrahub adapter), the two checks under `infrahub/checks/` that Infrahub's task workers
run, the scripts under `scripts/`, and the workflows under `.github/workflows/`.

**Not in scope**:

- The network operating system images and their published default logins, which a twin
  uses on purpose.
- Infrahub, containerlab, Temporal and Prefect themselves: report those to their projects
  ([Infrahub](https://github.com/opsmill/infrahub),
  [containerlab](https://github.com/srl-labs/containerlab),
  [Temporal](https://github.com/temporalio/temporal),
  [Prefect](https://github.com/PrefectHQ/prefect)).
- What this page states as the design: one token with no roles, sent without TLS, one
  platform credential with no roles, sent without TLS on the bridge, and the shared-host
  exposure above. A way around the token or the platform's credential, or a credential that
  reaches a snapshot, a bundle, a finding, a flow run's artifact or log, a log line or the
  output of a command or a script, is in scope.
