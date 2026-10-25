package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// The API's token and a login's value in these tests: each is searched for in everything
// fylgja serve prints, and must be in none of it.
const (
	serveToken    = "serve-test-token-6b1f0e"
	loginValue    = "serve-test-login-93c2aa"
	infrahubToken = "serve-test-infrahub-4d07e1"
)

// lockedBuffer is a buffer runServe writes from its goroutine and a test reads.
type lockedBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *lockedBuffer) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}

func (l *lockedBuffer) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.String()
}

// heldImages is the references a host is pretending to hold.
type heldImages map[string]bool

func (h heldImages) Present(_ context.Context, ref string) (bool, error) { return h[ref], nil }

// serveTestOptions are serve's options listening on listen alone, over two buffers, the
// environment env (a missing name is unset), and a host that holds the imported image.
func serveTestOptions(listen, pspDir string, env map[string]string) (*serveOptions, *lockedBuffer, *lockedBuffer) {
	stdout, stderr := &lockedBuffer{}, &lockedBuffer{}
	return &serveOptions{
		listen: []string{listen},
		pspDir: pspDir,
		stdout: stdout,
		stderr: stderr,
		getenv: func(name string) (string, bool) {
			v, ok := env[name]
			return v, ok
		},
		images: heldImages{"ceos:4.32.0.2F": true},
	}, stdout, stderr
}

// holdAddress listens on a loopback port for the test's length and returns its address: one
// fylgja serve cannot listen on, so a refusal that comes before its listen is told from the
// listen's own.
func holdAddress(t *testing.T) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	return ln.Addr().String()
}

// freeAddress is a loopback address nothing listens on.
func freeAddress(t *testing.T) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().String()
	_ = ln.Close()
	return addr
}

// nothingListens fails the test when addr takes a connection.
func nothingListens(t *testing.T, addr string) {
	t.Helper()
	if conn, err := net.DialTimeout("tcp", addr, time.Second); err == nil {
		_ = conn.Close()
		t.Errorf("something listens on %s after fylgja serve refused to start", addr)
	}
}

// unresolvableStateRoot makes lab.ResolvePaths fail as it does on a host: a relative state
// root under a working directory that no longer exists. It returns that failure's text.
func unresolvableStateRoot(t *testing.T) string {
	t.Helper()
	gone := t.TempDir()
	t.Chdir(gone)
	if err := os.Remove(gone); err != nil {
		t.Fatal(err)
	}
	t.Setenv(lab.EnvStateRoot, "local")
	_, err := lab.ResolvePaths()
	if err == nil {
		t.Fatal("the state root resolved under a removed working directory")
	}
	return err.Error()
}

