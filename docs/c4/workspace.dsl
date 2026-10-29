workspace "Fylgja" "A walking twin of network intent." {

    !identifiers hierarchical
    !impliedRelationships false

    model {
        operator = person "Operator" "Owns the lab host and Infrahub; drives the twin through the CLI."

        infrahub = softwareSystem "Infrahub" "The network source of truth. Holds intent on branches, versioned in time, in OpsMill's schema library's DCIM, which this repository vendors at 26336e9 (schema/dcim/), beside Fylgja's two kinds, the stage and the probe (schema/fylgja-stage.yaml, schema/fylgja-probe.yaml), both on the default branch; renders each device's configuration artifact." "External" {
            iserver = container "Infrahub server" "Infrahub's API at :8000: intent in the schema library's DCIM and artifacts on branches, proposed changes, stages and their comments, and the probes." "Python; Infrahub 1.11.2; GraphQL, REST" "External"
            taskWorker = container "Task worker" "Infrahub's own, two replicas: renders the artifacts, and runs this repository's checks on a proposed change, fylgja-step and fylgja-twin, clients of Fylgja's API; fylgja-twin posts the rehearsal's report as one comment in a new thread on the proposed change, which its overview shows." "Python; Infrahub 1.11.2" "External"
        }
        artifacts = softwareSystem "Artifacts repository" "This repository, registered in Infrahub read-only: the artifacts template (.infrahub.yml, infrahub/templates/) that renders each device's configuration from the schema library's kinds (the DcimDevice by name, its DcimPlatform and manufacturer, its InterfacePhysical ports, their addresses and their DcimCables), and beside it the two checks (infrahub/checks/) that ask Fylgja for a proposed change's plan and its rehearsal." "External"

        twin = softwareSystem "Walking twin" "Lab fylgja: a running containerlab topology of real network operating system images, built from one snapshot, and two synthesized hosts for each probe it declares." {
            node = container "NOS node" "One device of the twin, clab-fylgja-<node>: SR Linux or EOS, probed and read over gNMI and pushed its artifact." "Container"
            host = container "Probe host" "One end of a probe, clab-fylgja-<probe>-a or -b: a container of the probe package's image (linux, alpine:3.24.2 for ping) on an uncabled port of a device, addressed and routed by its exec lines; runs the step's flow and verify's burst, read by docker exec." "Container"
        }

        fylgja = softwareSystem "Fylgja" "Reads intent from Infrahub, compiles it into a deterministic bundle, boots it as a twin and pushes each device's production configuration." {
            cli = container "fylgja (client)" "Every command but the two roles, twin rehearse among them. Sends one request to the API and prints what comes back; twin rehearse --markdown prints the report as the markdown the server rendered." "Go, one static binary"
            server = container "fylgja serve" "The API's server, on the lab host. Reads Infrahub and a request's probes, takes and files each read's snapshot, compiles, checks the host, starts and follows runs, reads the twin. Loads the platform packages (psp/) and the probe packages (probes/), embedded, with the override directory's." "Go, the same binary; HTTP on 127.0.0.1:7650 and on the Docker bridge" {
                handlers = component "server" "The handlers: each command's logic behind POST /v1/<noun>/<verb>." "internal/server"
                api = component "api" "The wire: paths, frames, requests, problems, bounds. The client's side links it too." "internal/api"
                stage = component "stage" "The read and compile pipelines, the server's alone." "internal/stage"
                stages = component "stages" "A proposed change's stages: references, resolution, staleness, list, plan and the step's target." "internal/stages"
                provisionClient = component "provision" "Starts, follows and cancels runs on the workflow service." "internal/provision"
                lab = component "lab" "Host-bound code: containerlab, the host check, the dry run, twin.json." "internal/lab"
                verify = component "verify" "Assertions derived from the manifest; one read of the twin." "internal/verify"
                intent = component "intent" "The Infrahub reader of the schema library's DCIM at 26336e9, by the mapping (mapping.go): the scope's devices by their tag, then their physical ports by the devices' ids, two queries, each cable through its port's connector; conformance, the mapping's table of kinds and fields against the branch's schema, every finding naming the commit; artifacts, proposed changes, stages, stamps, intent events." "internal/intent"
                validate = component "validate" "Completeness and intent rules on the CTM." "internal/validate"
                step = component "step" "The pure step between two bundles; the push plan." "internal/step"
                rehearsal = component "rehearsal" "A rehearsal's pure rules and renderings: the deadline, the verdict, the report and its markdown." "internal/rehearsal"
                compiler = component "compiler" "CTM + PSPs -> bundle. Pure. Its manifest is what the others read." "internal/compiler"
                bundle = component "bundle" "The bundle format, canonical hashing, the store." "internal/bundle"
                snapshot = component "snapshot" "The snapshot: the document, its id, its validation, the store." "internal/snapshot"
                psp = component "psp" "Platform support packages: loading and validation." "internal/psp"
                probe = component "probe" "The probe declaration and its rules, the probe packages (loading, validation, their templates rendered) and the pure reading of a ping's output." "internal/probe"
                findings = component "findings" "Findings, rules, the findings document, exit codes. The client's side links it too." "internal/findings"
            }
            worker = container "fylgja worker run" "The lab-host worker: runs the workflows and the host-bound activities. Loads the platform packages (psp/) and the probe packages (probes/), embedded, with the override directory's." "Go, the same binary" {
                workflows = component "provision" "The four workflows, the rehearsal running the provision, step and destroy as its children, and the worker's registration. The provision, step and rehearsal take a snapshot id and a bundle id the server compiled; none reads a source of truth." "internal/provision"
                wlab = component "lab" "The host-bound activities: deploy, readiness, push, reconcile, record, the wait, and a step's flows, started before its first change and read after its wait." "internal/lab"
                wverify = component "verify" "The readers and the wait." "internal/verify"
                wire = component "lab/wire" "Activity names and the payloads crossing the task queue." "internal/lab/wire"
                wprobe = component "probe" "The probe packages a host's plan is read from, and the pure reading of a ping's output." "internal/probe"
                wrehearsal = component "rehearsal" "A rehearsal's pure rules and renderings: the deadline, the verdict, the report and its markdown." "internal/rehearsal"
            }
            temporal = container "Workflow service" "Durable execution: run history." "Temporal"
            store = container "Bundle store" "<state root>/bundles/<bundle_id>/: every bundle compiled or provisioned." "Files" "Files"
            snapshotStore = container "Snapshot store" "<state root>/snapshots/<snapshot_id>.json: every snapshot taken, each kept as first filed." "Files" "Files"
            twindir = container "Twin directory" "<state root>/twin/: the staged bundle, containerlab's directory, twin.json." "Files" "Files"
            clab = container "containerlab" "Deploys, reconciles, inspects and destroys lab fylgja." "CLI"
        }

        operator -> fylgja "Runs commands"
        operator -> infrahub "Edits intent; opens proposed changes and marks stages"
        fylgja -> infrahub "Reads intent, artifacts and probes" "GraphQL, REST"
        fylgja -> twin "Boots, probes, pushes, reads"
        infrahub -> artifacts "Clones; renders the template; runs the checks"
        infrahub -> fylgja "Runs fylgja-step and fylgja-twin, which ask for the stage plan and the rehearsal" "HTTP, bearer token, plaintext"

        operator -> fylgja.cli "Runs commands"
        fylgja.cli -> fylgja.server "POST /v1/<noun>/<verb>; bearer token" "HTTP, NDJSON"
        infrahub -> fylgja.server "Runs fylgja-step and fylgja-twin in its task worker, which ask for the stage plan and the rehearsal" "HTTP, bearer token, plaintext"
        infrahub.taskWorker -> fylgja.server "fylgja-step asks for the stage plan; fylgja-twin for the rehearsal, in markdown" "HTTP over the Docker bridge, bearer token, plaintext"
        infrahub.taskWorker -> infrahub.iserver "Reads the proposed change; posts fylgja-twin's comment in a new thread; concludes each check" "GraphQL"
        fylgja.server -> infrahub "Reads intent, artifacts and probes" "GraphQL, REST"
        fylgja.server -> infrahub.iserver "Reads intent, artifacts and probes" "GraphQL, REST"
        fylgja.server -> fylgja.temporal "Starts, follows, cancels runs" "gRPC"
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
        fylgja.server.handlers -> fylgja.server.probe "Loads the probe packages; reads a request's declaration file"
        fylgja.server.handlers -> fylgja.server.stage "Reads and compiles"
        fylgja.server.handlers -> fylgja.server.stages "Resolves, lists, plans"
        fylgja.server.handlers -> fylgja.server.intent "Reads stages and stamps; checks the schema against the mapping's table"
        fylgja.server.handlers -> fylgja.server.step "Diffs; plans the push"
        fylgja.server.handlers -> fylgja.server.bundle "Verifies and files bundles"
        fylgja.server.handlers -> fylgja.server.snapshot "Takes, validates and files snapshots"
        fylgja.server.handlers -> fylgja.server.validate "Holds a sent snapshot's CTM to the rules that read no package"
        fylgja.server.handlers -> fylgja.server.compiler "Reads manifests"
        fylgja.server.handlers -> fylgja.server.lab "Host check, inspect, dry run"
        fylgja.server.handlers -> fylgja.server.verify "Reads the twin"
        fylgja.server.handlers -> fylgja.server.provisionClient "Starts and follows runs"
        fylgja.server.handlers -> fylgja.server.rehearsal "Decides the deadline; builds the report and its markdown"
        fylgja.server.api -> fylgja.server.findings "Carries the document"
        fylgja.server.stages -> fylgja.server.stage "Reads and compiles each stage"
        fylgja.server.stages -> fylgja.server.snapshot "Takes each stage's snapshot"
        fylgja.server.stages -> fylgja.server.intent "Reads proposed changes, stages, stamps and intent events"
        fylgja.server.stages -> fylgja.server.step "Diffs each pair"
        fylgja.server.stages -> fylgja.server.compiler "Surveys each stage's lossy mappings"
        fylgja.server.stage -> fylgja.server.intent "Reads the scope by the mapping"
        fylgja.server.stage -> fylgja.server.validate "Validates"
        fylgja.server.stage -> fylgja.server.compiler "Compiles"
        fylgja.server.stage -> fylgja.server.bundle "Files"
        fylgja.server.lab -> fylgja.server.verify "Reads through its readers"
        fylgja.server.lab -> fylgja.server.bundle "Verifies the staged bundle"
        fylgja.server.lab -> fylgja.server.compiler "Reads the manifest"
        fylgja.server.verify -> fylgja.server.compiler "Derives from the manifest"
        fylgja.server.validate -> fylgja.server.compiler "Surveys each device"
        fylgja.server.step -> fylgja.server.compiler "Compares two manifests"
        fylgja.server.rehearsal -> fylgja.server.findings "Builds the report's block and words its findings"
        fylgja.server.rehearsal -> fylgja.server.step "Draws what each step changed"
        fylgja.server.compiler -> fylgja.server.psp "Applies the mapping profile"
        fylgja.server.compiler -> fylgja.server.probe "Places each probe's hosts; renders them from their package"
        fylgja.server.validate -> fylgja.server.probe "Places the probes, refusing as the compiler does"
        fylgja.server.snapshot -> fylgja.server.probe "Holds each declaration to its rules"
        fylgja.server.intent -> fylgja.server.psp "Finds each device's package by its manufacturer and platform"
        fylgja.server.intent -> fylgja.server.probe "Reads FylgjaProbe on the default branch as declarations"
        fylgja.server.verify -> fylgja.server.probe "Renders each burst from its package"
        fylgja.server.lab -> fylgja.server.probe "Plans each host from its package; reads the burst"
        fylgja.server.lab -> twin.host "Runs each probe's burst for verify" "docker exec"

        fylgja.worker.workflows -> fylgja.worker.wire "Schedules activities by name"
        fylgja.worker.workflows -> fylgja.worker.wlab "Registers the host-bound activities"
        fylgja.worker.workflows -> fylgja.worker.wrehearsal "Classifies each stage"
        fylgja.worker.workflows -> fylgja.worker.wverify "Takes the wait's default budget for the deadline"
        fylgja.worker.wlab -> fylgja.worker.wire "Takes and returns the payloads"
        fylgja.worker.wlab -> fylgja.worker.wverify "VerifyTwin waits"
        fylgja.worker.wverify -> fylgja.worker.wire "Reads the record's types"
        fylgja.worker.wverify -> fylgja.worker.wprobe "Renders each burst from its package"
        fylgja.worker.wlab -> fylgja.worker.wprobe "Plans each host from its package; renders and reads its flow and its burst"
        fylgja.worker.wlab -> twin.host "Awaits its address; starts and reads a step's flow; runs the burst in the wait" "docker exec"
        fylgja.worker.workflows -> fylgja.worker.wprobe "Names the probe packages in the start-up report"
        fylgja.worker.wrehearsal -> fylgja.worker.wire "Compares the waits' findings; sums the node plans' budgets"

        live = deploymentEnvironment "Lab" {
            deploymentNode "Operator's machine" "FYLGJA_API_TOKEN; FYLGJA_API_ADDRESS, or an SSH tunnel to the lab host" "" {
                containerInstance fylgja.cli
            }
            deploymentNode "Lab host" "Ubuntu, Docker, containerlab, the NOS images and the probe packages' images" "" {
                deploymentNode "fylgja serve" "127.0.0.1:7650, and 172.17.0.1:7650 on docker0, the Docker bridge, in plaintext; FYLGJA_API_TOKEN, INFRAHUB_API_TOKEN, both node logins" "process" {
                    containerInstance fylgja.server
                }
                deploymentNode "fylgja worker run" "both node logins; no API token" "process" {
                    containerInstance fylgja.worker
                }
                deploymentNode "temporal server start-dev" ":7233; UI :8233" "process" {
                    containerInstance fylgja.temporal
                }
                deploymentNode "State root" "FYLGJA_STATE_ROOT: bundles/, snapshots/, twin/" "directory" {
                    containerInstance fylgja.store
                    containerInstance fylgja.snapshotStore
                    containerInstance fylgja.twindir
                }
                containerInstance fylgja.clab
                deploymentNode "Docker" "privileged containers" "" {
                    deploymentNode "Lab fylgja" "clab-fylgja-<node>; gNMI :57400 (TLS) or :6030; JSON-RPC or eAPI :443; each probe's hosts, clab-fylgja-<probe>-a and -b, reached by docker exec" "" {
                        containerInstance twin.node
                        containerInstance twin.host
                    }
                }
            }
            deploymentNode "Infrahub host" "Docker Compose, project fylgja-infrahub; the lab host, for its task workers to reach the API on the bridge" "" {
                containerInstance infrahub.iserver
                deploymentNode "task-worker" "host.docker.internal:7650, docker0's address by the Compose override's host-gateway entry; FYLGJA_API_ADDRESS and FYLGJA_API_TOKEN from the override" "container" "" 2 {
                    containerInstance infrahub.taskWorker
                }
            }
        }
    }

    views {
        systemContext fylgja "Context" "The operator, Fylgja, Infrahub, the artifacts repository and the walking twin." {
            include *
            include artifacts
            autoLayout lr
        }
        container fylgja "Containers" "Fylgja's processes and files on the lab host, and what each reaches." {
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
