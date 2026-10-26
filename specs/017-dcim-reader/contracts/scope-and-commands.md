# The scope, the commands, the server setting and the identifiers

What moves in [cli.md](../../../contracts/cli.md) and [api.md](../../../contracts/api.md)
for 017, to land there as "017: the scope and the DCIM reader". Identifiers, exit
statuses and the JSON documents are the contract; text is illustrative except where a
sentence is quoted. Everything not named here is as 015 left it.

## The scope

`tag:<name>`: the literal `tag:` and one shell word (`^tag:\S+$`). It names the devices a
twin is of: every `DcimDevice` on the branch carrying the `BuiltinTag` of that name,
whatever its status; ports and cables follow their devices.

```
fylgja twin create   --branch <b> [--at <t>] [--scope tag:<name>] …
fylgja twin create   --stage <b>/<label> [--scope tag:<name>] …
fylgja twin rehearse --branch <b> [--scope tag:<name>]
fylgja intent read   --branch <b> | --stage <b>/<label> [--scope tag:<name>] --out ctm.json
fylgja stage plan    --branch <b> [--scope tag:<name>]
fylgja stage list    [--branch <b>] [--scope tag:<name>]      # the plan's addition; analyze settles it against FR-017
```

- Given, the scope is the request's. Not given, the server's `FYLGJA_DEFAULT_SCOPE`.
  Every stage a command resolves, reads or plans is read under that one scope, but the
  twin's: `stage list` judges the twin's stage for `stage.twin.moved` under the scope its
  twin's record carries, as `twin step` reads it (T102). The scope moves a head alone, so
  a head record of another scope is resolved once more under it, for the warning alone;
  the rows, the twin's mark and every other stage stay the listing's, and a `7` record, or
  an `8` whose scope is not `tag:<name>`, is judged under the listing's.
