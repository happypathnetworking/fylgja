// Package provision holds Fylgja's Temporal side: the provision and destroy workflows,
// the control activities that run the read and compile stages, the CLI's client to the
// workflow service, and worker assembly.
//
// Workflow files (workflow_*.go and options.go) are deterministic: no I/O, network,
// filesystem, environment, wall clock or randomness — workflow.Now and workflow.Sleep,
// never time.Now or time.Sleep (Constitution VIII). They schedule activities by name
// and never import internal/lab, so no workflow file can reach host-bound code.
//
// Everything that must run where the containers are lives in internal/lab. This package
// imports it only to register its activities with the worker; internal/lab never
// imports this one (D-015).
package provision