// invalidPackageDir is an override directory holding a package of the previous format, and
// the findings text psp validate gives for it, as the worker prints it.
func invalidPackageDir(t *testing.T) (dir, text string) {
	t.Helper()
	src, err := os.ReadFile(repoPath("testdata", "psp", "defects", "version-0-6.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	dir = t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "nokia_srlinux.yaml"), src, 0o644); err != nil {
		t.Fatal(err)
	}
	_, err = psp.Load(dir)
	var invalid *psp.InvalidError
	if !errors.As(err, &invalid) {
		t.Fatalf("psp.Load(%s) = %v, want the package refused", dir, err)
	}
	var b bytes.Buffer
	if err := findings.NewDocument(findings.OpPSPValidate, nil, invalid.Findings).WriteText(&b); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(b.String(), findings.RulePSPVersionUnknown) {
		t.Fatalf("the package's findings do not name %s:\n%s", findings.RulePSPVersionUnknown, b.String())
	}
	return dir, b.String()
}

// sharedPairDir is an override directory holding a package valid alone that names the
// embedded SR Linux package's pair under another NOS, and the findings text the registry's
// load gives for it, as the server prints it.
func sharedPairDir(t *testing.T) (dir, text string) {
	t.Helper()
	src, err := os.ReadFile(repoPath("testdata", "psp", "defects", "matches-shared.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	dir = t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "sharedos.yaml"), src, 0o644); err != nil {
		t.Fatal(err)
	}
	_, err = psp.Load(dir)
	var invalid *psp.InvalidError
	if !errors.As(err, &invalid) {
		t.Fatalf("psp.Load(%s) = %v, want the package refused", dir, err)
	}
	var b bytes.Buffer
	if err := findings.NewDocument(findings.OpPSPValidate, nil, invalid.Findings).WriteText(&b); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(b.String(), findings.RulePSPMatchesDuplicate) {
		t.Fatalf("the package's findings do not name %s:\n%s", findings.RulePSPMatchesDuplicate, b.String())
	}
	return dir, b.String()
}

// fylgja serve refuses to start in a fixed order, each refusal its own lines on
// stderr and exit 2, with nothing on stdout and nothing listening. Each case
// also fails the checks after it: the token's case has a --listen that is not host:port, the
// state root's an invalid package, and every case but the listen's own names an address the
// test holds, so a refusal made after the listen would be the listen's. With two --listen
// flags, the second's refusal comes before the first is listened on, or closes it.
func TestServeRefusesToStartInOrder(t *testing.T) {
	type refusal struct {
		name string
		// set up the case; it returns serve's options and the exact stderr wanted.
		setup func(t *testing.T) (opts *serveOptions, stdout, stderr *lockedBuffer, want string)
		// free makes the first --listen an address nothing listened on before the case,
		// checked after it.
		free bool
	}
	token := map[string]string{api.EnvToken: serveToken}
	cases := []refusal{
		{name: "the token unset", setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			dir, _ := invalidPackageDir(t)
			unresolvableStateRoot(t)
			o, out, errb := serveTestOptions("nonsense", dir, map[string]string{})
			return o, out, errb, "fylgja serve: FYLGJA_API_TOKEN is not set; the server does not start without the API's token\n"
		}},
		{name: "the token empty", setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			o, out, errb := serveTestOptions(holdAddress(t), "", map[string]string{api.EnvToken: ""})
			return o, out, errb, "fylgja serve: FYLGJA_API_TOKEN is not set; the server does not start without the API's token\n"
		}},
		{name: "the token unset, at a free address", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			o, out, errb := serveTestOptions("", "", map[string]string{})
			return o, out, errb, "fylgja serve: FYLGJA_API_TOKEN is not set; the server does not start without the API's token\n"
		}},
		// 017: a default scope no request could name is refused before anything is read.
		{name: "a malformed default scope", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			dir, _ := invalidPackageDir(t)
			unresolvableStateRoot(t)
			o, out, errb := serveTestOptions("", dir, map[string]string{api.EnvToken: serveToken, "FYLGJA_DEFAULT_SCOPE": "fylgja"})
			return o, out, errb, "fylgja serve: FYLGJA_DEFAULT_SCOPE fylgja is not tag:<name>\n"
		}},
		{name: "a default scope of two words", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			t.Setenv(lab.EnvStateRoot, t.TempDir())
			o, out, errb := serveTestOptions("", "", map[string]string{api.EnvToken: serveToken, "FYLGJA_DEFAULT_SCOPE": "tag:a b"})
			return o, out, errb, "fylgja serve: FYLGJA_DEFAULT_SCOPE tag:a b is not tag:<name>\n"
		}},
		{name: "--listen not host:port", setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			dir, _ := invalidPackageDir(t)
			unresolvableStateRoot(t)
			o, out, errb := serveTestOptions("127.0.0.1", dir, token)
			return o, out, errb, "fylgja serve: --listen 127.0.0.1 is not host:port\n"
		}},
		// Every value is checked before anything is read or listened on: a malformed second
		// one is refused before the state root, and the first is never listened on.
		{name: "a second --listen not host:port", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			dir, _ := invalidPackageDir(t)
			unresolvableStateRoot(t)
			o, out, errb := serveTestOptions("", dir, token)
			o.listen = append(o.listen, "127.0.0.1")
			return o, out, errb, "fylgja serve: --listen 127.0.0.1 is not host:port\n"
		}},
		{name: "the state root unresolvable", setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			dir, _ := invalidPackageDir(t)
			reason := unresolvableStateRoot(t)
			o, out, errb := serveTestOptions(holdAddress(t), dir, token)
			return o, out, errb, "fylgja serve: " + reason + "\n"
		}},
		{name: "the state root unresolvable, at a free address", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			reason := unresolvableStateRoot(t)
			o, out, errb := serveTestOptions("", "", token)
			return o, out, errb, "fylgja serve: " + reason + "\n"
		}},
		{name: "an invalid override package", setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			t.Setenv(lab.EnvStateRoot, t.TempDir())
			dir, text := invalidPackageDir(t)
			o, out, errb := serveTestOptions(holdAddress(t), dir, token)
			return o, out, errb, text + "fylgja serve: refusing to serve with an invalid support package\n"
		}},
		{name: "an invalid override package from FYLGJA_PSP_DIR", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			t.Setenv(lab.EnvStateRoot, t.TempDir())
			dir, text := invalidPackageDir(t)
			o, out, errb := serveTestOptions("", "", map[string]string{api.EnvToken: serveToken, lab.EnvPSPDir: dir})
			return o, out, errb, text + "fylgja serve: refusing to serve with an invalid support package\n"
		}},
		// Valid alone, refused by the registry's load beside the embedded packages (017).
		{name: "an override package sharing a pair, from FYLGJA_PSP_DIR", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			t.Setenv(lab.EnvStateRoot, t.TempDir())
			dir, text := sharedPairDir(t)
			o, out, errb := serveTestOptions("", "", map[string]string{api.EnvToken: serveToken, lab.EnvPSPDir: dir})
			return o, out, errb, text + "fylgja serve: refusing to serve with an invalid support package\n"
		}},
		// An override directory that cannot be read is refused where an invalid package is,
		// in psp.Load's words (contracts/cli.md).
		{name: "a missing override directory", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			t.Setenv(lab.EnvStateRoot, t.TempDir())
			dir := filepath.Join(t.TempDir(), "no-such-packages")
			o, out, errb := serveTestOptions("", dir, token)
			return o, out, errb, "fylgja serve: support package override directory: stat " + dir + ": no such file or directory\n"
		}},
		{name: "a missing override directory from FYLGJA_PSP_DIR", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			t.Setenv(lab.EnvStateRoot, t.TempDir())
			dir := filepath.Join(t.TempDir(), "no-such-packages")
			o, out, errb := serveTestOptions("", "", map[string]string{api.EnvToken: serveToken, lab.EnvPSPDir: dir})
			return o, out, errb, "fylgja serve: support package override directory: stat " + dir + ": no such file or directory\n"
		}},
		// psp.Load alone would serve the embedded packages over either.
		{name: "an override directory that is a file", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			t.Setenv(lab.EnvStateRoot, t.TempDir())
			file := filepath.Join(t.TempDir(), "packages")
			if err := os.WriteFile(file, []byte("not a directory\n"), 0o644); err != nil {
				t.Fatal(err)
			}
			o, out, errb := serveTestOptions("", file, token)
			return o, out, errb, "fylgja serve: support package override directory: " + file + " is not a directory\n"
		}},
		{name: "an override directory that cannot be listed", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			t.Setenv(lab.EnvStateRoot, t.TempDir())
			dir := filepath.Join(t.TempDir(), "packages")
			if err := os.Mkdir(dir, 0o000); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { _ = os.Chmod(dir, 0o755) })
			if _, err := os.ReadDir(dir); err == nil {
				t.Skip("the test runs with permission to list a mode 000 directory")
			}
			o, out, errb := serveTestOptions("", "", map[string]string{api.EnvToken: serveToken, lab.EnvPSPDir: dir})
			return o, out, errb, "fylgja serve: support package override directory: open " + dir + ": permission denied\n"
		}},
		{name: "the address taken", setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			t.Setenv(lab.EnvStateRoot, t.TempDir())
			addr := holdAddress(t)
			o, out, errb := serveTestOptions(addr, "", token)
			_, err := net.Listen("tcp", addr)
			if err == nil {
				t.Fatalf("%s took a second listener", addr)
			}
			return o, out, errb, "fylgja serve: listening on " + addr + ": " + err.Error() + "\n"
		}},
		// The first address is listened on before the second is refused, and is closed by
		// the refusal: the server listens on none.
		{name: "the second address taken", free: true, setup: func(t *testing.T) (*serveOptions, *lockedBuffer, *lockedBuffer, string) {
			t.Setenv(lab.EnvStateRoot, t.TempDir())
			addr := holdAddress(t)
			o, out, errb := serveTestOptions("", "", token)
			o.listen = append(o.listen, addr)
			_, err := net.Listen("tcp", addr)
			if err == nil {
				t.Fatalf("%s took a second listener", addr)
			}
			return o, out, errb, "fylgja serve: listening on " + addr + ": " + err.Error() + "\n"
		}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			opts, stdout, stderr, want := c.setup(t)
			if c.free {
				opts.listen[0] = freeAddress(t)
			}
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			err := runServe(ctx, opts, "0.1.0-test")
			var status exitStatus
			if !errors.As(err, &status) || int(status) != findings.ExitError {
				t.Errorf("runServe returned %v, want exit status 2", err)
			}
			if got := stderr.String(); got != want {
				t.Errorf("stderr:\n%s\nwant:\n%s", got, want)
			}
			if got := stdout.String(); got != "" {
				t.Errorf("stdout %q, want nothing: the server never started", got)
			}
			if c.free {
				nothingListens(t, opts.listen[0])
			}
			for _, secret := range []string{serveToken, loginValue} {
				if strings.Contains(stderr.String(), secret) {
					t.Errorf("stderr carries a secret:\n%s", stderr.String())
				}
			}
		})
	}
}

