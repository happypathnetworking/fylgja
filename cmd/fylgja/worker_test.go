package main

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// captureStderr runs fn with os.Stderr redirected and returns what it wrote.
func captureStderr(t *testing.T, fn func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	saved := os.Stderr
	os.Stderr = w
	done := make(chan string)
	go func() {
		b, _ := io.ReadAll(r)
		done <- string(b)
	}()
	defer func() { os.Stderr = saved }()
	fn()
	_ = w.Close()
	return <-done
}

// A worker that cannot reach the workflow service says so in one line naming the address,
// and exits 2.
func TestWorkerUnreachableServiceExitsTwo(t *testing.T) {
	t.Setenv(lab.EnvTemporalAddress, "localhost:1")
	t.Setenv(lab.EnvStateRoot, t.TempDir())

	var err error
	stdout := captureStdout(t, func() {
		stderr := captureStderr(t, func() { err = runWorker(context.Background(), &options{}) })
		lines := strings.Split(strings.TrimSpace(stderr), "\n")
		if len(lines) != 1 || !strings.HasPrefix(lines[0], "fylgja worker: workflow service unreachable at localhost:1: ") {
			t.Errorf("stderr:\n%s\nwant one line naming localhost:1", stderr)
		}
	})
	var status exitStatus
	if !errors.As(err, &status) || int(status) != findings.ExitError {
		t.Errorf("runWorker returned %v, want exit status 2", err)
	}
	if stdout != "" {
		t.Errorf("stdout %q, want nothing: the worker never started", stdout)
	}
}

// A worker handed a package of the previous format refuses to serve, naming the version
// it read and the one it understands, and exits 2 before dialling. A 0.3 package is what
// an upgraded host still has in its override directory:
// version-0-3-m5.yaml is M5's shipped package as it was, whose retired fields the strict
// decoder refuses; version-0-5.yaml is this build's package with the version line alone
// moved back; version-0-5-m10.yaml is M10's shipped package as it was, which decodes and
// lacks fidelity.link_change. Each asserts the version it declares.
func TestWorkerRefusesAPreviousFormatOverride(t *testing.T) {
	for fixture, declared := range map[string]string{
		"version-0-5.yaml": "0.5", "version-0-5-m10.yaml": "0.5", "version-0-3-m5.yaml": "0.3",
	} {
		t.Run(fixture, func(t *testing.T) {
			src, err := os.ReadFile(repoPath("testdata", "psp", "defects", fixture))
			if err != nil {
				t.Fatal(err)
			}
			dir := t.TempDir()
			if err := os.WriteFile(filepath.Join(dir, "nokia_srlinux.yaml"), src, 0o644); err != nil {
				t.Fatal(err)
			}
			// An address nothing answers on: the refusal must come before any dial.
			t.Setenv(lab.EnvTemporalAddress, "localhost:1")
			t.Setenv(lab.EnvStateRoot, t.TempDir())

			var runErr error
			stderr := captureStderr(t, func() { runErr = runWorker(context.Background(), &options{pspDir: dir}) })
			var status exitStatus
			if !errors.As(runErr, &status) || int(status) != findings.ExitError {
				t.Errorf("runWorker returned %v, want exit status 2", runErr)
			}
			for _, want := range []string{
				findings.RulePSPVersionUnknown,
				`declares format version "` + declared + `", this build understands "` + psp.FormatVersion + `"`,
				"refusing to serve with an invalid support package",
			} {
				if !strings.Contains(stderr, want) {
					t.Errorf("stderr does not name %q:\n%s", want, stderr)
				}
			}
			if strings.Contains(stderr, "unreachable") {
				t.Errorf("the worker dialled before refusing the package:\n%s", stderr)
			}
		})
	}
}

// repoPath is a path from the repository's root.
func repoPath(parts ...string) string {
	return filepath.Join(append([]string{"..", ".."}, parts...)...)
}

// captureStdout runs fn with os.Stdout redirected and returns what it wrote.
func captureStdout(t *testing.T, fn func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	saved := os.Stdout
	os.Stdout = w
	done := make(chan string)
	go func() {
		b, _ := io.ReadAll(r)
		done <- string(b)
	}()
	defer func() { os.Stdout = saved }()
	fn()
	_ = w.Close()
	return <-done
}
