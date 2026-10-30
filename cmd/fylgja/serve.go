package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/server"
)

// The server's own timeouts. Mechanism constants, none a
// platform's budget (Constitution II). There is no write timeout: an answer lasts as long
// as its run.
const (
	// serveReadHeaderTimeout bounds a request's headers.
	serveReadHeaderTimeout = 10 * time.Second
	// serveIdleTimeout bounds a kept-alive connection with no request.
	serveIdleTimeout = 120 * time.Second
)

// serveOptions are fylgja serve's: its flags, and what it reads of its process, which a
// test replaces.
type serveOptions struct {
	// listen is every address to listen on, in the order given; none is api.DefaultAddress.
	listen []string
	pspDir string

	stdout, stderr io.Writer
	// getenv reads the token, the override directory's fallback, the workflow service's
	// address for the report, and, at each request, the logins and the memory budget.
	getenv func(string) (string, bool)
	// images answers whether the host holds an image that is not pulled, for the report's
	// package lines, as the worker's does.
	images lab.Images
	// netListen makes each listener the server serves on; nil is net.Listen. A test gives
	// one whose Accept fails.
	netListen func(network, address string) (net.Listener, error)
}

func newServeCmd(version string) *cobra.Command {
	opts := &serveOptions{
		stdout: os.Stdout,
		stderr: os.Stderr,
		getenv: os.LookupEnv,
		images: lab.DockerImages{Runner: lab.ExecRunner{}},
	}
	cmd := &cobra.Command{
		Use:   "serve",
		Short: "Serve the API on this host",
		Long: "Serve the API, version " + api.Version + ", on the lab host beside fylgja worker run: every\n" +
			"other command is a request to it. Reads the API's token from FYLGJA_API_TOKEN, and no\n" +
			"source of truth: the orchestrator reads Infrahub. Runs until interrupted. Produces no findings document; start-up lines go to\n" +
			"stdout and logs to stderr.",
		// A usage error is a refusal to start, as the others are: a line on stderr and exit
		// 2, before anything listens, and no findings document, whose operation enum names
		// no serve (contracts/cli.md).
		Args: func(cmd *cobra.Command, args []string) error {
			if err := cobra.NoArgs(cmd, args); err != nil {
				return serveExit(opts, "%v", err)
			}
			return nil
		},
		RunE: func(cmd *cobra.Command, _ []string) error {
			ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			return runServe(ctx, opts, version)
		},
	}
	cmd.SetFlagErrorFunc(func(_ *cobra.Command, err error) error { return serveExit(opts, "%v", err) })
	cmd.Flags().StringArrayVar(&opts.listen, "listen", []string{api.DefaultAddress},
		"host:port to listen on, repeatable; an address that is not loopback carries the token unencrypted")
	cmd.Flags().StringVar(&opts.pspDir, "psp-dir", "",
		"directory of platform support packages overriding the embedded ones (or FYLGJA_PSP_DIR)")
	return cmd
}