// fylgja serve's usage errors are refusals to start, as its six others are: cobra's error in
// one line on stderr, exit 2, nothing on stdout, nothing listening, and no findings document,
// whose operation enum names no serve. Each runs through the root main builds, to the status
// main exits with, as given and with a --listen at a free address that is then checked
// (contracts/cli.md). The token is set empty, so a serve that ran anyway would
// refuse at it rather than listen.
func TestServeRefusesAUsageErrorToStart(t *testing.T) {
	t.Setenv(api.EnvToken, "")
	unknown := `fylgja serve: unknown command "extra" for "fylgja serve"` + "\n"
	for _, c := range []struct {
		before, after []string
		want          string
	}{
		{before: []string{"serve"}, after: []string{"extra"}, want: unknown},
		{before: []string{"serve"}, after: []string{"--nope"}, want: "fylgja serve: unknown flag: --nope\n"},
		{before: []string{"--json", "serve"}, after: []string{"extra"}, want: unknown},
	} {
		for _, listen := range []bool{false, true} {
			args := append([]string{}, c.before...)
			addr := ""
			if listen {
				addr = freeAddress(t)
				args = append(args, "--listen", addr)
			}
			args = append(args, c.after...)
			var code int
			var stderr string
			stdout := captureStdout(t, func() {
				stderr = captureStderr(t, func() {
					root := newRoot()
					root.SetArgs(args)
					cmd, err := root.ExecuteC()
					code = exitCode(cmd, err)
				})
			})
			if code != findings.ExitError {
				t.Errorf("%q: exit %d, want 2", args, code)
			}
			if stderr != c.want {
				t.Errorf("%q: stderr:\n%s\nwant:\n%s", args, stderr, c.want)
			}
			if stdout != "" {
				t.Errorf("%q: stdout %q, want nothing: the server never started and writes no document", args, stdout)
			}
			if listen {
				nothingListens(t, addr)
			}
		}
	}
}

// recordingListener counts the connections something made to it, and answers none.
type recordingListener struct {
	ln       net.Listener
	accepted atomic.Int32
}

func newRecordingListener(t *testing.T) *recordingListener {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	r := &recordingListener{ln: ln}
	var mu sync.Mutex
	var held []net.Conn
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			r.accepted.Add(1)
			mu.Lock()
			held = append(held, conn)
			mu.Unlock()
		}
	}()
	t.Cleanup(func() {
		_ = ln.Close()
		mu.Lock()
		defer mu.Unlock()
		for _, c := range held {
			_ = c.Close()
		}
	})
	return r
}

func (r *recordingListener) addr() string { return r.ln.Addr().String() }

