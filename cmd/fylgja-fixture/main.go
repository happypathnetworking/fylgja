//go:build fixture

// Command fylgja-fixture prepares a local Infrahub for development: it loads the
// generics contract and reference schema onto a branch and seeds the three-node fixture
// or the mixed one, or makes following's branch change on a throwaway branch, or writes
// and removes a test series of waypoints (M10), or prepares main: the schema, the group and
// this repository's read-only registration (D-044). Development tooling, not the product —
// it writes to Infrahub, which the product never does. Build-tagged so it cannot be built
// by accident.
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/testsupport"
	"github.com/happypathnetworking/fylgja/internal/waypoint"
)

func main() {
	branch := flag.String("branch", testsupport.FixtureBranch, "branch to prepare")
	schemaDir := flag.String("schema-dir", "schema", "directory holding the schema YAML")
	schemaOnly := flag.Bool("schema-only", false, "load the schema but do not seed data")
	remove := flag.Bool("delete", false,
		"delete the branch instead, and every "+testsupport.TestSeriesPrefix+"* waypoint naming it")
	sdl := flag.String("sdl", "", "write the branch's GraphQL SDL to this path and exit")
	addLink := flag.Bool("add-link", false,
		"add link n1:ethernet-1/3 <-> n3:ethernet-1/3 to a seeded throwaway branch and exit")
	addMixedLink := flag.Bool("add-mixed-link", false,
		"add link s1:ethernet-1/3 <-> e1:Ethernet3 to a throwaway branch seeded with -mixed, render both artifacts, and exit")
	generate := flag.Bool("generate", false,
		"render every device's artifact on a throwaway branch, wait for Ready, and exit")
	setRole := flag.String("set-role", "",
		"set every device's role on a throwaway branch and exit (the artifact-only change; regenerate with -generate)")
	setSite := flag.String("set-site", "",
		"set every device's site on a throwaway branch and exit (regenerates to identical bytes)")
	disablePort := flag.String("disable-port", "",
		"disable one interface on a throwaway branch and exit, as <device>:<interface>")
	mixed := flag.Bool("mixed", false,
		"seed the mixed fixture (two platforms, three devices) on a throwaway branch instead of the three-node one")
	wp := flag.String("waypoint", "",
		"write one waypoint <series>/<sequence> naming a throwaway -branch as it stands now, and exit; "+
			"the series begins "+testsupport.TestSeriesPrefix+" (write it after the writes it seals)")
	at := flag.String("at", "", "with -waypoint: the waypoint's as_of, verbatim; omitted, its at is when it was written")
	description := flag.String("description", "", "with -waypoint: the waypoint's description")
	deleteSeries := flag.String("delete-series", "",
		"delete every waypoint of a "+testsupport.TestSeriesPrefix+"* series and exit")
	prepare := flag.Bool("prepare-main", false,
		"load the schema on main, create the group "+testsupport.ArtifactGroupName+
			", register this repository read-only with no credential, wait for its import, and exit; takes no -branch")
	repoName := flag.String("repository-name", testsupport.RepositoryName, "with -prepare-main: the registration's name")
	repoLocation := flag.String("repository-location", testsupport.RepositoryLocation,
		"with -prepare-main: the repository's HTTPS location")
	repoRef := flag.String("repository-ref", testsupport.RepositoryRef, "with -prepare-main: the ref the registration tracks")
	wait := flag.Duration("wait", 300*time.Second, "with -prepare-main: how long to wait for the import")
	flag.Parse()

	// -prepare-main is refused or allowed before any request: it writes main, so a flag
	// meant for a branch beside it is a mistake, never a narrowing.
	if err := checkPrepareFlags(*prepare, *wait); err != nil {
		fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
		os.Exit(1)
	}
	if *prepare {
		if err := prepareMain(*schemaDir, *repoName, *repoLocation, *repoRef, *wait); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}

	if (*at != "" || *description != "") && *wp == "" {
		fmt.Fprintln(os.Stderr, "fylgja-fixture: -at and -description describe the waypoint -waypoint writes; give -waypoint")
		os.Exit(1)
	}
	if *wp != "" {
		if err := writeWaypoint(*branch, *wp, *at, *description); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}
	if *deleteSeries != "" {
		if err := removeSeries(*deleteSeries); err != nil {
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
	if *addMixedLink {
		if err := addMixedLinkTo(*branch); err != nil {
			fmt.Fprintln(os.Stderr, "fylgja-fixture:", err)
			os.Exit(1)
		}
		return
	}
	if *generate || *setRole != "" || *setSite != "" || *disablePort != "" {
		if err := change(*branch, *generate, *setRole, *setSite, *disablePort); err != nil {
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

// prepareMain makes main what every branch needs before it can render (D-028, D-044):
// the schema, the group the definition targets, and this repository registered read-only
// with no credential, imported. Each step looks up by name and skips what exists, so a
// second run writes nothing; nothing is updated or deleted.
func prepareMain(schemaDir, name, location, ref string, wait time.Duration) error {
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	if err := c.LoadSchema("main", schemaDir); err != nil {
		return err
	}
	fmt.Println("schema loaded on main")

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

// addThirdLink makes the change tier 3's following case rebuilds on.
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

// writeWaypoint writes one waypoint of a test series naming a throwaway branch. The durable
// fixture branch never gains a persistent series, and
// a series that is not a test's is refused before any request, so no call here can write
// where an operator's series live. Each call comes after the writes it seals and after the
// generate the previous flag ran: the one rule of schema/README.md.
func writeWaypoint(branch, ref, at, description string) error {
	r, err := waypoint.ParseRef(ref)
	if err != nil {
		return err
	}
	if branch == testsupport.FixtureBranch {
		return fmt.Errorf("-waypoint refuses branch %s: the fixture never gains a persistent series; "+
			"seed a throwaway branch and name it with -branch", branch)
	}
	if !strings.HasPrefix(r.Series, testsupport.TestSeriesPrefix) {
		return fmt.Errorf("-waypoint refuses series %s: every series this tool writes begins %s, and is a test's",
			r.Series, testsupport.TestSeriesPrefix)
	}
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	id, err := c.WriteWaypoint(r.Series, r.Sequence, branch, at, description)
	if err != nil {
		return err
	}
	fmt.Printf("waypoint %s written naming branch %s (id %s)\n", r, branch, id)
	return nil
}

// removeSeries deletes a test series by name: tier 2's cleanup by hand, when a test was
// killed before its own.
func removeSeries(series string) error {
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	n, err := c.DeleteWaypointSeries(series)
	if err != nil {
		return err
	}
	fmt.Printf("deleted %d waypoint(s) of series %s\n", n, series)
	return nil
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
func change(branch string, generate bool, role, site, port string) error {
	if branch == testsupport.FixtureBranch {
		return fmt.Errorf("this flag refuses branch %s: the fixture is written once and never changed; "+
			"seed a throwaway branch and name it with -branch", branch)
	}
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}

	devices, err := c.DeviceNames(branch)
	if err != nil {
		return err
	}
	if role != "" {
		for _, d := range devices {
			if err := c.SetDeviceRole(branch, d, role); err != nil {
				return err
			}
		}
		fmt.Printf("role set to %q on %d device(s) on %s\n", role, len(devices), branch)
	}
	if site != "" {
		for _, d := range devices {
			if err := c.SetDeviceSite(branch, d, site); err != nil {
				return err
			}
		}
		fmt.Printf("site set to %q on %d device(s) on %s\n", site, len(devices), branch)
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
	if generate {
		if err := c.GenerateArtifacts(branch); err != nil {
			return err
		}
		fmt.Printf("artifacts rendered and Ready on %s\n", branch)
	}
	return nil
}

func run(branch, schemaDir string, schemaOnly, remove, mixed bool) error {
	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	if remove {
		// The test series naming the branch first: a waypoint outlives its branch, so
		// one left behind would be listed by every waypoint list after.
		n, err := c.DeleteWaypointsNaming(branch)
		if err != nil {
			return err
		}
		fmt.Printf("deleted %d test waypoint(s) naming branch %s\n", n, branch)
		if err := c.DeleteBranch(branch); err != nil {
			return err
		}
		fmt.Printf("deleted branch %s\n", branch)
		return nil
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