// runServe serves the API until ctx ends: SIGINT or SIGTERM. Every refusal to start is one
// or more lines on stderr and exit 2, and each comes before anything listens.
// Nothing is dialled here: a request that needs the workflow service, Docker, containerlab or
// a node connects to it. From 020 the server reads no INFRAHUB_* and no FYLGJA_DEFAULT_SCOPE,
// since it reads no source of truth (D-065; FR-004).
func runServe(ctx context.Context, opts *serveOptions, version string) error {
	if ctx == nil {
		ctx = context.Background()
	}
	token, ok := opts.getenv(api.EnvToken)
	if !ok || token == "" {
		return serveExit(opts, "%s is not set; the server does not start without the API's token", api.EnvToken)
	}
	listen := opts.listen
	if len(listen) == 0 {
		listen = []string{api.DefaultAddress}
	}
	// Every address is checked before any is listened on.
	for _, addr := range listen {
		if _, _, err := net.SplitHostPort(addr); err != nil {
			return serveExit(opts, "--listen %s is not host:port", addr)
		}
	}
	paths, err := lab.ResolvePaths()
	if err != nil {
		return serveExit(opts, "%v", err)
	}
	pspDir := opts.pspDir
	if pspDir == "" {
		pspDir, _ = opts.getenv(lab.EnvPSPDir)
	}
	// psp.Load stats the override directory alone, and its glob passes over a file or a
	// directory it cannot list, which would serve the embedded packages instead. Both are
	// refused here, in psp.Load's words for a missing one.
	if err := listable(pspDir); err != nil {
		return serveExit(opts, "support package override directory: %v", err)
	}
	// A server must not serve with a package psp validate rejects: every request would be
	// refused under it. It is loaded again at each request, and checked once here.
	reg, err := psp.Load(pspDir)
	if err != nil {
		var invalid *psp.InvalidError
		if errors.As(err, &invalid) {
			doc := findings.NewDocument(findings.OpPSPValidate, nil, invalid.Findings)
			_ = doc.WriteText(opts.stderr)
			return serveExit(opts, "refusing to serve with an invalid support package")
		}
		return serveExit(opts, "%v", err)
	}
	// The probe packages (016, R-08) likewise: loaded again at each request, checked once here.
	probes, err := probe.Load(pspDir)
	if err != nil {
		var invalid *probe.InvalidError
		if errors.As(err, &invalid) {
			doc := findings.NewDocument(findings.OpPSPValidate, nil, invalid.Findings)
			_ = doc.WriteText(opts.stderr)
			return serveExit(opts, "refusing to serve with an invalid probe package")
		}
		return serveExit(opts, "%v", err)
	}
	netListen := opts.netListen
	if netListen == nil {
		netListen = net.Listen
	}
	// Every listener is opened before any serves. A failure closes those already opened, so
	// the server listens on none.
	listeners := make([]listener, 0, len(listen))
	for _, given := range listen {
		ln, err := netListen("tcp", given)
		if err != nil {
			for _, l := range listeners {
				_ = l.ln.Close()
			}
			return serveExit(opts, "listening on %s: %v", given, err)
		}
		listeners = append(listeners, listener{ln: ln, addr: reportedAddress(given, ln.Addr())})
	}

	logger := slog.New(slog.NewTextHandler(opts.stderr, nil))
	s := server.New(token)
	s.Paths = func() (lab.Paths, error) { return paths, nil }
	s.PSPDir = pspDir
	s.Getenv = opts.getenv
	s.Build = version
	s.Log = logger

	for _, line := range serveReport(ctx, opts, reg, probes, paths, listeners, version) {
		_, _ = fmt.Fprintln(opts.stdout, "fylgja serve: "+line)
	}

	srv := &http.Server{
		Handler:           s.Handler(),
		ReadHeaderTimeout: serveReadHeaderTimeout,
		IdleTimeout:       serveIdleTimeout,
		ErrorLog:          slog.NewLogLogger(logger.Handler(), slog.LevelWarn),
		// OPTIONS * is the API's too: net/http would answer it 200 itself, before the token
		// is compared, and log no line (contracts/api.md "The token").
		DisableGeneralOptionsHandler: true,
	}
	// One server serves every listener; each Serve returns once, into served.
	served := make(chan servedEnd, len(listeners))
	for _, l := range listeners {
		go func() { served <- servedEnd{addr: l.addr, err: srv.Serve(l.ln)} }()
	}
	// drain waits for every serving goroutine but those already received, once Close has
	// been called. After Close, Serve returns http.ErrServerClosed; anything else is a
	// failure that raced the stop, logged and not returned, since the stop is already decided.
	drain := func(remaining int) {
		for range remaining {
			if end := <-served; !errors.Is(end.err, http.ErrServerClosed) {
				logger.Warn("serving ended with an error while stopping", "addr", end.addr, "err", end.err)
			}
		}
	}
	select {
	case <-ctx.Done():
		// Every listener and every connection is closed at once, an answer in flight
		// included. A run goes on, since the worker holds it, and its client reports the API
		// unreachable.
		_ = srv.Close()
		drain(len(listeners))
		return nil
	case end := <-served:
		// A failure to accept on one listener ends the server on all of them.
		_ = srv.Close()
		drain(len(listeners) - 1)
		return serveExit(opts, "serving on %s: %v", end.addr, end.err)
	}
}