// serving is fylgja serve running in the test, until stop. done is closed when runServe
// has returned err.
type serving struct {
	stdout, stderr *lockedBuffer
	cancel         context.CancelFunc
	done           chan struct{}
	err            error
}

// startServe runs fylgja serve with opts and waits for its report's lines lines.
func startServe(t *testing.T, opts *serveOptions, stdout, stderr *lockedBuffer, lines int) *serving {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	s := &serving{stdout: stdout, stderr: stderr, cancel: cancel, done: make(chan struct{})}
	go func() {
		defer close(s.done)
		s.err = runServe(ctx, opts, "0.1.0-test")
	}()
	t.Cleanup(func() {
		cancel()
		select {
		case <-s.done:
		case <-time.After(5 * time.Second):
		}
	})
	deadline := time.Now().Add(10 * time.Second)
	for strings.Count(stdout.String(), "\n") < lines {
		select {
		case <-s.done:
			t.Fatalf("fylgja serve ended before its report: %v\nstdout:\n%s\nstderr:\n%s", s.err, stdout, stderr)
		default:
		}
		if time.Now().After(deadline) {
			t.Fatalf("no report after 10s:\nstdout:\n%s\nstderr:\n%s", stdout, stderr)
		}
		time.Sleep(5 * time.Millisecond)
	}
	return s
}

// stop interrupts the server and returns what runServe returned, failing the test when it
// has not returned within 5s.
func (s *serving) stop(t *testing.T) error {
	t.Helper()
	s.cancel()
	select {
	case <-s.done:
		return s.err
	case <-time.After(5 * time.Second):
		t.Fatal("fylgja serve did not stop within 5s of its interrupt")
		return nil
	}
}

// serveEnvironment sets the process environment a server reads at each request, and
// returns serve's options reading it: the token, a scratch state root, the workflow service
// and Infrahub at listeners that record a connection, Infrahub's token, one login variable
// set and the rest unset, no memory budget or override directory, and the fixture's default
// scope (017).
func serveEnvironment(t *testing.T, listen string) (opts *serveOptions, stdout, stderr *lockedBuffer, root, temporal string, recorders []*recordingListener) {
	t.Helper()
	root = t.TempDir()
	service, infrahub := newRecordingListener(t), newRecordingListener(t)
	for name, value := range map[string]string{
		api.EnvToken:              serveToken,
		lab.EnvStateRoot:          root,
		lab.EnvTemporalAddress:    service.addr(),
		lab.EnvTemporalNamespace:  "",
		"INFRAHUB_ADDRESS":        "http://" + infrahub.addr(),
		"INFRAHUB_API_TOKEN":      infrahubToken,
		"FYLGJA_SRLINUX_USERNAME": loginValue,
		"FYLGJA_SRLINUX_PASSWORD": "",
		"FYLGJA_EOS_USERNAME":     "",
		"FYLGJA_EOS_PASSWORD":     "",
		lab.EnvHostMemoryMB:       "",
		lab.EnvPSPDir:             "",
		"FYLGJA_DEFAULT_SCOPE":    "tag:fylgja",
	} {
		t.Setenv(name, value)
	}
	opts, stdout, stderr = serveTestOptions(listen, "", nil)
	opts.getenv = os.LookupEnv
	return opts, stdout, stderr, root, service.addr(), []*recordingListener{service, infrahub}
}

// reportAddress is the address the report's first line says the server listens on.
func reportAddress(t *testing.T, stdout string) string {
	t.Helper()
	first, _, _ := strings.Cut(stdout, "\n")
	const prefix = "fylgja serve: listening on "
	addr, _, ok := strings.Cut(strings.TrimPrefix(first, prefix), " (")
	if !strings.HasPrefix(first, prefix) || !ok {
		t.Fatalf("the report's first line %q does not say where it listens", first)
	}
	return addr
}

// reportAddresses is every address the report's listen lines say the server listens on, in
// the order printed.
func reportAddresses(t *testing.T, stdout string) []string {
	t.Helper()
	const prefix = "fylgja serve: listening on "
	var addrs []string
	for _, line := range strings.Split(stdout, "\n") {
		if !strings.HasPrefix(line, prefix) {
			continue
		}
		addr, _, ok := strings.Cut(strings.TrimPrefix(line, prefix), " (")
		if !ok {
			t.Fatalf("the listen line %q does not say where it listens", line)
		}
		addrs = append(addrs, addr)
	}
	return addrs
}

// dialable is addr with a wildcard host replaced by loopback, which a test can connect to.
func dialable(addr string) string {
	return strings.Replace(addr, "0.0.0.0", "127.0.0.1", 1)
}

