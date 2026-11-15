# Running the server

`fylgja-core-server` is the core as one process. It serves API 1 over HTTP and runs the loop that
brings each twin to its blueprint. It keeps every twin, blueprint and bundle in one store, and it
holds that store for itself alone: a second server started over the same store is refused. It is
installed with the extra `fylgja-core[server]`; the package alone carries the model and the client
library, and `fylgja-core-server` then ends with a line that names the library it lacks.

A client is `fylgja-core`, described in [the command page](cli.md), or a program that speaks API 1.
`-h` and `--help` print a short summary of the command and exit.

```sh
fylgja-core-server
```

## What it needs

The server is given everything it runs with as `FYLGJA_*` environment variables, never as a file it
reads for itself. It needs four things.

- A store: a directory, which the server creates on its first start, or an object store.
- A token file, which lists the clients that may call it.
- Packages of platforms and probes. Where `FYLGJA_PACKAGES` is unset or empty it loads the ones the
  install carries.
- A driver, which runs the twins: `containerlab` on this host, or `clabernetes` on a cluster. The
  server does not install the driver's runtime. The local driver needs containerlab and Docker on
  the host; the cluster driver needs a cluster with clabernetes.

Two variables are required, `FYLGJA_STORE` and `FYLGJA_TOKENS`. A start with the two set serves
`127.0.0.1:7650`, with the local driver, over HTTP.

```sh
export FYLGJA_STORE=/var/lib/fylgja FYLGJA_TOKENS=/etc/fylgja/tokens
fylgja-core-server
```

## Settings

Each variable is read once, at start. A variable that is missing, empty where a value is needed, or
malformed ends the start with one line that names the variable and never its value. The server also
refuses a combination that one setting rules out of another: an object store without a Lease, or
with a driver that keeps files in the store's directory, and one of the TLS pair without the other.