// listener is one address the server listens on, and the address its report names.
type listener struct {
	ln   net.Listener
	addr string
}

// servedEnd is what one listener's Serve returned.
type servedEnd struct {
	addr string
	err  error
}

// reportedAddress is the address as the operator gave it, with the port it got: one asked
// for as 0 is named by the port the system chose.
func reportedAddress(given string, got net.Addr) string {
	host, _, _ := net.SplitHostPort(given)
	if tcp, ok := got.(*net.TCPAddr); ok {
		return net.JoinHostPort(host, fmt.Sprint(tcp.Port))
	}
	return given
}

// listable refuses an override directory that is not a directory, or that cannot be
// listed; no directory at all is none to refuse.
func listable(dir string) error {
	if dir == "" {
		return nil
	}
	info, err := os.Stat(dir)
	if err != nil {
		return err
	}
	if !info.IsDir() {
		return fmt.Errorf("%s is not a directory", dir)
	}
	_, err = os.ReadDir(dir)
	return err
}

// serveReport is what the server says once it listens and before it takes a request, one
// line each with no prefix: each address it listens on, in the order given, with the API's
// version and its build, each followed straight away, when it is not loopback, by a line
// saying the token is sent unencrypted on it; the state root; that the workflow service,
// Docker, containerlab and the nodes, and nothing else, are dialled when a request needs them
// (020: no Infrahub and no default scope, FR-004); and the worker's own lines for the memory
// budget, each package and each probe package (016). It names variables, never their values.
func serveReport(ctx context.Context, opts *serveOptions, reg *psp.Registry, probes *probe.Registry, paths lab.Paths,
	listeners []listener, version string) []string {
	var lines []string
	for _, l := range listeners {
		lines = append(lines, fmt.Sprintf("listening on %s (API version %s, build %s)", l.addr, api.Version, version))
		if !loopback(l.ln.Addr()) {
			lines = append(lines, l.addr+" is not a loopback address: the API's token is sent unencrypted on it")
		}
	}
	lines = append(lines,
		fmt.Sprintf("state root %s (bundles: %s, snapshots: %s, twin: %s)", paths.Root, paths.Bundles, paths.Snapshots, paths.Twin),
		fmt.Sprintf("the workflow service (%s, namespace %s), Docker, containerlab and the nodes are dialled when a request needs them",
			envOr(opts.getenv, lab.EnvTemporalAddress, provision.DefaultAddress),
			envOr(opts.getenv, lab.EnvTemporalNamespace, provision.DefaultNamespace)),
		provision.BudgetLine(opts.getenv),
	)
	lines = append(lines, provision.LoginLines(ctx, reg, opts.images, opts.getenv)...)
	return append(lines, provision.ProbePackageLines(ctx, probes, opts.images)...)
}

// loopback is whether the listener's address is a loopback one. A host name is judged by
// the address it was resolved to, and a wildcard is not loopback.
func loopback(a net.Addr) bool {
	tcp, ok := a.(*net.TCPAddr)
	return ok && tcp.IP.IsLoopback()
}

// envOr is a variable's value, or fallback when it is unset or empty, as provision.Dial
// reads the workflow service's.
func envOr(getenv func(string) (string, bool), name, fallback string) string {
	if v, ok := getenv(name); ok && v != "" {
		return v
	}
	return fallback
}

// serveExit prints one line on stderr and exits 2.
func serveExit(opts *serveOptions, format string, args ...any) error {
	_, _ = fmt.Fprintf(opts.stderr, "fylgja serve: "+format+"\n", args...)
	return exitStatus(findings.ExitError)
}