// Given --listen more than once, the server listens on every address: its report names each
// in the order given with the port it got, and straight after each that is not loopback the
// line saying the token is sent unencrypted on it, before the rest of the report. A request
// on each is answered alike under the one token, and the log names no address
// (contracts/server-and-host.md "fylgja serve").
func TestServeListensOnEveryAddress(t *testing.T) {
	opts, stdout, stderr, root, _, _ := serveEnvironment(t, "")
	opts.listen = []string{"127.0.0.1:0", "0.0.0.0:0", "127.0.0.2:0"}
	s := startServe(t, opts, stdout, stderr, 12)

	addrs := reportAddresses(t, stdout.String())
	if len(addrs) != len(opts.listen) {
		t.Fatalf("the report names %d addresses, want %d:\n%s", len(addrs), len(opts.listen), stdout)
	}
	for i, addr := range addrs {
		host, port, _ := net.SplitHostPort(addr)
		if want := strings.Split(opts.listen[i], ":")[0]; host != want || port == "0" {
			t.Errorf("listen line %d names %s, want the host --listen gave, %s, with the port it got", i+1, addr, want)
		}
	}
	want := []string{
		"fylgja serve: listening on " + addrs[0] + " (API version 1, build 0.1.0-test)",
		"fylgja serve: listening on " + addrs[1] + " (API version 1, build 0.1.0-test)",
		"fylgja serve: " + addrs[1] + " is not a loopback address: the API's token is sent unencrypted on it",
		"fylgja serve: listening on " + addrs[2] + " (API version 1, build 0.1.0-test)",
		fmt.Sprintf("fylgja serve: state root %s (bundles: %s, twin: %s)", root, filepath.Join(root, "bundles"), filepath.Join(root, "twin")),
	}
	if got := strings.Split(stdout.String(), "\n"); len(got) < len(want) || strings.Join(got[:len(want)], "\n") != strings.Join(want, "\n") {
		t.Errorf("report:\n%s\nwant it to begin:\n%s", stdout, strings.Join(want, "\n"))
	}
	if n := strings.Count(stdout.String(), "is not a loopback address"); n != 1 {
		t.Errorf("%d unencrypted lines, want 1, for the one address off loopback:\n%s", n, stdout)
	}

	// Each address answers a request without the token, and one with it, as the others do.
	type answer struct {
		status int
		body   string
	}
	var first []answer
	for i, addr := range addrs {
		resp, err := http.Post("http://"+dialable(addr)+api.Path(findings.OpTwinShow), "application/json", strings.NewReader("{}"))
		if err != nil {
			t.Fatalf("%s does not answer: %v", addr, err)
		}
		body, _ := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		withToken, withBody := optionsStar(t, dialable(addr), serveToken)
		got := []answer{{resp.StatusCode, string(body)}, {withToken.StatusCode, string(withBody)}}
		if got[0].status != http.StatusUnauthorized || got[1].status != http.StatusNotFound {
			t.Errorf("%s answered %d without the token and %d with it, want 401 and 404", addr, got[0].status, got[1].status)
		}
		if i == 0 {
			first = got
		} else if fmt.Sprint(got) != fmt.Sprint(first) {
			t.Errorf("%s answered %v, want what %s answered, %v", addr, got, addrs[0], first)
		}
	}
	deadline := time.Now().Add(5 * time.Second)
	for len(requestLines(stderr.String())) < 2*len(addrs) && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if err := s.stop(t); err != nil {
		t.Errorf("runServe returned %v once interrupted, want nil (exit 0)", err)
	}
	lines := requestLines(stderr.String())
	if len(lines) != 2*len(addrs) {
		t.Errorf("%d request lines for %d requests:\n%s", len(lines), 2*len(addrs), stderr)
	}
	for _, line := range lines {
		for _, addr := range addrs {
			_, port, _ := net.SplitHostPort(addr)
			if strings.Contains(line, ":"+port) {
				t.Errorf("a request line names the address %s: %s", addr, line)
			}
		}
	}
	for _, addr := range addrs {
		if conn, err := net.DialTimeout("tcp", dialable(addr), time.Second); err == nil {
			_ = conn.Close()
			t.Errorf("%s still takes connections after the server stopped", addr)
		}
	}
}

// The start-up report, word for word, before the first request is taken: where it listens
// with the API's version and the build, the state
// root, the default scope (017), that the workflow service and Infrahub are dialled when a request needs them, and the
// worker's budget and package lines with the login variables' presence in the worker's words.
// A listen address that is not loopback says the token is sent unencrypted on it. Neither the
// token nor a login value is printed, and neither the workflow service nor Infrahub has been
// connected to by the time the report is out.
func TestServeReportsBeforeTakingARequest(t *testing.T) {
	for _, c := range []struct {
		name     string
		listen   string
		loopback bool
	}{
		{"loopback", "127.0.0.1:0", true},
		{"not loopback", "0.0.0.0:0", false},
	} {
		t.Run(c.name, func(t *testing.T) {
			opts, stdout, stderr, root, temporal, recorders := serveEnvironment(t, c.listen)
			lines := 9
			if !c.loopback {
				lines = 10
			}
			s := startServe(t, opts, stdout, stderr, lines)

			addr := reportAddress(t, stdout.String())
			if host, _, _ := net.SplitHostPort(addr); host != strings.Split(c.listen, ":")[0] {
				t.Errorf("the report names %s, want the host --listen gave, %s", addr, c.listen)
			}
			want := []string{fmt.Sprintf("fylgja serve: listening on %s (API version 1, build 0.1.0-test)", addr)}
			if !c.loopback {
				want = append(want, "fylgja serve: "+addr+" is not a loopback address: the API's token is sent unencrypted on it")
			}
			want = append(want,
				fmt.Sprintf("fylgja serve: state root %s (bundles: %s, twin: %s)", root, filepath.Join(root, "bundles"), filepath.Join(root, "twin")),
				"fylgja serve: default scope: tag:fylgja",
				"fylgja serve: the workflow service ("+temporal+", namespace default) and Infrahub are dialled when a request needs them",
				"fylgja serve: host memory budget: unset (memory sums will be warnings)",
				"fylgja serve: probe login arista_eos: FYLGJA_EOS_USERNAME unset, FYLGJA_EOS_PASSWORD unset",
				"fylgja serve: arista_eos (embedded): image ceos:4.32.0.2F (account_gated, present on this host), "+
					"push eapi replace over https:443, login FYLGJA_EOS_USERNAME/FYLGJA_EOS_PASSWORD (probe and push)",
				"fylgja serve: probe login nokia_srlinux: FYLGJA_SRLINUX_USERNAME set, FYLGJA_SRLINUX_PASSWORD unset",
				"fylgja serve: nokia_srlinux (embedded): image ghcr.io/nokia/srlinux:24.7.1, "+
					"push json_rpc replace over https:443, login FYLGJA_SRLINUX_USERNAME/FYLGJA_SRLINUX_PASSWORD (probe and push)",
			)
			if got := stdout.String(); got != strings.Join(want, "\n")+"\n" {
				t.Errorf("report:\n%s\nwant:\n%s", got, strings.Join(want, "\n"))
			}
			for _, r := range recorders {
				if n := r.accepted.Load(); n != 0 {
					t.Errorf("%s took %d connections before any request: the server dialled at start", r.addr(), n)
				}
			}

			// The listener is up: a request without the token is refused there.
			resp, err := http.Post("http://"+strings.Replace(addr, "0.0.0.0", "127.0.0.1", 1)+api.Path(findings.OpTwinShow), "application/json", strings.NewReader("{}"))
			if err != nil {
				t.Fatalf("the reported address does not answer: %v", err)
			}
			_ = resp.Body.Close()
			if resp.StatusCode != http.StatusUnauthorized {
				t.Errorf("a request without the token answered %d, want 401", resp.StatusCode)
			}

			if err := s.stop(t); err != nil {
				t.Errorf("runServe returned %v once interrupted, want nil (exit 0)", err)
			}
			for _, out := range []string{stdout.String(), stderr.String()} {
				for _, secret := range []string{serveToken, loginValue, infrahubToken} {
					if strings.Contains(out, secret) {
						t.Errorf("fylgja serve printed a secret:\n%s", out)
					}
				}
			}
		})
	}
}

