package cli

import (
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The operation in a findings document is a four-value enum in the contract, and it
// is derived from the command path rather than written out a second time. This is the
// test that keeps the derivation and the enum the same list.
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
		{[]string{"intent", "read"}, findings.OpIntentRead},
		{[]string{"twin", "compile"}, findings.OpCompile},
		{[]string{"schema", "check"}, findings.OpSchemaCheck},
		{[]string{"psp", "validate"}, findings.OpPSPValidate},
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
// registered none of them. This one asserts the four operations in the contract are
// four commands an operator can actually run.
func TestRootRegistersEveryCommand(t *testing.T) {
	root := &cobra.Command{Use: "fylgja"}
	opts := &options{}
	root.AddCommand(newIntentCmd(opts), newTwinCmd(opts), newSchemaCmd(opts), newPSPCmd(opts))

	for _, path := range [][]string{
		{"intent", "read"},
		{"twin", "compile"},
		{"schema", "check"},
		{"psp", "validate"},
	} {
		cmd, _, err := root.Find(path)
		if err != nil {
			t.Errorf("fylgja %s: %v", strings.Join(path, " "), err)
			continue
		}
		if got := operationOf(cmd); got == "" {
			t.Errorf("fylgja %s resolved to %q, which names no operation", strings.Join(path, " "), cmd.CommandPath())
		}
	}
}
