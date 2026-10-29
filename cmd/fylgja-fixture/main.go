//go:build fixture

// Command fylgja-fixture prepares a local Infrahub for development: it loads the
// schema library and the stage kind onto a branch and seeds the three-node fixture
// or the mixed one, or makes tier 3's branch changes on a throwaway branch, or opens,
// marks, readies, checks and closes a throwaway branch's proposed change (D-045), or prepares main:
// the schema, the group and this repository's read-only registration (D-044), or opens and
// closes a demo's window, the three-node baseline on main (D-054), or writes and deletes the
// probes of the probe kind on main (D-064). Development tooling, not the product —
// it writes to Infrahub, which the product never does. Build-tagged so it cannot be built
// by accident.
package main

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

func main() {
	branch := flag.String("branch", testsupport.FixtureBranch, "branch to prepare")
	schemaDir := flag.String("schema-dir", "schema", "directory holding the schema YAML")
	schemaOnly := flag.Bool("schema-only", false,
		"load the schema (the schema library under -schema-dir's dcim/, then the stage kind) but do not seed data")
	remove := flag.Bool("delete", false,
		"delete the branch instead, a "+testsupport.TestBranchPrefix+"* one or "+testsupport.FixtureBranch+
			": every stage of every proposed change whose source it is, those proposed changes, then the branch")
	sdl := flag.String("sdl", "", "write the branch's GraphQL SDL to this path and exit")
	addLink := flag.Bool("add-link", false,
		"add the InterfacePhysical ports n1:ethernet-1/3 and n3:ethernet-1/3 and the DcimCable between them "+
			"to a seeded throwaway branch and exit")
	addFourthNode := flag.String("add-fourth-node", "",
		"add the DcimDevice n4 with the InterfacePhysical ports mgmt0 and ethernet-1/1, and a DcimCable to a new "+
			"<peer>:ethernet-1/3, to a "+testsupport.TestBranchPrefix+
			"* -branch seeded with the three-node fixture, render every artifact, and exit; takes the peer's name")
	addMixedLink := flag.Bool("add-mixed-link", false,
		"add the InterfacePhysical ports s1:ethernet-1/3 and e1:Ethernet3 and the DcimCable between them "+
			"to a throwaway branch seeded with -mixed, render both artifacts, and exit")
	generate := flag.Bool("generate", false,
		"render every DcimDevice's artifact on a throwaway branch, wait for Ready, and exit")
	setDescription := flag.String("set-description", "",
		"set every DcimDevice's description on a throwaway branch and exit "+
			"(the artifact-only change: the template's header prints it; regenerate with -generate)")
	disablePort := flag.String("disable-port", "",
		"set one InterfacePhysical's status to disabled on a throwaway branch and exit, as <device>:<interface>")
	addInterface := flag.String("add-interface", "",
		"add one InterfacePhysical, active and uncabled, to a DcimDevice on a "+testsupport.TestBranchPrefix+
			"* -branch and exit, as <device>:<name> (render it with -generate)")
	mixed := flag.Bool("mixed", false,
		"seed the mixed fixture (two DcimPlatforms under their manufacturers, three DcimDevices) "+
			"on a throwaway branch instead of the three-node one")
	propose := flag.Bool("propose", false,
		"open a draft proposed change from a throwaway -branch into main, wait for its validators, print its id, and exit")
	stage := flag.String("stage", "",
		"mark one stage with this label on a throwaway -branch's open proposed change, and exit "+
			"(head and branch-point are written too: a test writes what Fylgja must refuse)")
	runCheck := flag.Bool("run-check", false,
		"run a throwaway -branch's open proposed change's artifact checks, wait for its artifact validator, and exit")
	runChecks := flag.String("run-checks", "",
		"artifact or user: run a throwaway -branch's open proposed change's checks of that kind and exit; "+
			"artifact is -run-check, user waits up to 4,500s for every user validator and prints each check's conclusion")
	ready := flag.Bool("ready", false,
		"mark a throwaway -branch's open proposed change ready for review (is_draft false), and exit; it starts no check")
	closePC := flag.Bool("close", false, "close a throwaway -branch's open proposed change (its stages stay), and exit")
	at := flag.String("at", "",
		"with -stage: its as_of, verbatim; omitted, its at is when it was written")
	description := flag.String("description", "", "with -stage: its description")
	prepare := flag.Bool("prepare-main", false,
		"load the stage and probe kinds where absent, then the schema library on a main holding none of its kinds "+
			"(refused, loading nothing of it, when it holds any), create the group "+testsupport.ArtifactGroupName+
			", register this repository read-only with no credential, wait for its import, and exit; takes no -branch")
	repoName := flag.String("repository-name", testsupport.RepositoryName, "with -prepare-main: the registration's name")
	repoLocation := flag.String("repository-location", testsupport.RepositoryLocation,
		"with -prepare-main: the repository's HTTPS location")
	repoRef := flag.String("repository-ref", testsupport.RepositoryRef, "with -prepare-main: the ref the registration tracks")
	wait := flag.Duration("wait", 300*time.Second, "with -prepare-main: how long to wait for the import")
	seedMain := flag.Bool("seed-main", false,
		"write the three-node baseline onto main in the schema library's kinds (the tag, the manufacturer, the "+
			"platform, the four locations, the DcimDevices, their InterfacePhysical ports and DcimCables), "+
			"which must hold none of them, for a demo's window (D-054), and exit; takes no other flag")
	clearMain := flag.Bool("clear-main", false,
		"delete the baseline -seed-main wrote in the schema library's kinds, and nothing else, once no "+
			testsupport.TestBranchPrefix+"* branch exists, and exit; takes no other flag")
	probesFile := flag.String("probes", "",
		"write each probe of this declaration file as one "+testsupport.ProbeKind+" on main, which every branch's "+
			"read with no probe file then carries, and exit; takes no other flag")
	deleteProbes := flag.Bool("delete-probes", false,
		"delete every "+testsupport.ProbeKind+" on main, and exit; takes no other flag")
	flag.Parse()

	// -prepare-main is refused or allowed before any request: it writes main, so a flag
	// meant for a branch beside it is a mistake, never a narrowing.
	if err := checkPrepareFlags(*prepare, *wait); err != nil {
		fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
		os.Exit(1)
	}
	if err := checkBaselineFlags(*seedMain, *clearMain); err != nil {
		fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
		os.Exit(1)
	}
	if err := checkProbeFlags(*probesFile, *deleteProbes); err != nil {
		fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
		os.Exit(1)
	}
	if *probesFile != "" || *deleteProbes {
		if err := probes(*probesFile, *deleteProbes); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}
	if *seedMain || *clearMain {
		if err := baseline(*seedMain); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}
	if *prepare {
		if err := prepareMain(*schemaDir, *repoName, *repoLocation, *repoRef, *wait); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}

	if (*at != "" || *description != "") && *stage == "" {
		fmt.Fprintln(os.Stderr, "fylgja-fixture: -at and -description describe the stage -stage marks; give it")
		os.Exit(1)
	}
	if *propose || *ready || *stage != "" || *runCheck || *runChecks != "" || *closePC {
		if err := proposal(*branch, proposalFlags{propose: *propose, ready: *ready, label: *stage, runCheck: *runCheck,
			runChecks: *runChecks, closePC: *closePC, at: *at, description: *description}); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}

	// Every change flag acts on a throwaway branch only. The durable fixture branch is
	// written once, by the seed, and by nothing afterwards.
	if *addLink {
		if err := addThirdLink(*branch); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}
	if *addFourthNode != "" {
		if err := addFourthNodeTo(*branch, *addFourthNode); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}
	if *addMixedLink {
		if err := addMixedLinkTo(*branch); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}
	if *generate || *setDescription != "" || *disablePort != "" || *addInterface != "" {
		if err := change(*branch, *generate, *setDescription, *disablePort, *addInterface); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}

	if *sdl != "" {
		if err := writeSDL(*branch, *sdl); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}
	if err := run(*branch, *schemaDir, *schemaOnly, *remove, *mixed); err != nil {
		fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
		os.Exit(1)
	}
}

