# Formats

Every format and interface the core reads and writes, version 1. Each has one version,
specified by its file here ([D-002](../design/decisions.md#d-002), Constitution XII). The
design they follow is [design/core.md](../design/core.md). A change found while
building the core is made here, in the same change as the code.

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

## Notes

1. **Links have `a` and `b`, not `endpoints[2]`.** `a` sorts first, so a link has one
   spelling.
2. **The blueprint's config is a plain `config` string.** The core does not know the
   source's word "artifact".
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
   answers 422 the same way, rule `plan.rejected` ([D-045](../design/decisions.md#d-045)).
9. **Verify is synchronous with no wait.** A waiting verify happens only inside a step's
   run, and the step's wait budget is the server's setting.
10. **A twin's name is a DNS-1123 label of at most 40 characters.** Run ids are ULIDs. A
    problem's `type` is a class, and `rule` is the specific id, so no fact is stored twice.
11. **Findings hold the core's rules alone.** Rules for readers, stages and rehearsals are
    the orchestrator's ([D-003](../design/decisions.md#d-003)).
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
  replaces every pod.
- **The twin record holds each node's `incarnation`** (the container's start time, the
  pod's uid), since a replaced node loses its push and `holds` must be voided.
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
  per-node requests in the deployment?
