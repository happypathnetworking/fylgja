# Specify brief: probes (F-014), moved to 0.3

**Moved to [Release 0.3](../../docs/roadmap.md#release-03) on 2026-10-21**, so that 0.2 is
ready to show sooner. The brief below was written as 0.2's third spec and is unchanged
but for this note and the prompt: where it says 0.2, read the release that takes it, and
re-read it against 0.2's close before specifying.

This is what `/speckit-specify` reads for roadmap F-014, the second feature of the
roadmap's [Release 0.2 section](../../docs/roadmap.md#release-02). It was written on 2026-10-16 in the
same design session as [015's brief](../015-proposed-change-rehearsal/brief.md), before
015 is specified. Specify after 015 is built: this feature adds to 015's report and gate,
and the brief's references to them name what 015 builds, so re-read them against 015's
spec and close before specifying. Specify what the operator gets, not a new design.

The prompt:

```
SPECIFY_FEATURE_DIRECTORY=specs/016-probes. 0.3: probes, as docs/roadmap.md's F-014 and Release 0.3 section define it. Read specs/016-probes/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design.
```

## Where the shape is fixed

- **The roadmap's F-014** and its [Release 0.2 section](../../docs/roadmap.md#release-02). This
  feature is what makes 0.2 a demo: loss measured across each stage of a rehearsed
  proposed change, and a flow that has not recovered failing the stage.
- **[Architecture §4.2](../../docs/architecture.md#42-canonical-topology-model-ctm)**:
  synthesized nodes justify the CTM, and provenance `synthesized` is in the model.
  Constitution X demands every synthesized node in the fidelity manifest.
- **[D-032](../../docs/decisions.md#d-032)'s pattern**: a Fylgja-owned, branch-agnostic
  kind beside the contract, written by the operator and only read by Fylgja. 014's entry
  supersedes D-032 and keeps the pattern for `FylgjaStage`.
  **[D-031](../../docs/decisions.md#d-031)**: a mechanism is code keyed by a format value,
  so a probe generator is a format, never a platform branch.
- **[D-038](../../docs/decisions.md#d-038)**: verify's assertions are derived from the
  bundle, and its consequences name probes as an assertion kind to add.
- **[D-028](../../docs/decisions.md#d-028)** and Constitution IV: Infrahub renders every
  device's configuration. Fylgja configures only what it synthesizes.
- **[Constitution 1.2.0](../../.specify/memory/constitution.md)**:
  - **V**: the compiler stays pure.
  - **VI**: what an `at` governs.
  - **IX**: the manifest is the provenance of what runs.
  - **X**: honesty. Container forwarding is not an ASIC's.

## What changes, and nothing else

1. **`FylgjaProbe`**: a branch-agnostic kind loaded on `main` beside the stage kind.
   - Each probe names two endpoints. An endpoint is a device interface plus the address
     its host takes.
   - Each probe names a flow: `ping` at a fixed rate.
2. **Probes as an input to a compile.**
   - The probe set is read once, unpinned, when a `twin create` or a `twin rehearse`
     starts.
   - It is passed to every compile of that twin, and hashed into the bundle beside
     intent.
   - It is recorded in the twin's record.
   - `twin compile` takes it as a file.
3. **Synthesized hosts.**
   - Each endpoint becomes a containerlab `linux` node with its address and a route via the
     device's address, on a synthesized link to the interface.
   - Both are recorded in the fidelity manifest with provenance `synthesized`.
   - The compiler refuses a probe whose interface the intent cables, which lacks an
     address in intent, or whose host address is outside that interface's prefix. A
     proposed change that cables a probe's port therefore fails `fylgja-step` with that
     finding.
4. **A probe package format**, keyed by a format value. `ping` is the first. It names the
   image, its acquisition and the mechanism, so iperf3 or Ixia-c (F-020) is another
   format.
5. **Transient loss, a step measurement.**
   - The step starts each flow before it applies the change and stops it after the wait.
   - The step's record carries packets lost and the longest gap per probe, labelled as
     container timing.
   - It is never asserted.
6. **Unrecovered loss, a verify assertion.** `verify.Derive` gains `probe.flow`: after the
   wait, a short burst gets N consecutive replies. A failure is a finding, so 015's gate
   fails the stage on it with no change to the gate.
7. **015's report gains the loss column**: transient loss per probe, per stage, with the
   caveat.
8. **The artifacts template renders an interface's addresses.** Today neither
   `device_config.gql` nor `device_config.j2` reads `addresses`. Every artifact therefore
   moves, as do the fixture's ids and possibly the goldens. A re-baseline is committed on
   its own.
9. **The records**: the contracts (bundle, manifest, twin record, step record, verify,
   and the probe package format's schema), the format versions moved, the schema README,
   the architecture and its C4 model, development.md, verified-facts.md, the glossary,
   the README's walk-through, and `CLAUDE.md`'s Formats and State.

## Decided

- **Probes are declared by the operator, not derived from the topology.** Deriving which
  ports hosts take, and which pairs to mesh, would be Fylgja guessing at intent.
- **The probe set is a separate input, read once and constant across a twin's life**,
  rather than read pinned at each stage's `at`. Read pinned, a probe written after the
  branch point would be missing from a rehearsal's first stage. Like a stage, a probe is
  a mark beside intent, never part of it, and the bundle stays content-addressed over
  everything it was built from.
- **The device side of a probe is intent's.** The interface's address comes from intent
  and is rendered by Infrahub. Fylgja configures only its host.
- **Transient loss is measured and reported, never gated. Unrecovered loss gates**, as a
  verify finding.
- **`ping` first**, from a containerlab `linux` node. iperf3 and Ixia-c are later formats.

## Open, for clarify

1. **Which probes a twin gets.** Every `FylgjaProbe` there is, those in a named set, or
   only when `--probes` is given (with the rehearsal always taking every one).
2. **The rate, and the `probe.flow` burst's N**: fixed in the format, or the probe's own.
3. **A probe whose device a stage removes**: the compiler refuses that stage, or the probe
   drops out of it with a finding.

## Left to the plan

- **Whether synthesized nodes enter the CTM or only the compile.** The architecture says
  synthesized nodes are added to the CTM before compilation, and the probe set is not
  intent.
- **The `linux` image and its acquisition**, verified on containerlab 0.79.0. Then how a
  step reads a flow's counters from inside its host.
- **What the fixture gains**: a probe-ready interface per device (uncabled, addressed),
  moving its compiled id, or probes only on throwaway branches.
- **The format versions** that move, and the frozen copies older tests read.

## Exit

- **Tier 1**: the probe set's compile, refusals and hash; `probe.flow`'s derivation; the
  goldens re-baselined on their own commit.
- **Tier 2**: the kind loads on `main`; the probe set and the addresses are read against
  the real Infrahub.
- **Tier 3**:
  - A twin with probes reports transient loss across a step.
  - 015's tier-3 rehearsal gains a stage that cuts a probe flow. The check fails at that
    stage on `probe.flow`, and the comment carries the loss column.
- **Owed before the work starts**: 014 and 015 built and closed.

## References

| Record | What it gives |
|---|---|
| [docs/roadmap.md](../../docs/roadmap.md): [F-014](../../docs/roadmap.md#f-014), [Release 0.2](../../docs/roadmap.md#release-02), [Decisions the order needs](../../docs/roadmap.md#decisions-the-order-needs) | the scope and the decisions owed |
| [015's brief](../015-proposed-change-rehearsal/brief.md), and its spec once written | the report and gate this feature extends |
| [docs/decisions.md](../../docs/decisions.md): D-010, D-022–D-024, D-028, D-031, D-032, D-037, D-038 | synthesized nodes, the bundle's hashing, the mechanism pattern, the assertions |
| [docs/architecture.md](../../docs/architecture.md) §4.2, §6 | the CTM's synthesized nodes and the known limitations |
| `schema/fylgja-generics.yaml` (`addresses`; removed at 017, whose CTM `2` carries no address), [014's stage kind](../014-proposed-change-stages/research-probe/fylgja-stage.yaml), [infrahub/](../../infrahub/) | the interface's addresses, the kind's pattern, the template to extend |
| [psp/README.md](../../psp/README.md), [contracts/](../../contracts/) | the package format's pattern and the documents that move |
