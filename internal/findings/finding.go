// Package findings carries every problem Fylgja reports, in one shape.
//
// A finding names the object at fault, the rule it violated, and how serious that is.
// Rejections prevent any artifact from being written; warnings and info do not. The
// machine-readable rendering is the contract acceptance tests assert against,
// so rule identifiers here are stable API.
package findings

// Severity orders findings by consequence.
type Severity string

const (
	// Rejection prevents any CTM file or bundle from being written.
	Rejection Severity = "rejection"
	// Warning is reported but does not prevent output.
	Warning Severity = "warning"
	// Info records something worth knowing, such as a recorded omission.
	Info Severity = "info"
)

// Rule identifiers. Stable: tests and reports refer to these by name. Every rule Fylgja
// reports has a constant here, and every constant here is used.
const (
	// CTM-side, run identically on fixtures and live intent.
	RuleRequiredMissing      = "data.required.missing"
	RuleDeviceNameDuplicate  = "device.name.duplicate"
	RulePlatformUnsupported  = "platform.unsupported"
	RuleLinkEndpointsCount   = "link.endpoints.count"
	RuleLinkEndpointsSameDev = "link.endpoints.same_device"
	RuleUnmappableLinked     = "interface.unmappable.linked"
	// RuleDevicesEmpty rejects a CTM with no devices: an empty read is almost always
	// a wrong `at`, and a manifest for zero nodes has no value for
	// fidelity.production_forwarding.
	RuleDevicesEmpty = "ctm.devices.empty"

	// Compiler-side omissions: recorded in the manifest, never a rejection.
	RuleOmitLinkMgmtOnly        = "omit.link.mgmt_only"
	RuleOmitInterfaceUnmappable = "omit.interface.unmappable"
	RuleOmitMgmtExtra           = "omit.mgmt.extra"

	// Platform support package validation.
	RulePSPSchema               = "psp.schema"
	RulePSPVersionUnknown       = "psp.version.unknown"
	RulePSPPatternsPlaceholders = "psp.patterns.placeholders"
	RulePSPPatternsBreakout     = "psp.patterns.breakout"
	RulePSPManagementCollides   = "psp.management.collides"
	RulePSPIdentityDuplicate    = "psp.identity.duplicate"
	RulePSPResourcesImplausible = "psp.resources.implausible"
	RulePSPReadinessImplausible = "psp.readiness.implausible"
	RulePSPAcquisitionKVM       = "psp.acquisition.kvm"
	// RulePSPReadinessEncoding rejects a gNMI probe that names no encoding: the proto
	// default is refused as Unimplemented, so the probe could never succeed.
	RulePSPReadinessEncoding = "psp.readiness.encoding"
	// RulePSPReadinessAwaitPushTransport rejects a package that asks readiness to wait for
	// the push transport and declares no config.push for it to wait on: the request cannot
	// be satisfied (M7 D-029).
	RulePSPReadinessAwaitPushTransport = "psp.readiness.await_push_transport"

	// Operational failures: the operation did not run (exit 2).
	RuleOperationFailed = "operation.failed"
	// RuleAtPrecision rejects an --at finer than Infrahub honours, before any query
	// is sent: Infrahub truncates past microseconds, so a finer value would silently
	// read a different instant than the operator asked for.

	// M2, provisioning. Each comment gives
	// the step the finding belongs to and its cause.

	// Host check: refusals before anything on the host is touched (exit 1).
	RuleHostLabPresent       = "host.lab.present"       // host_check: lab fylgja exists in some state; destroy clears it
	RuleHostTwinPresent      = "host.twin.present"      // host_check: a twin directory exists; destroy clears it
	RuleHostMemoryExceeded   = "host.memory.exceeded"   // host_check: the nodes' memory sum exceeds FYLGJA_HOST_MEMORY_MB
	RuleHostMemoryUnbudgeted = "host.memory.unbudgeted" // host_check: a warning; no host budget is set, so the sum is only reported
	RuleHostProbeLoginUnset  = "host.probe.login_unset" // host_check: a variable a probe login names is unset on the worker
	RuleHostPSPMissing       = "host.psp.missing"       // host_check: a node's manifest psp.id has no package on the worker

	// Bundle verification, before any run (exit 1).
	RuleBundleInvalid            = "bundle.invalid"             // verify: no manifest, an unparsable one, no topology, or a node whose artifact file is missing or not as its entry describes
	RuleBundleVersionUnsupported = "bundle.version.unsupported" // verify: bundle_version is not one this build deploys
	RuleBundleIDMismatch         = "bundle.id.mismatch"         // verify or compile: the bytes hash to a different identity than claimed

	// Starting and following a run.
	RuleRunInFlight           = "run.in_flight"           // start: a provisioning run is already running (exit 1)
	RuleRunWorkerAbsent       = "run.worker.absent"       // start: no worker polls queue fylgja, or none took the first task (exit 2)
	RuleRunServiceUnreachable = "run.service.unreachable" // start: the workflow service did not answer (exit 2)
	RuleRunCancelled          = "run.cancelled"           // any step: the run was cancelled by an interrupt or a destroy

	// Failures after the host was touched (exit 3, or 4 when something remains).
	RuleStageFailed       = "stage.failed"       // stage: the bundle could not be copied or verified into the twin directory
	RuleDeployFailed      = "deploy.failed"      // deploy: clab deploy exited non-zero or a node is not running afterwards
	RuleReadinessTimeout  = "readiness.timeout"  // readiness: a node did not answer its probe within its package's timeout
	RuleRecordFailed      = "record.failed"      // record: twin.json could not be written
	RuleCleanupIncomplete = "cleanup.incomplete" // teardown or unstage: something remains; names it and the command that clears it

	// M4 (contracts/cli.md). 019 retired following's seven, follow.interval.invalid,
	// follow.flags.conflict, follow.start.failed, follow.stop.failed, check.skipped,
	// rebuild.failed and follow.stopped, with the step follow (D-062); an earlier build's
	// document that names one is held to the contract frozen under 018-snapshots/.

	RuleShowServiceUnreachable = "show.service.unreachable" // no step: a warning; twin show or twin verify could not reach the workflow service, so whether a run is in flight is unknown (exit 0)

	// M5, configuration (contracts/cli.md). Each
	// comment gives the step the finding belongs to, the object it names, and when it fires.

	// Conformance and the read's artifact selection. Every device is decided before any
	// content is fetched, so one read reports every device's refusal (Constitution III).
	RuleArtifactMissing                = "artifact.missing"                  // read, and compile from validation: the device; no artifact of the package's name on it (at `at` when pinned; names `at`), or a CTM device without one
	RuleArtifactAmbiguous              = "artifact.ambiguous"                // read: the device; more than one artifact of that name; names the count and each checksum
	RuleArtifactNotReady               = "artifact.not_ready"                // read: the device; status is not Ready, or there is no storage object yet; names the state and that Fylgja never regenerates
	RuleArtifactContentTypeUnsupported = "artifact.content_type.unsupported" // read, and compile from validation: the device; the content type is not one the package accepts, or the bytes are not text
	RuleArtifactContentUnavailable     = "artifact.content.unavailable"      // read: the device; the storage object of the listed id is not served (404 or another non-auth status); names `at` when pinned
	RuleArtifactChecksumMismatch       = "artifact.checksum.mismatch"        // read, and compile from validation: the device; MD5 of the bytes is not Infrahub's checksum; names both

	// The push, on the lab host. Both fail the run at step push (exit 3, or 4 when
	// cleanup left something), after M2's cleanup has run.
	RulePushRefused = "push.refused" // push: the node; the node refused the artifact; names the artifact, its checksum, the line and the node's own reason, never the content
	RulePushFailed  = "push.failed"  // push: the node; the push could not be made or timed out: transport, status, budget, or a staged file that no longer matches its checksum; a lost heartbeat is named as M2 names a deploy cut short

	// Platform support package validation, format 0.3's config block. A platform whose
	// delivery this build cannot push by is refused at load, never silently skipped
	// (Constitution II).
	RulePSPConfigArtifactName          = "psp.config.artifact_name"          // verify: the package path; artifact_name equals startup_format or fails its pattern
	RulePSPConfigContentType           = "psp.config.content_type"           // verify: the package path; an entry of artifact_content_types is not text/*
	RulePSPConfigDeliveryUnimplemented = "psp.config.delivery.unimplemented" // verify: the package path; delivery names a mechanism this build does not push by
	RulePSPConfigPushMissing           = "psp.config.push.missing"           // verify: the package path; delivery json_rpc without push, or mode replace with commit implicit, for which no command list is defined

	// M6, the mapping profile (contracts/cli.md). Each comment gives the step, the object
	// and when it fires. The
	// three interface refusals are raised by validation and mirrored word for word by the
	// compiler's guards.
	RuleInterfacePortCollision        = "interface.port.collision"         // read; compile: <device>:<port>; two or more cabled interfaces of one device render to one port; names every interface and its rule
	RuleInterfaceBreakoutParentCabled = "interface.breakout.parent_cabled" // read; compile: <device>:<parent>; a breakout parent is cabled beside one or more of its cabled children; names each child and the rule
	RuleInterfaceRuleUnmatched        = "interface.rule.unmatched"         // read; compile: <device>:<interface>; no rule matches an interface no link touches; names every rule tried, in order
	RuleOmitInterfaceShared           = "omit.interface.shared"            // compile, info, recorded: <device>:<interface>; an uncabled interface renders to a port a cabled one holds; names the port, the holder and both rules
	RulePSPRuleName                   = "psp.rule.name"                    // verify: the package path; a rule without a name, or two rules with one name
	RulePSPManagementRule             = "psp.management.rule"              // verify: the package path; no management rule, more than one, or one with a data rule's fields
	RulePSPMappingsInvalid            = "psp.mappings.invalid"             // verify: the package path; no declared mappings, or a declaration that is malformed or names no rule of the profile

	// M7, the second platform (contracts/cli.md). Each comment gives the step, the
	// object and when it fires. No
	// step is added: the image refusal joins the host check's one pass, the artifact
	// warning is filed at read and at compile, and the package rule is a load-time
	// refusal like every other psp.* rule.
	RuleHostImageAbsent                = "host.image.absent"                // host_check: the image reference; a node's package declares an acquisition other than public_registry and the host holds no image under exactly that reference; a rejection, exit 1, before staging, and nothing is ever pulled or tagged
	RuleArtifactInterfaceUnrepresented = "artifact.interface.unrepresented" // read; compile: <device>:<interface>; the artifact names an interface the mapping omitted, or one the node calls by another name; a warning, exit 0, which never refuses a bundle
	RulePSPConfigBootstrapVia          = "psp.config.bootstrap_via"         // verify: the package path; bootstrap_via is push with mode replace, or with a delivery that carries no configuration lines

	// M11, stepping (contracts/cli.md). Each
	// comment gives the severity, the exit, the step, the object and when it fires. The
	// CLI's refusals before any run are at resolve (the twin, the target, the from
	// bundle) and compare (the plan's rules); the run's second locks reword them at
	// inspect and compare. A run in flight is M2's run.in_flight, not a new rule. 019
	// retired step.target.foreign: twin step's --stage names a stage of any proposed change
	// (D-062; research R-07), so its two cases, another branch and another proposed change
	// opened on the record's, are targets.
	RuleStepTwinUnsteppable   = "step.twin.unsteppable"   // rejection, exit 1, resolve (inspect from the run's second lock): lab fylgja, M3's object, or the record's bundle_id; no twin, an orphan, an unreadable record, a record without its lab, a record of twin.json 5 or earlier, or a record naming no stage; from 017, a record of 7 or earlier, or one of 8 or later naming a scope that is not tag:<name> or a mapping twin.json 8 cannot hold; from 019, the command alone, a record naming no snapshot: a bundle twin's, an 8, or a 9 or 10 naming none; from 020, a record of 11 or earlier (twin.json 12, naming fylgja twin destroy), a record whose snapshot the store does not hold (the snapshot's id), and a target whose snapshot's envelope names another scope or mapping than the twin's snapshot's (the target)
	RuleStepTwinDiverged      = "step.twin.diverged"      // rejection, exit 1, resolve (inspect): the record's bundle_id; the record's state is diverged, which only twin destroy clears
	RuleStepTargetUnknown     = "step.target.unknown"     // rejection, exit 1, resolve: the record's stage or the reference; the record's label is gone, no stage follows it, or the proposed change has not the one given; from 019, the record's bundle_id: no --stage and no --snapshot for a record naming no stage, before any connection; from 020, --snapshot: no --stage and no --snapshot, before anything is read
	RuleStepBundleMissing     = "step.bundle.missing"     // rejection, exit 1, resolve: the record's bundle_id; the store does not hold the bundle the twin was built from
	RuleStepPackageMerge      = "step.package.merge"      // rejection, exit 1, compare: the package id; a node of either bundle runs a package whose mode is merge, which has no reset
	RuleStepNodeUnapplied     = "step.node.unapplied"     // rejection, exit 1, compare: the node; the step changes its image, platform or psp and containerlab's plan does not recreate it, or adds it and the plan does not create it
	RuleStepRestartRequired   = "step.restart.required"   // rejection, exit 1, compare: the nodes; containerlab's plan restarts or recreates a node and --allow-restart was not given
	RuleStepDiverged          = "step.diverged"           // rejection, exit 4 (status diverged), the phase's step: the run id; the step failed or was cancelled from the stage on, and the twin is up and diverged
	RuleStepRestartUndeclared = "step.restart.undeclared" // warning, exit 0, compare: the node; containerlab's plan restarts a node whose package declares link_change live, or re-cables live one that declares restart

	// M12, verify (contracts/cli.md). Each comment
	// gives the severity, the exit, the step, the object and when it fires. An unread
	// node is operation.failed at observe, and a package not on this host or a login
	// unset is M2's host.psp.missing or host.probe.login_unset, so none is a new rule.
	RuleVerifyHostName          = "verify.host_name"          // rejection, exit 5 (status nonconforming), observe: the node; the host name read is not the node name, or nothing was read
	RuleVerifyPortEnabled       = "verify.port.enabled"       // rejection, exit 5, observe: <node>:<port>; a cabled port intent enables is not enabled, or nothing was read and the facet declares no meaning for absence
	RuleVerifyNeighbor          = "verify.neighbor"           // rejection, exit 5, observe: <node>:<port>; a link end does not see the far node and port the link names: nothing, another, or more than one
	RuleVerifyRecordHolds       = "verify.record.holds"       // rejection, exit 5, observe: the node; the record says the node holds the previous bundle, or none, labelled the record's claim
	RuleVerifyTwinAbsent        = "verify.twin.absent"        // rejection, exit 1, observe: lab fylgja or the twin directory; no twin, in M3's phrase, before any node is read
	RuleVerifyPackageUnreadable = "verify.package.unreadable" // rejection, exit 1, observe: the package id; the package declares no conformance facet, or its readiness probe is not gNMI
	RuleVerifyWaitInvalid       = "verify.wait.invalid"       // rejection, exit 2, start: --wait; not a duration, negative, empty, or a value given as an argument
	RuleVerifyWaitUnsettled     = "verify.wait.unsettled"     // warning, exit 0, observe: the step run id; the step's wait ended expired, cancelled or incomplete, beginning with the outcome and naming what still fails

	// M13, the client's own. Each comment gives
	// the severity, the status, the exit, the step, the object and when it fires. They
	// say what happened between the client and the server, so the client makes them and
	// the server never does, and none carries a step: none is a step of a run.
	RuleAPIUnreachable      = "api.unreachable"        // rejection, status error, exit 2, no step: the address; nothing answers there, the answer is not the API's, or it ended before its document
	RuleAPITokenRefused     = "api.token.refused"      // rejection, status error, exit 2, no step: FYLGJA_API_TOKEN when it is unset, holds a byte no header can carry or ends in a blank and nothing was sent, else the address that answered 401
	RuleAPIVersionUnknown   = "api.version.unknown"    // rejection, status error, exit 2, no step: the address; it answered 404 naming the versions it serves, none of them this client's
	RuleAPITransferTooLarge = "api.transfer.too_large" // rejection, status error, exit 2, no step: the operation; a request over the server's bound (413), or a frame of the answer over the client's

	// 017, the DCIM reader and the scope a request names
	// (specs/017-dcim-reader/contracts/scope-and-commands.md, "The identifiers"). Each
	// comment gives the severity, the exit, the step, the object and when it fires. They
	// replace the generics' rules, retired with their last users
	// (TestTheGenericsRulesAreRetired); platform.unsupported stays for a CTM naming a
	// package this build lacks. No status, step or exit is new. 020 retired the scope's and
	// the schema check's (T035, TestTheOrchestratorsRulesAreRetired): the orchestrator's
	// adapter reads Infrahub and files them; the core keeps the read's rules a snapshot's
	// CTM is still held to.
	RulePlatformMissing       = "platform.missing"         // rejection, exit 1, read: the device; no platform, or a platform with no manufacturer, naming what the device carries
	RulePlatformUnmatched     = "platform.unmatched"       // rejection, exit 1, read: the device; no package matches the pair exactly, naming the pair and every package's pairs
	RuleOmitCableEnds         = "omit.cable.ends"          // info, exit 0, read: the cable; it has other than two ends
	RuleOmitCableEndpoint     = "omit.cable.endpoint"      // info, exit 0, read: the cable; an end is not on a physical port
	RuleOmitCableOutsideScope = "omit.cable.outside_scope" // info, exit 0, read: the cable; an end is outside the scope
	RuleOmitCableKind         = "omit.cable.kind"          // info, exit 0, read: the connector; it is not a DcimCable, naming its kind (T096)
	RuleCTMVersionUnsupported = "ctm.version.unsupported"  // rejection, exit 1, no step at twin compile --snapshot, resolve at twin create --snapshot <file>: the snapshot file; its inner CTM is of another version, naming both (018; a bare CTM is snapshot.version.unsupported)
	RulePSPMatchesMissing     = "psp.matches.missing"      // rejection, exit 1, verify: the package path; no match, or a pair with an empty name
	RulePSPMatchesDuplicate   = "psp.matches.duplicate"    // rejection, exit 1, verify: the package path; two packages name one pair, naming both packages and the pair; it also refuses the registry's load, and so serve and worker run at start

	// 018, snapshots, the core's one input (D-061;
	// specs/018-snapshots/contracts/snapshot-commands.md, "Identifiers"). Each comment
	// gives the severity, the exit, the step, the object and when it fires. A snapshot's
	// inner CTM keeps its own rules, ctm.version.unsupported at the snapshot file and
	// data.required.missing at the field prefixed ctm.
	// No status, step or exit is new. snapshot.flags.conflict retired at 020 (T035), with
	// the read's flags beside --snapshot.
	RuleSnapshotInvalid            = "snapshot.invalid"             // rejection, exit 1, no step (twin compile) or resolve (twin create --snapshot <file>): the field, or the file; the outer shape is not version 2's: an unknown key, ctm absent or not an object, probes absent, null or not a list, snapshot_id not 64 lowercase hex characters, observed_at not of the CTM's form or not the inner CTM's; or the inner CTM's observed_at not of that form, at ctm.envelope.observed_at; from 016, an element of probes not a probe of the declaration's contract, or refused by its rules, at probes[<i>].<field>
	RuleSnapshotVersionUnsupported = "snapshot.version.unsupported" // rejection, exit 1, no step or resolve: the file; snapshot_version is neither "1" nor "2", or absent, naming the version read, or that none was, and the two read (016: a "1" reads as a "2" with no probes)
	RuleSnapshotIDMismatch         = "snapshot.id.mismatch"         // rejection, exit 1, no step or resolve, compile for the store: the file, or the store path; a declared snapshot_id is not what the body hashes to, naming both, or an entry under the id hashes to another, or hashes to it and declares another, naming the path and both
	RuleSnapshotUnknown            = "snapshot.unknown"             // rejection, exit 1, resolve: the id; twin create --snapshot <id> names an id the store does not hold, naming the store's directory

	// 016, probes (D-064; specs/016-probes/data-model.md §12). Each comment gives the
	// severity, the exit, the step, the object and when it fires. The declaration's rules
	// read no CTM and fire at start for a --probes file, at resolve for the kind's objects
	// or a sent snapshot's elements; the placement's fire at compile, a plan's stage's
	// compile included, worded alike by validation and the compiler. None retired at 016
	// (R-27); at 020 (T035) the declaration file's two, probes.version.unsupported and
	// probes.invalid, and probe.kind.absent left with the read: the core reads no
	// declaration file and no kind, and a snapshot's probe that breaks a declaration's
	// shape is snapshot.invalid.
	RuleProbeNameInvalid            = "probe.name.invalid"             // rejection, exit 1, start or resolve: the probe; its name is not ^[a-z0-9][a-z0-9-]{0,23}$, naming the name read
	RuleProbeNameDuplicate          = "probe.name.duplicate"           // rejection, exit 1, start or resolve: the probe; two or more probes share the name, naming each position
	RuleProbeAddressInvalid         = "probe.address.invalid"          // rejection, exit 1, start or resolve: <probe>/<a|b>.address; not an address with a prefix length
	RuleProbeGatewayInvalid         = "probe.gateway.invalid"          // rejection, exit 1, start or resolve: <probe>/<a|b>.gateway; not an address, or one carrying a prefix length
	RuleProbeGatewayOutside         = "probe.gateway.outside"          // rejection, exit 1, start or resolve: <probe>/<a|b>.gateway; the gateway is not within the address's prefix, so the host's route could not be added
	RuleProbeFamilyMixed            = "probe.family.mixed"             // rejection, exit 1, start or resolve: the probe; its four addresses are not of one family, naming each family read
	RuleProbeAddressDuplicate       = "probe.address.duplicate"        // rejection, exit 1, start or resolve: <probe>/<a|b>.address; two endpoints of the list share one host address, naming both probes (R-20)
	RuleProbeFormatUnknown          = "probe.format.unknown"           // rejection, exit 1, compile (start or resolve where a registry is at hand): <probe>; no loaded probe package declares the format, naming the formats loaded
	RuleProbeDeviceUnknown          = "probe.device.unknown"           // rejection, exit 1, compile: <probe>/<a|b>; the CTM has no device of the endpoint's name
	RuleProbeInterfaceUnknown       = "probe.interface.unknown"        // rejection, exit 1, compile: <probe>/<a|b>; the device has no interface of the endpoint's name
	RuleProbeInterfaceCabled        = "probe.interface.cabled"         // rejection, exit 1, compile: <probe>/<a|b>; the interface is cabled, naming the link: a probe takes an uncabled port that is not mgmt_only
	RuleProbeInterfaceMgmtOnly      = "probe.interface.mgmt_only"      // rejection, exit 1, compile: <probe>/<a|b>; the interface is mgmt_only
	RuleProbePortTaken              = "probe.port.taken"               // rejection, exit 1, compile: <probe>/<a|b>; an earlier probe's endpoint takes the interface, naming it
	RuleProbeHostCollision          = "probe.host.collision"           // rejection, exit 1, compile: <probe>/<a|b>; the host's name, <probe>-<a|b>, is a device's or another host's
	RuleProbePackageSchema          = "probe.package.schema"           // rejection, exit 1 (2 at serve and worker run start), verify: the package path; the package is not of probes/probe.schema.json, naming the field
	RuleProbePackageVersionUnknown  = "probe.package.version.unknown"  // rejection, exit 1 (2 at start), verify: the package path; probe_version is not one this build reads, naming it and the one read
	RuleProbePackageFormatDuplicate = "probe.package.format.duplicate" // rejection, exit 1 (2 at start), verify: the package path; two packages of one origin declare one format, naming both
	RuleProbePackageTemplate        = "probe.package.template"         // rejection, exit 1 (2 at start), verify: the package path; a command template names a placeholder no field renders, naming the template and the placeholder
	RuleHostProbePackageMissing     = "host.probe_package.missing"     // rejection, exit 1, host_check: the package id; a host node's manifest probe.package.id has no probe package on the worker
	RuleFlowStartFailed             = "flow.start.failed"              // warning, exit 0, flows: <probe>; a host's flow could not be started, so its probe is not_started and the step goes on
	RuleFlowReadFailed              = "flow.read.failed"               // warning, exit 0, flows: <probe>; a host's flow could not be read, so its probe is not_read
	RuleVerifyBurst                 = "verify.burst"                   // rejection, exit 5 (status nonconforming), observe: <probe>; the burst's replies are fewer than its count, naming the replies, the count, the far host and its address

	// 020, the core's runs by identity (specs/020-core-orchestrator-split/data-model.md §1,
	// §11; research R-03, R-04). Each comment gives the severity, the exit, the step, the
	// object and when it fires. A detached start answers its identity and goes on; a run
	// is read or interrupted by its workflow id and run id. None replaces a rule: the
	// orchestrator's retired at T035: 014's stages, 015's rehearsal, 017's scope and schema
	// check, the read's flags and the stage's step rules (step.target.current,
	// step.stage.skipped), each now orchestrator/src/fylgja_orchestrator/documents/rules.py's.
	RuleRunDetached        = "run.detached"         // info, exit 0 (status ok), start: <workflow_id> <run_id>; under detach the run started and goes on, the message `run <workflow_id> <run_id> started; read it with fylgja run read`
	RuleRunUnknown         = "run.unknown"          // rejection, exit 1, no step: the identity, <workflow_id> <run_id> or the workflow id alone; run.read or run.interrupt names a run the workflow service does not hold, after the describe alone
	RuleRunCancelRequested = "run.cancel.requested" // info, exit 0, no step: the identity; run.interrupt asked the workflow service to cancel a running run, which ends as run.cancelled
	RuleRunEnded           = "run.ended"            // rejection, exit 1, no step: the identity; run.interrupt names a run that has already closed, naming its state
	RuleRunFlagsConflict   = "run.flags.conflict"   // rejection, exit 1, start: dry_run; detach beside dry_run on twin.create, twin.provision, twin.step or twin.destroy, before any guard, since a dry run starts no run to detach from
)

