# Fylgja

[![ci](https://github.com/happypathnetworking/fylgja/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/happypathnetworking/fylgja/actions/workflows/ci.yml)

A blueprint is a network's intent: every device, link and configuration, as its source of truth
renders it, addressed by its contents, with optionally probes, small hosts that ping each other
through the twin. A twin is that network running on real network operating system images, where a
change is rehearsed before it reaches production: Fylgja compiles the blueprint to a bundle, runs
the bundle and pushes each configuration, then steps the twin from one blueprint to another.
Verify judges the running twin against its bundle, and sends each probe's burst of pings through the
twin as one of its checks; a step lists each probe's flow, which is not yet run.
Vendors are data, not code: Nokia SR Linux and Arista EOS, alone or mixed in one twin. Anything
that writes a blueprint can drive Fylgja, through its API or its command.

## Installing

```sh
python3.14 -m venv fylgja-env
fylgja-env/bin/pip install "fylgja-core[server]"
fylgja-env/bin/pip install fylgja-infrahub fylgja-netbox
```

The packages, the other ways to install them and what the server's host needs are in
[installing](docs/installing.md). The commands are in `fylgja-env/bin/`: the commands below need the
environment activated, or `fylgja-env/bin/` in front of each.

## A first twin

Start the server, as [running the server](docs/server.md) describes, with the login of the nodes
set as it says there. From a clone of the repository, with the address and token of a client set
as [the command page](docs/cli.md) says, create a twin of the example blueprint, look at it and
destroy it:

```sh
fylgja-core twin create demo --blueprint testdata/blueprint/three-node.json
fylgja-core twin show demo
fylgja-core twin destroy demo
```

The first command boots three nodes, pushes each its configuration and waits until the twin is
Ready.

## A demonstration

From a clone, one command starts a source of truth, seeds it with a network, makes a change in it
and rehearses the change on a twin:

```sh
make netbox-demo
```

[The demonstrations](docs/demonstrations.md) say what the host needs and what each one writes.

## Read on

- [What 1.0 holds](docs/compatibility.md) says what stays the same across the releases of major
  version 1, and what does not.
- [The documentation](docs/README.md) lists every page: the server, the command, API 1 and the
  client library.
- [The Infrahub reader](readers/infrahub/README.md) and
  [the NetBox reader](readers/netbox/README.md) read a source of truth into blueprints.
- [Integrating Fylgja](docs/integrating.md) joins Fylgja to a source of truth and a platform of
  your own, walked through the example orchestrator.

## For contributors

[CONTRIBUTING.md](CONTRIBUTING.md) says how to set up, build, test and change the repository. The
design is in [design/architecture.md](design/architecture.md), and the reasons for it are in
[design/decisions.md](design/decisions.md).

## Licence

[Apache License 2.0](LICENSE).
