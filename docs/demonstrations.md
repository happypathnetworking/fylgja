# The demonstrations

A demonstration rehearses a change of a source of truth on a twin, from nothing running: it
starts the source, seeds it with a network, starts the core and the example orchestrator, makes
a change in the source, waits for the twin to rehearse it and says the verdict and where the
report is read. There is one for Infrahub and one for NetBox.

The demonstrations are not in this repository. They moved with the example orchestrator to
[`fylgja-examples`](https://github.com/happypathnetworking/fylgja-examples/tree/v1.1.0/), which
runs them against the released packages of this one. Its page, [the
demonstrations](https://github.com/happypathnetworking/fylgja-examples/blob/v1.1.0/docs/demonstrations.md),
says what the host must have, how to run one, how long it takes, what it writes, its exit
statuses and how to end it. That page and everything under it is at the tag `v1.1.0`, the one
made with the release this page ships with.

What the example does, and what you would write in its place, is in
[integrating Fylgja](integrating.md). The demonstrations are a development tool: what they do is
not promised the way the commands in [the command line](cli.md) are.