// prepareFlags are the flags -prepare-main takes; any other beside it is refused.
var prepareFlags = map[string]bool{
	"prepare-main": true, "schema-dir": true,
	"repository-name": true, "repository-location": true, "repository-ref": true, "wait": true,
}

// checkPrepareFlags refuses -prepare-main beside -branch or any action flag, and its own
// flags without it. It reads only the command line, so it refuses before any request.
func checkPrepareFlags(prepare bool, wait time.Duration) error {
	var given []string
	flag.Visit(func(f *flag.Flag) { given = append(given, f.Name) })
	sort.Strings(given)
	if !prepare {
		for _, name := range given {
			if prepareFlags[name] && name != "schema-dir" {
				return fmt.Errorf("-%s goes with -prepare-main; give it, or leave -%s out", name, name)
			}
		}
		return nil
	}
	for _, name := range given {
		if name == "branch" {
			return fmt.Errorf("-prepare-main takes no -branch: it prepares main")
		}
	}
	for _, name := range given {
		if !prepareFlags[name] {
			return fmt.Errorf("-prepare-main combines with no other flag: -%s was given", name)
		}
	}
	if wait <= 0 {
		return fmt.Errorf("-wait must be positive, got %s", wait)
	}
	return nil
}

// checkBaselineFlags refuses -seed-main and -clear-main together, and either beside any
// other flag, -branch among them: each acts on main alone, so a flag beside it is a
// mistake, never a narrowing. It reads only the command line, so it refuses before any
// request.
func checkBaselineFlags(seed, clear bool) error {
	if !seed && !clear {
		return nil
	}
	if seed && clear {
		return fmt.Errorf("-seed-main and -clear-main open and close the window; give one")
	}
	own := "seed-main"
	if clear {
		own = "clear-main"
	}
	var other []string
	flag.Visit(func(f *flag.Flag) {
		if f.Name != own {
			other = append(other, "-"+f.Name)
		}
	})
	if len(other) > 0 {
		sort.Strings(other)
		return fmt.Errorf("-%s acts on main alone and combines with no other flag: %s was given", own, strings.Join(other, ", "))
	}
	return nil
}

