workspace "Fylgja" "A walking twin of network intent." {

    !identifiers hierarchical
    !impliedRelationships false

    model {
        operator = person "Operator" "Owns the lab host and Infrahub; drives the twin through the two CLIs, fylgja and fylgja-cli."

        infrahub = softwareSystem "Infrahub" "The network source of truth. Holds intent on branches, versioned in time, in OpsMill's schema library's DCIM, which this repository vendors at 26336e9 (schema/dcim/), beside Fylgja's two kinds, the stage and the probe (schema/fylgja-stage.yaml, schema/fylgja-probe.yaml), both on the default branch; renders each device's configuration artifact." "External" {
            iserver = container "Infrahub server" "Infrahub's API at :8000: intent in the schema library's DCIM and artifacts on branches, proposed changes, stages and their threads, and the probes." "Python; Infrahub 1.11.2; GraphQL, REST" "External"
            taskWorker = container "Task worker" "Infrahub's own, two replicas, on its own Prefect, which publishes no port: renders the artifacts, and runs this repository's checks on a proposed change, fylgja-step and fylgja-twin, clients of the orchestrator's platform, which trigger a flow, wait for it and conclude from its document's status." "Python; Infrahub 1.11.2" "External"
        }
        artifacts = softwareSystem "Artifacts repository" "This repository, registered in Infrahub read-only: the artifacts template (.infrahub.yml, infrahub/templates/) that renders each device's configuration from the schema library's kinds (the DcimDevice by name, its DcimPlatform and manufacturer, its InterfacePhysical ports, their addresses and their DcimCables), and beside it the two checks (infrahub/checks/) that start a proposed change's plan and its rehearsal on the orchestrator's platform." "External"

        twin = softwareSystem "Walking twin" "Lab fylgja: a running containerlab topology of real network operating system images, built from one snapshot, and two synthesized hosts for each probe it declares." {
            node = container "NOS node" "One device of the twin, clab-fylgja-<node>: SR Linux or EOS, probed and read over gNMI and pushed its artifact." "Container"
            host = container "Probe host" "One end of a probe, clab-fylgja-<probe>-a or -b: a container of the probe package's image (linux, alpine:3.24.2 for ping) on an uncabled port of a device, addressed and routed by its exec lines; runs the step's flow and verify's burst, read by docker exec." "Container"
        }

        fylgja = softwareSystem "Fylgja" "Two deployables (D-065): the core compiles a snapshot into a deterministic bundle, boots it as a twin and pushes each device's production configuration; the orchestrator reads intent from Infrahub into that snapshot, resolves a proposed change's stages and rehearses them, and drives the core through its API alone." {
            group "The core" {
                cli = container "fylgja (client)" "Every command of the core's but the two roles: a twin from a snapshot, its step, show, verify and destroy, a run read or interrupted by its identity, the step between two snapshots, compile and validate. Sends one request to the API and prints what comes back." "Go, one static binary"
                server = container "fylgja serve" "The API's server, on the lab host, on loopback alone. Reads no source of truth: files the snapshots it is sent, compiles, checks the host, starts, follows, reads and interrupts runs, reads the twin. Loads the platform packages (psp/) and the probe packages (probes/), embedded, with the override directory's." "Go, the same binary; HTTP on 127.0.0.1:7650" {
                    handlers = component "server" "The handlers: each command's logic behind POST /v1/<noun>/<verb>; every compile through server.Compile (compile.go)." "internal/server"
                    api = component "api" "The wire: paths, frames, requests, problems, bounds. The client's side links it too." "internal/api"
                    provisionClient = component "provision" "Starts, follows, reads and cancels runs on the workflow service; a run started detached or read by its identity." "internal/provision"
                    lab = component "lab" "Host-bound code: containerlab, the host check, the dry run, twin.json." "internal/lab"
                    verify = component "verify" "Assertions derived from the manifest; one read of the twin." "internal/verify"
                    validate = component "validate" "Completeness and intent rules on the CTM." "internal/validate"
                    step = component "step" "The pure step between two bundles; the push plan." "internal/step"
                    compiler = component "compiler" "CTM + PSPs -> bundle. Pure. Its manifest is what the others read." "internal/compiler"
                    bundle = component "bundle" "The bundle format, canonical hashing, the store." "internal/bundle"
                    snapshot = component "snapshot" "The snapshot: the document, its id, its validation, the store." "internal/snapshot"
                    psp = component "psp" "Platform support packages: loading and validation." "internal/psp"
                    probe = component "probe" "The probe declaration and its rules, the probe packages (loading, validation, their templates rendered) and the pure reading of a ping's output." "internal/probe"
                    findings = component "findings" "Findings, rules, the findings document, exit codes. The client's side links it too." "internal/findings"
                }
                worker = container "fylgja worker run" "The lab-host worker: runs the three workflows and the host-bound activities. Loads the platform packages (psp/) and the probe packages (probes/), embedded, with the override directory's." "Go, the same binary" {
                    workflows = component "provision" "The three workflows, provision, step and destroy, and the worker's registration. The provision and the step take a snapshot id and a bundle id the server compiled; none reads a source of truth." "internal/provision"
                    wlab = component "lab" "The host-bound activities: deploy, readiness, push, reconcile, record, the wait, and a step's flows, started before its first change and read after its wait." "internal/lab"
                    wverify = component "verify" "The readers and the wait." "internal/verify"
                    wire = component "lab/wire" "Activity names and the payloads crossing the task queue." "internal/lab/wire"
                    wprobe = component "probe" "The probe packages a host's plan is read from, and the pure reading of a ping's output." "internal/probe"
                }
                temporal = container "Workflow service" "Durable execution: run history." "Temporal"
                store = container "Bundle store" "<state root>/bundles/<bundle_id>/: every bundle compiled or provisioned." "Files" "Files"
                snapshotStore = container "Snapshot store" "<state root>/snapshots/<snapshot_id>.json: every snapshot sent, each kept as first filed." "Files" "Files"
                twindir = container "Twin directory" "<state root>/twin/: the staged bundle, containerlab's directory, twin.json 12, which names no stage." "Files" "Files"
                clab = container "containerlab" "Deploys, reconciles, inspects and destroys lab fylgja." "CLI"
            }
            group "The orchestrator" {
                orchestrator = container "fylgja-orchestrator" "The orchestrator's package, fylgja_orchestrator: fylgja-cli, which runs a flow in its own process, and the runner, fylgja-orchestrator serve, which serves the six flows to the platform. Reads Infrahub through its adapter, takes and files each snapshot, drives the core through the API alone, posts a rehearsal's report." "Python 3.14; Prefect 3.8.8; infrahub-sdk 1.23.2" {
                    ocli = component "cli" "fylgja-cli: intent read, stage list, stage plan, twin create, twin step, twin rehearse and schema check, each but stage list its flow run in this process; prints and exits as fylgja did." "cli.py"
                    oserve = component "serve" "The runner: the six flows' deployments main, each entrypoint its module path, served to the platform." "serve.py"
                    flows = component "flows" "intent-read, twin-create, twin-step, stage-plan, twin-rehearse and schema-check; each files its findings document as its run's artifact and logs its out lines." "flows/"
                    adapter = component "adapters/infrahub" "The Infrahub adapter, ported from the Go reader to the same bytes: the schema library's DCIM at 26336e9 by the mapping, conformance, the stages, stamps and intent events, the probes, the snapshot and its id; posts the report as a thread." "adapters/infrahub/"
                    documents = component "documents" "The stages, plan and rehearsal blocks, their text and markdown, the deadline, the findings document and every rule the orchestrator files." "documents/"
                    coreClient = component "core" "The core's client: POST /v1/<noun>/<verb> with the API's token; every run detached, then run.read every 2 s." "core.py"
                    record = component "record" "The orchestrator's store, snapshots/<id>.json, and its record, twin.json, of the twin it last drove, trusted while twin show names its snapshot." "record.py"
                }
                platform = container "Orchestrator's platform" "Prefect's open-source server, apart from the one Infrahub runs: the six deployments, their runs, each run's artifact fylgja-findings and its log; basic authentication." "Prefect 3.8.8; SQLite; HTTP on the Docker bridge, :4200"
                orchStore = container "Orchestrator's store" "<orchestrator root>/: snapshots/<snapshot_id>.json, every snapshot the adapter took, each kept as first filed; twin.json, the record of the twin it last drove." "Files" "Files"
            }
        }

        operator -> fylgja "Runs commands"
        operator -> infrahub "Edits intent; opens proposed changes and marks stages"
        fylgja -> infrahub "Reads intent, artifacts, stages and probes; posts a rehearsal's report" "GraphQL, REST"
        fylgja -> twin "Boots, probes, pushes, reads"
        infrahub -> artifacts "Clones; renders the template; runs the checks"
        infrahub -> fylgja "Runs fylgja-step and fylgja-twin, which start the plan's flow and the rehearsal's on the orchestrator's platform" "HTTP, basic auth, plaintext"

        operator -> fylgja.cli "Runs the core's commands"
        operator -> fylgja.orchestrator "Runs fylgja-cli, for a branch, a stage or a rehearsal"
        fylgja.cli -> fylgja.server "POST /v1/<noun>/<verb>; bearer token" "HTTP, NDJSON"
        fylgja.orchestrator -> fylgja.server "Sends each snapshot as a file; starts every run detached, then reads it by its identity" "HTTP on loopback, bearer token, NDJSON"
        fylgja.orchestrator -> infrahub "Reads intent, artifacts, stages and probes; posts a rehearsal's report as a thread" "GraphQL, REST"
        fylgja.orchestrator -> infrahub.iserver "Reads intent, artifacts, stages and probes; posts a rehearsal's report as a thread" "GraphQL, REST"
        fylgja.orchestrator -> fylgja.platform "Serves the deployments; records each flow run, its artifact and its log" "HTTP, basic auth"
        fylgja.orchestrator -> fylgja.orchStore "Files snapshots; writes and reads the record"
        infrahub -> fylgja.platform "Runs fylgja-step and fylgja-twin in its task worker, which trigger stage-plan and twin-rehearse and read each run's document" "HTTP over the Docker bridge, basic auth, plaintext"
        infrahub.taskWorker -> fylgja.platform "fylgja-step triggers stage-plan; fylgja-twin twin-rehearse; each reads the run's state, artifact and log, and cancels it at its deadline" "HTTP over the Docker bridge, basic auth, plaintext"
        infrahub.taskWorker -> infrahub.iserver "Reads the proposed change; concludes each check" "GraphQL"
        fylgja.server -> fylgja.temporal "Starts, follows, reads, cancels runs" "gRPC"
        fylgja.server -> fylgja.store "Files and reads bundles"
        fylgja.server -> fylgja.snapshotStore "Files and reads snapshots"
        fylgja.server -> fylgja.twindir "Reads the record and the staged bundle"
        fylgja.server -> fylgja.clab "Inspects; dry runs"
        fylgja.server -> twin.node "Reads for verify" "gNMI"
        fylgja.server -> twin.host "Runs each probe's burst for verify" "docker exec"
        fylgja.worker -> fylgja.temporal "Polls task queue fylgja" "gRPC"
        fylgja.worker -> fylgja.store "Files and reads bundles"
        fylgja.worker -> fylgja.twindir "Stages, records"
        fylgja.worker -> fylgja.clab "Deploys, reconciles, destroys"
        fylgja.worker -> twin.node "Probes; pushes the artifact; waits" "gNMI; JSON-RPC or eAPI"
        fylgja.worker -> twin.host "Awaits its address; starts and reads a step's flow; runs the burst in the wait" "docker exec"
        fylgja.clab -> twin.node "Creates and cables"
        fylgja.clab -> twin.host "Creates, cables to its device's port and addresses"

        fylgja.server.handlers -> fylgja.server.api "Decodes requests; writes frames"
        fylgja.server.handlers -> fylgja.server.findings "Words every refusal; writes the document"
        fylgja.server.handlers -> fylgja.server.psp "Loads the packages"
        fylgja.server.handlers -> fylgja.server.probe "Loads the probe packages"
        fylgja.server.handlers -> fylgja.server.step "Diffs; plans the push"
        fylgja.server.handlers -> fylgja.server.bundle "Identifies, verifies and files bundles"
        fylgja.server.handlers -> fylgja.server.snapshot "Validates and files the snapshots sent"
        fylgja.server.handlers -> fylgja.server.validate "Holds a sent snapshot's CTM to the rules that read no package; validates before each compile"
        fylgja.server.handlers -> fylgja.server.compiler "Compiles; reads manifests"
        fylgja.server.handlers -> fylgja.server.lab "Host check, inspect, dry run"
        fylgja.server.handlers -> fylgja.server.verify "Reads the twin"
        fylgja.server.handlers -> fylgja.server.provisionClient "Starts, follows, reads and interrupts runs"
        fylgja.server.api -> fylgja.server.findings "Carries the document"
        fylgja.server.lab -> fylgja.server.verify "Reads through its readers"
        fylgja.server.lab -> fylgja.server.bundle "Verifies the staged bundle"
        fylgja.server.lab -> fylgja.server.compiler "Reads the manifest"
        fylgja.server.verify -> fylgja.server.compiler "Derives from the manifest"
        fylgja.server.validate -> fylgja.server.compiler "Surveys each device"
        fylgja.server.step -> fylgja.server.compiler "Compares two manifests"
        fylgja.server.compiler -> fylgja.server.psp "Applies the mapping profile"
        fylgja.server.compiler -> fylgja.server.probe "Places each probe's hosts; renders them from their package"
        fylgja.server.validate -> fylgja.server.probe "Places the probes, refusing as the compiler does"
        fylgja.server.snapshot -> fylgja.server.probe "Holds each declaration to its rules"
        fylgja.server.verify -> fylgja.server.probe "Renders each burst from its package"
        fylgja.server.lab -> fylgja.server.probe "Plans each host from its package; reads the burst"
        fylgja.server.lab -> twin.host "Runs each probe's burst for verify" "docker exec"

        fylgja.worker.workflows -> fylgja.worker.wire "Schedules activities by name"
        fylgja.worker.workflows -> fylgja.worker.wlab "Registers the host-bound activities"
        fylgja.worker.wlab -> fylgja.worker.wire "Takes and returns the payloads"
        fylgja.worker.wlab -> fylgja.worker.wverify "VerifyTwin waits"
        fylgja.worker.wverify -> fylgja.worker.wire "Reads the record's types"
        fylgja.worker.wverify -> fylgja.worker.wprobe "Renders each burst from its package"
        fylgja.worker.wlab -> fylgja.worker.wprobe "Plans each host from its package; renders and reads its flow and its burst"
        fylgja.worker.wlab -> twin.host "Awaits its address; starts and reads a step's flow; runs the burst in the wait" "docker exec"
        fylgja.worker.workflows -> fylgja.worker.wprobe "Names the probe packages in the start-up report"

        fylgja.orchestrator.ocli -> fylgja.orchestrator.flows "Runs a flow in its own process; stage list's plain body"
        fylgja.orchestrator.ocli -> fylgja.platform "Records the run when PREFECT_API_URL names it, else on an ephemeral server" "HTTP, basic auth"
        fylgja.orchestrator.oserve -> fylgja.orchestrator.flows "Serves the six as deployments main"
        fylgja.orchestrator.oserve -> fylgja.platform "Serves the deployments; takes their runs" "HTTP, basic auth"
        fylgja.orchestrator.flows -> fylgja.orchestrator.adapter "Reads, resolves and lists stages, checks the schema, takes snapshots, posts the report"
        fylgja.orchestrator.flows -> fylgja.orchestrator.documents "Renders the stages, the plan and the rehearsal; words the findings document"
        fylgja.orchestrator.flows -> fylgja.orchestrator.coreClient "Compiles, diffs, creates, steps, verifies, destroys and shows through the core"
        fylgja.orchestrator.flows -> fylgja.orchestrator.record "Files snapshots; follows the twin in the record; asks after a dead rehearsal's run"
        fylgja.orchestrator.flows -> fylgja.platform "Files the document as the run's artifact; logs the out lines" "HTTP, basic auth"
        fylgja.orchestrator.adapter -> fylgja.orchestrator.documents "Words its findings by the rules"
        fylgja.orchestrator.adapter -> infrahub.iserver "Reads intent, artifacts, stages, stamps, events and probes; posts the report" "GraphQL, REST"
        fylgja.orchestrator.coreClient -> fylgja.server "POST /v1/<noun>/<verb>: every run detached, then run.read" "HTTP on loopback, bearer token"
        fylgja.orchestrator.record -> fylgja.orchStore "Files and reads"
        fylgja.orchestrator.record -> fylgja.platform "Reads a flow run's state for the reclaim" "HTTP, basic auth"

        live = deploymentEnvironment "Lab" {
            deploymentNode "Operator's machine" "FYLGJA_API_TOKEN; FYLGJA_API_ADDRESS, or an SSH tunnel to the lab host" "" {
                containerInstance fylgja.cli
            }
            deploymentNode "Lab host" "Ubuntu, Docker, containerlab, the NOS images and the probe packages' images; five processes" "" {
                deploymentNode "fylgja serve" "127.0.0.1:7650 alone; FYLGJA_API_TOKEN, both node logins; no Infrahub variable" "process" {
                    containerInstance fylgja.server
                }
                deploymentNode "fylgja worker run" "both node logins; no API token" "process" {
                    containerInstance fylgja.worker
                }
                deploymentNode "temporal server start-dev" ":7233; UI :8233" "process" {
                    containerInstance fylgja.temporal
                }
                deploymentNode "prefect server start" "172.17.0.1:4200 on docker0, the Docker bridge, basic auth in plaintext; PREFECT_HOME local/orchestrator/prefect" "process" {
                    containerInstance fylgja.platform
                }
                deploymentNode "fylgja-orchestrator serve" "the runner; INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN, FYLGJA_API_TOKEN, PREFECT_API_URL and PREFECT_API_AUTH_STRING, FYLGJA_DEFAULT_SCOPE" "process" {
                    containerInstance fylgja.orchestrator
                }
                deploymentNode "State root" "FYLGJA_STATE_ROOT: bundles/, snapshots/, twin/" "directory" {
                    containerInstance fylgja.store
                    containerInstance fylgja.snapshotStore
                    containerInstance fylgja.twindir
                }
                deploymentNode "Orchestrator root" "FYLGJA_ORCHESTRATOR_ROOT: snapshots/, twin.json; prefect/, the platform's home" "directory" {
                    containerInstance fylgja.orchStore
                }
                containerInstance fylgja.clab
                deploymentNode "Docker" "privileged containers" "" {
                    deploymentNode "Lab fylgja" "clab-fylgja-<node>; gNMI :57400 (TLS) or :6030; JSON-RPC or eAPI :443; each probe's hosts, clab-fylgja-<probe>-a and -b, reached by docker exec" "" {
                        containerInstance twin.node
                        containerInstance twin.host
                    }
                }
            }
            deploymentNode "Infrahub host" "Docker Compose, project fylgja-infrahub; the lab host, for its task workers to reach the orchestrator's platform on the bridge" "" {
                containerInstance infrahub.iserver
                deploymentNode "task-worker" "host.docker.internal:4200, docker0's address by the Compose override's host-gateway entry; FYLGJA_ORCHESTRATOR_ADDRESS and FYLGJA_ORCHESTRATOR_AUTH from the override; no API token" "container" "" 2 {
                    containerInstance infrahub.taskWorker
                }
            }
        }
    }

    views {
        systemContext fylgja "Context" "The operator, Fylgja's two deployables, Infrahub, the artifacts repository and the walking twin." {
            include *
            include artifacts
            autoLayout lr
        }
        container fylgja "Containers" "The core's processes and files and the orchestrator's on the lab host, and what each reaches." {
            include *
            include twin.node
            include twin.host
            autoLayout lr
        }
        component fylgja.server "ServerComponents" "The packages the API's server runs. The client's side of the boundary is internal/cli, which links api, findings and tree alone." {
            include *
            autoLayout tb
        }
        component fylgja.worker "WorkerComponents" "The packages the worker runs." {
            include *
            autoLayout tb
        }
        component fylgja.orchestrator "OrchestratorComponents" "The orchestrator's modules, run by fylgja-cli or by the runner, and what each reaches." {
            include *
            autoLayout tb
        }
        deployment * live "Deployment" "Where each role runs, its ports and the credentials it holds." {
            include *
            autoLayout lr
        }
        properties {
            "c4plantuml.tags" "true"
        }
        styles {
            element "Element" {
                color #ffffff
            }
            element "Software System" {
                background #1168bd
            }
            element "Container" {
                background #438dd5
            }
            element "Component" {
                background #85bbf0
                color #000000
            }
            element "Person" {
                shape person
                background #08427b
                color #ffffff
            }
            element "External" {
                background #999999
                color #ffffff
            }
            element "Files" {
                shape cylinder
            }
            relationship "Relationship" {
                style solid
            }
        }
    }
}
