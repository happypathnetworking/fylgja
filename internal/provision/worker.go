package provision

import (
	"context"
	"errors"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// HeartbeatThrottle caps how long the SDK may hold back an activity's heartbeat. It also
// sets how long a heartbeat call may go unanswered before the SDK gives up on it and
// abandons the attempt: about half the throttle, whether the workflow service is
// unreachable or merely slow. At 2s that was 1s, and one stall cut a deploy short on a
// host with nothing else running; at 5s it was 2.5s, and
// four of six tier-3 runs still lost a working deploy to it once the host also carried
// Infrahub. At 10s it is about 5s.
//
// It must not exceed lab.HeartbeatInterval, which is raised with it: a cancellation
// travels on the answer to a heartbeat, so the pair also bounds how late one reaches a
// running clab — about 10s now, rather than the SDK's default of 80% of the heartbeat
// timeout (D-030). A mechanism constant.
const HeartbeatThrottle = 10 * time.Second

// workerOptions are the options the one worker runs with.
func workerOptions() worker.Options {
	return worker.Options{MaxHeartbeatThrottleInterval: HeartbeatThrottle}
}

// NewWorker assembles the one worker on task queue fylgja: the provisioning and destroy
// runs, the check (registered under the type name Schedule fylgja-follow starts), the step
// run (M11), the control
// activities and every host-bound activity, each registered by the name workflows
// schedule it by (D-015). There is one registration site, here.
func NewWorker(c client.Client, acts *lab.Activities, control *ControlActivities) worker.Worker {
	w := worker.New(c, TaskQueue, workerOptions())
	w.RegisterWorkflow(Provision)
	w.RegisterWorkflow(Destroy)
	w.RegisterWorkflowWithOptions(Reconcile, workflow.RegisterOptions{Name: reconcileWorkflowType})
	w.RegisterWorkflow(Step)
	registerActivities(w, control.Names())
	registerActivities(w, acts.Names())
	return w
}

// registerActivities registers a name → method table, in name order so registration
// never depends on map order.
func registerActivities(w worker.Worker, table map[string]any) {
	names := make([]string, 0, len(table))
	for name := range table {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		w.RegisterActivityWithOptions(table[name], activity.RegisterOptions{Name: name})
	}
}

// StartupReport is what a worker says when it starts, one line each (contracts/cli.md,
// worker run): the queue and the service it serves, its state root, the host memory
// budget, whether each loaded package's probe login variables are set — by name, never a
// value — then each package's image, whether this host holds one that is not pulled, and
// how it pushes a node its configuration (M5), and what the host holds of a
// twin.
//
// The last line is the orphan detection Constitution VII requires at worker start: the
// host check's own inspection, lab.InspectHost. It is reported and never acted on; there
// is no sweeper (D-007).
func StartupReport(ctx context.Context, acts *lab.Activities, address, namespace string) []string {
	getenv := acts.Getenv
	if getenv == nil {
		getenv = os.LookupEnv
	}
	lines := []string{
		fmt.Sprintf("serving task queue %s at %s (namespace %s)", TaskQueue, address, namespace),
		fmt.Sprintf("state root %s (bundles: %s, twin: %s)", acts.Paths.Root, acts.Paths.Bundles, acts.Paths.Twin),
		BudgetLine(getenv),
	}
	lines = append(lines, LoginLines(ctx, acts.Registry, acts.Images, getenv)...)
	lines = append(lines, hostLine(ctx, acts))
	for i, l := range lines {
		lines[i] = "fylgja worker: " + l
	}
	return lines
}

// BudgetLine reports FYLGJA_HOST_MEMORY_MB as the host check will read it, with no
// prefix. fylgja serve's start-up report prints it too, under its own prefix, so the two
// roles say it alike (M13).
func BudgetLine(getenv func(string) (string, bool)) string {
	mb, set, err := lab.HostBudgetMB(getenv)
	switch {
	case err != nil:
		return "host memory budget: invalid: " + err.Error() + "; every host check fails until it is corrected"
	case !set:
		return "host memory budget: unset (memory sums will be warnings)"
	default:
		return fmt.Sprintf("host memory budget: %d MiB", mb)
	}
}

// LoginLines names, for each loaded package in platform id order, the variables its
// readiness probe logs in with and whether each is set. Only presence is looked at, as the
// host check looks at it (a variable set to the empty string is unset), so no value is
// ever held here. Each line has no prefix: fylgja serve's start-up report prints them too,
// under its own (M13).
func LoginLines(ctx context.Context, reg *psp.Registry, images lab.Images, getenv func(string) (string, bool)) []string {
	if reg == nil {
		return nil
	}
	// Registry.index answers an id with the package whose NOS sorts first; so does this.
	byID := map[string]*psp.PSP{}
	var ids []string
	for _, nos := range reg.Platforms() {
		p, _ := reg.Lookup(nos)
		if _, seen := byID[p.Platform.ID]; seen {
			continue
		}
		byID[p.Platform.ID] = p
		ids = append(ids, p.Platform.ID)
	}
	sort.Strings(ids)

	lines := make([]string, 0, len(ids))
	for _, id := range ids {
		login := byID[id].Readiness.Login
		var parts []string
		for _, name := range []string{login.UsernameEnv, login.PasswordEnv} {
			if name == "" {
				continue
			}
			state := "unset"
			if v, ok := getenv(name); ok && v != "" {
				state = "set"
			}
			parts = append(parts, name+" "+state)
		}
		if len(parts) == 0 {
			parts = []string{"no login variables declared"}
		}
		lines = append(lines, fmt.Sprintf("probe login %s: %s", id, strings.Join(parts, ", ")))
		lines = append(lines, packageLine(ctx, byID[id], images, getenv))
	}
	return lines
}

// packageLine names a package's image and its push (M5 contracts/cli.md, worker run):
// `nokia_srlinux (embedded): image …, push json_rpc merge over https:443, login U/P (probe
// and push)`. A push login that is the probe's is named once, its presence already on the
// probe login line; one of its own is named with whether each variable is set. An image
// that is not pulled carries whether this host holds it (M7).
func packageLine(ctx context.Context, p *psp.PSP, images lab.Images, getenv func(string) (string, bool)) string {
	c := p.Config
	line := fmt.Sprintf("%s (%s): %s, push %s %s", p.Platform.ID, p.Origin, imageClause(ctx, p, images), c.Delivery, c.Mode)
	if c.Push == nil {
		return line
	}
	line += fmt.Sprintf(" over %s:%d", c.Push.Scheme, c.Push.Port)
	push, probe := c.Push.Login, p.Readiness.Login
	if push == probe {
		return line + fmt.Sprintf(", login %s/%s (probe and push)", push.UsernameEnv, push.PasswordEnv)
	}
	var parts []string
	for _, name := range []string{push.UsernameEnv, push.PasswordEnv} {
		state := "unset"
		if v, ok := getenv(name); ok && v != "" {
			state = "set"
		}
		parts = append(parts, name+" "+state)
	}
	return line + ", login " + strings.Join(parts, ", ") + " (push)"
}

// imageClause names a package's image and, for one whose acquisition is not
// public_registry, whether this host already holds it: a create that needs an image the
// host does not hold is refused at its host check, and the worker serves either
// way, so an operator learns of it at start rather than at the refusal. A runtime that
// will not answer is reported rather than guessed at; every host check then fails
// operation.failed until it is fixed.
func imageClause(ctx context.Context, p *psp.PSP, images lab.Images) string {
	ref := "image " + p.Image.Ref
	if p.Image.Acquisition == psp.AcquisitionPublicRegistry {
		return ref
	}
	var state string
	switch present, err := imagePresent(ctx, images, p.Image.Ref); {
	case err != nil:
		state = "image presence not checked: " + err.Error()
	case present:
		state = "present on this host"
	default:
		state = "absent from this host; a create needing it is refused"
	}
	return fmt.Sprintf("%s (%s, %s)", ref, p.Image.Acquisition, state)
}

// imagePresent asks the worker's image driver. A worker built without one says so rather
// than claiming an image is absent.
func imagePresent(ctx context.Context, images lab.Images, ref string) (bool, error) {
	if images == nil {
		return false, errors.New("this worker has no image driver")
	}
	return images.Present(ctx, ref)
}

// hostLine says whether lab fylgja and a twin directory are present and, when either is,
// names what was detected — the twin or an orphan, in the phrase the host check's refusals
// carry, from the same inspection — and the remedy. The worker still acts on
// nothing (D-007). An inspection that fails is reported rather than refused: every host
// check will report the same failure under its own identifier.
func hostLine(ctx context.Context, acts *lab.Activities) string {
	host, err := acts.InspectHost(ctx)
	if err != nil {
		return "host: not inspected: " + err.Error()
	}
	labState := "lab " + wire.LabName + " absent"
	if host.Lab.Present {
		labState = fmt.Sprintf("lab %s present (%s)", wire.LabName, plural(len(host.Lab.Nodes), "node"))
	}
	twin := "twin directory absent"
	if host.TwinDirPresent {
		twin = "twin directory present"
	}
	line := "host: " + labState + "; " + twin
	if host.Lab.Present || host.TwinDirPresent {
		line += "; " + host.Describe() + "; fylgja twin destroy clears it"
	}
	return line
}
