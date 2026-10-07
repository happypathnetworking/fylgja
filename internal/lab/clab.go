package lab

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// LabName is the containerlab lab name, fixed and written by the compiler
// (Constitution VII).
const LabName = wire.LabName

// containerPrefix is how containerlab names a lab's containers: clab-<lab>-<node>.
const containerPrefix = "clab-" + LabName + "-"

// Runner executes a command on the lab host and reports what it printed and how it
// exited. Clab drives containerlab through it so tier-1 tests can substitute the
// recorded output of the real tool (D-017).
//
// args[0] is the program. env holds only the entries that override the inherited
// environment. err is non-nil when the command could not be run to completion (not
// found, or cancelled); a command that ran and failed reports its exit status with a
// nil err.
type Runner interface {
	Run(ctx context.Context, env []string, args ...string) (stdout, stderr []byte, exit int, err error)
}

// Process is one process on the lab host: its pid and its command line.
type Process struct {
	PID  int
	Args []string
}

// ProcessTable lists the lab host's processes and kills one. Clab looks through it for a
// containerlab still acting on lab fylgja that nothing waits for; tier-1 tests substitute
// a fake, so no test lists or signals the host's real processes (D-017).
type ProcessTable interface {
	Processes() ([]Process, error)
	Kill(pid int) error
}

// LabState is lab fylgja as containerlab reports it.
type LabState struct {
	Present bool
	Nodes   []wire.LabNode // sorted by name
	// TopoPaths is each container's absLabPath, distinct, sorted: the topology file the
	// lab was deployed from. It is used on the worker, in messages that
	// name an orphan, and never crosses the queue.
	TopoPaths []string
}

// ToolError is containerlab having run and failed: its exit status and what it said on
// stderr, which is where it explains itself.
type ToolError struct {
	Command string
	Exit    int
	Stderr  string
}

func (e *ToolError) Error() string {
	msg := strings.TrimSpace(e.Stderr)
	if msg == "" {
		msg = "no message on stderr"
	}
	return fmt.Sprintf("%s exited %d: %s", e.Command, e.Exit, msg)
}

// Clab drives the containerlab CLI (D-008). Every invocation is logged with
// its full argument list and environment override, so a broken lab can be reproduced by
// hand with the same command.
type Clab struct {
	Runner Runner
	Log    *slog.Logger
	// Bin is the containerlab executable; "clab" when empty.
	Bin string
	// Procs is the host's process table; /proc when nil.
	Procs ProcessTable
}

// InspectAll reports whether lab fylgja exists and its nodes. `clab inspect --all` is
// the one call that tells "no lab" (`{}`, exit 0) from an error (non-zero exit):
// `inspect --name` exits 1 for both, so it is never used to test existence.
func (c *Clab) InspectAll(ctx context.Context) (LabState, error) {
	stdout, err := c.run(ctx, nil, "inspect", "--all", "--format", "json")
	if err != nil {
		return LabState{}, err
	}
	return parseLabs(stdout)
}

// Deploy runs `clab deploy` on the staged topology with containerlab's working
// directory placed under labDirBase (CLAB_LABDIR_BASE), so the twin directory holds the
// bundle copy and clab-fylgja/ side by side. reconfigure recreates a lab that is
// already present, which is the only re-deploy that re-applies the bootstrap after a
// cut-off attempt. On success stdout is the same document inspect returns; a
// failure prints nothing there and is a *ToolError carrying stderr.
func (c *Clab) Deploy(ctx context.Context, topoPath, labDirBase string, reconfigure bool) (LabState, error) {
	args := []string{"deploy", "--topo", topoPath, "--format", "json"}
	if reconfigure {
		args = append(args, "--reconfigure")
	}
	stdout, err := c.run(ctx, []string{"CLAB_LABDIR_BASE=" + labDirBase}, args...)
	if err != nil {
		return LabState{}, err
	}
	return parseLabs(stdout)
}

