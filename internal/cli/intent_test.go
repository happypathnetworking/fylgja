package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// runRead exercises the command flow exactly as the CLI does, up to wherever it
// stops. Every case here stops before the first request, so none of it needs Infrahub.
func runReadDoc(t *testing.T, f *readFlags) (int, *findingsDoc) {
	t.Helper()
	err := runRead(t.Context(), &options{asJSON: true}, f)
	var res *result
	if !asResult(err, &res) {
		t.Fatalf("runRead returned %v, want a findings result", err)
	}
	b, mErr := json.Marshal(res.doc)
	if mErr != nil {
		t.Fatal(mErr)
	}
	var doc findingsDoc
	if err := json.Unmarshal(b, &doc); err != nil {
		t.Fatal(err)
	}
	return res.doc.Status.ExitCode(), &doc
}

// An `at` finer than Infrahub honours is refused before any query, under its own rule
// rather than the catch-all: the operator has to be told that the value was too
// precise, not merely that something failed.
func TestAtTooPreciseIsRefusedBeforeAnyQuery(t *testing.T) {
	for _, at := range []string{
		"2026-09-08T19:37:02.1234567Z",
		"2026-09-08T19:37:02.123456789Z",
	} {
		out := filepath.Join(t.TempDir(), "never.json")
		// No INFRAHUB_ADDRESS is set for this test: reaching the client at all would
		// fail with a different rule, which is exactly what must not happen.
		t.Setenv("INFRAHUB_ADDRESS", "")
		t.Setenv("INFRAHUB_API_TOKEN", "")

		code, doc := runReadDoc(t, &readFlags{branch: "fylgja-fixture", at: at, out: out})
		if code != findings.ExitError {
			t.Errorf("at %s: exit %d, want %d", at, code, findings.ExitError)
		}
		if doc.Status != string(findings.StatusError) {
			t.Errorf("at %s: status = %q, want error", at, doc.Status)
		}
		if len(doc.Findings) != 1 {
			t.Fatalf("at %s: %d findings, want exactly one: %+v", at, len(doc.Findings), doc.Findings)
		}
		f := doc.Findings[0]
		if f.Rule != findings.RuleAtPrecision {
			t.Errorf("at %s: rule = %s, want %s", at, f.Rule, findings.RuleAtPrecision)
		}
		if f.Object != at {
			t.Errorf("at %s: finding names %q, want the at", at, f.Object)
		}
		if !strings.Contains(f.Message, "microseconds") {
			t.Errorf("at %s: message does not name the precision honoured: %s", at, f.Message)
		}
		if _, err := os.Stat(out); !os.IsNotExist(err) {
			t.Errorf("at %s: a refused read left a file at %s", at, out)
		}
	}
}

// A missing credential is an operational failure naming the variable to set, and no
// request is sent.
func TestMissingCredentialIsNamed(t *testing.T) {
	t.Setenv("INFRAHUB_ADDRESS", "http://localhost:8000")
	t.Setenv("INFRAHUB_API_TOKEN", "")
	out := filepath.Join(t.TempDir(), "never.json")

	code, doc := runReadDoc(t, &readFlags{branch: "fylgja-fixture", out: out})
	if code != findings.ExitError {
		t.Errorf("exit %d, want %d", code, findings.ExitError)
	}
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed {
		t.Fatalf("want one operation.failed finding, got %+v", doc.Findings)
	}
	if !strings.Contains(doc.Findings[0].Message, "INFRAHUB_API_TOKEN") {
		t.Errorf("message does not name the variable to set: %s", doc.Findings[0].Message)
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Error("a failed read left a file behind")
	}
}

// The required flags are refused as usage failures, before anything else.
func TestReadRequiresBranchAndOut(t *testing.T) {
	for _, tc := range []struct {
		name string
		f    readFlags
		want string
	}{
		{"no branch", readFlags{out: "x.json"}, "--branch or --waypoint is required"},
		{"no out beside a waypoint", readFlags{waypoint: "demo/2"}, "--out is required"},
		{"no out", readFlags{branch: "fylgja-fixture"}, "--out is required"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			code, doc := runReadDoc(t, &tc.f)
			if code != findings.ExitError {
				t.Errorf("exit %d, want %d", code, findings.ExitError)
			}
			if len(doc.Findings) != 1 || doc.Findings[0].Message != tc.want {
				t.Errorf("want %q, got %+v", tc.want, doc.Findings)
			}
		})
	}
}

// The operation is intent.read on every document this command produces, including its
// failures: a machine reader routes on that field.
func TestReadDocumentsNameTheOperation(t *testing.T) {
	_, doc := runReadDoc(t, &readFlags{out: "x.json"})
	if doc.Operation != findings.OpIntentRead {
		t.Errorf("operation = %q, want %q", doc.Operation, findings.OpIntentRead)
	}
}

