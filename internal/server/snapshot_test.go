package server

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
)

// fixtureSnapshotID is the fixture CTM's snapshot id (testdata/snapshot/three-node.json).
const fixtureSnapshotID = "b9db37f826fc612346974b7f54bc5345513662f21c357a0c51fd2802c9b4de00"

// loadCTM is a fixture CTM under testdata/ctm/, as a read returns one, observed at
// observedAt.
func loadCTM(t *testing.T, name, observedAt string) *ctm.CTM {
	t.Helper()
	c, err := ctm.Load(repoPath("testdata", "ctm", name))
	if err != nil {
		t.Fatal(err)
	}
	c.Envelope.ObservedAt = observedAt
	return c
}

// takeSnapshot files c, a read's CTM, as a snapshot carrying probes in the store under the
// state root, as the orchestrator's adapter files a take, and returns it and its store path,
// or snapshot.id.mismatch at step for an entry under its id that hashes to another: the
// store a create, a step and a resolve begin from. From 020 the server takes no snapshot,
// which the adapter takes (D-065), and this is the tests' alone.
func takeSnapshot(ctx context.Context, paths lab.Paths, step string, c *ctm.CTM, probes []probe.Probe) (*snapshot.Snapshot,
	string, findings.List, error) {
	s := snapshot.Take(c, probes)
	store := snapshot.NewDirStore(paths.Snapshots)
	_, err := store.Put(ctx, s)
	var mismatch *snapshot.ErrIDMismatch
	switch {
	case errors.As(err, &mismatch):
		var list findings.List
		list.AddStep(findings.Rejection, step, findings.RuleSnapshotIDMismatch, mismatch.Path, corruptEntry(mismatch, "filed"))
		return nil, "", list, nil
	case err != nil:
		return nil, "", nil, fmt.Errorf("filing snapshot %s: %v", s.ID, err)
	}
	return s, store.Path(s.ID), nil, nil
}