// DeployPlan is containerlab's plan for the running lab against the topology at topoPath:
// `clab deploy --dry-run --topo <topoPath> --format json`, with CLAB_LABDIR_BASE set to
// labDirBase. The dry run reads the lab state
// containerlab stored under labDirBase at deploy (clab-<lab>/.state.clab.yaml) and the
// containers, and writes nothing. labDirBase is the twin directory: without that state an
// image or kind change is invisible and the plan comes back empty. topoPath is
// the target's topology in the store on both sides: PlanReconcile runs before StageStep,
// while twin/bundle still holds the from bundle, and is given the store's copy.
//
// Each list is containerlab's own, sorted, and Reasons its node-change-reasons text. A
// list containerlab writes as null is empty. A plan that would deploy the lab afresh
// (deployed-lab true, every list null: verified 2026-10-02) is not a
// reconcile: containerlab found no running lab under labDirBase, and that is refused, as
// is a document that is not a dry run.
func (c *Clab) DeployPlan(ctx context.Context, topoPath, labDirBase string) (wire.ReconcilePlan, error) {
	stdout, err := c.run(ctx, []string{"CLAB_LABDIR_BASE=" + labDirBase},
		"deploy", "--dry-run", "--topo", topoPath, "--format", "json")
	if err != nil {
		return wire.ReconcilePlan{}, err
	}
	return parsePlan(stdout, labDirBase)
}

// planDocument is the document `clab deploy --dry-run --format json` prints (containerlab
// 0.79.0).
type planDocument struct {
	DryRun            *bool             `json:"dry-run"`
	DeployedLab       bool              `json:"deployed-lab"`
	LabName           string            `json:"lab-name"`
	AddedNodes        []string          `json:"added-nodes"`
	DeletedNodes      []string          `json:"deleted-nodes"`
	RecreatedNodes    []string          `json:"recreated-nodes"`
	RestartedNodes    []string          `json:"restarted-nodes"`
	AddedLinks        []string          `json:"added-links"`
	DeletedEndpoints  []string          `json:"deleted-endpoints"`
	NodeChangeReasons map[string]string `json:"node-change-reasons"`
}

// parsePlan reads a dry-run document into a ReconcilePlan.
func parsePlan(stdout []byte, labDirBase string) (wire.ReconcilePlan, error) {
	var doc planDocument
	if err := json.Unmarshal(stdout, &doc); err != nil {
		return wire.ReconcilePlan{}, fmt.Errorf("reading containerlab's dry-run plan: %w", err)
	}
	if doc.DryRun == nil || !*doc.DryRun {
		return wire.ReconcilePlan{}, fmt.Errorf("containerlab's answer to a dry run is not a dry-run plan")
	}
	if doc.DeployedLab {
		return wire.ReconcilePlan{}, fmt.Errorf("containerlab's plan would deploy lab %s afresh: it finds no running lab to reconcile under %s",
			doc.LabName, labDirBase)
	}
	sorted := func(l []string) []string {
		out := append([]string{}, l...)
		sort.Strings(out)
		return out
	}
	plan := wire.ReconcilePlan{
		Added:            sorted(doc.AddedNodes),
		Deleted:          sorted(doc.DeletedNodes),
		Recreated:        sorted(doc.RecreatedNodes),
		Restarted:        sorted(doc.RestartedNodes),
		LinksAdded:       sorted(doc.AddedLinks),
		EndpointsDeleted: sorted(doc.DeletedEndpoints),
	}
	if len(doc.NodeChangeReasons) > 0 {
		plan.Reasons = doc.NodeChangeReasons
	}
	return plan, nil
}

// Reconcile applies the topology at topoPath to the running lab: `clab deploy` exactly as
// Deploy runs it but without --reconfigure, which would recreate every node. containerlab
// then acts on its own plan: it
// re-cables a node live, restarts one for a link change, recreates one whose image or kind
// drifted, creates an added node and deletes a removed one, leaving every other container
// as it was. Its lifecycle lines on stderr (Restarting node after link apply, Deleting node
// for recreate, Creating node) are logged, since they are the only account of what it did
// beyond the plan. On success stdout is the inspect document, as Deploy's is; a failure is
// a *ToolError carrying stderr.
func (c *Clab) Reconcile(ctx context.Context, topoPath, labDirBase string) (LabState, error) {
	stdout, stderr, err := c.runCapture(ctx, []string{"CLAB_LABDIR_BASE=" + labDirBase},
		"deploy", "--topo", topoPath, "--format", "json")
	log := c.logger()
	for _, line := range strings.Split(string(stderr), "\n") {
		for _, lifecycle := range reconcileLifecycleLines {
			if strings.Contains(line, lifecycle) {
				log.Info("containerlab reconcile", "line", strings.TrimSpace(line))
				break
			}
		}
	}
	if err != nil {
		return LabState{}, err
	}
	return parseLabs(stdout)
}

