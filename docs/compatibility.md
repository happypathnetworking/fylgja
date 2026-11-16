# What 1.0 holds

This page says what a program, a document or a script of yours may rely on across the releases of
major version 1, and what it may not. The other pages say how each thing works; this one says which
of them are held.

## The version

The three published distributions, `fylgja-core`, `fylgja-infrahub` and `fylgja-netbox`, share one
version and follow semantic versioning from 1.0.0. A release is never one distribution alone. Each
reader requires the core at the reader's own version or a later one below 2, so it works with the
core of its own major version.

## What is held

Within major version 1, each of these is held.

### The API and the formats

[API 1](api.md), as [`api-1.openapi.yaml`](../formats/api-1.openapi.yaml) states it, and each format
at version 1 that you write or that the core answers with:

| Format | What it is |
|---|---|
| [blueprint](../formats/blueprint-1.schema.json) | The network's intent, which you write |
| [platform package](../formats/platform-package-1.schema.json) | How a platform is run, which a site may write |
| [probe package](../formats/probe-package-1.schema.json) | How a probe's hosts are run, which a site may write |
| [probe declaration](../formats/probes-1.schema.json) | A blueprint's probes |
| [Infrahub reader document](../formats/infrahub-reader-1.schema.json) | How `fylgja-infrahub` reads Infrahub, which you write |
| [NetBox reader document](../formats/netbox-reader-1.schema.json) | How `fylgja-netbox` reads NetBox, which you write |
| [findings](../formats/findings-1.schema.json) | A verdict, which the core answers |
| [problem](../formats/problem-1.schema.json) | A refusal, which the core answers |
| [twin record](../formats/twin-record-1.schema.json) | A twin, which the core answers |
| [bundle](../formats/bundle-1.schema.json) | A compiled blueprint, which the core answers |
| [deployment](../formats/deployment-1.schema.json) | What was run, which the core answers |

### The commands

Each command is held with its options and its exit statuses.

| Command | Its options and exit statuses |
|---|---|
| `fylgja-core` | [The command page](cli.md#commands), [its exit statuses](cli.md#exit-statuses) |
| `fylgja-core-server` | [The server page](server.md#options), [its exit statuses](server.md#exit-statuses) |
| `fylgja-infrahub` | [The Infrahub reader](../readers/infrahub/README.md#the-command) |
| `fylgja-netbox` | [The NetBox reader](../readers/netbox/README.md#the-command) |

### The settings

The names of the variables those commands read are held: [the server's](server.md#settings),
[the client's](cli.md#before-a-command) and each reader's, which its README gives. A credential's
name is held by its pattern: `FYLGJA_CREDENTIAL_<NAME>_USERNAME`,
`FYLGJA_CREDENTIAL_<NAME>_PASSWORD` and `FYLGJA_CREDENTIAL_<NAME>_REGISTRY`, for each `<NAME>` a
platform package gives.

### The Python names

The names that [the client library](client.md) gives, and those under "The library" in
[the Infrahub reader's README](../readers/infrahub/README.md#the-library) and in
[the NetBox reader's](../readers/netbox/README.md#the-library). A module or a name no page gives is
not held, and the names of the example's code that [Integrating](integrating.md) gives are the
example's, which is not held.

## What held means

- A document or a request that is valid under one release of major version 1 is valid under every
  later one, and means the same.
- What the core answers may gain a member, a route, a rule id or a finding in a minor release, and
  loses none.
- A blueprint's id, which the blueprint format defines as a hash of its network and probes, is held
  with the format: one blueprint document has the same id under every later release of major
  version 1. A bundle's and a deployment's ids are not held (see below).
- A refusal that is lifted is no loss. `package.versions.several`, which refuses a platform package
  that lists more than one version, is one that is expected to be lifted.

## Reading an answer

The client library, `fylgja-core` and the example read an answer as the release they come with
holds it: they read the members they use, refuse an answer that lacks one, and pass over a member
they do not know. What you write, a blueprint or a package, is held to its schema whole, and a
member the schema does not name is refused.

Only a member, a route, a rule id or a finding may be added within major version 1. Adding a value
to an enumeration that an answer closes waits for a major release: a 1.0 client refuses an answer
whose `status`, `operation`, `severity`, `wait.outcome`, `loss.outcome` or `loss.from` holds a value
it does not know.

If you check an answer against a schema of your own making, use the schema of the release that
answers: a later release may add a member that an earlier release's schema lacks.

## A format's next version

A format's version 2 comes only with a major release, and replaces version 1.

## Not promised

- The example orchestrator, `fylgja-orchestrator`, and its two documents, which the example writes
  and reads: [`plan-1.schema.json`](../formats/plan-1.schema.json) and
  [`rehearsal-1.schema.json`](../formats/rehearsal-1.schema.json). [Integrating](integrating.md)
  describes it as a model to copy.
- The make targets, the scripts, the demonstrations and `deploy/`.
- The wording of a message. Read a refusal by its rule id.
- A bundle's or a deployment's id from one release to the next: a package's content moves it.
- A module or a name that no page gives.
- Flows across a step: a step lists each probe's flow as not started and measures no loss. The
  probe package declares the flow so that a later release can run it.
- A store with twins in it, read by a later release. Destroy your twins before you upgrade: a
  release need not read a store that holds twins an earlier release made. List them with
  `fylgja-core twin list`, destroy each with `fylgja-core twin destroy <name>`, upgrade, start the
  server, and apply them again from their blueprints.
