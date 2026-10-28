package probe

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"gopkg.in/yaml.v3"

	"github.com/happypathnetworking/fylgja"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// Subdirectory is where an override directory holds its probe packages: the PSP override
// directory's probes/, so no flag is added (R-08). psp.Load globs the directory's own
// *.yaml alone and never reads it (TestThePSPLoaderSkipsTheProbesSubdirectory).
const Subdirectory = "probes"

// schemaID is the probe package schema's `$id`, which moves with the format, as the PSP's
// does.
const schemaID = "https://github.com/happypathnetworking/fylgja/probes/v" + PackageVersion

// Registry is the set of probe formats this build runs, keyed by format, by which an
// override package shadows an embedded one and a declaration's probe names its package.
type Registry struct {
	byFormat map[string]*Package
}

// Lookup returns the package of a format, and whether one is loaded. A missing package is
// data that has not been written, never a code path (Constitution II).
func (r *Registry) Lookup(format string) (*Package, bool) {
	p, ok := r.byFormat[format]
	return p, ok
}

// Formats lists the loaded formats, sorted: what a declaration's probe may name, and what
// probe.format.unknown names.
func (r *Registry) Formats() []string {
	out := make([]string, 0, len(r.byFormat))
	for f := range r.byFormat {
		out = append(out, f)
	}
	sort.Strings(out)
	return out
}

// InvalidError reports that the override directory's probes/ holds a package
// ValidatePackages rejects, or that two packages of one origin declare one format. It
// carries the findings, so a role reports them under their own probe.package.* identifiers,
// as psp.InvalidError carries a PSP's.
type InvalidError struct {
	Findings findings.List
}

func (e *InvalidError) Error() string {
	var parts []string
	for _, f := range e.Findings {
		if f.Severity == findings.Rejection {
			parts = append(parts, fmt.Sprintf("%s: %s: %s", f.Object, f.Rule, f.Message))
		}
	}
	return "invalid probe package: " + strings.Join(parts, "; ")
}

// source is one package file's path and bytes.
type source struct {
	path string
	data []byte
}

// embeddedSources reads the packages compiled into the binary, in path order.
func embeddedSources() ([]source, error) {
	names, err := fs.Glob(fylgja.Data, Subdirectory+"/*.yaml")
	if err != nil {
		return nil, err
	}
	sort.Strings(names)
	out := make([]source, 0, len(names))
	for _, name := range names {
		data, err := fylgja.Data.ReadFile(name)
		if err != nil {
			return nil, err
		}
		out = append(out, source{path: name, data: data})
	}
	return out, nil
}

// Load builds the registry: the embedded packages, then any in <overrideDir>/probes/, which
// shadow an embedded package of their format. An empty overrideDir means embedded only, and
// an override directory with no probes/ overrides nothing.
//
// Override packages are validated (ValidatePackages) before they are parsed, and any
// rejection is an *InvalidError, so serve and worker run refuse at start a package the
// validation rejects, under the rule that names its defect. Embedded packages are not re-validated:
// TestTheShippedPackagesAreValidAndEmbedded guarantees them at build time. Two packages of
// one origin declaring one format are probe.package.format.duplicate.
func Load(overrideDir string) (*Registry, error) {
	r := &Registry{byFormat: map[string]*Package{}}
	embedded, err := embeddedSources()
	if err != nil {
		return nil, fmt.Errorf("loading embedded probe packages: %w", err)
	}
	if err := r.add(embedded, OriginEmbedded); err != nil {
		return nil, err
	}
	if overrideDir == "" {
		return r, nil
	}
	if _, err := os.Stat(overrideDir); err != nil {
		return nil, fmt.Errorf("support package override directory: %w", err)
	}
	paths, err := filepath.Glob(filepath.Join(overrideDir, Subdirectory, "*.yaml"))
	if err != nil {
		return nil, err
	}
	sort.Strings(paths)
	sources, err := readSources(paths)
	if err != nil {
		return nil, err
	}
	if list := validate(sources); list.Rejected() {
		return nil, &InvalidError{Findings: list}
	}
	over := &Registry{byFormat: map[string]*Package{}}
	if err := over.add(sources, OriginOverride); err != nil {
		return nil, err
	}
	for f, p := range over.byFormat {
		r.byFormat[f] = p
	}
	return r, nil
}