// reconcileLifecycleLines are the stderr lines in which containerlab says what its
// reconcile did to a node.
var reconcileLifecycleLines = []string{"Restarting node after link apply", "Deleting node for recreate", "Creating node",
	"Applying link change without node lifecycle action", "Deleting node"}

// Destroy removes lab fylgja by name, with its working directory. By name, because the
// containers' labels carry the topology path, so an orphan with no twin directory is
// cleared too.
func (c *Clab) Destroy(ctx context.Context) error {
	_, err := c.run(ctx, nil, "destroy", "--name", LabName, "--cleanup")
	return err
}

// StrayStopTimeout bounds how long StopStrays waits for a killed containerlab to exit. A
// mechanism constant, not a platform budget.
const StrayStopTimeout = 10 * time.Second

// strayPollInterval is how often StopStrays looks again for a killed containerlab.
const strayPollInterval = 100 * time.Millisecond

// StopStrays kills every containerlab still deploying or destroying lab fylgja — of the
// twin's topology topo, or of the lab by name — and returns once none is left, so that the
// command this worker runs next is the only one acting on the lab.
//
// Such a process is one nothing waits for. containerlab is installed setuid root, and the
// kernel drops the parent-death signal when a setuid binary starts, so a deploy outlives a
// worker killed under it and carries on; the retried step would otherwise
// run a second deploy of the same lab beside it, and one deploy acts on a lab at a time. Killing
// it leaves the lab as a deploy killed part-way leaves it, which `--reconfigure` and
// `destroy --cleanup` both converge from. The kill is permitted: the process runs
// with the worker's real user id.
func (c *Clab) StopStrays(ctx context.Context, topo string) ([]Process, error) {
	procs := c.procs()
	strays, err := straysIn(procs, topo)
	if err != nil || len(strays) == 0 {
		return nil, err
	}
	log := c.logger()
	for _, p := range strays {
		command := strings.Join(p.Args, " ")
		log.Warn("stopping a containerlab still acting on lab "+LabName+" that no activity waits for",
			"pid", p.PID, "command", command)
		if err := procs.Kill(p.PID); err != nil {
			return strays, fmt.Errorf("containerlab pid %d (%s) is still acting on lab %s and could not be stopped: %w; stop it with sudo kill -9 %d",
				p.PID, command, LabName, err, p.PID)
		}
	}

	wait, cancel := context.WithTimeout(ctx, StrayStopTimeout)
	defer cancel()
	tick := time.NewTicker(strayPollInterval)
	defer tick.Stop()
	for {
		left, err := straysIn(procs, topo)
		if err != nil {
			return strays, err
		}
		left = slices.DeleteFunc(left, func(p Process) bool {
			return !slices.ContainsFunc(strays, func(s Process) bool { return s.PID == p.PID })
		})
		if len(left) == 0 {
			log.Info("stopped every containerlab acting on lab "+LabName, "stopped", len(strays))
			return strays, nil
		}
		select {
		case <-wait.Done():
			p := left[0]
			return strays, fmt.Errorf("containerlab pid %d (%s) is still acting on lab %s after it was killed: %w; stop it with sudo kill -9 %d",
				p.PID, strings.Join(p.Args, " "), LabName, wait.Err(), p.PID)
		case <-tick.C:
		}
	}
}

// straysIn lists the processes acting on lab fylgja.
func straysIn(procs ProcessTable, topo string) ([]Process, error) {
	all, err := procs.Processes()
	if err != nil {
		return nil, fmt.Errorf("listing the host's processes for a containerlab acting on lab %s: %w", LabName, err)
	}
	var out []Process
	for _, p := range all {
		if actsOnLab(p.Args, topo) {
			out = append(out, p)
		}
	}
	return out, nil
}

