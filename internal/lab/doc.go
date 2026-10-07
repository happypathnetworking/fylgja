// Package lab holds everything that must run where the containers are: the host-bound
// activities (host check, stage, deploy, readiness, record, teardown, unstage), the
// containerlab driver, the readiness probe and the twin directory.
//
// It never imports internal/provision. That boundary is what makes per-host task queues
// at M9 a dispatch change rather than a refactor (D-015): workflows reach this package
// only by activity name, and nothing here knows which workflow scheduled it.
package lab