// pinnedCTM reads the CTM at path with its observed_at pinned, as the ctm package's own
// parity test pins it, and marshals it canonically: two reads of one reference differ by
// when they were taken and by nothing else.
func pinnedCTM(t *testing.T, path string) []byte {
	t.Helper()
	c, err := ctm.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	c.Envelope.ObservedAt = "2026-09-28T00:00:00.000000Z"
	b, err := ctm.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// intent read --waypoint writes exactly the CTM intent read --branch B --at T writes for the
// reference the waypoint names, from the same Infrahub: the pinned read, with the at
// verbatim, given or written, and nothing of the waypoint in the envelope.
// The success line and the document name the waypoint.
func TestReadFromAWaypointIsThePinnedRead(t *testing.T) {
	for _, c := range []struct {
		ref, at, source string
	}{
		{"demo/2", fixtureAt, "given"},
		{"demo/1", demoWrittenAt, "written"},
	} {
		t.Run(c.source, func(t *testing.T) {
			f := demoInfrahub(t)
			f.start()
			dir := t.TempDir()
			byWaypoint, byReference := filepath.Join(dir, "waypoint.json"), filepath.Join(dir, "reference.json")

			var err error
			out := captureStdout(t, func() {
				err = runRead(t.Context(), &options{}, &readFlags{waypoint: c.ref, out: byWaypoint})
			})
			if code, doc := exitOf(t, err); code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
			}
			want := "wrote " + byWaypoint + ": 3 devices (nokia_srlinux 3), 12 interfaces, 3 links, 3 artifacts, 0 lossy mappings, " +
				"0 shared ports (waypoint " + c.ref + ": branch fylgja-fixture, at " + c.at + ", schema fixture)\n"
			if out != want {
				t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
			}
			if code, doc := exitOf(t, runRead(t.Context(), &options{asJSON: true},
				&readFlags{branch: "fylgja-fixture", at: c.at, out: byReference})); code != findings.ExitOK {
				t.Fatalf("the --branch --at read: exit %d, findings %+v", code, doc.Findings)
			}

			got, ref := pinnedCTM(t, byWaypoint), pinnedCTM(t, byReference)
			if !bytes.Equal(got, ref) {
				t.Errorf("the waypoint's CTM differs from the pinned read's:\n%s\nwant:\n%s", got, ref)
			}
			raw, err := os.ReadFile(byWaypoint)
			if err != nil {
				t.Fatal(err)
			}
			for _, word := range []string{"waypoint", "demo", c.source} {
				if strings.Contains(string(raw), word) {
					t.Errorf("the CTM names %q: a waypoint enters no CTM", word)
				}
			}
			if c.source == "given" && !bytes.Equal(got, pinnedCTM(t, repoPath("testdata", "ctm", "three-node.json"))) {
				t.Error("the fixture's waypoint does not read as the fixture")
			}

			code, doc := exitOf(t, runRead(t.Context(), &options{asJSON: true}, &readFlags{waypoint: c.ref, out: byWaypoint}))
			if code != findings.ExitOK || doc.Waypoint == nil || doc.Waypoint.At != c.at || doc.Waypoint.AtSource != c.source ||
				doc.Subject.Waypoint != c.ref || doc.Subject.Branch != "fylgja-fixture" || doc.Subject.At != c.at {
				t.Errorf("exit %d, document %+v; want 0 naming %s resolved to fylgja-fixture at %s", code, doc, c.ref, c.at)
			}
			mustCarryNoToken(t, c.ref, doc, out)
			validateM10Document(t, doc)
		})
	}
}

