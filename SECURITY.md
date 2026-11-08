# Security

fylgja-core turns a blueprint into a twin of a network. This page says what it protects,
what it leaves to the person running it, and how to report a vulnerability. The core is
being built ([design/core.md](design/core.md)), so this page states the design.
Each point holds from the release that implements it.

## The threat model

**Every request carries a principal** ([D-025](design/decisions.md#d-025)).
- Clients authenticate with per-client bearer tokens.
- A missing or unknown token is `401`, and a refused action is `403`.
- Several tokens can be valid at once, for rotation.
- An audit log names the principal behind every change to a twin.
- The server ends TLS itself when given a certificate and its key (`FYLGJA_TLS_CERT`,
  `FYLGJA_TLS_KEY`), and serves HTTP without them, which is for loopback
  ([D-063](design/decisions.md#d-063)).

**One credential provider.**
- Node logins and tokens come from the environment locally, and from Secrets on a cluster.
- On a cluster the core's service account acts on Secrets and pods in every namespace
  ([D-062](design/decisions.md#d-062)), so the namespace `fylgja` holds the core and its store
  alone.
- `local/.env`, at mode `0600`, is the only file that holds a value locally.
- **No credential reaches any output:** not a blueprint, bundle, deployment, twin record,
  finding, API answer or log line (Constitution X).

**Twins are isolated by their driver** ([D-019](design/decisions.md#d-019)).
- **On clabernetes,** each twin has its own namespace, and a NetworkPolicy admits no other
  twin's pods.
- **On the local containerlab driver,** each twin has its own lab and management network,
  but the host routes between twins' management networks. Local twins are for development,
  where every twin is its operator's own.

### On a shared host

- **A twin's nodes use their images' published default logins,** on a management network
  the host can reach. Treat a local twin as open to everyone on the host.
- **Anyone who can read `local/.env`,** or the environment of the processes that loaded it,
  has every credential.

## Reporting a vulnerability

Report it privately, through GitHub's private vulnerability reporting: the repository's
**Security** tab, then **Report a vulnerability**. Do not open a public issue. Say what you
found, how to reproduce it, and the commit it applies to.

**In scope**: the core under `core/`, the scripts under `scripts/`, and the workflows under
`.github/workflows/`.

**Not in scope**:
- **The network operating system images and their default logins,** which a twin uses on
  purpose.
- **containerlab, clabernetes and Kubernetes themselves.** Report those to their projects.
- **The local driver's shared management reach,** stated above as the design.

A way around a credential, or a credential that reaches any output, is in scope.