// fixtureFile is testdata/snapshot/three-node.json as a map, edited by edit, as a client
// would send it under the path snap.json.
func fixtureFile(t *testing.T, edit func(map[string]any)) []api.File {
	t.Helper()
	raw, err := os.ReadFile(repoPath("testdata", "snapshot", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	if edit == nil {
		return []api.File{{Path: "snap.json", Data: raw}}
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	edit(doc)
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	return []api.File{{Path: "snap.json", Data: b}}
}

// fileRefusal is a snapshot file the server refuses by snapshot.Unmarshal's rules, and the
// one finding it is refused with, but for its step, which the command places: resolve for
// twin create --snapshot, none for twin compile (R-03).
type fileRefusal struct {
	name          string
	files         []api.File
	code          int
	rule, object  string
	message       string
	messagePrefix bool
}

// fileRefusals are the refusals of contracts/cli.md, "018: snapshots", as they print, each
// sent under the path snap.json; a file that is not JSON was never validated and is
// operation.failed, exit 2.
func fileRefusals(t *testing.T) []fileRefusal {
	t.Helper()
	ctmOf := func(doc map[string]any) map[string]any { return doc["ctm"].(map[string]any) }
	return []fileRefusal{
		{"another version", fixtureFile(t, func(d map[string]any) { d["snapshot_version"] = "3" }), findings.ExitRejected,
			findings.RuleSnapshotVersionUnsupported, "snap.json",
			`the snapshot declares snapshot_version "3"; this build reads "1" and "2", and nothing converts one`, false},
		{"a bare CTM", func() []api.File {
			raw, err := os.ReadFile(repoPath("testdata", "ctm", "three-node.json"))
			if err != nil {
				t.Fatal(err)
			}
			return []api.File{{Path: "snap.json", Data: raw}}
		}(), findings.ExitRejected, findings.RuleSnapshotVersionUnsupported, "snap.json",
			`the snapshot declares no snapshot_version; this build reads "1" and "2", and nothing converts one`, false},
		{"a probe in a 1", fixtureFile(t, func(d map[string]any) {
			d["snapshot_version"] = "1"
			d["probes"] = []any{map[string]any{}}
		}), findings.ExitRejected,
			findings.RuleSnapshotInvalid, "probes", "probes holds 1 entry", true},
		{"an inner CTM of version 1", fixtureFile(t, func(d map[string]any) { ctmOf(d)["ctm_version"] = "1" }), findings.ExitRejected,
			findings.RuleCTMVersionUnsupported, "snap.json", `the CTM declares ctm_version "1"; this build reads "2", and nothing converts one`, false},
		{"an inner CTM with no fidelity list", fixtureFile(t, func(d map[string]any) {
			delete(ctmOf(d)["envelope"].(map[string]any), "fidelity")
		}), findings.ExitRejected, findings.RuleRequiredMissing, "ctm.envelope.fidelity", "ctm.envelope.fidelity", true},
		{"an inner CTM recording no observed_at", fixtureFile(t, func(d map[string]any) {
			delete(d, "observed_at")
			delete(ctmOf(d)["envelope"].(map[string]any), "observed_at")
		}), findings.ExitRejected, findings.RuleRequiredMissing, "ctm.envelope.observed_at",
			"ctm.envelope.observed_at, the read's time, is not recorded", true},
		{"an inner CTM's observed_at not of its form", fixtureFile(t, func(d map[string]any) {
			delete(d, "observed_at")
			ctmOf(d)["envelope"].(map[string]any)["observed_at"] = "2026-10-27T18:55:42Z"
		}), findings.ExitRejected, findings.RuleSnapshotInvalid, "ctm.envelope.observed_at",
			`ctm.envelope.observed_at "2026-10-27T18:55:42Z" is not a UTC time with six fractional digits`, true},
		{"a declared id its body does not hash to", fixtureFile(t, func(d map[string]any) { d["snapshot_id"] = strings.Repeat("1", 64) }),
			findings.ExitRejected, findings.RuleSnapshotIDMismatch, "snap.json", "snap.json declares snapshot_id " + strings.Repeat("1", 64) +
				", but its body hashes to " + fixtureSnapshotID + "; leave snapshot_id out to have it computed", false},
		{"not JSON", []api.File{{Path: "snap.json", Data: []byte("{")}}, findings.ExitError, findings.RuleOperationFailed, "snap.json",
			"decoding snapshot: ", true},
	}
}

// A snapshot file is refused by snapshot.Unmarshal's rules, each under its own identifier at
// resolve, exit 1, naming the file or the field (R-03; contracts/cli.md, "018: snapshots",
// the refusals as they print); a file that is not JSON was never validated and is
// operation.failed, exit 2. Nothing is filed for any of them.
func TestResolveSnapshotRefusesAFileByItsRules(t *testing.T) {
	for _, c := range fileRefusals(t) {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			_, _, err := resolveSnapshot(context.Background(), paths, findings.OpTwinCreate, &findings.Subject{Snapshot: "snap.json"},
				"snap.json", c.files)
			code, doc := exitOf(t, err)
			if code != c.code || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want %d with %s alone", code, doc.Findings, c.code, c.rule)
			}
			f := doc.Findings[0]
			matches := f.Message == c.message || c.messagePrefix && strings.HasPrefix(f.Message, c.message)
			if f.Rule != c.rule || f.Step != findings.StepResolve || f.Object != c.object || !matches {
				t.Errorf("finding %+v; want %s at resolve on %s: %s", f, c.rule, c.object, c.message)
			}
			if _, err := os.Stat(paths.Snapshots); !os.IsNotExist(err) {
				t.Errorf("snapshots/ exists after a refused file (%v)", err)
			}
			validateWithShow(t, currentContract, "018", doc)
		})
	}
}

