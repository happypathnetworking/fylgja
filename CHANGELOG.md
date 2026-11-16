# Changelog

What each release changed for a user, newest first, and its known limits ([D-106](design/decisions.md#d-106)). A
release's section is headed `## <version> - <date>`, `unreleased` standing in the date until the commit that is tagged
dates it.

## 1.0.0rc1 - unreleased

The first release. The three distributions, `fylgja-core`, `fylgja-infrahub` and `fylgja-netbox`, are published
as wheels at one version, each built from this repository alone: a release on PyPI, a candidate on TestPyPI.

What 1.0 holds, and what it does not, is stated on [one page](docs/compatibility.md): the API
and the formats at version 1, the four commands with their options and exit statuses, and the names
of the variables they read are held within major version 1, and the example orchestrator, the make
targets and the scripts are not.

Not published: an image, a source distribution and the example orchestrator.

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
distributions. Each line is one question of [Open questions](design/decisions.md#open-questions)
there, where its readings are.

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
  does not allow a restart, in a step that adds or removes a node or in the next step after one. A
  node added or removed can move another node's management address, and clabernetes then makes that
  node's pod anew. By a simulation of how clabernetes draws the addresses, it happens in about one
  step in a hundred that adds a probe's two hosts. ([more][oq])
- A step runs no flow and measures no loss: each probe of a step's target is reported `not_started`
  in its verdict, as [the findings format](formats/findings-1.schema.json) says.
- A core remembers in memory alone that an apply of a twin on the cluster was cancelled, so that its
  destroy waits for the cluster's API to settle. A core that restarts forgets it, and its next
  destroy of that twin does not wait, so a namespace the cancelled request goes on to make may be
  left standing.

The example's, the test suites' and the development tooling's open questions are in
[Open questions](design/decisions.md#open-questions) and are not promised: the many-twins
scenario's forty-node twin, Infrahub on volumes kept for days, the cluster's rehearsal time, the
task worker's clone, a registration read from GitHub, Prefect's credential in NetBox's changelog,
authoring a change of several steps in NetBox, three small gaps, and `make netbox-up`'s network.

[oq]: design/decisions.md#open-questions