// checkProbeFlags refuses -probes and -delete-probes together, and either beside any other
// flag, -branch among them, so -branch fylgja-fixture too: each writes the probe kind on
// main, which is branch-agnostic (D-064), so a branch beside it is a mistake, never a
// narrowing. It reads only the command line, so it refuses before any request.
func checkProbeFlags(file string, remove bool) error {
	if file == "" && !remove {
		return nil
	}
	if file != "" && remove {
		return fmt.Errorf("-probes and -delete-probes write and delete the probes on %s; give one", testsupport.DefaultBranch)
	}
	own := "probes"
	if remove {
		own = "delete-probes"
	}
	var other []string
	flag.Visit(func(f *flag.Flag) {
		if f.Name != own {
			other = append(other, "-"+f.Name)
		}
	})
	if len(other) > 0 {
		sort.Strings(other)
		return fmt.Errorf("-%s acts on %s's %s alone and combines with no other flag: %s was given",
			own, testsupport.DefaultBranch, testsupport.ProbeKind, strings.Join(other, ", "))
	}
	return nil
}

// probes writes a declaration's probes into the probe kind on main, or deletes every probe
// there (R-26). The file is held to the declaration's own rules first, as the server holds
// a --probes file, so a probe the server would refuse is never written; a probe of a name
// the kind holds is Infrahub's to refuse, by its uniqueness constraint.
func probes(file string, remove bool) error {
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	if remove {
		n, err := c.DeleteProbes()
		if err != nil {
			return fmt.Errorf("after deleting %s: %w", plural(n, "probe", "probes"), err)
		}
		fmt.Printf("deleted %s of %s on %s\n", plural(n, "probe", "probes"), testsupport.ProbeKind, testsupport.DefaultBranch)
		return nil
	}
	raw, err := os.ReadFile(file)
	if err != nil {
		return err
	}
	decl, list := probe.Parse(raw, file)
	if decl == nil {
		var lines []string
		for _, f := range list {
			lines = append(lines, fmt.Sprintf("%s at %s: %s", f.Rule, f.Object, f.Message))
		}
		return fmt.Errorf("%s is refused, nothing written:\n  %s", file, strings.Join(lines, "\n  "))
	}
	if err := c.WriteProbes(decl); err != nil {
		return err
	}
	names := make([]string, 0, len(decl.Probes))
	for _, p := range decl.Probes {
		names = append(names, p.Name)
	}
	fmt.Printf("wrote %s to %s on %s: %s\n", plural(len(names), "probe", "probes"), testsupport.ProbeKind,
		testsupport.DefaultBranch, strings.Join(names, ", "))
	return nil
}