// A file whose CTM breaks a rule validation applies without the packages is refused before
// it is filed, under the rules and objects the compile would give it, at compile, and leaves
// the store as it was; one whose fault needs the packages, a platform no package matches, is
// filed, and the compile refuses it afterwards, as a read's take is (018, T082).
func TestResolveSnapshotHoldsAFilesCTMBeforeFilingIt(t *testing.T) {
	envelope := func(d map[string]any) map[string]any { return d["ctm"].(map[string]any)["envelope"].(map[string]any) }
	// An edited body hashes to another id: the fixture's declared one goes, to be computed.
	edited := func(edit func(map[string]any)) func(map[string]any) {
		return func(d map[string]any) {
			delete(d, "snapshot_id")
			edit(d)
		}
	}
	missing := func(object, message string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRequiredMissing, Step: findings.StepCompile,
			Object: object, Message: message}
	}
	for _, c := range []struct {
		name string
		edit func(map[string]any)
		want []findings.Finding
	}{
		{"no branch", func(d map[string]any) { envelope(d)["branch"] = "" },
			[]findings.Finding{missing("envelope.branch", "the branch intent was read from is not recorded")}},
		{"no scope", func(d map[string]any) { envelope(d)["scope"] = "" },
			[]findings.Finding{missing("envelope.scope", "the scope intent was read under is not recorded")}},
		{"no mapping", func(d map[string]any) { envelope(d)["mapping"] = map[string]any{} },
			[]findings.Finding{
				missing("envelope.mapping.reader", "the reader that mapped intent is not recorded"),
				missing("envelope.mapping.model", "the model the reader read is not recorded"),
				missing("envelope.mapping.version", "the version of the model the reader read is not recorded"),
			}},
		{"no devices", func(d map[string]any) {
			d["ctm"].(map[string]any)["devices"] = []any{}
			d["ctm"].(map[string]any)["links"] = []any{}
		}, []findings.Finding{{Severity: findings.Rejection, Rule: findings.RuleDevicesEmpty, Step: findings.StepCompile,
			Object: "fylgja-fixture@2026-09-08T12:00:00Z", Message: `no devices in intent for branch "fylgja-fixture" at ` +
				"2026-09-08T12:00:00Z; a twin of nothing cannot be built and has no fidelity to report"}}},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			_, _, err := resolveSnapshot(context.Background(), paths, findings.OpTwinCreate, &findings.Subject{Snapshot: "snap.json"},
				"snap.json", fixtureFile(t, edited(c.edit)))
			code, doc := exitOf(t, err)
			if code != findings.ExitRejected || len(doc.Findings) != len(c.want) {
				t.Fatalf("exit %d, findings %+v; want 1 with %+v", code, doc.Findings, c.want)
			}
			for i, f := range doc.Findings {
				if f != c.want[i] {
					t.Errorf("finding %d: %+v; want %+v", i, f, c.want[i])
				}
			}
			if doc.SnapshotID != "" {
				t.Errorf("the refusal names snapshot %s, which nothing filed", doc.SnapshotID)
			}
			if _, err := os.Stat(paths.Snapshots); !os.IsNotExist(err) {
				t.Errorf("snapshots/ exists after a refused file (%v)", err)
			}
			validateWithShow(t, currentContract, "018", doc)
		})
	}

	t.Run("a platform no package matches", func(t *testing.T) {
		paths := useStateRoot(t)
		files := fixtureFile(t, edited(func(d map[string]any) {
			d["ctm"].(map[string]any)["devices"].([]any)[0].(map[string]any)["platform"].(map[string]any)["package"] = "nosuch"
		}))
		s, path, err := resolveSnapshot(context.Background(), paths, findings.OpTwinCreate, &findings.Subject{Snapshot: "snap.json"},
			"snap.json", files)
		if err != nil {
			t.Fatalf("resolveSnapshot = %v; want the file filed, for the compile to refuse", err)
		}
		if _, err := os.Stat(path); err != nil || path != filepath.Join(paths.Snapshots, s.ID+".json") {
			t.Errorf("the file is not filed under its id at %s (%v)", path, err)
		}
	})
}

