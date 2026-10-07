package cli

import (
	"testing"

	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// The defaults and floors the client's help names are the core's, written as literals since
// the client links neither package (create.go); each is held to the constant it stands for,
// and the flags carry them as M12's did.
func TestFlagDefaultsAreTheCoresOwn(t *testing.T) {
	for _, c := range []struct{ name, got, want string }{
		{"the follow interval", defaultInterval, provision.DefaultInterval.String()},
		{"its floor", minInterval, provision.MinInterval.String()},
		{"verify's budget", defaultBudget, verify.DefaultBudget.String()},
	} {
		if c.got != c.want {
			t.Errorf("%s is %q here and %q in the core", c.name, c.got, c.want)
		}
	}
	twin := newTwinCmd(&options{})
	for _, c := range []struct {
		path               []string
		flag, value, noOpt string
	}{
		{[]string{"create"}, "interval", provision.DefaultInterval.String(), ""},
		{[]string{"verify"}, "wait", "", verify.DefaultBudget.String()},
	} {
		cmd, _, err := twin.Find(c.path)
		if err != nil {
			t.Fatal(err)
		}
		f := cmd.Flags().Lookup(c.flag)
		if f == nil || f.DefValue != c.value || f.NoOptDefVal != c.noOpt {
			t.Errorf("twin %v --%s: %+v, want default %q and bare value %q", c.path, c.flag, f, c.value, c.noOpt)
		}
	}
}
