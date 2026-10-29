package server

import (
	"context"
	"errors"
	"fmt"
	"slices"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/probe"
)

// ProbeReader is the kind's read the server makes when a request names no probe file (016,
// R-06): intent.ProbeReader's two calls, on the default branch and unpinned, behind an
// interface so tier 1 hands the server its own (Server.Probes).
type ProbeReader interface {
	// Check holds FylgjaProbe and its ten attributes against the default branch's schema:
	// an *intent.ProbeKindError when it lacks either.
	Check(ctx context.Context) error
	// Probes is every probe declared there, in name order, [] when none.
	Probes(ctx context.Context) ([]probe.Probe, error)
}

// probeReader is the server's kind read: Server.Probes when a test set it, and otherwise the
// one Infrahub's address and token in the process environment name.
func (o *options) probeReader() (ProbeReader, error) {
	if o.c.s.Probes != nil {
		return o.c.s.Probes()
	}
	r, err := intent.ProbeReaderFromEnv()
	if err != nil {
		return nil, err
	}
	return r, nil
}

// takesProbes are the operations that take --probes (016; contracts/api.md, "016: probes"):
// each reads intent, and each take it makes carries the request's one list.
var takesProbes = []string{findings.OpIntentRead, findings.OpTwinCreate, findings.OpTwinStep, findings.OpStagePlan,
	findings.OpTwinRehearse}

// probesFiles holds the files of a request to the shape probes gives them, before the answer
// begins: a request naming probes carries the one file it names, under that path, and an
// operation that takes a file beside probes alone carries none without it. Any other is 400,
// the request is not one, as an argument not taken is: no client's command sends another.
// Beside snapshot, which twin.create and twin.step refuse as snapshot.flags.conflict, the
// files are the handler's, so the conflict answers whatever they are; without probes,
// twin.create's and twin.step's are snapshotFiles' to hold. The sentence names the
// argument and never a file's content.
func probesFiles(op string, a args, files []api.File) error {
	if !slices.Contains(takesProbes, op) {
		return nil
	}
	snapshotOp := op == findings.OpTwinCreate || op == findings.OpTwinStep
	switch {
	case !a.given("probes"):
		if len(files) > 0 && !snapshotOp {
			return fmt.Errorf("the request is not one: %s carries %s where it takes a probe file beside its argument %q alone",
				op, plural(len(files), "file"), "probes")
		}
	case a.given("snapshot"):
	case len(files) != 1:
		return fmt.Errorf("the request is not one: %s carries %s where it takes the probe file its argument %q names, "+
			"under that path, alone", op, plural(len(files), "file"), "probes")
	case files[0].Path != a.string("probes"):
		return fmt.Errorf("the request is not one: %s carries its probe file under another path than its argument %q gives",
			op, "probes")
	}
	return nil
}

// probesArg is --probes as a request gives it (016): whether it was given, the path, and the
// file probesFiles has held to that path, nil beside --snapshot, where the conflict answers.
type probesArg struct {
	given bool
	path  string
	file  *api.File
}

// probesOf is the request's --probes and the files left to the operation once its probe
// file is taken out: none beside a probes argument with no snapshot, which probesFiles has
// held to the one file it names, and every file otherwise.
func probesOf(a args, files []api.File) (probesArg, []api.File) {
	pa := probesArg{given: a.given("probes"), path: a.string("probes")}
	if pa.given && !a.given("snapshot") && len(files) == 1 {
		pa.file = &files[0]
		return pa, nil
	}
	return pa, files
}

// probeKindRemedy follows intent.ProbeKindError's sentence in every probe.kind.absent
// finding, naming the schema file to load, as stage.kind.absent names its own.
const probeKindRemedy = ": load " + intent.ProbeSchemaFile + " on it; only a request that sends no --probes file reads it"

// readProbes is the request's one probe list (016, R-06; FR-005–FR-007), read once, after
// the guards and before any read of intent, and handed to every take the request makes: the
// file --probes sent, parsed by probe.Parse and held to the declaration's rules with the
// formats the probe packages declare, each refusal at start; else the probes declared in
// FylgjaProbe on the default branch, unpinned (Check then Probes), held to the same rules,
// each refusal at resolve, the kind absent probe.kind.absent; and with neither, []. A file
// replaces the kind's probes, never adds to them. A refusal is the command's document,
// returned as the error, and an Infrahub that cannot be asked is operation.failed at resolve.
func readProbes(ctx context.Context, opts *options, op string, subject *findings.Subject, pa probesArg) ([]probe.Probe, error) {
	if pa.given {
		return fileProbes(opts, op, subject, pa)
	}
	reader, err := opts.probeReader()
	if err != nil {
		return nil, failAt(op, subject, findings.StepResolve, intent.ProbeKind, "%v", err)
	}
	if err := reader.Check(ctx); err != nil {
		var kindErr *intent.ProbeKindError
		if !errors.As(err, &kindErr) {
			return nil, failAt(op, subject, findings.StepResolve, intent.ProbeKind, "%v", err)
		}
		var list findings.List
		list.AddStep(findings.Rejection, findings.StepResolve, findings.RuleProbeKindAbsent, intent.ProbeKind,
			kindErr.Error()+probeKindRemedy)
		return nil, finish(op, subject, list)
	}
	probes, err := reader.Probes(ctx)
	if err != nil {
		return nil, failAt(op, subject, findings.StepResolve, intent.ProbeKind, "%v", err)
	}
	if probes == nil {
		probes = []probe.Probe{}
	}
	packages, err := opts.probes()
	if err != nil {
		return nil, loadFailureAt(op, subject, findings.StepResolve, err)
	}
	if list := probe.Validate(probes, packages.Formats(), nil); list.Rejected() {
		return nil, finish(op, subject, inKind(list).AtStep(findings.StepResolve))
	}
	return probes, nil
}

// fileProbes is the list of the probe file pa carries, at start: the declaration's version and
// shape, then its rules with the formats the probe packages declare. Each finding names the
// file: those about the document are at its path, and those about a probe or a field say the
// path before their sentence.
func fileProbes(opts *options, op string, subject *findings.Subject, pa probesArg) ([]probe.Probe, error) {
	if pa.file == nil {
		// probesFiles admits none, and beside --snapshot the conflict has answered.
		return nil, failAt(op, subject, findings.StepStart, "--probes", "the request carries no probe file under %s", pa.path)
	}
	d, list := probe.Parse(pa.file.Data, pa.path)
	if d == nil {
		return nil, finish(op, subject, inFile(list, pa.path).AtStep(findings.StepStart))
	}
	packages, err := opts.probes()
	if err != nil {
		return nil, loadFailureAt(op, subject, findings.StepStart, err)
	}
	list = append(list, probe.Validate(d.Probes, packages.Formats(), nil)...)
	if list.Rejected() {
		return nil, finish(op, subject, inFile(list, pa.path).AtStep(findings.StepStart))
	}
	return d.Probes, nil
}

// inFile names the probe file path in each finding that is not already at it.
func inFile(list findings.List, path string) findings.List {
	out := make(findings.List, len(list))
	for i, f := range list {
		if f.Object != path {
			f.Message = "probe file " + path + ": " + f.Message
		}
		out[i] = f
	}
	return out
}

// inKind names the kind in each finding about a probe read from it, as inFile names the file.
func inKind(list findings.List) findings.List {
	out := make(findings.List, len(list))
	for i, f := range list {
		f.Message = intent.ProbeKind + " on the default branch: " + f.Message
		out[i] = f
	}
	return out
}