// baseline opens or closes a demo's window (D-054): -seed-main writes the three-node
// fixture onto main, -clear-main removes it, each refusing when main is not as it expects.
func baseline(seed bool) error {
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	if seed {
		if err := c.SeedMainBaseline(); err != nil {
			return err
		}
		fmt.Printf("three-node baseline seeded on %s, with every artifact rendered and Ready; "+
			"no tier 2 or tier 3 until -clear-main removes it\n", testsupport.DefaultBranch)
		return nil
	}
	done, err := c.ClearMainBaseline()
	if err != nil {
		if done == (testsupport.ClearedBaseline{}) {
			return err
		}
		return fmt.Errorf("%w (deleted before it: %s)", err, clearedLine(done))
	}
	fmt.Printf("baseline removed from %s: %s\n", testsupport.DefaultBranch, clearedLine(done))
	return nil
}

// clearedLine says what -clear-main deleted, and how many of the devices' artifacts
// Infrahub had already removed with them.
func clearedLine(d testsupport.ClearedBaseline) string {
	return fmt.Sprintf("%s, %s, %s, %s, %s, %s, %s, %s; artifacts: %d gone with their devices, %d deleted",
		plural(d.Addresses, "address", "addresses"), plural(d.Cables, "cable", "cables"), plural(d.Interfaces, "interface", "interfaces"),
		plural(d.Devices, "device", "devices"), plural(d.Platforms, "platform", "platforms"),
		plural(d.Manufacturers, "manufacturer", "manufacturers"), plural(d.Locations, "location", "locations"),
		plural(d.Tags, "tag", "tags"), d.ArtifactsWithDevices, d.Artifacts)
}

// prepareMain makes main what every branch needs before it can render (D-028, D-044):
// the stage and probe kinds (D-064), the schema library, the group the definition targets,
// and this repository registered read-only with no credential, imported.
//
// The stage and probe kinds go first, wherever either is absent: they are Fylgja's own and
// name none of the library's kinds, so a main holding the library and lacking one gains it
// (016's upgrade). The library goes next, and only onto a main that holds none of its
// kinds (R-13): the development host's migrated main and CI's fresh one. A main holding
// any of them is refused before any write of the library, the group and the registration
// included, since a library already there is its operator's, of whatever commit. So a
// second run is the own kinds present, then that refusal, which the bring-up script reads
// as present. After the library, each step looks up by name and skips what exists;
// nothing is updated or deleted.
func prepareMain(schemaDir, name, location, ref string, wait time.Duration) error {
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	loaded, files, err := c.PrepareMainSchema(schemaDir)
	var held *testsupport.LibraryHeldError
	if err != nil && !errors.As(err, &held) {
		return err
	}
	// The stage and probe kinds are schema/'s own files, loaded in one request: on a main
	// that holds both the hash does not move, and one it lacks is added beside the other.
	if loaded {
		fmt.Printf("stage and probe kinds loaded on %s\n", testsupport.DefaultBranch)
	} else {
		fmt.Println("stage and probe kinds present")
	}
	if err != nil {
		return err
	}
	fmt.Printf("schema library loaded on %s (%d files, %s@%s)\n",
		testsupport.DefaultBranch, files, ctm.ModelSchemaLibrary, ctm.ModelVersion)

	created, err := c.EnsureGroup(testsupport.ArtifactGroupName)
	if err != nil {
		return err
	}
	if created {
		fmt.Printf("group %s created\n", testsupport.ArtifactGroupName)
	} else {
		fmt.Printf("group %s present\n", testsupport.ArtifactGroupName)
	}

	created, err = c.EnsureReadOnlyRepository(name, location, ref)
	if err != nil {
		return err
	}
	if created {
		fmt.Printf("repository %s created (location %s, ref %s, no credential)\n", name, location, ref)
	} else {
		fmt.Printf("repository %s present (location %s, ref %s)\n", name, location, ref)
	}

	took, err := c.AwaitImport(name, wait)
	if err != nil {
		return err
	}
	fmt.Printf("import complete after %.0fs: query, transform and definition on main\n", took.Seconds())
	return nil
}

