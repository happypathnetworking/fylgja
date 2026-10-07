package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// readSummary is what a dry run's read saw, for the report's read: line.
type readSummary struct {
	counts   intent.Counts
	packages []intent.PackageCount
	envelope ctm.Envelope
}

// dryRunReport runs the host check in this process, against the bundle already filed at
// bundlePath, and reports what a real run would do: the nodes and their images, the memory
// they need against the host budget, what the host holds, and the verdict (contracts/cli.md).
// No workflow service is dialled and nothing on the host changes: the
// check is lab.CheckHost itself, the run's own host check, called without Temporal, so a
// refusal here carries the identifier the real run would refuse with.
// Sound because the server and the worker share the host (D-041); at M9 this moves behind
// the queue.
//
// read is nil when no read took place (twin provision). prior holds the read's and the
// compile's findings, reported with the host check's. follow is whether the twin would follow
// its branch (M4); the dry run schedules nothing either way.
func dryRunReport(ctx context.Context, opts *options, op string, subject *findings.Subject, reg *psp.Registry,
	paths lab.Paths, bundlePath, id string, read *readSummary, prior findings.List, follow findings.DryRunFollow) error {
	plan, err := lab.CheckHost(ctx, dryRunActivities(opts, reg, paths), wire.CheckHostInput{BundlePath: bundlePath, BundleID: id})
	if err != nil {
		return failAt(op, subject, findings.StepHostCheck, findings.StepHostCheck, "host check: %s", activityMessage(err))
	}

	// What would be pushed, and what the mapping loses, are the manifest's to say: the plan
	// carries only the file and checksum the push needs, and a dry run
	// of a bundle has no intent to survey. A manifest that cannot be
	// read here was just read by the host check, so this names nothing new and is an
	// operational failure.
	artifacts, lossy, err := manifestSummary(bundlePath)
	if err != nil {
		return failAt(op, subject, findings.StepHostCheck, findings.StepHostCheck, "host check: %v", err)
	}

	block, verdict := dryRunBlock(plan, artifacts, lossy, plan.Findings)
	block.Follow = &follow

	opts.note("dry run: no lab, container, twin directory or run is created")
	if read != nil {
		opts.note("read: %s (%s)", readCounts(read.counts, read.packages, lossy), readSubject(read.envelope))
	}
	opts.note("bundle_id %s  stored: %s", id, bundlePath)
	opts.note("nodes:")
	for _, n := range block.Nodes {
		push := ""
		if a := n.Artifact; a != nil {
			push = fmt.Sprintf("  push %s %s (%d bytes)", a.Name, a.Checksum, a.Size)
		}
		opts.note("  %s  %s  %s  %d MiB%s", n.Name, n.Image, n.PSP, n.MemoryMB, push)
	}
	opts.note("mapping: %d lossy mappings, %d shared ports", lossy.LossyMappings, lossy.SharedPorts)
	printDryRunHost(opts, plan)
	opts.note("follow: %s", followLine(subject.Branch, follow))
	opts.note("verdict: %s", verdict)

	list := append(append(findings.List{}, prior...), plan.Findings...)
	doc := findings.NewDocument(op, subject, list)
	doc.BundleID = id
	doc.DryRun = block
	return &result{doc: doc}
}

// dryRunActivities are the lab host's activities as a dry run calls them, in the server's
// process: lab.CheckHost and containerlab's own plan, through the server's runner, never the
// workflow service. Shared by the create's and provision's dry run, by twin step, whose host
// check and plan are read the same way, and by twin verify
// (D-041).
func dryRunActivities(opts *options, reg *psp.Registry, paths lab.Paths) *lab.Activities {
	return opts.c.activities(reg, paths)
}