// Steps a finding can belong to, as contracts/findings.schema.json enumerates them. New
// at M2; findings from M1's operations carry none.
const (
	StepVerify    = "verify"
	StepStart     = "start"
	StepRead      = "read"
	StepCompile   = "compile"
	StepHostCheck = "host_check"
	StepStage     = "stage"
	StepDeploy    = "deploy"
	StepReadiness = "readiness"
	StepRecord    = "record"
	StepTeardown  = "teardown"
	StepUnstage   = "unstage"

	// M4: an earlier build's check's own steps. Inspect is a step run's too (M11), and
	// destroy and provision a rehearsal's children's (015). 019 retired M4's follow, the
	// step following began or stopped at.
	StepInspect   = "inspect"
	StepCompare   = "compare"
	StepDestroy   = "destroy"
	StepProvision = "provision"

	// M5: the push, between readiness and the record.
	StepPush = "push"

	// M10: the server's step between the flag guards and the run, where a reference
	// resolves (a stage's since 014), as verify is twin provision's. No workflow step.
	StepResolve = "resolve"

	// M11: the step's stage and reconcile, the first phase that touches the host.
	// A stage.failed keeps step stage inside
	// it, and M2's host-check findings keep host_check inside the compare phase.
	StepReconcile = "reconcile"

	// M12: where twin verify reads the twin and asserts intent against what it observed,
	// and where the step run's wait reports. verify
	// is M2's: twin provision's check of a bundle directory.
	StepObserve = "observe"

	// 016: the step's flows, started after its stage and read after its wait
	// (StartFlows, ReadFlows), between stage and reconcile in the step's order.
	StepFlows = "flows"
)

