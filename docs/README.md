# Fylgja's documentation

These pages are for someone who installs and uses Fylgja. They are held to the code: each command,
option, setting, exit status, route and call a page lists is the code's own. Read them in this
order.

1. [Installing](installing.md): the packages, how to install them, and what the server's host needs.
2. [Running the server](server.md): the settings, the token file, the packages, starting and
   stopping, and the server's exit statuses.
3. [The `fylgja-core` command](cli.md): every command, with examples of what each prints.
4. [API 1](api.md): the server's HTTP API, by task, for a program of your own.
5. [The client library](client.md): the Python calls of API 1, for a script of your own.
6. [What 1.0 holds](compatibility.md): what stays the same across the releases of major version 1,
   and what does not.
7. [The demonstrations](demonstrations.md): a change of Infrahub or of NetBox rehearsed on a twin,
   from nothing running.

Beside them:

- [The Infrahub reader](../readers/infrahub/README.md) and
  [the NetBox reader](../readers/netbox/README.md) read a source of truth into blueprints. Each has
  a command and a library.
- [Rules](rules.md) lists every finding and refusal the core files, by its rule id.
- [The glossary](glossary.md) defines the terms these pages use.
- [Integrating Fylgja](integrating.md) walks through the example orchestrator, to join Fylgja to a
  source of truth and a platform of your own. The example is a model to copy. It is not part of
  what version 1.0 promises, and its commands may change.
- [The formats](../formats/README.md) say what a blueprint and a package are written in, for
  anything that writes one, and [the shipped platform packages](../psp/README.md) say what each
  platform's package holds, for a site that writes its own.