// writeSDL fetches the branch's GraphQL schema. genqlient generates the typed client
// from it, so it is committed: the build must never need a live Infrahub (D-017).
func writeSDL(branch, path string) error {
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	sdl, err := c.SDL(branch)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(path, sdl, 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %d bytes of SDL from %s to %s\n", len(sdl), branch, path)
	return nil
}

// addThirdLink makes the topology change tier 3's cases 5 and 7 step a twin to and case 9
// rehearses (until 019, the change case 5's following rebuilt on).
// The durable fixture branch is never changed: every test and the twins
// built from it rely on its bundle_id staying put.
func addThirdLink(branch string) error {
	if branch == testsupport.FixtureBranch {
		return fmt.Errorf("-add-link refuses branch %s: the fixture is never changed; seed a throwaway branch and name it with -branch",
			branch)
	}
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	if err := c.SeedThirdLink(branch); err != nil {
		return err
	}
	fmt.Printf("link n1:ethernet-1/3 <-> n3:ethernet-1/3 added on %s\n", branch)
	return nil
}

// addFourthNodeTo adds n4 to a three-node test branch, cabled to peer's ethernet-1/3: the
// last stage of a demo's change (D-054), a node a step adds to a running lab. It refuses,
// before any request, the fixture, a branch outside the test prefix and a peer that is not
// a plain device name. Every artifact is rendered, but a rewrite is not awaited: a caller
// that seals the change waits for n4's artifact and the peer's checksum.
func addFourthNodeTo(branch, peer string) error {
	if branch == testsupport.FixtureBranch {
		return fmt.Errorf("-add-fourth-node refuses branch %s: the fixture is never changed; seed a throwaway branch and name it with -branch",
			branch)
	}
	if !strings.HasPrefix(branch, testsupport.TestBranchPrefix) {
		return fmt.Errorf("-add-fourth-node refuses branch %s: every branch it changes begins %s; "+
			"seed a throwaway branch and name it with -branch", branch, testsupport.TestBranchPrefix)
	}
	if strings.ContainsAny(peer, ": \t/") {
		return fmt.Errorf("-add-fourth-node takes the peer device's name, such as n2, got %q", peer)
	}
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	if err := c.SeedFourthNode(branch, peer); err != nil {
		return err
	}
	fmt.Printf("device n4 added on %s, link n4:ethernet-1/1 <-> %s:ethernet-1/3, every artifact rendered\n", branch, peer)
	return nil
}

// addMixedLinkTo makes the change tier 3's step case steps over: a
// link between the mixed fixture's s1 and e1, which re-cables s1 live and restarts e1. The
// durable fixture branch is refused before any request, as -add-link refuses it.
func addMixedLinkTo(branch string) error {
	if branch == testsupport.FixtureBranch {
		return fmt.Errorf("-add-mixed-link refuses branch %s: the fixture is never changed; seed a throwaway branch with -mixed and name it with -branch",
			branch)
	}
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	if err := c.SeedMixedLink(branch); err != nil {
		return err
	}
	fmt.Printf("link s1:ethernet-1/3 <-> e1:Ethernet3 added on %s, both artifacts rendered\n", branch)
	return nil
}

// proposalFlags are the proposed-change flags as given: -stage's label, with -at and
// -description, and -run-checks' kind.
type proposalFlags struct {
	propose, ready  bool
	label           string
	runCheck        bool
	runChecks       string
	closePC         bool
	at, description string
}

// The kinds -run-checks takes: artifact, which -run-check is, and user.
const (
	checksArtifact = "artifact"
	checksUser     = "user"
)

// userChecksWait bounds -run-checks user: the live check's timeout of 4,260 s and a margin
// (research R-09, R-20).
const userChecksWait = 4500 * time.Second

// proposal runs the one proposed-change flag given. Each is refused, before any request,
// on the fixture and on a branch outside the test prefix: an operator's proposed change is
// the operator's, and the fixture has none. More than one at once is refused rather than
// run in an order the command line does not show, and so is a kind -run-checks does not
// take.
func proposal(branch string, f proposalFlags) error {
	var given []string
	for _, g := range []struct {
		name string
		set  bool
	}{{"propose", f.propose}, {"ready", f.ready}, {"stage", f.label != ""}, {"run-check", f.runCheck},
		{"run-checks", f.runChecks != ""}, {"close", f.closePC}} {
		if g.set {
			given = append(given, "-"+g.name)
		}
	}
	if len(given) > 1 {
		return fmt.Errorf("%s act on one proposed change one at a time; give one", strings.Join(given, " and "))
	}
	flagName := given[0]
	if f.runChecks != "" && f.runChecks != checksArtifact && f.runChecks != checksUser {
		return fmt.Errorf("-run-checks takes %s or %s, got %q", checksArtifact, checksUser, f.runChecks)
	}
	if branch == testsupport.FixtureBranch {
		return fmt.Errorf("%s refuses branch %s: the fixture has no proposed change", flagName, branch)
	}
	if !strings.HasPrefix(branch, testsupport.TestBranchPrefix) {
		return fmt.Errorf("%s refuses branch %s: every branch this tool proposes from begins %s; "+
			"seed a throwaway branch and name it with -branch", flagName, branch, testsupport.TestBranchPrefix)
	}
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	if f.propose {
		return openProposal(c, branch)
	}
	id, err := openProposalOf(c, branch)
	if err != nil {
		return err
	}
	switch {
	case f.label != "":
		return markStage(c, branch, id, f.label, f.at, f.description)
	case f.ready:
		if err := c.MarkReady(id); err != nil {
			return err
		}
		fmt.Printf("proposed change %s on %s marked ready for review\n", id, branch)
	case f.runCheck || f.runChecks == checksArtifact:
		start := time.Now()
		stamp, err := c.RunCheck(id, 120*time.Second)
		if err != nil {
			return err
		}
		fmt.Printf("artifact checks of proposed change %s on %s concluded: validator completed at %s, after %.0fs\n",
			id, branch, stamp, time.Since(start).Seconds())
	case f.runChecks == checksUser:
		return runUserChecks(c, branch, id)
	default:
		if err := c.CloseProposedChange(id); err != nil {
			return err
		}
		fmt.Printf("proposed change %s on %s closed; its stages stay\n", id, branch)
	}
	return nil
}

// openProposal opens a draft and waits for its pipeline, which renders the branch's
// artifacts: an intent change made before the wait ends could be rendered under the
// first mark (research §2.4).
func openProposal(c *testsupport.Client, branch string) error {
	start := time.Now()
	id, err := c.OpenProposedChange(branch, true)
	if err != nil {
		if id != "" {
			return fmt.Errorf("proposed change %s on %s: %w", id, branch, err)
		}
		return err
	}
	took := time.Since(start)
	rows, err := c.ValidatorsOf(id)
	if err != nil {
		return err
	}
	fmt.Printf("proposed change %s opened on %s, draft; %s concluded in %.0fs\n",
		id, branch, plural(len(rows), "validator", "validators"), took.Seconds())
	return nil
}

// openProposalOf finds a branch's one open proposed change: Infrahub holds at most one
// per source branch (research §2.3), so the branch names it.
func openProposalOf(c *testsupport.Client, branch string) (string, error) {
	rows, err := c.ProposedChangesOf(branch)
	if err != nil {
		return "", err
	}
	var open []string
	for _, r := range rows {
		if r.State == "open" {
			open = append(open, r.ID)
		}
	}
	switch len(open) {
	case 0:
		return "", fmt.Errorf("branch %s has no open proposed change; open one with -propose", branch)
	case 1:
		return open[0], nil
	default:
		return "", fmt.Errorf("branch %s has %d open proposed changes, want one", branch, len(open))
	}
}

// markStage marks one stage. Its at is the given as_of, or the moment of the write when
// none is given, so mark it after the writes it seals and after their generate has moved
// the artifacts. A reserved label is written as given: a test writes what Fylgja refuses.
func markStage(c *testsupport.Client, branch, id, label, at, description string) error {
	stageID, stamp, err := c.MarkStage(id, label, at, description)
	if err != nil {
		return err
	}
	shown, source := stamp, "written"
	if at != "" {
		shown, source = at, "given"
	}
	fmt.Printf("stage %s/%s marked on proposed change %s (stage id %s) at %s (%s)\n",
		branch, label, id, stageID, shown, source)
	return nil
}

// runUserChecks runs the open proposed change's user checks, waits for each check
// definition Infrahub runs on the branch to run again to completed, and prints one line per
// check: its name, its conclusion and its message's length, never the message, which a
// check fills. A branch that sees no definition of a registered repository returns at once,
// saying so.
func runUserChecks(c *testsupport.Client, branch, id string) error {
	rows, err := c.RunUserChecks(id, userChecksWait)
	if err != nil {
		return err
	}
	if len(rows) == 0 {
		fmt.Printf("no user check ran on proposed change %s on %s: the branch sees no check definition of a registered repository\n", id, branch)
		return nil
	}
	for _, r := range rows {
		fmt.Printf("check %s: %s (message %s characters)\n", r.Name, r.Conclusion, grouped(utf8.RuneCountInString(r.Message)))
	}
	return nil
}

// grouped writes n with a comma between each group of three digits, as the contracts write
// a count: 2,311.
func grouped(n int) string {
	s := strconv.Itoa(n)
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return s
}

// plural names a count with its noun's form.
func plural(n int, one, many string) string {
	if n == 1 {
		return fmt.Sprintf("%d %s", n, one)
	}
	return fmt.Sprintf("%d %s", n, many)
}

// change applies one of the branch-change flags. Each refuses the durable fixture branch
// for the same reason -add-link does: every test, and every twin built from it, relies
// on its artifacts and its bundle_id staying put. The fixture branch is written
// once, by the seed that creates it.
//
// None of these generates on its own except -generate: Infrahub 1.11.2 regenerates
// nothing when intent changes, so a change and its rendering are two
// calls, and a caller that forgets the second sees the old bytes — which is the
// behaviour the tiers are written against, not a bug to paper over here.
//
// -add-interface (015) is narrower still: it refuses any branch outside the test prefix as
// the proposed-change flags do, and a value that is not <device>:<name>, both before any
// request. The port it adds is one the device's artifact names once generated, and the
// compile may omit (research R-14): a rehearsal's stage made to fail at the push.
func change(branch string, generate bool, description, port, addIface string) error {
	if branch == testsupport.FixtureBranch {
		return fmt.Errorf("this flag refuses branch %s: the fixture is written once and never changed; "+
			"seed a throwaway branch and name it with -branch", branch)
	}
	var ifDevice, ifName string
	if addIface != "" {
		if !strings.HasPrefix(branch, testsupport.TestBranchPrefix) {
			return fmt.Errorf("-add-interface refuses branch %s: every branch it changes begins %s; "+
				"seed a throwaway branch and name it with -branch", branch, testsupport.TestBranchPrefix)
		}
		var ok bool
		ifDevice, ifName, ok = strings.Cut(addIface, ":")
		if !ok || ifDevice == "" || ifName == "" {
			return fmt.Errorf("-add-interface takes <device>:<name>, got %q", addIface)
		}
	}
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}

	devices, err := c.DeviceNames(branch)
	if err != nil {
		return err
	}
	if description != "" {
		for _, d := range devices {
			if err := c.SetDeviceDescription(branch, d, description); err != nil {
				return err
			}
		}
		fmt.Printf("description set to %q on %d device(s) on %s\n", description, len(devices), branch)
	}
	if port != "" {
		device, iface, ok := strings.Cut(port, ":")
		if !ok || device == "" || iface == "" {
			return fmt.Errorf("-disable-port takes <device>:<interface>, got %q", port)
		}
		if err := c.DisablePort(branch, device, iface); err != nil {
			return err
		}
		fmt.Printf("interface %s on %s disabled on %s\n", iface, device, branch)
	}
	if addIface != "" {
		if err := c.AddInterface(branch, ifDevice, ifName); err != nil {
			return err
		}
		fmt.Printf("interface %s added on %s on %s: physical, active, no cable; -generate renders it\n", ifName, ifDevice, branch)
	}
	if generate {
		if err := c.GenerateArtifacts(branch); err != nil {
			return err
		}
		fmt.Printf("artifacts rendered and Ready on %s\n", branch)
	}
	return nil
}

