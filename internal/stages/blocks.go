package stages

import (
	"encoding/json"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The conversions the surface needs: each result as the findings document carries it
// (contracts/stages.schema.json). The package's own types stay its own, so the core reads
// no wire type but here. twin.json 12 names no stage (020, research R-06), so no record is
// read here: a RecordView is built by a caller that has one, and the server has none.

// Block is the resolved stage as the document's stage block carries it ($defs/resolved).
func (r Resolved) Block() findings.StageBlock {
	return findings.StageBlock{Ref: r.Ref.String(), Branch: r.Branch, Label: r.Label,
		ProposedChange: r.ProposedChange.block(), At: r.At, AtSource: r.AtSource, Description: r.Description}
}

// block is the proposed change as the blocks name it ($defs/proposed_change).
func (pc ProposedChange) block() findings.StageChange {
	return findings.StageChange{ID: pc.ID, Name: pc.Name, Branch: pc.Branch, Draft: pc.Draft}
}

// Block is the record's stage as the stages block carries it ($defs/record), towards
// written as an explicit null unless the record is diverged.
func (v RecordView) Block() *findings.StageRecord {
	b := &findings.StageRecord{Ref: v.Ref().String(),
		ProposedChange: findings.StageChangeRef{ID: v.ProposedChange.ID, Branch: v.ProposedChange.Branch},
		Label:          v.Label, Branch: v.Branch, At: v.At, AtSource: v.AtSource, State: v.State}
	if v.State == wire.StateDiverged && v.Towards != "" {
		b.Towards = &findings.StageTowards{Ref: Ref{Branch: v.ProposedChange.Branch, Label: v.Towards}.String()}
	}
	return b
}

// Block is the listing as stage list's document carries it ($defs/list).
func (r ListResult) Block() *findings.StagesBlock {
	b := &findings.StagesBlock{}
	if r.Branch != "" {
		branch := r.Branch
		b.Branch = &branch
	}
	for _, row := range r.Rows {
		b.Rows = append(b.Rows, findings.StageRow{StageBlock: row.Block(), Twin: row.Twin})
	}
	for _, o := range r.Orphans {
		b.Orphans = append(b.Orphans, findings.StageOrphan{ID: o.ID, Label: o.Label, At: o.At, AtSource: o.AtSource})
	}
	if r.Record != nil {
		b.Record = r.Record.Block()
	}
	return b
}

// Block is the plan as stage plan's document carries it ($defs/plan), or nil for a plan
// refused before its proposed change was found, which has no stages (the contract's plan
// holds at least two).
func (p *PlanResult) Block() (*findings.PlanBlock, error) {
	if p.ProposedChange == nil || len(p.Stages) == 0 {
		return nil, nil
	}
	b := &findings.PlanBlock{Branch: p.Branch, ProposedChange: p.ProposedChange.block()}
	for _, st := range p.Stages {
		b.Stages = append(b.Stages, st.Block())
	}
	for _, s := range p.Steps {
		raw, err := json.Marshal(s)
		if err != nil {
			return nil, err
		}
		b.Steps = append(b.Steps, raw)
	}
	return b, nil
}

// Block is one stage as the plan block carries it ($defs/plan_stage): its reference,
// label, description and at's source in every case, its branch and at once it resolved,
// its snapshot once its read was filed (018), written null before, its bundle once it
// compiled and its read counts once the read did.
func (p PlanStage) Block() findings.PlanStage {
	out := findings.PlanStage{Ref: p.Ref.String(), Label: p.Label, Description: p.Description, AtSource: p.AtSource,
		Findings: p.Findings}
	if r := p.Resolved; r != nil {
		out.Branch, out.At, out.AtSource = r.Branch, r.At, r.AtSource
	}
	if p.SnapshotID != "" {
		id := p.SnapshotID
		out.SnapshotID = &id
	}
	if p.Bundle != nil {
		id := p.Bundle.ID
		out.BundleID = &id
	}
	if s := p.Read; s != nil {
		out.Read = &findings.ReadCounts{Devices: s.Counts.Devices, Interfaces: s.Counts.Interfaces, Links: s.Counts.Links,
			Artifacts: s.Counts.Artifacts, LossyMappings: s.Lossy.LossyMappings, SharedPorts: s.Lossy.SharedPorts}
	}
	return out
}
