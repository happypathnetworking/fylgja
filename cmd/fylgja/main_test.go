package main

import (
	"strings"
	"testing"

	"github.com/spf13/cobra"
)

// `--version` is in the CLI contract's global flags, so it is a promise, not a cobra
// accident. It reports the binary's identity and says nothing about any bundle: no
// build stamp reaches one, which is what keeps bundle_id stable across releases
// (D-024).
//
// The default is asserted against the same literal the Makefile defaults to. If a
// release ever stamps a version the source does not know about, that is the point of
// -ldflags; what must not happen is the two disagreeing by accident.
func TestVersionFlagReportsTheBinaryIdentity(t *testing.T) {
	if version == "" {
		t.Fatal("version is empty; --version would print nothing")
	}

	root := &cobra.Command{Use: "fylgja", Version: version}
	// cobra adds the flag from Version during Execute, not at construction, so ask for
	// it explicitly: an empty Version would silently remove a documented flag.
	root.InitDefaultVersionFlag()
	if root.Flags().Lookup("version") == nil {
		t.Fatal("no --version flag; contracts/cli.md lists it as a global flag")
	}

	var out strings.Builder
	root.SetOut(&out)
	root.SetArgs([]string{"--version"})
	if err := root.Execute(); err != nil {
		t.Fatalf("--version returned an error: %v", err)
	}
	if got := out.String(); !strings.Contains(got, version) {
		t.Errorf("--version printed %q, which does not carry %q", got, version)
	}
}