// The default scope is reported after the state root, and is the scope a request naming none
// is read under (017): set, a request with no scope goes on to Infrahub; unset or empty, the
// report says so and such a request is scope.unset, naming the variable, with Infrahub never
// dialled.
func TestServeReportsAndServesItsDefaultScope(t *testing.T) {
	for _, c := range []struct {
		name  string
		value *string
		line  string
	}{
		{"set", ptr("tag:lab-b"), "fylgja serve: default scope: tag:lab-b"},
		{"unset", nil, "fylgja serve: default scope: unset (a request that names no scope is refused)"},
		{"empty", ptr(""), "fylgja serve: default scope: unset (a request that names no scope is refused)"},
	} {
		t.Run(c.name, func(t *testing.T) {
			opts, stdout, stderr, _, _, recorders := serveEnvironment(t, "127.0.0.1:0")
			infrahub := recorders[1]
			if c.value != nil {
				t.Setenv("FYLGJA_DEFAULT_SCOPE", *c.value)
			} else if err := os.Unsetenv("FYLGJA_DEFAULT_SCOPE"); err != nil {
				t.Fatal(err)
			}
			s := startServe(t, opts, stdout, stderr, 9)
			lines := strings.Split(stdout.String(), "\n")
			if len(lines) < 3 || !strings.HasPrefix(lines[1], "fylgja serve: state root ") || lines[2] != c.line {
				t.Errorf("report:\n%s\nwant %q after the state root", stdout, c.line)
			}

			req, err := http.NewRequest(http.MethodPost, "http://"+reportAddress(t, stdout.String())+api.Path(findings.OpIntentRead),
				strings.NewReader(`{"render":"json","args":{"branch":"fylgja-test-serve","out":"ctm.json"}}`))
			if err != nil {
				t.Fatal(err)
			}
			req.Header.Set("Authorization", "Bearer "+serveToken)
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatalf("the request was not answered: %v", err)
			}
			defer func() { _ = resp.Body.Close() }()
			if c.value != nil && *c.value != "" {
				deadline := time.Now().Add(10 * time.Second)
				for infrahub.accepted.Load() == 0 {
					if time.Now().After(deadline) {
						t.Fatal("a request naming no scope never reached Infrahub under the default")
					}
					time.Sleep(5 * time.Millisecond)
				}
			} else {
				body, _ := io.ReadAll(resp.Body)
				var frame api.Frame
				var doc findings.Document
				lines := strings.Split(strings.TrimSpace(string(body)), "\n")
				if err := json.Unmarshal([]byte(lines[len(lines)-1]), &frame); err != nil || json.Unmarshal(frame.Document, &doc) != nil {
					t.Fatalf("the answer's last line is not a document frame:\n%s", body)
				}
				if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleScopeUnset || doc.Findings[0].Object != "FYLGJA_DEFAULT_SCOPE" ||
					doc.Status.ExitCode() != findings.ExitError {
					t.Errorf("the document %+v; want scope.unset naming FYLGJA_DEFAULT_SCOPE alone, exit 2", doc)
				}
				if n := infrahub.accepted.Load(); n != 0 {
					t.Errorf("Infrahub took %d connections, want none before scope.unset", n)
				}
			}
			if err := s.stop(t); err != nil {
				t.Errorf("runServe returned %v once interrupted, want nil (exit 0)", err)
			}
		})
	}
}

func ptr(s string) *string { return &s }