// Location points into a file, for findings about files rather than intent.
type Location struct {
	File string `json:"file"`
	Line int    `json:"line,omitempty"`
}

// Finding is one problem: what, where, how bad, and why.
type Finding struct {
	Severity Severity `json:"severity"`
	Rule     string   `json:"rule"`
	Object   string   `json:"object"`
	Message  string   `json:"message"`
	// Step names the provisioning step the finding belongs to. Empty for M1's
	// operations, which have no steps.
	Step     string    `json:"step,omitempty"`
	Location *Location `json:"location,omitempty"`
}

// List is a set of findings gathered in one pass.
type List []Finding

// Add appends a finding.
func (l *List) Add(sev Severity, rule, object, message string) {
	*l = append(*l, Finding{Severity: sev, Rule: rule, Object: object, Message: message})
}

// AddStep appends a finding that belongs to a provisioning step.
func (l *List) AddStep(sev Severity, step, rule, object, message string) {
	*l = append(*l, Finding{Severity: sev, Rule: rule, Object: object, Message: message, Step: step})
}

// AtStep returns a copy of the list with every finding placed at step, for findings a
// stage reports without one, such as M1's read and compile findings inside a run.
func (l List) AtStep(step string) List {
	out := make(List, len(l))
	for i, f := range l {
		f.Step = step
		out[i] = f
	}
	return out
}

// AddAt appends a finding that points into a file.
func (l *List) AddAt(sev Severity, rule, object, message, file string, line int) {
	loc := &Location{File: file, Line: line}
	*l = append(*l, Finding{Severity: sev, Rule: rule, Object: object, Message: message, Location: loc})
}

// Rejected reports whether any finding prevents output.
func (l List) Rejected() bool {
	for _, f := range l {
		if f.Severity == Rejection {
			return true
		}
	}
	return false
}

// Count returns how many findings carry the given severity.
func (l List) Count(sev Severity) int {
	n := 0
	for _, f := range l {
		if f.Severity == sev {
			n++
		}
	}
	return n
}
