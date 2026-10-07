package lab

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
)

// Environment variables Fylgja reads for provisioning. Names only:
// a value is read where it is used and never kept anywhere that might be printed.
//
// Two groups are deliberately absent. The probe login variables (the shipped SR Linux
// package's FYLGJA_SRLINUX_USERNAME and _PASSWORD) are declared by each package's
// readiness.login and read by the names it gives, so a platform's login is data and not
// a constant in code (Constitution II). INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN belong to
// internal/intent, which reads them where the request is made.
const (
	EnvTemporalAddress   = "FYLGJA_TEMPORAL_ADDRESS"
	EnvTemporalNamespace = "FYLGJA_TEMPORAL_NAMESPACE"
	EnvStateRoot         = "FYLGJA_STATE_ROOT"
	EnvHostMemoryMB      = "FYLGJA_HOST_MEMORY_MB"
	EnvPSPDir            = "FYLGJA_PSP_DIR"
)

// DefaultStateRoot is the state root, relative to the working directory, when
// FYLGJA_STATE_ROOT is unset.
const DefaultStateRoot = "local"

// Paths are the state root and the directories under it, all absolute.
// A CLI and a worker agree on these only if they resolve the same root, which is why
// the absolute form is what crosses the task queue.
type Paths struct {
	Root       string // the state root
	Bundles    string // <root>/bundles: the bundle store
	Twin       string // <root>/twin: the twin directory, present exactly while a twin is
	TwinBundle string // <root>/twin/bundle: the verified copy of the bundle deployed
	TwinJSON   string // <root>/twin/twin.json: the twin's record, written last
}

// PathsAt lays out the state root at root, which must already be absolute.
func PathsAt(root string) Paths {
	twin := filepath.Join(root, "twin")
	return Paths{
		Root:       root,
		Bundles:    filepath.Join(root, "bundles"),
		Twin:       twin,
		TwinBundle: filepath.Join(twin, "bundle"),
		TwinJSON:   filepath.Join(twin, "twin.json"),
	}
}

// ResolvePaths reads FYLGJA_STATE_ROOT (default `local` under the working directory)
// and makes it absolute once, at start, so nothing later depends on the working
// directory staying put.
func ResolvePaths() (Paths, error) {
	root := DefaultStateRoot
	if v, ok := os.LookupEnv(EnvStateRoot); ok && v != "" {
		root = v
	}
	abs, err := filepath.Abs(root)
	if err != nil {
		return Paths{}, fmt.Errorf("resolving the state root %q: %w", root, err)
	}
	return PathsAt(abs), nil
}

// HostBudgetMB reads FYLGJA_HOST_MEMORY_MB: the memory the operator allows the twin on
// this host. Unset (or empty) is not an error; it makes the host check warn with the
// sum and proceed. A value that is not a positive whole number of MiB is an
// error, never silently treated as unset.
//
// getenv is os.LookupEnv in production and a map in tests.
func HostBudgetMB(getenv func(string) (string, bool)) (mb int, set bool, err error) {
	v, ok := getenv(EnvHostMemoryMB)
	if !ok || v == "" {
		return 0, false, nil
	}
	n, convErr := strconv.Atoi(v)
	if convErr != nil || n <= 0 {
		return 0, false, fmt.Errorf("%s must be a positive whole number of MiB, got %q", EnvHostMemoryMB, v)
	}
	return n, true, nil
}