// Interrupted, the server closes its listener and every connection at once, an answer in
// flight included, and exits 0. The answer here is schema check's, held
// open by an Infrahub that takes the connection and never answers; its client sees the
// answer cut, with no document.
func TestServeStopsAtOnceAndExitsZero(t *testing.T) {
	opts, stdout, stderr, _, _, recorders := serveEnvironment(t, "127.0.0.1:0")
	infrahub := recorders[1]
	s := startServe(t, opts, stdout, stderr, 9)
	addr := reportAddress(t, stdout.String())

	req, err := http.NewRequest(http.MethodPost, "http://"+addr+api.Path(findings.OpSchemaCheck),
		strings.NewReader(`{"args":{"branch":"fylgja-test-serve"}}`))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer "+serveToken)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("the request was not answered: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("the request answered %d, want 200 with the answer open", resp.StatusCode)
	}
	deadline := time.Now().Add(10 * time.Second)
	for infrahub.accepted.Load() == 0 {
		if time.Now().After(deadline) {
			t.Fatal("schema check never reached Infrahub")
		}
		time.Sleep(5 * time.Millisecond)
	}

	if err := s.stop(t); err != nil {
		t.Errorf("runServe returned %v once interrupted, want nil (exit 0)", err)
	}

	// The answer was cut: whatever came before the close carries no document, and the read
	// ends in an error rather than a clean end.
	read := make(chan error, 1)
	var frames []string
	go func() {
		sc := bufio.NewScanner(resp.Body)
		for sc.Scan() {
			frames = append(frames, sc.Text())
		}
		read <- sc.Err()
	}()
	select {
	case err := <-read:
		if err == nil {
			t.Error("the answer ended cleanly, want it cut by the close")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the answer's connection was still open 5s after the server stopped")
	}
	for _, f := range frames {
		if strings.Contains(f, `"document"`) {
			t.Errorf("the cut answer carried a document: %s", f)
		}
	}
	if _, err := net.DialTimeout("tcp", addr, time.Second); err == nil {
		t.Errorf("%s still takes connections after the server stopped", addr)
	}
}

// failingListener is a loopback listener whose Accept fails: with temporary, a net.Error the
// HTTP server retries, once, before it accepts as the listener does; otherwise with err,
// which ends Serve.
type failingListener struct {
	net.Listener
	err       error
	temporary atomic.Bool
}

func (l *failingListener) Accept() (net.Conn, error) {
	if l.temporary.CompareAndSwap(true, false) {
		return nil, temporaryError{}
	}
	if l.err != nil {
		return nil, l.err
	}
	return l.Listener.Accept()
}

// temporaryError is an Accept failure the HTTP server retries.
type temporaryError struct{}

func (temporaryError) Error() string   { return "the test refuses one connection" }
func (temporaryError) Timeout() bool   { return false }
func (temporaryError) Temporary() bool { return true }

// listenFailing gives opts a loopback listener that fails as l is set to, and returns it.
func listenFailing(t *testing.T, opts *serveOptions, l *failingListener) {
	t.Helper()
	opts.netListen = func(network, address string) (net.Listener, error) {
		ln, err := net.Listen(network, address)
		if err != nil {
			return nil, err
		}
		l.Listener = ln
		return l, nil
	}
}

// Once it serves, a failure to accept ends fylgja serve with `serving on <address>: <error>`,
// exit 2, the address the listen line named (contracts/cli.md).
func TestServeEndsWhenAcceptingFails(t *testing.T) {
	opts, stdout, stderr, _, _, _ := serveEnvironment(t, "127.0.0.1:0")
	listenFailing(t, opts, &failingListener{err: errors.New("the test's listener is closed")})
	err := runServe(context.Background(), opts, "0.1.0-test")
	var exit exitStatus
	if !errors.As(err, &exit) || int(exit) != findings.ExitError {
		t.Fatalf("runServe = %v, want exit 2", err)
	}
	addr := reportAddress(t, stdout.String())
	if got, want := stderr.String(), "fylgja serve: serving on "+addr+": the test's listener is closed\n"; got != want {
		t.Errorf("stderr %q, want %q", got, want)
	}
}

// A failure to accept on one listener of several ends fylgja serve on all of them, naming
// that listener's address, exit 2.
func TestServeEndsOnEveryAddressWhenOneFailsToAccept(t *testing.T) {
	opts, stdout, stderr, _, _, _ := serveEnvironment(t, "")
	opts.listen = []string{"127.0.0.1:0", "127.0.0.2:0"}
	failing := &failingListener{err: errors.New("the test's listener is closed")}
	opts.netListen = func(network, address string) (net.Listener, error) {
		ln, err := net.Listen(network, address)
		if err != nil || !strings.HasPrefix(address, "127.0.0.2:") {
			return ln, err
		}
		failing.Listener = ln
		return failing, nil
	}
	err := runServe(context.Background(), opts, "0.1.0-test")
	var exit exitStatus
	if !errors.As(err, &exit) || int(exit) != findings.ExitError {
		t.Fatalf("runServe = %v, want exit 2", err)
	}
	addrs := reportAddresses(t, stdout.String())
	if len(addrs) != 2 {
		t.Fatalf("the report names %v, want two addresses:\n%s", addrs, stdout)
	}
	if got, want := stderr.String(), "fylgja serve: serving on "+addrs[1]+": the test's listener is closed\n"; got != want {
		t.Errorf("stderr %q, want %q", got, want)
	}
	if conn, err := net.DialTimeout("tcp", addrs[0], time.Second); err == nil {
		_ = conn.Close()
		t.Errorf("%s still takes connections after the server ended on %s", addrs[0], addrs[1])
	}
}