| Variable | Default | Holds |
|---|---|---|
| `FYLGJA_STORE` | required | The store: a directory, which the server holds locked while it runs, or `s3://<bucket>[/<prefix>]`, an object store. A directory also holds the local driver's working files. An object store needs `FYLGJA_LEASE` and the `clabernetes` driver. |
| `FYLGJA_TOKENS` | required | The token file, described [below](#the-token-file). |
| `FYLGJA_PACKAGES` | the packages the install carries | Colon-separated directories of platform and probe packages. The server loads every one of them and no other, so a site that wants its own beside the shipped ones lists the shipped ones as well; [the packages](#the-packages) shows how. |
| `FYLGJA_LISTEN` | `127.0.0.1:7650` | The address the server serves on, as `host:port` with a port from 1 to 65535. |
| `FYLGJA_DRIVER` | `containerlab` | The driver the twins run on: `containerlab` or `clabernetes`. |
| `FYLGJA_WORKERS` | `8` | How many twins the loop works on at once, an integer of 1 or more. Each twin being created or stepped holds one worker until its apply ends. |
| `FYLGJA_STEP_WAIT_S` | `180` | Seconds a step waits for the twin to verify before it ends anyway, an integer of 1 or more. |
| `FYLGJA_RESYNC_S` | `300` | Seconds between the loop's resyncs, an integer of 1 or more. A resync queues every twin again, so an event the loop missed is only late. |
| `FYLGJA_LAB_POOL` | `172.20.0.0/16` | The pool the local driver takes each lab's management subnet from: an IPv4 network in CIDR form, with no host bit set, that holds at least one /24. A create that finds no /24 of it free is refused. A twin already made keeps its subnet when the value changes. The server checks the value whichever the driver is. |
| `FYLGJA_CLABERNETES_NAMESPACE` | none; required by `clabernetes` | The namespace clabernetes runs in, a DNS label. |
| `FYLGJA_POD_CIDR` | none; required by `clabernetes` | The cluster's pod network as an IPv4 network in CIDR form, such as `198.51.100.0/24`. Each twin's network policy admits any source outside this network. |
| `FYLGJA_LEASE` | none; required with `s3://` | The name of the Kubernetes Lease that holds the store for one core, in the namespace the server runs in. The server takes it before it opens the store. A server that finds the Lease held waits and says once whom it waits for. A server that loses it stops at once, with status 1. |
| `FYLGJA_S3_ENDPOINT` | required with `s3://` | The object store's endpoint, an `http://` or `https://` URL of a host and an optional port. |
| `FYLGJA_S3_ACCESS_KEY` | required with `s3://` | The endpoint's access key. |
| `FYLGJA_S3_SECRET_KEY` | required with `s3://` | The endpoint's secret key. |
| `FYLGJA_S3_REGION` | `us-east-1` | The region the object store's requests are signed for. |
| `FYLGJA_S3_CA` | the system's trust | A file of CA certificates that an `https://` endpoint is verified against. |
| `FYLGJA_TLS_CERT` | none | The certificate the server ends TLS with. It is set with `FYLGJA_TLS_KEY`; see [TLS](#tls). |
| `FYLGJA_TLS_KEY` | none | The certificate's key, unencrypted. |
| `FYLGJA_CREDENTIAL_<NAME>_USERNAME` | none | The login a platform package's nodes accept, for the package whose `credentials` value is `<NAME>` in upper case, with dashes written as underscores. A twin that needs a login which is not set fails with `credential.missing`. |
| `FYLGJA_CREDENTIAL_<NAME>_PASSWORD` | none | The password of that login. |
| `FYLGJA_CREDENTIAL_<NAME>_REGISTRY` | none | With the clabernetes driver, the image prefix a gated image is pulled under. Its login is the two variables above, under the same `<NAME>`. |

On the clabernetes driver, and for the Lease, the server reaches the cluster with the service
account when it runs in a pod and with the kubeconfig that `KUBECONFIG` names when it runs off the
cluster. The commands the local driver runs, `containerlab` and `docker`, receive `DOCKER_HOST` and
`PATH` from the server's environment and nothing else.

## The token file

The token file lists the clients that may call the server. It holds one line for each client, the
SHA-256 hash of the client's token in lower-case hex, a space and the client's principal, a name
that the server logs for every write. Blank lines and lines that begin with `#` are skipped. The
file never holds a token, and several lines are valid at once. The server reads the file at start,
so a line added later is read at the next start. A line that does not have a hash and a principal,
a hash that is not 64 characters of lower-case hex and the same hash twice are each refused, and
the refusal names the line and never its content.

This makes a token for a client named `alice`, adds its line to the file and leaves the token in
`client.env`, readable by its owner alone. It prints nothing.

```sh
token=$(head -c 24 /dev/urandom | base64)
printf '%s %s\n' "$(printf %s "$token" | sha256sum | cut -d' ' -f1)" alice >> "$FYLGJA_TOKENS"
(umask 077; printf 'FYLGJA_API_TOKEN=%s\n' "$token" > client.env)
unset token
```

The client sets `FYLGJA_API_TOKEN` to the value in `client.env`, as [the command page](cli.md)
says. A request without a bearer token, or with one the file does not list, is refused with status
401. Only the call that asks which API version the server speaks needs no token.

## The packages

The packages say which platforms a twin can run and which probes it can carry. An install carries a
set of them: a wheel's are beside the Python package, and a checkout's are the `psp/` and `probes/`
directories of the tree. `FYLGJA_PACKAGES` unset or empty means those. Set, it means exactly the
directories it names. A site that keeps its own packages beside the shipped ones lists both:

```sh
export FYLGJA_PACKAGES="$(python3 -c 'from fylgja_core import packages; print(*packages.shipped(), sep=":")'):/srv/site/psp"
```

The program prints the two directories the install carries, joined by a colon. A package the
server refuses ends the start with status 2.

## Starting and stopping

Set the variables in the environment, then run `fylgja-core-server`. The server writes one JSON
object a line on standard error: the principal is on every write, and a token or a password is
never on any line. A start that is refused is one line that names the variable or the file at
fault. A start that has to wait for a Lease says so once and binds no socket.

SIGTERM and Ctrl-C stop the server in the same way: open watches are told to end, the loop stops,
the store is closed and the Lease is released. They stop it during the start too, and whatever the
start had opened is closed again. A second Ctrl-C gives the loop two seconds to stop. The server
handles SIGTERM itself, so it stops as PID 1 in a container. A create that a stop cut short resumes
at the next start. The exit statuses are [below](#exit-statuses).

## TLS

Without `FYLGJA_TLS_CERT` and `FYLGJA_TLS_KEY` the server serves HTTP, which is for loopback: a
client's token crosses the network in clear. A server that listens on an address off loopback
without TLS logs one warning at start. Set the two together to serve TLS. The key must not be
encrypted, since the server never asks for a passphrase. A pair that does not load, or an encrypted
key, ends the start with status 2.

A client verifies the certificate strictly. The certificate names the server's address as an IP
subject alternative name, and the certificate of the CA that signed it carries a key usage that
allows signing certificates. A client given that CA's file in `FYLGJA_API_CA` then trusts the
server.

## On a cluster

On a cluster the server is one pod under a Lease, from an image built in the tree, and it serves
the `clabernetes` driver alone. [deploy/README.md](../deploy/README.md) holds the manifests, the
secrets each pod reads and the steps that deploy it.

## Options

The command has two options besides the settings.

| Option | Prints |
|---|---|
| `--version` | The command's name, its version and the commit it was built at, and exits. |

## Exit statuses

| Status | Means |
|---|---|
| 0 | The server stopped cleanly. The Lease, where one was held, was released first. |
| 1 | The store is held by another core. The object store could not be opened, because its endpoint is unreachable or refuses the server. The Lease was lost. The application did not start; the lines above the last say why. |
| 2 | A misconfiguration. A variable is not set, is empty or is malformed, or is set to what another rules out; a certificate or key does not load, or the key is encrypted; a Lease cannot be taken for want of a cluster or of the service account's rights; a CA file does not load; the object store's endpoint fails the server's proof that it writes conditionally; Python runs optimised, with `-O` or `PYTHONOPTIMIZE`; a package is refused; the token file cannot be read; a driver cannot be made, or the cluster cannot be reached; the address cannot be listened on; or the server's libraries are not installed. |
| 130 | The server was stopped by Ctrl-C, with no traceback. The store was closed and the Lease released first, where one was held. |
| 143 | The server was stopped by SIGTERM, with what 130 says. |

Waiting for a Lease that another core holds is no exit. A start that is stopped at that wait ends
with 130 or 143, and no Lease is released, since none was taken.