// actsOnLab reports whether args are a containerlab deploy or destroy of lab fylgja: of the
// twin's topology, or of the lab by name. An inspect, another lab, or a different program
// naming the topology is not.
func actsOnLab(args []string, topo string) bool {
	if len(args) < 2 {
		return false
	}
	switch filepath.Base(args[0]) {
	case "clab", "containerlab":
	default:
		return false
	}
	acts, ours := false, false
	for i := 1; i < len(args); i++ {
		switch a := args[i]; {
		case a == "deploy" || a == "destroy" || a == "redeploy":
			acts = true
		case (a == "--topo" || a == "-t" || a == "--name" || a == "-n") && i+1 < len(args):
			if v := args[i+1]; v == topo || v == LabName {
				ours = true
			}
		case a == "--topo="+topo || a == "-t="+topo || a == "--name="+LabName || a == "-n="+LabName:
			ours = true
		}
	}
	return acts && ours
}

func (c *Clab) procs() ProcessTable {
	if c.Procs == nil {
		return procTable{}
	}
	return c.Procs
}

func (c *Clab) logger() *slog.Logger {
	if c.Log == nil {
		return slog.Default()
	}
	return c.Log
}

func (c *Clab) run(ctx context.Context, env []string, args ...string) ([]byte, error) {
	stdout, _, err := c.runCapture(ctx, env, args...)
	return stdout, err
}

// runCapture is run, with what containerlab printed on stderr returned beside stdout
// whether or not it succeeded.
func (c *Clab) runCapture(ctx context.Context, env []string, args ...string) ([]byte, []byte, error) {
	bin := c.Bin
	if bin == "" {
		bin = "clab"
	}
	full := append([]string{bin}, args...)
	command := strings.Join(full, " ")
	log := c.logger()
	// Only the override is logged, never the inherited environment: that holds
	// credentials.
	log.Info("containerlab", "command", command, "env", env)
	start := time.Now()
	stdout, stderr, exit, err := c.Runner.Run(ctx, env, full...)
	var failed error
	switch {
	case err != nil:
		failed = fmt.Errorf("%s: %w", command, err)
	case exit != 0:
		failed = &ToolError{Command: command, Exit: exit, Stderr: string(stderr)}
	}
	// A failed invocation is a warning, carrying its override again, so a logger that keeps
	// only warnings, such as the dry run's, still records the command that broke.
	level, msg := slog.LevelInfo, "containerlab finished"
	if failed != nil {
		level, msg = slog.LevelWarn, "containerlab failed"
	}
	log.Log(ctx, level, msg, "command", command, "env", env, "exit", exit,
		"duration", time.Since(start).Round(time.Millisecond).String(), "error", errString(failed))
	if failed != nil {
		return nil, stderr, failed
	}
	return stdout, stderr, nil
}

func errString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

// clabContainer is one entry of containerlab's JSON document. Only the fields
// Fylgja uses are decoded; `status` is human text and deliberately not parsed, and
// `labPath` is not decoded because it is relative to the caller's directory when the
// file is under it — `absLabPath` is always absolute.
type clabContainer struct {
	Name        string `json:"name"`
	Kind        string `json:"kind"`
	Image       string `json:"image"`
	State       string `json:"state"`
	IPv4Address string `json:"ipv4_address"`
	AbsLabPath  string `json:"absLabPath"`
}

// parseLabs reads the document inspect and deploy print: an object keyed by lab name.
// Other labs on the host are not Fylgja's and are ignored.
func parseLabs(stdout []byte) (LabState, error) {
	var labs map[string][]clabContainer
	if err := json.Unmarshal(stdout, &labs); err != nil {
		return LabState{}, fmt.Errorf("reading containerlab's JSON output: %w", err)
	}
	containers, ok := labs[LabName]
	if !ok {
		return LabState{}, nil
	}
	state := LabState{Present: true}
	paths := map[string]bool{}
	for _, ct := range containers {
		if ct.AbsLabPath != "" && !paths[ct.AbsLabPath] {
			paths[ct.AbsLabPath] = true
			state.TopoPaths = append(state.TopoPaths, ct.AbsLabPath)
		}
		addr, _, _ := strings.Cut(ct.IPv4Address, "/")
		state.Nodes = append(state.Nodes, wire.LabNode{
			Name:      strings.TrimPrefix(ct.Name, containerPrefix),
			Container: ct.Name,
			Kind:      ct.Kind,
			Image:     ct.Image,
			State:     ct.State,
			MgmtIPv4:  addr,
		})
	}
	sort.Slice(state.Nodes, func(i, j int) bool { return state.Nodes[i].Name < state.Nodes[j].Name })
	sort.Strings(state.TopoPaths)
	return state, nil
}