// A file whose inner CTM records no observed_at, or one not of its form, hashes to the id
// every valid take of its intent does, since the id leaves observed_at out. It is refused
// before anything is filed, so a later take of the same intent, read with a proper
// observed_at, files and returns the entry rather than meeting one the store cannot read
// back.
func TestARefusedObservedAtLeavesTheTakeOfItsIntent(t *testing.T) {
	ctx := context.Background()
	var refused []fileRefusal
	for _, c := range fileRefusals(t) {
		if c.object == "ctm.envelope.observed_at" {
			refused = append(refused, c)
		}
	}
	if len(refused) != 2 {
		t.Fatalf("fileRefusals holds %d refusals of the inner CTM's observed_at, want 2", len(refused))
	}
	for _, c := range refused {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			_, _, err := resolveSnapshot(ctx, paths, findings.OpTwinCreate, &findings.Subject{Snapshot: "snap.json"}, "snap.json",
				c.files)
			if code, doc := exitOf(t, err); code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0].Rule != c.rule {
				t.Fatalf("exit %d, findings %+v; want %s alone", code, doc.Findings, c.rule)
			}

			const observedAt = "2026-10-27T09:00:00.000000Z"
			s, path, list, err := takeSnapshot(ctx, paths, findings.StepRead, loadCTM(t, "three-node.json", observedAt), nil)
			if err != nil || len(list) != 0 || s.ID != fixtureSnapshotID || path != filepath.Join(paths.Snapshots, fixtureSnapshotID+".json") {
				t.Fatalf("takeSnapshot = %v at %s, %v, %v; want %s filed", s, path, list, err, fixtureSnapshotID)
			}
			stored, err := snapshot.NewDirStore(paths.Snapshots).Fetch(ctx, fixtureSnapshotID)
			if err != nil || stored.ObservedAt != observedAt {
				t.Errorf("the store holds %+v (%v); want the take observed at %s", stored, err, observedAt)
			}
		})
	}
}

// An id the store does not hold is snapshot.unknown at resolve, naming the store's
// directory; an entry under the id that hashes to another is snapshot.id.mismatch naming its
// path; a stored one is the stored document, at its store path (R-12).
func TestResolveSnapshotByID(t *testing.T) {
	ctx := context.Background()
	paths := useStateRoot(t)
	subject := &findings.Subject{Snapshot: fixtureSnapshotID}

	_, _, err := resolveSnapshot(ctx, paths, findings.OpTwinCreate, subject, fixtureSnapshotID, nil)
	code, doc := exitOf(t, err)
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSnapshotUnknown, Step: findings.StepResolve,
		Object: fixtureSnapshotID, Message: "the store under " + paths.Snapshots + " holds no snapshot " + fixtureSnapshotID +
			"; a snapshot id comes from a create, a dry run, a plan or intent read --out on this server"}
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("exit %d, findings %+v; want 1 with %+v", code, doc.Findings, want)
	}
	validateWithShow(t, currentContract, "018", doc)

	stored, path, _, err := takeSnapshot(ctx, paths, findings.StepRead, loadCTM(t, "three-node.json", "2026-10-27T09:00:00.000000Z"), nil)
	if err != nil {
		t.Fatal(err)
	}
	s, got, err := resolveSnapshot(ctx, paths, findings.OpTwinCreate, subject, fixtureSnapshotID, nil)
	if err != nil || s.ID != stored.ID || s.ObservedAt != stored.ObservedAt || got != path {
		t.Errorf("resolved %+v at %s (%v); want the stored %s at %s", s, got, err, stored.ID, path)
	}

	// The lossy fixture's stored bytes under the three-node's id.
	other, _, _, err := takeSnapshot(ctx, paths, findings.StepRead, loadCTM(t, "lossy.json", "2026-10-27T09:00:00.000000Z"), nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(filepath.Join(paths.Snapshots, other.ID+".json"), path); err != nil {
		t.Fatal(err)
	}
	_, _, err = resolveSnapshot(ctx, paths, findings.OpTwinCreate, subject, fixtureSnapshotID, nil)
	code, doc = exitOf(t, err)
	want = findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSnapshotIDMismatch, Step: findings.StepResolve,
		Object: path, Message: "store entry " + path + " hashes to " + other.ID + ", not " + fixtureSnapshotID + ", so snapshot " +
			fixtureSnapshotID + " cannot be read"}
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("exit %d, findings %+v; want 1 with %+v", code, doc.Findings, want)
	}

	// The three-node's own body under its id, declaring the lossy's id: the message names
	// what the entry declares beside what its body hashes to.
	b, err := snapshot.Marshal(stored)
	if err != nil {
		t.Fatal(err)
	}
	b = bytes.Replace(b, []byte(`"snapshot_id": "`+fixtureSnapshotID+`"`), []byte(`"snapshot_id": "`+other.ID+`"`), 1)
	if err := os.WriteFile(path, b, 0o644); err != nil {
		t.Fatal(err)
	}
	_, _, err = resolveSnapshot(ctx, paths, findings.OpTwinCreate, subject, fixtureSnapshotID, nil)
	code, doc = exitOf(t, err)
	want = findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSnapshotIDMismatch, Step: findings.StepResolve,
		Object: path, Message: "store entry " + path + " declares snapshot_id " + other.ID + ", but its body hashes to " +
			fixtureSnapshotID + ", so snapshot " + fixtureSnapshotID + " cannot be read"}
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("exit %d, findings %+v; want 1 with %+v", code, doc.Findings, want)
	}
}

