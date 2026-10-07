workspace "Fylgja" "A walking twin of network intent." {

    !identifiers hierarchical
    !impliedRelationships false

    model {
        operator = person "Operator" "Owns the lab host and Infrahub; drives the twin through the CLI."

        infrahub = softwareSystem "Infrahub" "The network source of truth. Holds intent on branches, versioned in time, and renders each device's configuration artifact." "External"
        artifacts = softwareSystem "Artifacts repository" "This repository, registered in Infrahub read-only: the artifacts template (.infrahub.yml, infrahub/) that renders each device's configuration from the Fylgja generics." "External"

        twin = softwareSystem "Walking twin" "Lab fylgja: a running containerlab topology of real network operating system images, built from one branch at one time." {
            node = container "NOS node" "One device of the twin, clab-fylgja-<node>: SR Linux or EOS, probed and read over gNMI and pushed its artifact." "Container"
        }

        fylgja = softwareSystem "Fylgja" "Reads intent from Infrahub, compiles it into a deterministic bundle, boots it as a twin and pushes each device's production configuration." {
            cli = container "fylgja (client)" "Every command but the two roles. Sends one request to the API and prints what comes back." "Go, one static binary"
            server = container "fylgja serve" "The API's server, on the lab host. Reads Infrahub, compiles, checks the host, starts and follows runs, reads the twin." "Go, the same binary; HTTP on 127.0.0.1:7650" {
                handlers = component "server" "The handlers: each command's logic behind POST /v1/<noun>/<verb>." "internal/server"
                api = component "api" "The wire: paths, frames, requests, problems, bounds. The client's side links it too." "internal/api"
                stage = component "stage" "The read and compile pipelines, shared with the worker." "internal/stage"
                waypoint = component "waypoint" "Waypoint references, their resolution, list and plan." "internal/waypoint"
                provisionClient = component "provision" "Starts, follows and cancels runs on the workflow service." "internal/provision"
                lab = component "lab" "Host-bound code: containerlab, the host check, the dry run, twin.json." "internal/lab"
                verify = component "verify" "Assertions derived from the manifest; one read of the twin." "internal/verify"
                intent = component "intent" "The Infrahub client: intent, conformance, artifacts, waypoints." "internal/intent"
                validate = component "validate" "Completeness and intent rules on the CTM." "internal/validate"
                step = component "step" "The pure step between two bundles; the push plan." "internal/step"
                compiler = component "compiler" "CTM + PSPs -> bundle. Pure. Its manifest is what the others read." "internal/compiler"
                bundle = component "bundle" "The bundle format, canonical hashing, the store." "internal/bundle"
                psp = component "psp" "Platform support packages: loading and validation." "internal/psp"
                findings = component "findings" "Findings, rules, the findings document, exit codes. The client's side links it too." "internal/findings"
            }
            worker = container "fylgja worker run" "The lab-host worker: runs the workflows and the host-bound activities." "Go, the same binary" {
                workflows = component "provision" "The four workflows, their control activities, the worker's registration." "internal/provision"
                wlab = component "lab" "The host-bound activities: deploy, readiness, push, reconcile, record, the wait." "internal/lab"
                wstage = component "stage" "The read and compile pipelines." "internal/stage"
                wverify = component "verify" "The readers and the wait." "internal/verify"
                wire = component "lab/wire" "Activity names and the payloads crossing the task queue." "internal/lab/wire"
            }
            temporal = container "Workflow service" "Durable execution: run history, Schedule fylgja-follow." "Temporal"
            store = container "Bundle store" "<state root>/bundles/<bundle_id>/: every bundle compiled or provisioned." "Files" "Files"
            twindir = container "Twin directory" "<state root>/twin/: the staged bundle, containerlab's directory, twin.json." "Files" "Files"
            clab = container "containerlab" "Deploys, reconciles, inspects and destroys lab fylgja." "CLI"
        }

        operator -> fylgja "Runs commands"
        operator -> infrahub "Edits intent; writes waypoints"
        fylgja -> infrahub "Reads intent and artifacts" "GraphQL, REST"
        fylgja -> twin "Boots, probes, pushes, reads"
        infrahub -> artifacts "Clones; renders the template"

        operator -> fylgja.cli "Runs commands"
        fylgja.cli -> fylgja.server "POST /v1/<noun>/<verb>; bearer token" "HTTP, NDJSON"
        fylgja.server -> infrahub "Reads intent and artifacts" "GraphQL, REST"
        fylgja.server -> fylgja.temporal "Starts, follows, cancels runs" "gRPC"
        fylgja.server -> fylgja.store "Files and reads bundles"
        fylgja.server -> fylgja.twindir "Reads the record and the staged bundle"
        fylgja.server -> fylgja.clab "Inspects; dry runs"
        fylgja.server -> twin.node "Reads for verify" "gNMI"
        fylgja.worker -> fylgja.temporal "Polls task queue fylgja" "gRPC"
        fylgja.worker -> infrahub "Reads intent and artifacts" "GraphQL, REST"
        fylgja.worker -> fylgja.store "Files and reads bundles"
        fylgja.worker -> fylgja.twindir "Stages, records"
        fylgja.worker -> fylgja.clab "Deploys, reconciles, destroys"
        fylgja.worker -> twin.node "Probes; pushes the artifact; waits" "gNMI; JSON-RPC or eAPI"
        fylgja.clab -> twin.node "Creates and cables"

        fylgja.server.handlers -> fylgja.server.api "Decodes requests; writes frames"
        fylgja.server.handlers -> fylgja.server.findings "Words every refusal; writes the document"
        fylgja.server.handlers -> fylgja.server.psp "Loads the packages"
        fylgja.server.handlers -> fylgja.server.stage "Reads and compiles"
        fylgja.server.handlers -> fylgja.server.waypoint "Resolves, lists, plans"
        fylgja.server.handlers -> fylgja.server.intent "Reads waypoints; checks the schema"
        fylgja.server.handlers -> fylgja.server.step "Diffs; plans the push"
        fylgja.server.handlers -> fylgja.server.bundle "Verifies and files bundles"
        fylgja.server.handlers -> fylgja.server.compiler "Reads manifests"
        fylgja.server.handlers -> fylgja.server.lab "Host check, inspect, dry run"
        fylgja.server.handlers -> fylgja.server.verify "Reads the twin"
        fylgja.server.handlers -> fylgja.server.provisionClient "Starts and follows runs"
        fylgja.server.api -> fylgja.server.findings "Carries the document"
        fylgja.server.waypoint -> fylgja.server.stage "Reads and compiles each waypoint"
        fylgja.server.waypoint -> fylgja.server.intent "Reads the series"
        fylgja.server.waypoint -> fylgja.server.step "Diffs each pair"
        fylgja.server.waypoint -> fylgja.server.compiler "Reads manifests"
        fylgja.server.stage -> fylgja.server.intent "Reads"
        fylgja.server.stage -> fylgja.server.validate "Validates"
        fylgja.server.stage -> fylgja.server.compiler "Compiles"
        fylgja.server.stage -> fylgja.server.bundle "Files"
        fylgja.server.lab -> fylgja.server.verify "Reads through its readers"
        fylgja.server.lab -> fylgja.server.bundle "Verifies the staged bundle"
        fylgja.server.lab -> fylgja.server.compiler "Reads the manifest"
        fylgja.server.verify -> fylgja.server.compiler "Derives from the manifest"
        fylgja.server.validate -> fylgja.server.compiler "Surveys each device"
        fylgja.server.step -> fylgja.server.compiler "Compares two manifests"
        fylgja.server.compiler -> fylgja.server.psp "Applies the mapping profile"

        fylgja.worker.workflows -> fylgja.worker.wire "Schedules activities by name"
        fylgja.worker.workflows -> fylgja.worker.wlab "Registers the host-bound activities"
        fylgja.worker.workflows -> fylgja.worker.wstage "ReadIntent, Compile"
        fylgja.worker.wlab -> fylgja.worker.wire "Takes and returns the payloads"
        fylgja.worker.wlab -> fylgja.worker.wverify "VerifyTwin waits"
        fylgja.worker.wverify -> fylgja.worker.wire "Reads the record's types"

        live = deploymentEnvironment "Lab" {
            deploymentNode "Operator's machine" "FYLGJA_API_TOKEN; FYLGJA_API_ADDRESS, or an SSH tunnel to the lab host" "" {
                containerInstance fylgja.cli
            }
            deploymentNode "Lab host" "Ubuntu, Docker, containerlab, the NOS images" "" {
                deploymentNode "fylgja serve" "127.0.0.1:7650; FYLGJA_API_TOKEN, INFRAHUB_API_TOKEN, both node logins" "process" {
                    containerInstance fylgja.server
                }
                deploymentNode "fylgja worker run" "INFRAHUB_API_TOKEN, both node logins; no API token" "process" {
                    containerInstance fylgja.worker
                }
                deploymentNode "temporal server start-dev" ":7233; UI :8233" "process" {
                    containerInstance fylgja.temporal
                }
                deploymentNode "State root" "FYLGJA_STATE_ROOT: bundles/, twin/" "directory" {
                    containerInstance fylgja.store
                    containerInstance fylgja.twindir
                }
                containerInstance fylgja.clab
                deploymentNode "Docker" "privileged containers" "" {
                    deploymentNode "Lab fylgja" "clab-fylgja-<node>; gNMI :57400 (TLS) or :6030; JSON-RPC or eAPI :443" "" {
                        containerInstance twin.node
                    }
                }
            }
            deploymentNode "Infrahub host" "Docker Compose, :8000; may be the lab host" "" {
                softwareSystemInstance infrahub
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
