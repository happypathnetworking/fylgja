package lab

import (
	"context"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// InspectTwin is a check's first step: what the host holds, as InspectHost reads it, with
// the phrase Describe gives it, returned over the queue.
// It only reads, and writes nothing. An inspection that could not run is operation.failed
// at step inspect, which no retry helps, as the other lab activities report a step that
// could not run.
func (a *Activities) InspectTwin(ctx context.Context) (wire.HostReport, error) {
	host, err := a.InspectHost(ctx)
	if err != nil {
		return wire.HostReport{}, StepFailure(findings.StepInspect, findings.RuleOperationFailed, "lab "+LabName, err.Error())
	}
	return wire.HostReport{
		LabPresent:     host.Lab.Present,
		Nodes:          host.Lab.Nodes,
		TopoPaths:      host.Lab.TopoPaths,
		TwinDirPresent: host.TwinDirPresent,
		Twin:           host.Twin,
		TwinReadError:  host.TwinReadError,
		Phrase:         host.Describe(),
	}, nil
}