// deleteBranch deletes a branch and what hangs on it. A test branch goes in the fixed
// order: every stage of every proposed change whose source it is, then those proposed
// changes, then the branch, since Infrahub refuses a proposed change's delete while a
// stage names it (research §8.8) and a branch deleted first cancels its open proposed
// change (research §2.3). The fixture has no proposed change and is deleted as before,
// which make infrahub-clean needs; any other branch is refused by deletable before any
// request, being an operator's.
func deleteBranch(c *testsupport.Client, branch string) error {
	if branch == testsupport.FixtureBranch {
		if err := c.DeleteBranch(branch); err != nil {
			return err
		}
		fmt.Printf("deleted branch %s\n", branch)
		return nil
	}
	stages, proposed, err := c.DeleteTestBranchCounting(branch)
	if err != nil {
		return fmt.Errorf("after deleting %s and %s: %w",
			plural(stages, "stage", "stages"), plural(proposed, "proposed change", "proposed changes"), err)
	}
	fmt.Printf("deleted %s, %s, branch %s\n",
		plural(stages, "stage", "stages"), plural(proposed, "proposed change", "proposed changes"), branch)
	return nil
}

// deletable refuses -delete on a branch that is neither a test's nor the fixture.
func deletable(branch string) error {
	if branch != testsupport.FixtureBranch && !strings.HasPrefix(branch, testsupport.TestBranchPrefix) {
		return fmt.Errorf("-delete refuses branch %s: every branch this tool deletes begins %s, or is %s",
			branch, testsupport.TestBranchPrefix, testsupport.FixtureBranch)
	}
	return nil
}

func run(branch, schemaDir string, schemaOnly, remove, mixed bool) error {
	if remove {
		if err := deletable(branch); err != nil {
			return err
		}
	}
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	if remove {
		return deleteBranch(c, branch)
	}
	if err := c.CreateBranch(branch); err != nil {
		return err
	}
	if err := c.LoadSchema(branch, schemaDir); err != nil {
		return err
	}
	fmt.Printf("schema loaded on %s\n", branch)
	if schemaOnly {
		return nil
	}
	// The seed joins the group and renders, for every branch including the fixture's
	// one re-creation: a branch whose devices have no artifact is one every read
	// refuses. SeedMixed refuses the durable fixture branch itself, as every
	// change flag does: that branch holds the three-node fixture and nothing else.
	seeded := "three-node fixture"
	seed := c.SeedThreeNode
	if mixed {
		seeded, seed = "mixed fixture (two platforms, three devices)", c.SeedMixed
	}
	if err := seed(branch); err != nil {
		return err
	}
	fmt.Printf("%s seeded on %s, with every artifact rendered and Ready\n", seeded, branch)
	return nil
}
