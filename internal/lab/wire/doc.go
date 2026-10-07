// Package wire holds the payloads that cross the task queue between the workflows and
// the lab host, and nothing else: activity names, the host-bound activities' inputs and
// outputs, and the twin record they return.
//
// It exists so that workflow files can name these types without importing internal/lab,
// which is host-bound (D-015). At M9, when the lab host gets its own
// queue, this package is that queue's contract.
//
// No I/O and no behaviour live here: types, constants, nothing that touches the clock,
// the filesystem or the network. A test holds the package to that, because workflow
// files import it and must stay deterministic (Constitution VIII).
package wire
