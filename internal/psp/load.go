package psp

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/happypathnetworking/fylgja"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// Registry is the set of platforms this build supports, keyed by the NOS identifier
// that devices carry (the join from Device.platform.nos).
type Registry struct {
	byNOS  map[string]*PSP
	byID   map[string]*PSP
	byKind map[string]*PSP
}

// Lookup returns the package for a NOS identifier, and whether one exists. A missing
// package is data that has not been written, never a code path (Constitution II).
func (r *Registry) Lookup(nos string) (*PSP, bool) {
	p, ok := r.byNOS[nos]
	return p, ok
}

// LookupID returns the package with a platform id: the join from a bundle manifest's
// nodes[].psp.id, which is how provisioning finds a stored bundle's budgets and probe.
func (r *Registry) LookupID(id string) (*PSP, bool) {
	p, ok := r.byID[id]
	return p, ok
}

// LookupKind returns the package whose image.clab_kind is kind: the join from the
// `kind` containerlab reports per container, which is how the teardown of an orphan
// with no manifest is budgeted.
func (r *Registry) LookupKind(kind string) (*PSP, bool) {
	p, ok := r.byKind[kind]
	return p, ok
}

// index rebuilds the id and kind joins from the packages that survived shadowing. When
// two packages share an id or a kind, the one whose NOS sorts first answers, so the
// answer never depends on map order.
func (r *Registry) index() {
	r.byID = map[string]*PSP{}
	r.byKind = map[string]*PSP{}
	for _, nos := range r.Platforms() {
		p := r.byNOS[nos]
		if _, taken := r.byID[p.Platform.ID]; !taken {
			r.byID[p.Platform.ID] = p
		}
		if _, taken := r.byKind[p.Image.ClabKind]; !taken {
			r.byKind[p.Image.ClabKind] = p
		}
	}
}

// InvalidError reports that an override directory holds a package `psp validate`
// rejects. It carries the findings, so a command can report them under their own psp.*
// identifiers as a rejection rather than as a failure to load.
type InvalidError struct {
	Findings findings.List
}

func (e *InvalidError) Error() string {
	var parts []string
	for _, f := range e.Findings {
		if f.Severity != findings.Rejection {
			continue
		}
		where := f.Object
		if f.Location != nil {
			where = f.Location.File
		}
		parts = append(parts, fmt.Sprintf("%s: %s: %s", where, f.Rule, f.Message))
	}
	return "invalid support package: " + strings.Join(parts, "; ")
}

// Platforms lists the supported NOS identifiers, sorted.
func (r *Registry) Platforms() []string {
	out := make([]string, 0, len(r.byNOS))
	for k := range r.byNOS {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// Parse decodes one package. Unknown fields are rejected so a typo in a contributed
// package fails at load rather than silently doing nothing.
func Parse(data []byte, path, origin string) (*PSP, error) {
	dec := yaml.NewDecoder(strings.NewReader(string(data)))
	dec.KnownFields(true)
	var p PSP
	if err := dec.Decode(&p); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	p.Origin = origin
	p.Path = path
	return &p, nil
}

// ParseFile decodes one package from disk.
func ParseFile(path, origin string) (*PSP, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading support package: %w", err)
	}
	return Parse(data, path, origin)
}

// Embedded loads the packages compiled into the binary.
func Embedded() ([]*PSP, error) {
	entries, err := fs.Glob(fylgja.Data, "psp/*.yaml")
	if err != nil {
		return nil, err
	}
	sort.Strings(entries)
	out := make([]*PSP, 0, len(entries))
	for _, name := range entries {
		data, err := fylgja.Data.ReadFile(name)
		if err != nil {
			return nil, err
		}
		p, err := Parse(data, name, OriginEmbedded)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, nil
}

// FromDir loads every package in a directory.
func FromDir(dir string) ([]*PSP, error) {
	matches, err := filepath.Glob(filepath.Join(dir, "*.yaml"))
	if err != nil {
		return nil, err
	}
	sort.Strings(matches)
	out := make([]*PSP, 0, len(matches))
	for _, path := range matches {
		p, err := ParseFile(path, OriginOverride)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, nil
}

// Load builds the registry: embedded packages first, then any in overrideDir, which
// shadow embedded ones with the same NOS identifier. An empty overrideDir means
// embedded only.
//
// Override packages are validated before they are parsed, and any rejection returns an
// *InvalidError; warnings and notes pass. Every command that loads packages therefore
// refuses one `psp validate` rejects, under the rule that names its defect, instead of
// accepting it and failing later under the wrong identifier (Constitution II, X).
// Embedded packages are not re-validated here: TestShippedPackagesAreValidAndEmbedded
// guarantees them at build time.
func Load(overrideDir string) (*Registry, error) {
	r := &Registry{byNOS: map[string]*PSP{}}
	embedded, err := Embedded()
	if err != nil {
		return nil, fmt.Errorf("loading embedded support packages: %w", err)
	}
	for _, p := range embedded {
		r.byNOS[p.Platform.NOS] = p
	}
	if overrideDir == "" {
		r.index()
		return r, nil
	}
	if _, err := os.Stat(overrideDir); err != nil {
		return nil, fmt.Errorf("support package override directory: %w", err)
	}
	paths, err := filepath.Glob(filepath.Join(overrideDir, "*.yaml"))
	if err != nil {
		return nil, err
	}
	sort.Strings(paths)
	if list := Validate(paths); list.Rejected() {
		return nil, &InvalidError{Findings: list}
	}
	over, err := FromDir(overrideDir)
	if err != nil {
		return nil, err
	}
	for _, p := range over {
		r.byNOS[p.Platform.NOS] = p
	}
	r.index()
	return r, nil
}

// SchemaBytes returns the embedded PSP format schema, used for validation.
func SchemaBytes() ([]byte, error) {
	return fylgja.Data.ReadFile("psp/psp.schema.json")
}