// dryRunBlock is the dry_run block over the host check's plan: each node with what it would
// be pushed, the memory against the budget, what the host holds, the lossy counts, and the
// verdict, refused by every rejection in refusals, each rule named once in the order found.
// The second value is the verdict as the verdict: line prints it. Follow is the caller's.
func dryRunBlock(plan wire.CheckHostResult, artifacts map[string]*findings.DryRunArtifact, lossy compiler.SurveyCounts,
	refusals findings.List) (*findings.DryRunBlock, string) {
	block := &findings.DryRunBlock{
		Nodes:         make([]findings.DryRunNode, 0, len(plan.Nodes)),
		MemorySumMB:   plan.MemorySumMB,
		HostBudgetMB:  plan.HostBudgetMB,
		Host:          findings.DryRunHost{LabPresent: plan.LabPresent, TwinDirPresent: plan.TwinDirPresent},
		Verdict:       findings.VerdictClear,
		LossyMappings: lossy.LossyMappings,
		SharedPorts:   lossy.SharedPorts,
	}
	for _, n := range plan.Nodes {
		block.Nodes = append(block.Nodes, findings.DryRunNode{Name: n.Name, Image: n.Image, PSP: n.PSPID, MemoryMB: n.MemoryMB,
			Artifact: artifacts[n.Name]})
	}
	var refusedBy []string
	for _, f := range refusals {
		if f.Severity == findings.Rejection && !slices.Contains(refusedBy, f.Rule) {
			refusedBy = append(refusedBy, f.Rule)
		}
	}
	verdict := findings.VerdictClear
	if len(refusedBy) > 0 {
		block.Verdict = findings.VerdictRefused
		verdict = fmt.Sprintf("%s (%s)", findings.VerdictRefused, strings.Join(refusedBy, ", "))
	}
	return block, verdict
}

// printDryRunHost prints a dry run's memory: and host: lines from the host check's plan.
func printDryRunHost(opts *options, plan wire.CheckHostResult) {
	budget := "unset"
	if plan.HostBudgetMB != nil {
		budget = fmt.Sprintf("%d MiB", *plan.HostBudgetMB)
	}
	opts.note("memory: sum %d MiB; host budget %s", plan.MemorySumMB, budget)
	opts.note("host: %s; %s", presence("lab "+wire.LabName, plan.LabPresent), presence("twin directory", plan.TwinDirPresent))
}

// manifestSummary names, by node, what the bundle's manifest says each node would be
// pushed: name, content type, checksum and size, never a byte of it;
// and counts its lossy record.
func manifestSummary(bundlePath string) (map[string]*findings.DryRunArtifact, compiler.SurveyCounts, error) {
	b, err := os.ReadFile(filepath.Join(bundlePath, compiler.ManifestFile))
	if err != nil {
		return nil, compiler.SurveyCounts{}, fmt.Errorf("reading the bundle manifest: %w", err)
	}
	var m compiler.Manifest
	if err := json.Unmarshal(b, &m); err != nil {
		return nil, compiler.SurveyCounts{}, fmt.Errorf("reading the bundle manifest: %w", err)
	}
	out := make(map[string]*findings.DryRunArtifact, len(m.Nodes))
	for _, n := range m.Nodes {
		if a := n.Artifact; a != nil {
			out[n.Name] = &findings.DryRunArtifact{Name: a.Name, ContentType: a.ContentType, Checksum: a.Checksum, Size: a.Size}
		}
	}
	return out, m.LossyCounts(), nil
}

// readCounts is what a read holds, as `intent read`'s summary and a dry run's read line
// both say it (contracts/cli.md).
//
// The devices are broken down by support package, in package id order: with
// two platforms in one read, how many nodes of each is the first thing an operator wants,
// and a read of one platform says so in the same shape.
func readCounts(n intent.Counts, packages []intent.PackageCount, lossy compiler.SurveyCounts) string {
	parts := make([]string, 0, len(packages))
	for _, p := range packages {
		parts = append(parts, fmt.Sprintf("%s %d", p.PSPID, p.Devices))
	}
	devices := fmt.Sprintf("%d devices", n.Devices)
	if len(parts) > 0 {
		devices += " (" + strings.Join(parts, ", ") + ")"
	}
	return fmt.Sprintf("%s, %d interfaces, %d links, %d artifacts, %d lossy mappings, %d shared ports",
		devices, n.Interfaces, n.Links, n.Artifacts, lossy.LossyMappings, lossy.SharedPorts)
}

// followLine is the dry run's follow: line (contracts/cli.md).
func followLine(branch string, follow findings.DryRunFollow) string {
	if follow.Enabled {
		return fmt.Sprintf("would follow branch %s, checked every %s", branch, time.Duration(follow.IntervalS)*time.Second)
	}
	why := map[string]string{
		findings.FollowReasonPinned:   "--at given",
		findings.FollowReasonNoFollow: "--no-follow given",
		findings.FollowReasonBundle:   "a bundle never follows",
		findings.FollowReasonWaypoint: "--waypoint given: a waypoint is pinned",
	}[follow.Reason]
	return "would not follow (" + why + ")"
}

func presence(what string, present bool) string {
	if present {
		return what + " present"
	}
	return what + " absent"
}

// activityMessage is what an activity's failure says, without the SDK's type annotation.
func activityMessage(err error) string {
	var appErr *temporal.ApplicationError
	if errors.As(err, &appErr) {
		return appErr.Message()
	}
	return err.Error()
}
