package cli

import (
	"bytes"
	"slices"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The operation in a findings document is an enum in the contract, and it is derived from
// the command path rather than written out a second time. This is the test that keeps the
// derivation and the enum the same list.
func TestOperationOfMatchesTheContractEnum(t *testing.T) {
	build := func(path ...string) *cobra.Command {
		root := &cobra.Command{Use: "fylgja"}
		parent := root
		for _, p := range path {
			child := &cobra.Command{Use: p}
			parent.AddCommand(child)
			parent = child
		}
		return parent
	}
	for _, tc := range []struct {
		path []string
		want string
	}{
		{[]string{"twin", "create"}, findings.OpTwinCreate},
		{[]string{"twin", "compile"}, findings.OpCompile},
		{[]string{"psp", "validate"}, findings.OpPSPValidate},
		{[]string{"run", "read"}, findings.OpRunRead},
	} {
		if got := operationOf(build(tc.path...)); got != tc.want {
			t.Errorf("operationOf(%v) = %q, want %q", tc.path, got, tc.want)
		}
	}
}

// A failure at the root names no operation, and a document that invented one would be
// wrong in a machine-readable field.
func TestOperationOfIsEmptyAtTheRoot(t *testing.T) {
	if got := operationOf(&cobra.Command{Use: "fylgja"}); got != "" {
		t.Errorf("operationOf(root) = %q, want empty", got)
	}
	if got := operationOf(nil); got != "" {
		t.Errorf("operationOf(nil) = %q, want empty", got)
	}
}

// The enum test above builds its commands, so it would still pass if the real root
// registered none of them. This one asserts every operation of the API is a command an
// operator can actually run, each resolving to the operation it names.
func TestRootRegistersEveryCommand(t *testing.T) {
	root := &cobra.Command{Use: "fylgja"}
	AddCommands(root, build)
	for _, op := range api.Operations {
		path := strings.Split(op, ".")
		cmd, _, err := root.Find(path)
		if err != nil {
			t.Errorf("fylgja %s: %v", strings.Join(path, " "), err)
			continue
		}
		if got := operationOf(cmd); got != op {
			t.Errorf("fylgja %s resolved to %q, which names %q", strings.Join(path, " "), cmd.CommandPath(), got)
		}
	}
}

// fylgja --help, with no server, names the core's nouns and none of the three the
// orchestrator took, and fylgja twin --help names no rehearse (020, FR-003): the operator
// who asks this binary what it does is not told of a command it has no more.
func TestHelpNamesNoCommandTheOrchestratorTook(t *testing.T) {
	help := func(args ...string) string {
		t.Helper()
		root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true, Version: version}
		AddCommands(root, version)
		var out bytes.Buffer
		root.SetOut(&out)
		root.SetArgs(append(args, "--help"))
		cmd, err := root.ExecuteC()
		if code := Report(cmd, err); code != findings.ExitOK {
			t.Fatalf("fylgja %s --help: exit %d", strings.Join(args, " "), code)
		}
		return out.String()
	}
	nouns := func(text string) []string {
		var names []string
		in := false
		for line := range strings.SplitSeq(text, "\n") {
			switch {
			case strings.HasPrefix(line, "Available Commands:"):
				in = true
			case in && strings.TrimSpace(line) == "":
				in = false
			case in:
				names = append(names, strings.Fields(line)[0])
			}
		}
		return names
	}
	if got := nouns(help()); !slices.Equal(got, []string{"completion", "help", "psp", "run", "twin"}) {
		t.Errorf("fylgja --help lists %v; want completion, help, psp, run and twin alone", got)
	}
	got := nouns(help("twin"))
	want := []string{"compile", "create", "destroy", "diff", "provision", "show", "step", "verify"}
	if !slices.Equal(got, want) {
		t.Errorf("fylgja twin --help lists %v; want %v", got, want)
	}
}