// The HTTP server's own errors are WARN lines in the server's log, beside its request lines
// (contracts/cli.md): here an Accept it retries.
func TestServeLogsTheHTTPServersErrorsAsWarnings(t *testing.T) {
	opts, stdout, stderr, _, _, _ := serveEnvironment(t, "127.0.0.1:0")
	l := &failingListener{}
	l.temporary.Store(true)
	listenFailing(t, opts, l)
	s := startServe(t, opts, stdout, stderr, 9)
	addr := reportAddress(t, stdout.String())

	// A request is taken once the retried Accept has passed.
	resp, err := http.Post("http://"+addr+api.Path(findings.OpTwinShow), "application/json", strings.NewReader("{}"))
	if err != nil {
		t.Fatalf("the server does not answer after a retried Accept: %v", err)
	}
	_ = resp.Body.Close()
	if err := s.stop(t); err != nil {
		t.Errorf("runServe returned %v once interrupted, want nil (exit 0)", err)
	}
	var warned bool
	for _, line := range strings.Split(stderr.String(), "\n") {
		warned = warned || strings.Contains(line, "level=WARN") &&
			strings.Contains(line, `msg="http: Accept error: the test refuses one connection; retrying in `)
	}
	if !warned {
		t.Errorf("no WARN line names the HTTP server's error:\n%s", stderr)
	}
}

// optionsStar sends a raw `OPTIONS * HTTP/1.1` to addr, with the token when token is not
// empty, and returns the answer and its body.
func optionsStar(t *testing.T, addr, token string) (*http.Response, []byte) {
	t.Helper()
	conn, err := net.DialTimeout("tcp", addr, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	req := "OPTIONS * HTTP/1.1\r\nHost: " + addr + "\r\n"
	if token != "" {
		req += "Authorization: Bearer " + token + "\r\n"
	}
	if _, err := conn.Write([]byte(req + "\r\n")); err != nil {
		t.Fatal(err)
	}
	resp, err := http.ReadResponse(bufio.NewReader(conn), nil)
	if err != nil {
		t.Fatalf("OPTIONS * was not answered: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return resp, body
}

// requestLines is the server's request lines in what it wrote to stderr.
func requestLines(stderr string) []string {
	var lines []string
	for _, l := range strings.Split(stderr, "\n") {
		if strings.Contains(l, " msg=request ") {
			lines = append(lines, l)
		}
	}
	return lines
}

// `OPTIONS *` reaches the API's handler, as every other request does, rather than net/http's
// own answer, 200 with no line logged: without the token it is 401 with WWW-Authenticate and
// the problem body, before the route is looked up, and with it the 404 of a path under no
// version served, `*` being answered as `/*`, the path it cleans to. Each is one line in the
// log (contracts/api.md "The token" and "The transport's statuses"; contracts/cli.md fylgja
// serve).
func TestServeAnswersOptionsStarThroughTheAPI(t *testing.T) {
	opts, stdout, stderr, _, _, _ := serveEnvironment(t, "127.0.0.1:0")
	s := startServe(t, opts, stdout, stderr, 9)
	addr := reportAddress(t, stdout.String())

	for _, c := range []struct {
		name, token string
		status      int
		headers     map[string]string
		message     string
		logged      string
	}{
		{
			name: "without the token", status: http.StatusUnauthorized,
			headers: map[string]string{"WWW-Authenticate": "Bearer", api.HeaderVersion: "", api.HeaderBuild: "", api.HeaderVersions: ""},
			message: "this request does not carry the API's token; nothing was read or done",
			logged:  "level=WARN msg=request operation=unknown outcome=token_refused ",
		},
		{
			name: "with the token", token: serveToken, status: http.StatusNotFound,
			headers: map[string]string{"WWW-Authenticate": "", api.HeaderVersion: "1", api.HeaderBuild: "0.1.0-test", api.HeaderVersions: "1"},
			message: "this server serves API version 1; nothing was read or done",
			logged:  "level=WARN msg=request operation=unknown outcome=version_unknown ",
		},
	} {
		before := len(requestLines(stderr.String()))
		resp, body := optionsStar(t, addr, c.token)
		if resp.StatusCode != c.status {
			t.Errorf("%s: OPTIONS * answered %d, want %d", c.name, resp.StatusCode, c.status)
		}
		for name, want := range c.headers {
			if got := resp.Header.Get(name); got != want {
				t.Errorf("%s: %s %q, want %q", c.name, name, got, want)
			}
		}
		var p api.Problem
		if err := json.Unmarshal(body, &p); err != nil || p.Message != c.message || resp.Header.Get("Content-Type") != "application/json" {
			t.Errorf("%s: body %q (%s), want the problem %q", c.name, body, resp.Header.Get("Content-Type"), c.message)
		}
		deadline := time.Now().Add(5 * time.Second)
		for len(requestLines(stderr.String())) == before && time.Now().Before(deadline) {
			time.Sleep(5 * time.Millisecond)
		}
		if lines := requestLines(stderr.String())[before:]; len(lines) != 1 || !strings.Contains(lines[0], c.logged) {
			t.Errorf("%s: logged %q, want one line with %q", c.name, lines, c.logged)
		}
	}
	if err := s.stop(t); err != nil {
		t.Errorf("runServe returned %v once interrupted, want nil (exit 0)", err)
	}
	if lines := requestLines(stderr.String()); len(lines) != 2 {
		t.Errorf("%d request lines for two requests:\n%s", len(lines), stderr)
	}
	if strings.Contains(stderr.String(), serveToken) {
		t.Errorf("the log carries the token:\n%s", stderr)
	}
}
