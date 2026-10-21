# Contract: the server on two addresses, the override, the bring-up script, the host

## `fylgja serve --listen <host:port>...`

`--listen` is repeatable; none given is `127.0.0.1:7650` as today. In order, before anything
listens: every value is checked `host:port` (`fylgja serve: --listen <value> is not
host:port`, exit 2); every listener is opened, and a failure closes those opened and refuses
to start naming the address (`fylgja serve: listening on <address>: <error>`, exit 2,
listening on none). One `http.Server` serves every listener; a failure to accept on any is
`fylgja serve: serving on <address>: <error>`, exit 2. The report:

```
fylgja serve: listening on 127.0.0.1:7650 (API version 1, build 0.1.0-dev)
fylgja serve: listening on 172.17.0.1:7650 (API version 1, build 0.1.0-dev)
fylgja serve: 172.17.0.1:7650 is not a loopback address: the API's token is sent unencrypted on it
fylgja serve: state root …
```

one listen line per address in the order given, each with the port it got (`:0` names the
port the system chose), and straight after each that is not loopback its unencrypted line.
One token guards every address; a request on either is answered alike, and the log names
no address.

## The Compose override (`scripts/infrahub/docker-compose.override.yml`)

Beside the pin and the cap:

```yaml
  task-worker:
    image: registry.opsmill.io/opsmill/infrahub:1.11.2
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      FYLGJA_API_ADDRESS: host.docker.internal:7650
      FYLGJA_API_TOKEN: ${FYLGJA_API_TOKEN}
```

`host-gateway` is the host's docker0 address (`172.17.0.1` by Docker's default); the task
workers reach the server there (research §1.1). The file holds no value: the token is read
by Compose from `local/.env` through `--env-file`, and the address is a name. Nothing else
of Fylgja's reaches the task workers. `.env.example` says, under `FYLGJA_API_ADDRESS`, that
the task workers get `host.docker.internal:7650` from the override and the token from this
file.

## The bring-up script

- **`infrahub`**: when the override is copied or replaced (`item infrahub override
  installed`), `compose up -d` runs even when every service is running, so the task workers
  are recreated with the entry and the variables.
- **`fylgja`**: the bridge address is read from `docker network inspect bridge -f
  '{{(index .IPAM.Config 0).Gateway}}'` (a host with no `bridge` network fails the item
  naming it); the server is started with `--listen 127.0.0.1:7650 --listen <bridge>:7650`;
  `report_ok` requires both listen lines and the bridge's unencrypted line, and a running
  process is judged by that report only when its standard output (`/proc/<pid>/fd/1`) is
  the log read and, for the server, its arguments hold both `--listen` values, so a server
  running from this tree on loopback alone is restarted, `make serve`'s among them, though
  an earlier server's report in the log names both; the last report's `running:
  server` line names both addresses and says the token crosses the bridge in the clear.
  A second run keeps a server that reports both.

`CLAUDE.md`'s start line becomes:

```
set -a; . local/.env; set +a; setsid nohup env FYLGJA_STATE_ROOT="$PWD/local" bin/fylgja serve --listen 127.0.0.1:7650 --listen "$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'):7650" >> local/server.log 2>&1 < /dev/null &
```

and its verification names both listen lines. `docs/development.md`'s three-process
paragraph says how the bridge address is found and that the task workers reach it.

## `SECURITY.md`

A paragraph "The bridge listener": the server also listens on the host's Docker bridge
address so that Infrahub's task workers, on their Compose network, reach it; any container
on the host can reach that address, the twin's nodes included; the bearer check is what
guards it; the token is in the task workers' environment and in `local/.env`, so whoever can
inspect those containers or read that file holds it; no TLS; one token with no roles, the
revisit [D-042](../../../docs/decisions.md#d-042) names for the check inside Infrahub
consciously deferred ([D-050](../research.md#3-the-decision-entries-drafted)). "On a shared host"'s first bullet
says the port is on loopback and the bridge.

## The host: the reclaim and the refusals

Before a rehearsal starts (research R-04): a run in flight refuses it (`run.in_flight`,
naming `fylgja-rehearse`, `fylgja-provision`, `fylgja-step` or `fylgja-destroy`'s run); a
twin whose record's `rehearsal` names a run that is not running is destroyed first (the
destroy run, followed in the answer; `rehearsal.twin.reclaimed`), by a start that refuses,
never cancels, a rehearsal, provisioning or step run begun since the first look
(`run.in_flight`, naming it); any other lab, twin
directory or orphan refuses it as the host check refuses a create, naming what holds the
host and `twin destroy`. No lock is added and nothing waits inside Fylgja; `fylgja-twin`
retries (contracts/checks.md).

`twin destroy` cancels a rehearsal in flight and waits for its destroy before its own;
`twin create`, `twin provision` and `twin step` are refused beside one. `twin show` names
the run in flight with its child and the stage it is at, and a rehearsal's twin by its run.
