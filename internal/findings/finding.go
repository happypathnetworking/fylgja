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
	// Conformance, against Infrahub schema metadata.
	RuleContractVersionMismatch = "contract.version.mismatch"
	RuleContractNodeMissing     = "contract.node.missing"

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
	RuleAtPrecision = "intent.at.precision"

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

	// M4, following (contracts/cli.md). Each comment
	// gives the step the finding belongs to and when it fires.

	RuleFollowIntervalInvalid  = "follow.interval.invalid"  // start: --interval unparseable or below the floor, before any connection (exit 2)
	RuleFollowFlagsConflict    = "follow.flags.conflict"    // start: --interval given with --at or --no-follow (exit 2)
	RuleFollowStartFailed      = "follow.start.failed"      // follow: a warning; the run ended ready but schedule fylgja-follow could not be created
	RuleFollowStopFailed       = "follow.stop.failed"       // follow: schedule fylgja-follow could not be deleted; a destroy or a run's stop step refuses to go on
	RuleCheckSkipped           = "check.skipped"            // inspect: a warning; nothing to compare against, another branch, a twin that does not follow, or a run in flight
	RuleRebuildFailed          = "rebuild.failed"           // destroy or provision: a rebuild's child did not end clean or ready; following stops
	RuleFollowStopped          = "follow.stopped"           // follow: a warning; following stopped after a failed rebuild
	RuleShowServiceUnreachable = "show.service.unreachable" // no step: a warning; twin show could not reach the workflow service (exit 0)

	// M5, configuration (contracts/cli.md). Each
	// comment gives the step the finding belongs to, the object it names, and when it fires.

	// Conformance and the read's artifact selection. Every device is decided before any
	// content is fetched, so one read reports every device's refusal (Constitution III).
	RuleArtifactMissing                = "artifact.missing"                  // read, and compile from validation: the device; no artifact of the package's name on it (at `at` when pinned; names `at`), or a CTM device without one
	RuleArtifactAmbiguous              = "artifact.ambiguous"                // read: the device; more than one artifact of that name; names the count and each checksum
	RuleArtifactNotReady               = "artifact.not_ready"                // read: the device; status is not Ready, or there is no storage object yet; names the state and that Fylgja never regenerates
	RuleArtifactContentTypeUnsupported = "artifact.content_type.unsupported" // read: the device; the content type is not one the package accepts, or the bytes are not text
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

	// 014, a proposed change's stages (D-045, D-046), in place of M10's rules: seven of
	// them renamed, five new, and M10's reversed-time warning dropped, since marks are
	// ordered by their at. Each comment gives the severity, the exit, the step, the
	// object and when it fires. The syntax and flag guards are at start, before any
	// connection; the resolution's refusals at resolve, before any run and before any
	// branch's intent is read (none in intent read, whose operations carry no step); the
	// listing's two warnings at none, stage.twin.moved on twin step too. stage.failed above
	// is M2's staging step, not a stage.
	RuleStageRefInvalid          = "stage.ref.invalid"            // rejection, exit 2, start: the text given; --stage is not <branch>/<label>, or stage list's or stage plan's --branch is not a branch
	RuleStageFlagsConflict       = "stage.flags.conflict"         // rejection, exit 2, start: the conflicting flag; --stage beside --branch, --at or --interval, the first found in that order
	RuleStageKindAbsent          = "stage.kind.absent"            // rejection, exit 1, resolve: FylgjaStage; the default branch's schema lacks the kind, an attribute or the relationship this build reads, or CoreProposedChange lacks the extension, naming schema/fylgja-stage.yaml
	RuleStageUnknown             = "stage.unknown"                // rejection, exit 1, resolve: the branch or <branch>/<label>; no open proposed change has the source branch, naming the branches with one; the branch is gone (in stage list a warning, the stages still listed); or the proposed change has no stage of the label, naming its stages
	RuleStageDuplicate           = "stage.duplicate"              // rejection, exit 1, resolve: <branch>/<label>; two or more marks of one proposed change share the label, naming every id and choosing none
	RuleStageAtUnresolved        = "stage.at.unresolved"          // rejection, exit 1, resolve: <branch>/<label>; a given as_of later than the server's clock, or a stage with no stamp at all to name its at (in stage list a warning, the row listed with no at)
	RuleStageAtBeforeBranchPoint = "stage.at.before_branch_point" // rejection, exit 1, resolve: <branch>/<label>; the stage's at is before the branch's branched_from, saying a rebase did it when the branch was created before the at
	RuleStageLabelReserved       = "stage.label.reserved"         // rejection, exit 1, resolve: <branch>/<label>; a mark is labelled head or branch-point, which name the derived stages
	RuleStageArtifactStale       = "stage.artifact.stale"         // rejection, exit 1, resolve: the device; at the stage's at, the device's intent, written by its own stamps or by an intent event naming it or one of its interfaces (D-048), is newer than its generation stamp (D-046), naming both remedies
	RuleStageOrphaned            = "stage.orphaned"               // warning, exit 0, no step: the stage's id; a stage its proposed change no longer names, removed from its fylgja_stages (D-047)
	RuleStageMainMoved           = "stage.main.moved"             // warning, exit 0, resolve: the branch; main's latest stamp is later than the branch's branched_from, and nothing is refused
	RuleStageTwinMoved           = "stage.twin.moved"             // warning, exit 0, no step: the record's <branch>/<label>; the record's stage no longer resolves to the record's (branch, at), or is gone; stage list files it beside the record's row, twin step beside its target's findings

	// M11, stepping (contracts/cli.md). Each
	// comment gives the severity, the exit, the step, the object and when it fires. The
	// CLI's refusals before any run are at resolve (the twin, the target, the from
	// bundle) and compare (the plan's rules); the run's second locks reword them at
	// inspect and compare. A run in flight is M2's run.in_flight, not a new rule.
	RuleStepTwinUnsteppable   = "step.twin.unsteppable"   // rejection, exit 1, resolve (inspect from the run's second lock): lab fylgja, M3's object, or the record's bundle_id; no twin, an orphan, an unreadable record, a record without its lab, a record of twin.json 5 or earlier, or a record naming no stage
	RuleStepTwinDiverged      = "step.twin.diverged"      // rejection, exit 1, resolve (inspect): the record's bundle_id; the record's state is diverged, which only twin destroy clears
	RuleStepTargetForeign     = "step.target.foreign"     // rejection, exit 1, resolve: the given reference; --stage names another branch than the record's, or another proposed change on it
	RuleStepTargetUnknown     = "step.target.unknown"     // rejection, exit 1, resolve: the record's stage or the reference; the record's label is gone, no stage follows it, or the proposed change has not the one given
	RuleStepTargetCurrent     = "step.target.current"     // rejection, exit 1, resolve: the reference; the target resolves to the record's own (branch, at)
	RuleStepBundleMissing     = "step.bundle.missing"     // rejection, exit 1, resolve: the record's bundle_id; the store does not hold the bundle the twin was built from
	RuleStepPackageMerge      = "step.package.merge"      // rejection, exit 1, compare: the package id; a node of either bundle runs a package whose mode is merge, which has no reset
	RuleStepNodeUnapplied     = "step.node.unapplied"     // rejection, exit 1, compare: the node; the step changes its image, platform or psp and containerlab's plan does not recreate it, or adds it and the plan does not create it
	RuleStepRestartRequired   = "step.restart.required"   // rejection, exit 1, compare: the nodes; containerlab's plan restarts or recreates a node and --allow-restart was not given
	RuleStepDiverged          = "step.diverged"           // rejection, exit 4 (status diverged), the phase's step: the run id; the step failed or was cancelled from the stage on, and the twin is up and diverged
	RuleStepStageSkipped      = "step.stage.skipped"      // warning, exit 0, resolve: the target; the proposed change has marks strictly between the record's stage and the target, either direction (014: M11's step.sequence.skipped, renamed)
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

	// 015, a proposed change rehearsed on a twin (D-051;
	// specs/015-proposed-change-rehearsal/contracts/rehearse-command.md). Each comment
	// gives the severity, the exit, the step, the object and when it fires. The refusals
	// before the start keep their identifiers (stage.*, run.in_flight, host.*), an
	// interrupt is run.cancelled and a destroy that leaves something cleanup.incomplete;
	// the baseline's and each stage's verify findings are verify's, filed as warnings
	// with the stage prefixed to their object, so none of those is a new rule. No step is
	// added.
	RuleRehearsalDeadlineUnfit  = "rehearsal.deadline.unfit"  // rejection, exit 1, start: the branch; the stages' budgets summed exceed the ceiling, naming the time the stages need and the ceiling
	RuleRehearsalTwinReclaimed  = "rehearsal.twin.reclaimed"  // warning, exit 0, destroy: the dead rehearsal's run id; the twin of a rehearsal whose run was no longer running was destroyed before the start, naming what was removed
	RuleRehearsalStepsNone      = "rehearsal.steps.none"      // warning, exit 0, resolve: the one compiled stage's <branch>/<label>; it was built, verified and destroyed, and no step was rehearsed
	RuleRehearsalStageFailed    = "rehearsal.stage.failed"    // rejection, exit 5 (status nonconforming), the diverged phase's step, or observe for a finding: the stage's <branch>/<label>; the step diverged, naming the phase and the nodes landed and not, or its wait holds a finding the baseline's did not, naming it by rule and object
	RuleRehearsalStageError     = "rehearsal.stage.error"     // rejection, exit 2, the step reached: the stage's <branch>/<label>; its step could not run, was rejected by its locks or cancelled before its stage, or its wait could not complete
	RuleRehearsalBaselineFailed = "rehearsal.baseline.failed" // rejection, exit 3 (status failed), provision: the baseline's <branch>/<label>; the baseline could not be built, and the provision child's own findings stand beside it
	RuleRehearsalDeadlineCut    = "rehearsal.deadline.cut"    // rejection, exit 2, the step reached: the <branch>/<label> of the stage in progress; the deadline passed, naming each finished stage's time and the deadline
	RuleRehearsalStageMoved     = "rehearsal.stage.moved"     // warning, exit 0, resolve: the stage's <branch>/<label>; after the run, a rehearsed stage, the head included, no longer resolves to the (branch, at) it was rehearsed at, or is gone
	RuleRehearsalChangeClosed   = "rehearsal.change.closed"   // warning, exit 0, resolve: the branch; after the run, the proposed change is no longer open

	// 017, the DCIM reader and the scope a request names
	// (specs/017-dcim-reader/contracts/scope-and-commands.md, "The identifiers"). Each
	// comment gives the severity, the exit, the step, the object and when it fires. They
	// stand beside the generics' rules until the tasks that remove those rules' last users;
	// platform.unsupported stays for a CTM naming a package this build lacks. No status,
	// step or exit is new.
	RuleScopeInvalid          = "scope.invalid"            // rejection, exit 2, start: the value given; --scope is not tag:<name>, an empty value included; before any connection, after --branch's and --stage's guards
	RuleScopeUnset            = "scope.unset"              // rejection, exit 2, start: FYLGJA_DEFAULT_SCOPE; no --scope and the server has no default; before any connection
	RuleScopeEmpty            = "scope.empty"              // rejection, exit 1, read (none on intent.read; resolve for a stage's branch point): the scope; the device query answered 0 on the branch at the at, and the rehearsal and fylgja-step pass over a branch point refused by this rule alone
	RuleSchemaKindMissing     = "schema.kind.missing"      // rejection, exit 1, read (none on schema.check): the kind; the branch's schema lacks a kind the mapping reads
	RuleSchemaFieldMissing    = "schema.field.missing"     // rejection, exit 1, read: <kind>.<field>; the kind lacks a field the mapping reads
	RuleSchemaFieldMismatch   = "schema.field.mismatch"    // rejection, exit 1, read: <kind>.<field>; the field's kind, cardinality, peer or optionality is not the table's, naming both
	RuleSchemaChoiceMissing   = "schema.choice.missing"    // rejection, exit 1, read: <kind>.<field>; the dropdown lacks management (role) or disabled (status)
	RuleSchemaUsedByMissing   = "schema.used_by.missing"   // rejection, exit 1, read: the generic; the generic is not implemented by the kind the mapping expects
	RulePlatformMissing       = "platform.missing"         // rejection, exit 1, read: the device; no platform, or a platform with no manufacturer, naming what the device carries
	RulePlatformUnmatched     = "platform.unmatched"       // rejection, exit 1, read: the device; no package matches the pair exactly, naming the pair and every package's pairs
	RuleOmitCableEnds         = "omit.cable.ends"          // info, exit 0, read: the cable; it has other than two ends
	RuleOmitCableEndpoint     = "omit.cable.endpoint"      // info, exit 0, read: the cable; an end is not on a physical port
	RuleOmitCableOutsideScope = "omit.cable.outside_scope" // info, exit 0, read: the cable; an end is outside the scope
	RuleCTMVersionUnsupported = "ctm.version.unsupported"  // rejection, exit 1, no step: the CTM file; twin compile was given a CTM of another version, naming both
	RulePSPMatchesMissing     = "psp.matches.missing"      // rejection, exit 1, verify: the package path; no match, or a pair with an empty name
	RulePSPMatchesDuplicate   = "psp.matches.duplicate"    // rejection, exit 1, verify: the package path; two packages name one pair, naming both packages and the pair; it also refuses the registry's load, and so serve and worker run at start
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

	// M4: a check's own steps, and the step following begins or stops at.
	StepInspect   = "inspect"
	StepCompare   = "compare"
	StepDestroy   = "destroy"
	StepProvision = "provision"
	StepFollow    = "follow"

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