- `twin step` takes no `--scope` (cobra's `unknown flag: --scope`, exit 2, no request): it
  reads under the scope its twin's record carries. A following twin's checks read under
  the record's scope too.
- `twin show` prints it; `twin compile` takes none (the CTM carries it); `twin provision`,
  `twin verify`, `twin destroy`, `schema check` and `psp validate` take none.
- The checks `fylgja-step` and `fylgja-twin` send no `scope`.

## The server

| | |
|---|---|
| Variable | `FYLGJA_DEFAULT_SCOPE`, read by the server at start and never by a client or the worker; documented in `.env.example` under the server's variables; scaffolded by `scripts/bring-up.sh` as `tag:fylgja` |
| Report line | `fylgja serve: default scope: tag:fylgja`, after the state root line; or `fylgja serve: default scope: unset (a request that names no scope is refused)` |
| Refusal to start | none: an unset or empty value is reported, not refused; a value that is not `tag:<name>` is `fylgja serve: FYLGJA_DEFAULT_SCOPE <value> is not tag:<name>`, exit 2, before it listens |

## The API

`scope` is a new optional string argument of `twin.create`, `twin.rehearse`,
`intent.read`, `stage.plan` and `stage.list`. The API's version stays `1`: a client that
never sends it is served under the default. `twin.step` takes none: a request carrying it
is `400`, `the request is not one: twin.step takes no argument "scope"`. Present and empty
(`"scope": ""`) is `--scope=`, refused `scope.invalid`.

## The identifiers

| Rule | Severity, exit, step | Object | When |
|---|---|---|---|
| `scope.invalid` | rejection, 2, `start` | the value given | `--scope` is not `tag:<name>`, an empty value included; before any connection, after `--branch`'s and `--stage`'s guards |
| `scope.unset` | rejection, 2, `start` | `FYLGJA_DEFAULT_SCOPE` | no `--scope` and the server has no default; before any connection |
| `scope.empty` | rejection, 1, `read` (none on `intent.read`; a stage's at its read, the branch point's included, where `contract.node.missing` was: `[step read]` in 0.2's `contracts/cli.md`); `resolve` for a stage's head (a warning in `stage list`) | the scope | the device query answered 0 on the branch at the `at`; or, for a head, the stamps read under the scope selected no device and the branch holds no intent event since its branch point, so the head has no `at` to read at (`scope <scope> selects no device on branch <b>`; T076), where `stage.at.unresolved` was; the rehearsal and `fylgja-step` pass over a branch point refused by this rule at `read` alone, as they passed over `contract.node.missing` |
| `schema.kind.missing` | rejection, 1, `read` / none on `schema.check` | the kind | the branch's schema lacks a kind the mapping reads |
| `schema.field.missing` | rejection, 1, `read` | `<kind>.<field>` | the kind lacks a field the mapping reads |
| `schema.field.mismatch` | rejection, 1, `read` | `<kind>.<field>` | the field's kind, cardinality, peer or optionality is not the table's; names both |
| `schema.choice.missing` | rejection, 1, `read` | `<kind>.<field>` | the dropdown lacks `management` (role) or `disabled` (status) |
| `schema.used_by.missing` | rejection, 1, `read` | the generic | the generic is not implemented by the kind the mapping expects |
| `platform.missing` | rejection, 1, `read` | the device | no platform, or a platform with no manufacturer; names what the device carries |
| `platform.unmatched` | rejection, 1, `read` | the device | no package matches the pair exactly; names the pair and every package's pairs |
| `omit.cable.ends` | info, 0, `read` | the cable | other than two ends |
| `omit.cable.endpoint` | info, 0, `read` | the cable | an end not on a physical port |
| `omit.cable.outside_scope` | info, 0, `read` | the cable | an end outside the scope |
| `omit.cable.kind` | info, 0, `read` | the connector | a connector that is not a DcimCable (`<kind>`) |
| `ctm.version.unsupported` | rejection, 1, none | the CTM file | `twin compile` given a CTM of another version, or declaring none; names both, or the one it reads |
| `psp.matches.missing` | rejection, 1, `verify` | the package path | no match, or a pair with an empty name |
| `psp.matches.duplicate` | rejection, 1, `verify` | the package path | two packages name one pair; names both packages and the pair; also refuses `serve` and `worker run` at start, and the registry's load |

The five `schema.*` rules are also filed at `resolve` by every stage command (`stage plan`,
`stage list`, `twin create --stage`, `intent read --stage`, `twin step`, `twin rehearse`)
when a branch whose stamps it reads, the source branch or the destination, does not
conform: each branch's conformance is checked once per command, before its first stamps
read, and its findings are the read's, every one in one pass, each message prefixed
`branch <b>: ` (T075). The proposed change is refused whole when its source branch does not
conform; a destination that does not conform refuses the branch point in a plan, and the
resolution of any other stage at its `stage.main.moved` step; `stage list` lists the rows
beside the rejections, a source branch's head with no `at`. Until 017's T075 such a branch
ended the command `operation.failed`, exit 2, on its stamps query.

Removed: `contract.version.mismatch`, `contract.node.missing`,
`schema.generic.unimplemented`, `schema.artifact_target.missing`,
`interface.iftype.unimplemented`, `interface.mgmt_only.iftype`,
`interface.parent.missing`, `link.endpoint.iftype`. No new status, step or exit.
`platform.unsupported` stays for a CTM naming a package this build lacks (validation and
`twin compile`).

## The text

- `intent read`: `wrote ctm.json: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3
  artifacts, 0 lossy mappings, 0 shared ports (branch b, scope tag:fylgja, schema
  908871c3…)`; with omissions, `…; 1 cable omitted (…)`; with a stage, `stage b/seeded:
  …` first as today.
- `twin create`'s and `twin show`'s record line: `record: branch b at …, bundle_id …,
  schema …, scope tag:fylgja, read by infrahub-dcim from opsmill/schema-library@26336e9`;
  a `7` record: `…, scope unknown (record 7)`; an `8` whose scope is not `tag:<name>`
  (edited by hand: no build writes one): `…, scope unknown (record 8 names scope "fylgja",
  not tag:<name>)`, its JSON record carrying neither `scope` nor `mapping` (T097); an `8`
  whose mapping `twin.json` 8 cannot hold (edited by hand alike): `…, scope tag:fylgja,
  read by an unknown reader (record 8 names mapping reader "Infrahub DCIM")`, each field it
  fails named (`model ""`, `version ""`), its JSON record carrying neither, since the show
  contract has the scope only beside the mapping (T106).
- `schema check`: `conformant with opsmill/schema-library@26336e9: DcimDevice,
  DcimPlatform, OrganizationManufacturer, InterfacePhysical, DcimCable, DcimConnector`
  (the generic among the table's rows, [mapping.md](mapping.md) §3), then `stages:
  …`; `--json`'s `verified` is `{model, version, kinds: [{kind, fields: [...]}], stages}`.
- `stage plan` and `twin rehearse` headings end `, scope tag:fylgja`.
- `twin rehearse`'s commands that reproduce a failed stage name the scope every stage was
  read under on the create alone, always, the request's or the server's default: `fylgja
  twin create --stage change-1/seeded --scope tag:fylgja`, shell-quoted as the reference
  is, since the server that reproduces it may hold another default; each `twin step` after
  it reads its record's scope and takes none (T104). The JSON's `rehearsal.reproduce`, the
  closing line and the markdown's block carry the same commands.
- The document's `subject` carries `scope` whenever a read was made under one.

## `twin step` and the following twin

The record's `provenance.scope` is the scope of every read the step and the follow make:
the target's resolution, its staleness and its read. A `7` record is refused
`step.twin.unsteppable` naming its version (`the twin was created from a record version
this build no longer reads (twin.json 7); fylgja twin destroy clears it`), as a `5` is,
and an `8` whose scope is not `tag:<name>` alike, naming the value (`the twin's record
names scope "fylgja", which is not tag:<name>, and every read a step makes is under the
record's scope; fylgja twin destroy clears it`; T097), each before any Infrahub read,
after the check for a rehearsal in flight: with the workflow service down, a step that is
not a dry run ends `operation.failed` at `start` before the record is read (T109).

A following twin created before 017 keeps a Schedule whose `ReconcileInput` names no
scope (`omitempty`), so its checks ask for a read under `""`. `stage.Read` refuses a scope
that is not `tag:<name>` before any connection, as `operation.failed` at `read`: `the read
names scope "", which is not tag:<name>: a twin created before 017 follows its branch under
no scope, and this build reads only under one; fylgja twin destroy clears it` (T080). The
workflows are unchanged and the recorded histories replay.
