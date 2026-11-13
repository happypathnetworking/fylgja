# Formats

Every format of every distribution, version 1: each format and interface the core reads
and writes, the reader document each reader takes, and the example orchestrator's two
documents. Each has one version,
specified by its file here ([D-002](../design/decisions.md#d-002), Constitution XII). The
design they follow is [design/core.md](../design/core.md). A change found while
building the core is made here, in the same change as the code.

The core's wheel carries the core's formats as the package's data, copied when it is built from the list in `core/setup.py` ([D-066](../design/decisions.md#d-066), [D-084](../design/decisions.md#d-084)); a format another distribution reads is carried by that distribution's wheel. This directory stays the one place a format is changed.

Version 1 of every format starts at the repository's baseline. The earlier formats are in
the project's archived repository, where the input was called a snapshot
([D-006](../design/decisions.md#d-006)).

Every property has a description that names its consumer (Constitution XII). `$id`s are
under `https://github.com/happypathnetworking/fylgja/schemas/`, and cross-file `$ref`s are
relative to them.

## The files

| File | Introduced by |
|---|---|
| [`blueprint-1.schema.json`](blueprint-1.schema.json) | [D-006](../design/decisions.md#d-006) |
| [`platform-package-1.schema.json`](platform-package-1.schema.json) | [D-015](../design/decisions.md#d-015) |
| [`probe-package-1.schema.json`](probe-package-1.schema.json) | [D-015](../design/decisions.md#d-015) |
| [`probes-1.schema.json`](probes-1.schema.json) | [D-002](../design/decisions.md#d-002) |
| [`bundle-1.schema.json`](bundle-1.schema.json) | [D-011](../design/decisions.md#d-011) |
| [`deployment-1.schema.json`](deployment-1.schema.json) | [D-011](../design/decisions.md#d-011), [D-017](../design/decisions.md#d-017) |
| [`twin-record-1.schema.json`](twin-record-1.schema.json) | [D-019](../design/decisions.md#d-019), [D-023](../design/decisions.md#d-023) |
| [`findings-1.schema.json`](findings-1.schema.json) | [D-025](../design/decisions.md#d-025) |
| [`problem-1.schema.json`](problem-1.schema.json) | [D-025](../design/decisions.md#d-025) |
| [`api-1.openapi.yaml`](api-1.openapi.yaml) | [D-025](../design/decisions.md#d-025) |
| [`infrahub-reader-1.schema.json`](infrahub-reader-1.schema.json) | [D-082](../design/decisions.md#d-082) |
| [`netbox-reader-1.schema.json`](netbox-reader-1.schema.json) | [D-095](../design/decisions.md#d-095) |
| [`plan-1.schema.json`](plan-1.schema.json) | [D-086](../design/decisions.md#d-086) |
| [`rehearsal-1.schema.json`](rehearsal-1.schema.json) | [D-086](../design/decisions.md#d-086) |

## Notes

1. **Links have `a` and `b`, not `endpoints[2]`.** `a` sorts first, so a link has one
   spelling.
2. **The blueprint's config is a plain `config` string.** The core does not know the
   source's word "artifact". It is optional in blueprint 1 and bundle 1
   ([D-048](../design/decisions.md#d-048)): a device without one is unmanaged.
3. **The bundle stores no `image`.** An image is runtime-specific, and the bundle stays
   runtime-neutral. The deployment's rendered topology carries the image, and a step finds an
   image change by comparing the old and new deployments. Bundle diff covers only
   runtime-independent changes.
4. **Lossiness is computed, not declared.** It exists only where a kind with no aliases
   needs a `rename`, so the plan counts it per deployment. There are no breakout parents:
   aliases carry each lane as its own port.
5. **No bootstrap** ([D-015](../design/decisions.md#d-015)). With no startup-config, both
   kinds' baselines hold the hostname, linked ports enabled, LLDP and gNMI, and all of it
   survives the replace push on both drivers.
6. **`last_step` names its `run_id`.** The run's verdict holds the findings, the wait and
   the loss, once.
7. **The twin is a resource in Kubernetes's shape** ([D-025](../design/decisions.md#d-025)).
   The record's `spec` (written by clients) and `status` (written by the loop), with
   `generation`, `revision` and `deletion_requested_at`, are the twin the API serves. A step
   is a new spec, a dry run is `PUT …?dry_run=true`, and clients watch a twin by server-sent
   events. `status.phase` and `status.run_id` let a restarted core resume (constitution VIII).
8. **A compile that fails answers 422 with a problem document**, rule `bundle.rejected`, and
   every fault in `findings`. It is not a verdict document. A plan the driver refuses
   answers 422 the same way, rule `plan.rejected` ([D-045](../design/decisions.md#d-045)),
   and so does a dry run's refused admission, under the refusal's rule with its finding, since
   a refusal leaves no deployment for a `Plan`.
9. **Verify is synchronous with no wait.** A waiting verify happens only inside a step's
   run, and the step's wait budget is the server's setting.
10. **A twin's name is a DNS-1123 label of at most 40 characters.** Run ids are ULIDs. A
    problem's `type` is a class, and `rule` is the specific id, so no fact is stored twice.
11. **Findings hold the core's rules alone.** A reader's rules are its own, in its own
    `rules.md`: the Infrahub reader's are in
    [`readers/infrahub/rules.md`](../readers/infrahub/rules.md)
    ([D-082](../design/decisions.md#d-082)), the NetBox reader's in
    [`readers/netbox/rules.md`](../readers/netbox/rules.md)
    ([D-095](../design/decisions.md#d-095)). Rules for stages and rehearsals are the example
    orchestrator's ([D-081](../design/decisions.md#d-081)), in
    [`orchestrator/rules.md`](../orchestrator/rules.md).
12. **A device name is a DNS-1123 label** of at most 63 characters
    ([D-038](../design/decisions.md#d-038)). It becomes the node's host name, its container
    or pod name and its bundle file name, so the blueprint requires the one form all of them
    accept; a reader that renames a device to fit records it in its fidelity rows.
13. **The twin record carries `status.allocation` since phase 4.** `admit` reserves into the
    record by compare-and-set ([D-017](../design/decisions.md#d-017)), a resumed plan reads it
    back so that plan stays pure, and destroy releases it. Its shape is the driver's, as in the
    deployment.
14. **`TwinApply` takes a partial spec** since phase 4. A client names one of the two ids,
    and `driver` and `allow_restart` only when it sets them. The server fills what is absent
    (its configured driver, `false`) and writes the whole spec, which the twin record still
    requires.
15. **A package validation's verdict has an empty `subject`** since phase 4: no id applies to
    a package the request carried, so findings-1's `subject` may hold none.
16. **API 1's driver capabilities carry `isolation`** since phase 4: `names` for a local lab,
    whose management network routes to other twins' through the host, or `network` for a
    NetworkPolicy per namespace ([D-019](../design/decisions.md#d-019)), so a client can say
    how far apart its twins are.
17. **A malformed query parameter is 400** (`request.invalid`) since phase 4, on the four
    operations that take one and declared no 400 before: `listTwins` and `getTwin`
    (`watch`, `since_revision`), `listRuns` (`twin`) and `getRunEvents` (`after`, and the
    stream's `Last-Event-ID`).
18. **`Event.rule` says what each ending's rule holds** since phase 4: on `failed` and
    `timed_out`, the failing finding's rule, which is the Ready condition's reason too; on the
    cancel phase's `done`, `run.cancelled`; and on a transient failure's `failed`, the error's
    rule with no finding filed, the phase's next `started` being the retry.
19. **No route answers 501 since phase 5.** In phase 4, what a phase did not build answered
    501, rule `api.unbuilt`, with the phase that builds it in the detail (API 1's `NotBuilt`
    response): the bundle diff, verify, and a step (a new spec on a twin that exists). Phase 5
    builds all three, and the response and the rule went with the last.
20. **A dry run of a step answers what changes** since phase 5: on a twin that runs, `Plan`
    carries `changes`, API 1's `Changes`, which mirrors the driver's `changes` key for key
    ([D-049](../design/decisions.md#d-049)), and its verdict is `rejected` with the findings
    of the refusal the loop would make ([D-050](../design/decisions.md#d-050)). A new spec of
    a diverged twin is `409 twin.diverged`, a dry run's too.
21. **API 1's driver capabilities carry `reapply`** since phase 6: `true` where applying a
    deployment again finishes an apply that was cut short (clabernetes, whose controller goes
    on after the core stops), `false` where a resumed apply probes the lab first and may
    reconfigure it (a local lab, whose plain redeploy of a partial lab fixes nothing)
    ([D-068](../design/decisions.md#d-068)), so a client can say how a twin resumes from a core
    stopped during its apply.
22. **A run's operation may be `restore`** since phase 6, and so may its verdict's: the loop's
    own run, by the principal `core`, that readies, pushes and verifies again a node a kick
    found replaced on a settled twin ([D-067](../design/decisions.md#d-067)). Its verdict
    carries verify's counts and the wait, as a step's does, and no loss. A run's verdict
    names its run's operation, so findings 1 gains `restore` beside API 1.
23. **The plan and the rehearsal are the example orchestrator's documents** since phase 8,
    carried by its wheel and not the core's ([D-084](../design/decisions.md#d-084)). Each
    `$ref`s nothing outside the two files, so that wheel resolves them alone.

## Settled by measurement (2026-10-30)

Measured on containerlab 0.79 and clabernetes 0.10.1:

- **cEOS has no interface aliases** in containerlab 0.79 through 0.82. `arista_eos` keeps
  `alias: false` and one `rename` per rule. The kind's name pattern is unanchored at the
  start, so a wrong name ending in `et<digit>` is accepted silently; the plan emits only
  rename output for such a kind.
- **No bootstrap** is needed on either kind or either driver.
- **`link_apply_mode` and `hot_add_ports`.** `live` re-cables both
  kinds with no restart on both drivers, for ports present at boot. cEOS never sees a port
  added after boot. The mode is set at create and never changed: on clabernetes a change
  replaces the pod of each node whose mode changed.
- **The twin record holds each node's `incarnation`** (the container's start time, the
  pod's uid and its container's restart count), since a replaced node loses its push and
  `holds` must be voided. On clabernetes a container ended in its pod is restarted there,
  with the pod's uid unchanged, and an SR Linux node's, read so, booted again and lost its
  push too: the restart count is what moves.
- **The deployment holds an `allocation`**, from the seam call `admit`
  ([D-017](../design/decisions.md#d-017)), and on clabernetes a NetworkPolicy per twin
  ([D-019](../design/decisions.md#d-019)).
- **Node access on clabernetes** is a LoadBalancer per node
  ([D-020](../design/decisions.md#d-020)), so `access` stays absent there.

## Still open

- **Name lengths.** Device names are DNS-1123 labels of at most 63 characters and the twin
  name one of at most 40. Should both be checked against clabernetes's and containerlab's
  limits? clabernetes names a Service per node, and a Service name is a DNS-1035 label,
  which begins with a letter.
- **Image acquisition locally.** With `pull_secret` set, the image must be present. Without
  it, may the local driver pull a platform or probe image?
- **Admission's demand.** Are `cpu` and `memory_mb` sums enough, or does clabernetes need
  per-node requests in the deployment? *Settled 2026-11-08* ([D-073](../design/decisions.md#d-073)):
  the sums suffice; the per-node figures are in the rendered Topology and in the packages the
  fit rule reads. Phase 7 adds `demand` to the allocation instead, on both drivers.
