# Changelog

What each release changed for a user, newest first, and its known limits ([D-106](design/decisions.md#d-106)). A
release's section is headed `## <version> - <date>`, `unreleased` standing in the date until the commit that is tagged
dates it.

## 1.0.1 - unreleased

A fix to the core's server. The four distributions are released at 1.0.1 together, and each reader
requires the core at 1.0.1 or a later version below 2.

- **A SIGTERM while `fylgja-core-server` starts now ends it.** Python can run a signal handler where
  an exception it raises is printed and dropped, inside the callback of an import's lock among
  them. 1.0.0's handler raised one, so a SIGTERM handled there was lost and the server went on to
  serve: once in 284 starts under load. In a container the server is PID 1, and it ran until it was
  killed. The server now exits 143 at a SIGTERM wherever its start has reached.
- **The Nautobot reader, `fylgja-nautobot`, is published.** It reads free Nautobot as it stands,
  under a tag, into a blueprint whose every configuration is Golden Config's render at the read, or
  the findings that refused it. Its command, its document, its settings and its library are held as
  [the compatibility page](docs/compatibility.md) says.

For a checkout, `make demo-dependencies` gives a host what [the demonstrations](docs/demonstrations.md)
need where it is missing, and says what is left to do by hand.

### Known limits

What is unread or unmended, and so not promised, in what you can run from the published
distributions. Each line that ends ([more]) is one question of
[Open questions](design/decisions.md#open-questions) there, where its readings are.

- A drain of a cluster host is unread at the packages' requests of 0.5 CPU and 1.5 to 2 GiB. The
  spread of five twins over three hosts was read at them. ([more][oq])
- The connections the core opens to the nodes are unbounded and were read only for three twins of
  three nodes. What larger twins, or five twins at once on the cluster, open is unread. ([more][oq])
- A twin's `Ready` condition does not carry verify's status. A step or a restore whose wait expired
  ends `ok` with `Ready` true, and only its verdict says that verify did not hold. ([more][oq])
- A core that holds the Lease may go on past its deadline when the store is slow: two store calls
  back to back, each bounded by 10 s, held one on the cluster until 21.08 s after its last renewal,
  6.08 s past its 15 s deadline, where a waiting core takes the Lease from about 15.5 s.
  ([more][oq])
- A core that releases the Lease and meets a conflict gives up after a warning, and the next holder
  takes the Lease once its duration has passed. ([more][oq])
- A cEOS node with no data link refuses `ip routing`, so the push of a configuration that carries it
  is refused. ([more][oq])
- A read of Infrahub cost more as one development instance's history grew: the reader's contract run
  took 396 s, then 1,783 s. The cause is not established, so what a read costs on an old instance is
  unknown. ([more][oq])
- The reader's stale rule, which refuses a configuration older than its intent, has cases unread: an
  artifact that reads `Error`, a device's platform changed, an address moved to another port, a
  rebase of a branch. Nor was it read which role of Infrahub's grants a reader needs. ([more][oq])
- NetBox may commit a row of its changelog below one already committed: not read. The NetBox
  reader's bracket counts rows to catch one, and a changelog that prunes rows could hide it.
  ([more][oq])
- A `view` grant of NetBox that carries constraints may shorten a list and its count alike, so a
  read could pass on less than NetBox holds, and nothing in the read can tell. Give the reader's
  account a grant with none. ([more][oq])
- The Nautobot reader was read against one Nautobot web instance and one writer at a time. Several
  web instances, each with its own clone of a template repository, two writers at once, a changelog
  that prunes rows, a template repository behind credentials, and the stored members of a
  dynamic-set or a static group, which the reader warns of as unchecked, are unread. ([more][oq])
- No rule of verify reads an address. A step that gives a port an address is shown pushed, not shown
  in force. ([more][oq])
- A mark made through one core and planned through another is unread: the source reads a mark's
  blueprint from the core it runs through, by its id, so that core must have been given the same
  intent. ([more][oq])
- On the clabernetes driver, a node the dry run answers `recabled` may be replaced, though the spec
  does not allow a restart, if a step since the node was last made added or removed a node. A node
  added or removed can move another node's management address, and clabernetes then makes that
  node's pod anew at the next step that changes its links. By a simulation of how clabernetes draws
  the addresses, a step that adds a probe's two hosts moves a device's address about 1.3 times in a
  hundred. ([more][oq])
- A step runs no flow and measures no loss: each probe of a step's target is reported `not_started`
  in its verdict, as [the findings format](formats/findings-1.schema.json) says.
- A core remembers in memory alone that an apply of a twin on the cluster was cancelled, so that its
  destroy waits for the cluster's API to settle. A core that restarts forgets it, and its next
  destroy of that twin does not wait, so a namespace the cancelled request goes on to make may be
  left standing. A create cut by a transport failure, a timeout or a connection lost after the
  send, is not marked, though the API may likewise still make it. The local driver's mark is lost
  the same way: it marks a twin whose `containerlab deploy` was cancelled or ran out of its
  budget, so that the destroy that follows lists the lab's containers again until none has appeared
  for 5 s, but a core that restarts forgets the mark, and its next destroy of that twin does not.
- A Ctrl-C while the server starts can be lost the same way a SIGTERM was in 1.0.0, and the server
  then goes on to serve; a second Ctrl-C stops it. A SIGINT sets nothing the start reads again, as a
  SIGTERM now does.

The example's, the test suites' and the development tooling's open questions are in
[Open questions](design/decisions.md#open-questions) and are not promised: the many-twins
scenario's forty-node twin, the cluster's rehearsal time, the task worker's clone, a registration
read from GitHub, Prefect's credential in NetBox's changelog, authoring a change of several steps in
NetBox, three small gaps, `make netbox-up`'s network, a rehearsal's time on an Infrahub kept for
days, what the first release left unread, and a permission's groups the seed leaves. The
development database's health check on such an Infrahub is answered: it allows 180 s.

[oq]: design/decisions.md#open-questions

## 1.0.0 - 2026-11-18

The first release. The three distributions, `fylgja-core`, `fylgja-infrahub` and `fylgja-netbox`, are published
as wheels at one version, each built from this repository alone: a release on PyPI, a candidate on TestPyPI.

What 1.0 holds, and what it does not, is stated on [one page](docs/compatibility.md): the API
and the formats at version 1, the four commands with their options and exit statuses, and the names
of the variables they read are held within major version 1, and the example orchestrator, the make
targets and the scripts are not.

Not published: an image, a source distribution and the example orchestrator.

Two candidates came before it, `1.0.0rc1` and `1.0.0rc2`, and both stay on TestPyPI. The acceptance
of `1.0.0rc1` found that the Infrahub reader failed at once when Infrahub sheds load. Infrahub 1.11
answers a request it sheds with an HTTP 429 that it marks as a shed, before the request does
anything. The reader now sends such a request again after the `Retry-After` it gives, up to 300 s for
one request, and past that the read is an `InfrahubError`. That wait was not seen against a live
shed: the acceptance of `1.0.0rc2` met none.

### Upgrading from a checkout before 1.0

- A platform package of your own is rewritten to the shape the format now has. Its `versions` is a
  list of objects each with a `name`, and each runtime section names its image for each version
  in `images`, keyed by that name, where it named one `image`. A package that lists more than one
  version is refused: this build runs one a package.
- A text that ends in a newline is refused wherever a pattern of a format ends in `$`, in a
  document and in a request body alike. A device name written as a folded YAML scalar is one: it
  ended in a newline that a checkout before 1.0 let through.
- `FYLGJA_PACKAGES` may be left unset. It then names the packages the install carries, and set it
  still names exactly the directories it lists.
- Destroy your twins before you upgrade. A release need not read a store that holds twins an
  earlier release made: list them with `fylgja-core twin list`, destroy each with
  `fylgja-core twin destroy <name>`, upgrade, start the server, and apply them again from their
  blueprints.

### Known limits

What is unread or unmended, and so not promised, in what you can run from the published
distributions. Each line that ends ([more]) is one question of
[Open questions](design/decisions.md#open-questions) there, where its readings are.

- A drain of a cluster host is unread at the packages' requests of 0.5 CPU and 1.5 to 2 GiB. The
  spread of five twins over three hosts was read at them. ([more][oq])
- The connections the core opens to the nodes are unbounded and were read only for three twins of
  three nodes. What larger twins, or five twins at once on the cluster, open is unread. ([more][oq])
- A twin's `Ready` condition does not carry verify's status. A step or a restore whose wait expired
  ends `ok` with `Ready` true, and only its verdict says that verify did not hold. ([more][oq])
- A core that holds the Lease may go on past its deadline when the store is slow: two store calls
  back to back, each bounded by 10 s, held one on the cluster until 21.08 s after its last renewal,
  6.08 s past its 15 s deadline, where a waiting core takes the Lease from about 15.5 s.
  ([more][oq])
- A core that releases the Lease and meets a conflict gives up after a warning, and the next holder
  takes the Lease once its duration has passed. ([more][oq])
- A cEOS node with no data link refuses `ip routing`, so the push of a configuration that carries it
  is refused. ([more][oq])
- A read of Infrahub cost more as one development instance's history grew: the reader's contract run
  took 396 s, then 1,783 s. The cause is not established, so what a read costs on an old instance is
  unknown. ([more][oq])
- The reader's stale rule, which refuses a configuration older than its intent, has cases unread: an
  artifact that reads `Error`, a device's platform changed, an address moved to another port, a
  rebase of a branch. Nor was it read which role of Infrahub's grants a reader needs. ([more][oq])
- NetBox may commit a row of its changelog below one already committed: not read. The NetBox
  reader's bracket counts rows to catch one, and a changelog that prunes rows could hide it.
  ([more][oq])
- A `view` grant of NetBox that carries constraints may shorten a list and its count alike, so a
  read could pass on less than NetBox holds, and nothing in the read can tell. Give the reader's
  account a grant with none. ([more][oq])
- No rule of verify reads an address. A step that gives a port an address is shown pushed, not shown
  in force. ([more][oq])
- A mark made through one core and planned through another is unread: the source reads a mark's
  blueprint from the core it runs through, by its id, so that core must have been given the same
  intent. ([more][oq])
- On the clabernetes driver, a node the dry run answers `recabled` may be replaced, though the spec
  does not allow a restart, if a step since the node was last made added or removed a node. A node
  added or removed can move another node's management address, and clabernetes then makes that
  node's pod anew at the next step that changes its links. By a simulation of how clabernetes draws
  the addresses, a step that adds a probe's two hosts moves a device's address about 1.3 times in a
  hundred. ([more][oq])
- A step runs no flow and measures no loss: each probe of a step's target is reported `not_started`
  in its verdict, as [the findings format](formats/findings-1.schema.json) says.
- A core remembers in memory alone that an apply of a twin on the cluster was cancelled, so that its
  destroy waits for the cluster's API to settle. A core that restarts forgets it, and its next
  destroy of that twin does not wait, so a namespace the cancelled request goes on to make may be
  left standing. A create cut by a transport failure, a timeout or a connection lost after the
  send, is not marked, though the API may likewise still make it. The local driver's mark is lost
  the same way: it marks a twin whose `containerlab deploy` was cancelled or ran out of its
  budget, so that the destroy that follows lists the lab's containers again until none has appeared
  for 5 s, but a core that restarts forgets the mark, and its next destroy of that twin does not.

The example's, the test suites' and the development tooling's open questions are in
[Open questions](design/decisions.md#open-questions) and are not promised: the many-twins
scenario's forty-node twin, the cluster's rehearsal time, the task worker's clone, a registration
read from GitHub, Prefect's credential in NetBox's changelog, authoring a change of several steps in
NetBox, three small gaps, `make netbox-up`'s network, a rehearsal's time on an Infrahub kept for
days, and what the first release left unread. The development database's health check on such an
Infrahub is answered: it allows 180 s.

[oq]: design/decisions.md#open-questions