// Beside --waypoint, --branch and --at are refused before any connection, exit 2; a
// resolution refusal is the create's, with no step, as M1's operations carry none
// (contracts/cli.md).
func TestReadFromAWaypointRefusals(t *testing.T) {
	const whole = "a waypoint is a whole pinned reference (branch and at)"
	for _, c := range []struct {
		name  string
		flags readFlags
		code  int
		want  findings.Finding
		asked bool
	}{
		{"--branch", readFlags{waypoint: "demo/2", branch: "fylgja-fixture"}, findings.ExitError,
			findings.Finding{Severity: findings.Rejection, Rule: findings.RuleWaypointFlagsConflict, Object: "--branch",
				Message: "--branch is meaningless with --waypoint: " + whole}, false},
		{"--at", readFlags{waypoint: "demo/2", at: fixtureAt}, findings.ExitError,
			findings.Finding{Severity: findings.Rejection, Rule: findings.RuleWaypointFlagsConflict, Object: "--at",
				Message: "--at is meaningless with --waypoint: " + whole}, false},
		{"not a reference", readFlags{waypoint: "demo/"}, findings.ExitError,
			findings.Finding{Severity: findings.Rejection, Rule: findings.RuleWaypointRefInvalid, Object: "demo/",
				Message: `--waypoint "demo/" is not a waypoint reference: expected <series>/<sequence>, a series with no "/" and no whitespace and a positive integer`}, false},
		{"unknown", readFlags{waypoint: "demo/3"}, findings.ExitRejected,
			findings.Finding{Severity: findings.Rejection, Rule: findings.RuleWaypointUnknown, Object: "demo/3",
				Message: "series demo has no waypoint 3; its sequences are 1, 2, 5, 6, 7"}, true},
		{"nine digits", readFlags{waypoint: "demo/6"}, findings.ExitError,
			findings.Finding{Severity: findings.Rejection, Rule: findings.RuleAtPrecision, Object: "demo/6",
				Message: "waypoint demo/6: at 2026-09-20T10:00:00.123456789Z carries 9 fractional digits; Infrahub honours at most 6 (microseconds). Write the waypoint's as_of with at most six."}, true},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := demoInfrahub(t)
			f.start()
			c.flags.out = filepath.Join(t.TempDir(), "never.json")

			code, doc := exitOf(t, runRead(t.Context(), &options{asJSON: true}, &c.flags))
			if code != c.code || len(doc.Findings) != 1 || doc.Findings[0] != c.want {
				t.Errorf("exit %d, findings %+v; want %d with %+v", code, doc.Findings, c.code, c.want)
			}
			if asked := len(f.requests()) > 0; asked != c.asked {
				t.Errorf("Infrahub asked %v, want %v: %+v", asked, c.asked, f.requests())
			}
			for _, r := range f.requests() {
				if r.Path != "/api/schema" && r.Path != "/graphql" {
					t.Errorf("a refused resolution read the branch: %+v", r)
				}
			}
			if _, err := os.Stat(c.flags.out); !os.IsNotExist(err) {
				t.Errorf("a refused read wrote %s", c.flags.out)
			}
			validateM10Document(t, doc)
		})
	}
}

// An explicitly empty --waypoint= is a reference that is not the form, through the command
// line, alone or beside --branch: waypoint.ref.invalid, exit 2, with no step, before any
// connection and with nothing written. Beside --branch it is never the branch's read.
func TestReadEmptyWaypointIsRefused(t *testing.T) {
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleWaypointRefInvalid, Object: "",
		Message: `--waypoint "" is not a waypoint reference: expected <series>/<sequence>, a series with no "/" and no whitespace and a positive integer`}
	for _, c := range []struct {
		name string
		args []string
	}{
		{"alone", []string{"--waypoint="}},
		{"beside --branch", []string{"--branch", "fylgja-fixture", "--waypoint="}},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := demoInfrahub(t)
			f.start()
			out := filepath.Join(t.TempDir(), "never.json")

			code, doc := executeTwin(t, append(append([]string{"intent", "read"}, c.args...), "--out", out)...)
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want {
				t.Errorf("exit %d, findings %+v; want 2 with %+v", code, doc.Findings, want)
			}
			if got := f.requests(); len(got) != 0 {
				t.Errorf("Infrahub was asked %+v before the flags were refused", got)
			}
			if doc.Waypoint != nil || subjectWaypoint(doc) != "" {
				t.Errorf("subject %+v, waypoint %+v; an empty reference names no waypoint", doc.Subject, doc.Waypoint)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Errorf("a refused read wrote %s", out)
			}
			validateM10Document(t, doc)
		})
	}
}

// A read the resolved reference refuses keeps M1's wording, word for word what --branch and
// --at would say, and the document names the waypoint that resolved to it.
func TestReadFromAWaypointKeepsTheReadsRefusal(t *testing.T) {
	f := demoInfrahub(t)
	f.waypoint("wp-gone-1", "gone", 1, "deleted-branch", demoWrittenAt, "", "its branch was deleted")
	f.start()
	dir := t.TempDir()

	code, doc := exitOf(t, runRead(t.Context(), &options{asJSON: true}, &readFlags{waypoint: "gone/1", out: filepath.Join(dir, "a.json")}))
	_, ref := exitOf(t, runRead(t.Context(), &options{asJSON: true},
		&readFlags{branch: "deleted-branch", at: demoWrittenAt, out: filepath.Join(dir, "b.json")}))
	if code != findings.ExitError || len(doc.Findings) != 1 || len(ref.Findings) != 1 || doc.Findings[0] != ref.Findings[0] {
		t.Errorf("exit %d, findings %+v; want 2 with the --branch --at read's %+v", code, doc.Findings, ref.Findings)
	}
	want := findings.WaypointBlock{Series: "gone", Sequence: 1, Branch: "deleted-branch", At: demoWrittenAt, AtSource: "written",
		Description: "its branch was deleted"}
	if doc.Waypoint == nil || *doc.Waypoint != want {
		t.Errorf("waypoint block %+v, want %+v", doc.Waypoint, want)
	}
	validateM10Document(t, doc)
}