// add parses sources of one origin into the registry, refusing two of one format.
func (r *Registry) add(sources []source, origin string) error {
	var list findings.List
	for _, s := range sources {
		p, err := ParsePackage(s.data, s.path, origin)
		if err != nil {
			return fmt.Errorf("loading probe package: %w", err)
		}
		if prior, taken := r.byFormat[p.Format]; taken {
			list.Add(findings.Rejection, findings.RuleProbePackageFormatDuplicate, s.path, duplicateMessage(p.Format, prior.Path, s.path))
			continue
		}
		r.byFormat[p.Format] = p
	}
	if list.Rejected() {
		return &InvalidError{Findings: list}
	}
	return nil
}

func duplicateMessage(format, first, second string) string {
	return fmt.Sprintf("format %q is declared by %s and %s; a format is one package's, which an override shadows by format", format, first, second)
}

func readSources(paths []string) ([]source, error) {
	out := make([]source, 0, len(paths))
	for _, p := range paths {
		data, err := os.ReadFile(p)
		if err != nil {
			return nil, fmt.Errorf("reading probe package: %w", err)
		}
		out = append(out, source{path: p, data: data})
	}
	return out, nil
}

// ValidatePackages holds package files to the format, every finding of every file in one pass:
// probe.package.version.unknown for a probe_version this build does not read (and nothing
// else of that file), probe.package.schema naming each field the schema refuses,
// probe.package.template for a placeholder no field renders, and
// probe.package.format.duplicate for two files of the list declaring one format. Each
// finding's object is the package's path.
func ValidatePackages(paths []string) findings.List {
	sources, err := readSources(paths)
	if err != nil {
		var list findings.List
		list.Add(findings.Rejection, findings.RuleProbePackageSchema, strings.Join(paths, ", "), err.Error())
		return list
	}
	return validate(sources)
}

// ValidateEmbedded holds the shipped packages to the format, as ValidatePackages holds files.
func ValidateEmbedded() (findings.List, error) {
	sources, err := embeddedSources()
	if err != nil {
		return nil, err
	}
	return validate(sources), nil
}

func validate(sources []source) findings.List {
	var list findings.List
	firstByFormat := map[string]string{}
	for _, s := range sources {
		p, ok := validateOne(s, &list)
		if !ok {
			continue
		}
		if first, taken := firstByFormat[p.Format]; taken {
			list.Add(findings.Rejection, findings.RuleProbePackageFormatDuplicate, s.path, duplicateMessage(p.Format, first, s.path))
			continue
		}
		firstByFormat[p.Format] = s.path
	}
	return list
}