// procTable is the lab host's process table, read from /proc.
type procTable struct{}

// Processes implements ProcessTable. A process with no command line — a zombie awaiting
// its reaper, or a kernel thread — is left out: it acts on nothing.
func (procTable) Processes() ([]Process, error) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, err
	}
	var out []Process
	for _, e := range entries {
		pid, err := strconv.Atoi(e.Name())
		if err != nil {
			continue
		}
		b, err := os.ReadFile(filepath.Join("/proc", e.Name(), "cmdline"))
		if err != nil || len(b) == 0 {
			continue // exited since the listing, a zombie, or a kernel thread
		}
		out = append(out, Process{PID: pid, Args: strings.Split(strings.TrimRight(string(b), "\x00"), "\x00")})
	}
	return out, nil
}

// Kill implements ProcessTable with SIGKILL. A process already gone is not an error.
func (procTable) Kill(pid int) error {
	if err := syscall.Kill(pid, syscall.SIGKILL); err != nil && !errors.Is(err, syscall.ESRCH) {
		return err
	}
	return nil
}

// childWaitDelay bounds how long the runner waits for a killed child's output pipes to
// close. A mechanism constant, not a platform budget.
const childWaitDelay = 5 * time.Second

// ExecRunner runs commands as children of the worker. Linux only, as the lab host always
// is. The child gets its own process group, and cancellation kills the whole group, so no
// grandchild outlives the activity.
//
// The child is also started with a parent-death signal, so a child the kernel lets it
// apply to dies with the worker. containerlab is not one: it is installed setuid root, and
// the kernel clears the parent-death signal when a setuid binary starts, so a `clab` does
// outlive a killed worker. Clab.StopStrays, not this signal, is what keeps
// such a `clab` from acting beside the retried step.
type ExecRunner struct{}

// childSysProcAttr is the process attributes every child is started with.
func childSysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
}

// Run implements Runner. It returns only after the child has exited, including when ctx
// is cancelled: a cancelled activity must not report itself stopped while its `clab` is
// still acting on the host.
func (ExecRunner) Run(ctx context.Context, env []string, args ...string) ([]byte, []byte, int, error) {
	if len(args) == 0 {
		return nil, nil, -1, errors.New("no command to run")
	}
	type outcome struct {
		stdout, stderr []byte
		exit           int
		err            error
	}
	done := make(chan outcome, 1)
	go func() {
		// Pdeathsig fires when the thread that started the child exits, not the process.
		// Holding this goroutine on its thread until the child has exited makes the
		// signal mean "the worker died", never "the runtime retired a thread".
		runtime.LockOSThread()
		defer runtime.UnlockOSThread()

		var stdout, stderr bytes.Buffer
		cmd := exec.Command(args[0], args[1:]...)
		cmd.Env = append(os.Environ(), env...)
		cmd.Stdout, cmd.Stderr = &stdout, &stderr
		cmd.SysProcAttr = childSysProcAttr()
		cmd.WaitDelay = childWaitDelay
		if err := cmd.Start(); err != nil {
			done <- outcome{exit: -1, err: err}
			return
		}
		waited := make(chan error, 1)
		go func() { waited <- cmd.Wait() }()

		var waitErr, runErr error
		select {
		case waitErr = <-waited:
		case <-ctx.Done():
			// The negative pid is the process group: the child and everything it started.
			_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
			waitErr = <-waited
			runErr = ctx.Err()
		}
		exit := 0
		var exitErr *exec.ExitError
		switch {
		case errors.As(waitErr, &exitErr):
			exit = exitErr.ExitCode()
		case waitErr != nil && runErr == nil:
			runErr = waitErr
		}
		done <- outcome{stdout: stdout.Bytes(), stderr: stderr.Bytes(), exit: exit, err: runErr}
	}()
	o := <-done
	return o.stdout, o.stderr, o.exit, o.err
}
