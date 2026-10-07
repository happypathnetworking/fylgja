# Security

Fylgja builds a network twin on one lab host from intent it reads in Infrahub. This page
says what it protects, what it leaves to the operator, and how to report a vulnerability.

## The threat model

**The API has one token.** Every command but `fylgja serve` and `fylgja worker run` is a
request to the API's server, `fylgja serve`, on the lab host. The server reads one token,
`FYLGJA_API_TOKEN`, from its environment and refuses to start without it. A client sends
it as `Authorization: Bearer <token>` on every request, and the server compares it, in
constant time, before it reads anything else. There are no roles and no second token:
whoever holds the token can do everything the operator can, from reading intent to
building, stepping and destroying the twin ([D-042](docs/decisions.md#d-042)).

**The token is sent in the clear.** The server speaks HTTP/1.1 and terminates no TLS. It
listens on `127.0.0.1:7650` unless `--listen` says otherwise; told otherwise, its
start-up report says the token is sent unencrypted on that address. Keeping the token
confidential is the transport's work, and the transport is the operator's: loopback, an
SSH tunnel (`ssh -N -L 7650:127.0.0.1:7650 <lab host>` from a client's machine), or a
proxy that terminates TLS, which a client addresses by an `https://` URL. A client follows
no redirect, so it never sends the token to an address the operator did not give.

**The server and the worker hold every credential.** Both run on the lab host with
Infrahub's token and both node logins in their process environment. The server also
holds the API's token, which the worker never reads; a client holds the API's token
alone. `local/.env`, kept at mode `0600`, is the one file that holds a value. Fylgja
reads the process environment only, and never prints, logs or persists a credential: none
is in a bundle, a finding, an answer, a log line or a start-up report.

### On a shared host

- **The API's port** is on loopback, so any local user can reach it, but nothing is done
  without the token.
- **The environment and `local/.env` are the credentials.** Anyone who can read the
  environment of the operator's processes (as that user, or as root) or `local/.env` has
  every credential: the API's token, Infrahub's token and both node logins.
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
what you found, how to reproduce it, and the version (`fylgja --version`) or commit it
applies to.

**In scope**: the `fylgja` binary (the API's server, the worker and the client's
commands), the scripts under `scripts/`, and the workflows under `.github/workflows/`.

**Not in scope**:

- The network operating system images and their published default logins, which a twin
  uses on purpose.
- Infrahub, containerlab and Temporal themselves: report those to their projects
  ([Infrahub](https://github.com/opsmill/infrahub),
  [containerlab](https://github.com/srl-labs/containerlab),
  [Temporal](https://github.com/temporalio/temporal)).
- What this page states as the design: one token with no roles, sent without TLS, and the
  shared-host exposure above. A way around the token, or a credential that reaches a
  bundle, a finding, a log line or the output of a command or a script, is in scope.