// A file is filed under the id its body hashes to, computed when it declares none; one of a
// snapshot the store holds leaves the entry as it was, and what is returned is the stored
// document, its observed_at the first take's (US3 scenarios 4 and 8).
func TestResolveSnapshotFilesAFile(t *testing.T) {
	ctx := context.Background()
	paths := useStateRoot(t)
	files := fixtureFile(t, func(d map[string]any) {
		delete(d, "snapshot_id")
		delete(d, "observed_at")
	})
	s, path, err := resolveSnapshot(ctx, paths, findings.OpTwinCreate, &findings.Subject{Snapshot: "snap.json"}, "snap.json", files)
	if err != nil || s.ID != fixtureSnapshotID || path != filepath.Join(paths.Snapshots, fixtureSnapshotID+".json") {
		t.Fatalf("resolved %+v at %s (%v); want %s filed", s, path, err, fixtureSnapshotID)
	}
	first, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}

	later := fixtureFile(t, func(d map[string]any) {
		d["observed_at"] = "2026-10-27T10:30:00.000000Z"
		d["ctm"].(map[string]any)["envelope"].(map[string]any)["observed_at"] = "2026-10-27T10:30:00.000000Z"
	})
	again, _, err := resolveSnapshot(ctx, paths, findings.OpTwinCreate, &findings.Subject{Snapshot: "snap.json"}, "snap.json", later)
	if err != nil || again.ID != fixtureSnapshotID || again.ObservedAt != s.ObservedAt {
		t.Errorf("resolved %+v (%v); want %s observed at the first take's %s", again, err, fixtureSnapshotID, s.ObservedAt)
	}
	if b, err := os.ReadFile(path); err != nil || !bytes.Equal(b, first) {
		t.Errorf("the second file changed the entry (%v)", err)
	}
}

// A create's files are one snapshot file beside a --snapshot that is a path, under that
// path, or none: any other is refused before anything is parsed, operation.failed, exit 2,
// as twin compile's are, and nothing is dialled or filed (contracts/api.md, "018:
// snapshots").
func TestACreatesFilesAreOneSnapshotFile(t *testing.T) {
	one := []api.File{{Path: "snap.json", Data: []byte("{")}}
	for _, c := range []struct {
		name    string
		flags   createFlags
		files   []api.File
		message string
	}{
		{"a file beside an id", createFlags{snapshot: fixtureSnapshotID}, one,
			"the request carries 1 file where twin create takes a snapshot file beside --snapshot alone"},
		{"two files", createFlags{snapshot: "snap.json"}, append(one, api.File{Path: "other.json"}),
			"the request carries 2 files where twin create takes a snapshot file beside --snapshot alone"},
		{"no file beside a path", createFlags{snapshot: "snap.json"}, nil,
			"the request carries no file where twin create takes the snapshot file --snapshot names, under that path"},
		{"a file under another path", createFlags{snapshot: "other.json"}, one,
			"the request carries its snapshot file under another path than --snapshot gives, where twin create takes a snapshot " +
				"file beside --snapshot alone, under that path"},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			code, doc := exitOf(t, runCreate(context.Background(), testOptions(t, true), &c.flags, c.files))
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: findings.OpTwinCreate,
				Message: c.message}
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want {
				t.Errorf("exit %d, findings %+v; want 2 with %+v", code, doc.Findings, want)
			}
			if _, err := os.Stat(paths.Root); err == nil {
				if entries, _ := os.ReadDir(paths.Root); len(entries) != 0 {
					t.Errorf("the state root holds %v after the refusal", entries)
				}
			}
		})
	}
}
