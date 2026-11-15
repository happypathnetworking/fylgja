# Installing Fylgja

Fylgja is installed as up to four packages, which share one version. Each is a Python distribution,
published to PyPI as a wheel from version 1.0.0 on.

| Distribution | What it gives |
|---|---|
| `fylgja-core` | The model of a blueprint, a twin and a bundle, the client library and the `fylgja-core` command. |
| `fylgja-core[server]` | The same, with the libraries the server needs, and the `fylgja-core-server` command. |
| `fylgja-infrahub` | The Infrahub reader, which reads an Infrahub into blueprints, and its `fylgja-infrahub` command. |
| `fylgja-netbox` | The NetBox reader, which reads a NetBox into blueprints, and its `fylgja-netbox` command. |

Install `fylgja-core` where you only call a server or read a blueprint. Install the extra `server`
where the server runs. Install a reader beside the core where you read that source of truth. A
reader requires `fylgja-core>=1.0.0rc1,<2`, so installing it brings the core in.

The example orchestrator, which rehearses a change of a source of truth on a twin, is not
published. It is installed from a clone of the repository and is described in
[integrating Fylgja](integrating.md).

## What it needs

Python 3.14 on Linux. The packages are pure Python; the server's libraries have wheels for Linux.
Make an environment of your own for the install, so that it touches no other.

```sh
python3.14 -m venv fylgja-env
fylgja-env/bin/pip install fylgja-core
fylgja-env/bin/pip install "fylgja-core[server]"
fylgja-env/bin/pip install fylgja-infrahub fylgja-netbox
```

Or with uv:

```sh
uv venv --python 3.14 fylgja-env
uv pip install --python fylgja-env/bin/python fylgja-core
uv pip install --python fylgja-env/bin/python "fylgja-core[server]"
uv pip install --python fylgja-env/bin/python fylgja-infrahub fylgja-netbox
```

The commands are then in `fylgja-env/bin/`.

## From a clone

Where a version is not on PyPI yet, or you want the tree as it is, build the wheels from a clone.
You need Python 3.14, git, GNU make, uv 0.12.23 and the network: the build fetches its tools. Another
uv is refused. `make wheels` builds the three published wheels into `dist/`, at the version in the
file `VERSION`. The shell finds each wheel by its name, since neither uv nor pip expands a pattern.

```sh
make wheels
core=$(ls dist/fylgja_core-*.whl)
infrahub=$(ls dist/fylgja_infrahub-*.whl)
netbox=$(ls dist/fylgja_netbox-*.whl)
uv venv --python 3.14 fylgja-env
uv pip install --python fylgja-env/bin/python "$core"
uv pip install --python fylgja-env/bin/python "$core[server]"
uv pip install --python fylgja-env/bin/python "$core" "$infrahub" "$netbox"
```

Install a reader's wheel in the same command as the core's, as in the last line, so that the core it
requires is found beside it and not on an index.

## Checking it

`--version` prints the command's name, the version and the commit the build was made at, and
exits 0. `fylgja-core-server`, `fylgja-infrahub` and `fylgja-netbox` answer it the same way.

```console
$ fylgja-core --version
fylgja-core <version> (commit <commit>)
```

A tree that was not built from a commit prints `unknown` for it. A server answers the same text
for itself in the `build` of `GET /v1/version`, which [the API page](api.md) describes.

## What the server's host needs

The client and the readers need nothing of the host but Python. The server's driver for one host,
`containerlab`, runs the twin's nodes as containers, and needs these of the host:

- containerlab 0.81.0 and Docker 29.8.1, the versions the server is tested on.
- The user that runs the server in the groups `docker` and `clab_admins`, in a login begun after
  the user was added to them. A group added reaches no process that began before it.
- The images of the nodes. The SR Linux image is public and Docker pulls it. The cEOS image is
  not: download it from an Arista account and import it with `docker import`, under the name the
  platform's package gives.
- On Ubuntu, two lines added to AppArmor's local profile for rsyslogd, which SR Linux's logging
  needs: `/opt/srlinux/** mr,` and `/run/srlinux/** rw,` in
  `/etc/apparmor.d/local/usr.sbin.rsyslogd`, then `apparmor_parser -r
  /etc/apparmor.d/usr.sbin.rsyslogd`.

The cluster driver, `clabernetes`, needs a cluster instead and nothing of the host. The next page,
[running the server](server.md), sets the server up and starts it.