// validateOne checks one file and returns its package when nothing of it is rejected.
func validateOne(s source, list *findings.List) (*Package, bool) {
	var doc any
	if err := yaml.Unmarshal(s.data, &doc); err != nil {
		list.Add(findings.Rejection, findings.RuleProbePackageSchema, s.path, fmt.Sprintf("not valid YAML: %v", err))
		return nil, false
	}
	obj, ok := doc.(map[string]any)
	if !ok {
		list.Add(findings.Rejection, findings.RuleProbePackageSchema, s.path, "the file must hold a single probe package object")
		return nil, false
	}
	if v, ok := obj["probe_version"].(string); !ok || v != PackageVersion {
		got := "none"
		if raw, present := obj["probe_version"]; present {
			got = fmt.Sprintf("%v", raw)
		}
		list.Add(findings.Rejection, findings.RuleProbePackageVersionUnknown, s.path, fmt.Sprintf(
			"probe_version is %s; this build reads probe packages of format %q", got, PackageVersion))
		return nil, false
	}

	schema, err := compiledSchema()
	if err != nil {
		list.Add(findings.Rejection, findings.RuleProbePackageSchema, s.path, err.Error())
		return nil, false
	}
	instance, err := asJSON(obj)
	if err != nil {
		list.Add(findings.Rejection, findings.RuleProbePackageSchema, s.path, err.Error())
		return nil, false
	}
	if err := schema.Validate(instance); err != nil {
		var ve *jsonschema.ValidationError
		if !errors.As(err, &ve) {
			list.Add(findings.Rejection, findings.RuleProbePackageSchema, s.path, err.Error())
			return nil, false
		}
		for _, c := range flatten(ve) {
			list.Add(findings.Rejection, findings.RuleProbePackageSchema, s.path, c.where+": "+c.what)
		}
		return nil, false
	}

	p, err := ParsePackage(s.data, s.path, "")
	if err != nil {
		list.Add(findings.Rejection, findings.RuleProbePackageSchema, s.path, err.Error())
		return nil, false
	}
	clean := true
	for _, t := range p.Templates() {
		for _, m := range unrendered(t.Args, t.Places) {
			clean = false
			list.Add(findings.Rejection, findings.RuleProbePackageTemplate, s.path, fmt.Sprintf(
				"%s names %s, which no field renders there; it may name %s", t.Field, m, braced(t.Places)))
		}
	}
	return p, clean
}

func braced(places []string) string {
	out := make([]string, len(places))
	for i, p := range places {
		out[i] = "{" + p + "}"
	}
	return strings.Join(out, ", ")
}

// asJSON turns a decoded YAML document into what the JSON Schema validator reads, through
// JSON's own encoding, so numbers and maps are JSON's.
func asJSON(doc any) (any, error) {
	b, err := json.Marshal(doc)
	if err != nil {
		return nil, fmt.Errorf("the package does not convert to JSON: %w", err)
	}
	return jsonschema.UnmarshalJSON(bytes.NewReader(b))
}

var (
	schemaOnce     sync.Once
	schemaCompiled *jsonschema.Schema
	schemaErr      error
)

// SchemaBytes returns the embedded probe package schema.
func SchemaBytes() ([]byte, error) {
	return fylgja.Data.ReadFile(Subdirectory + "/probe.schema.json")
}

// compiledSchema is the probe package schema, compiled once.
func compiledSchema() (*jsonschema.Schema, error) {
	schemaOnce.Do(func() {
		raw, err := SchemaBytes()
		if err != nil {
			schemaErr = fmt.Errorf("reading the probe package schema: %w", err)
			return
		}
		doc, err := jsonschema.UnmarshalJSON(bytes.NewReader(raw))
		if err != nil {
			schemaErr = fmt.Errorf("parsing the probe package schema: %w", err)
			return
		}
		c := jsonschema.NewCompiler()
		if err := c.AddResource(schemaID, doc); err != nil {
			schemaErr = err
			return
		}
		schemaCompiled, schemaErr = c.Compile(schemaID)
	})
	return schemaCompiled, schemaErr
}

type schemaCause struct{ where, what string }

// flatten turns a nested validation error into one cause per leaf, each naming the field
// at fault, so a package with three faults reports three.
func flatten(ve *jsonschema.ValidationError) []schemaCause {
	if len(ve.Causes) == 0 {
		where := "/" + strings.Join(ve.InstanceLocation, "/")
		if where == "/" {
			where = "(root)"
		}
		what := ve.Error()
		if i := strings.LastIndex(what, "]: "); i >= 0 {
			what = what[i+3:]
		}
		return []schemaCause{{where: where, what: strings.TrimSpace(what)}}
	}
	var out []schemaCause
	for _, c := range ve.Causes {
		out = append(out, flatten(c)...)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].where < out[j].where })
	return out
}
