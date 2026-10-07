package psp

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"gopkg.in/yaml.v3"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// schemaID is the PSP format schema's `$id`, which moves with the format: each format's
// schema has said `v` and its version since `0.2`. The schema is registered under it, and
// TestSchemaIDMovesWithTheFormat holds the document's `$id` to it.
const schemaID = "https://fylgja.dev/psp/v" + FormatVersion

// compiledSchema is the PSP format schema, compiled once.
func compiledSchema() (*jsonschema.Schema, error) {
	raw, err := SchemaBytes()
	if err != nil {
		return nil, fmt.Errorf("reading the support package schema: %w", err)
	}
	doc, err := jsonschema.UnmarshalJSON(strings.NewReader(string(raw)))
	if err != nil {
		return nil, fmt.Errorf("parsing the support package schema: %w", err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource(schemaID, doc); err != nil {
		return nil, err
	}
	return c.Compile(schemaID)
}

// validateShape checks one package against the published format.
//
// The schema catches shape; only code can check that two naming patterns agree with
// each other, which is what checkConsistency is for. Both run, and both report every
// finding they have: a platform author fixing a package wants the whole list.
func validateShape(data []byte, path string, list *findings.List) (map[string]any, bool) {
	var doc any
	if err := yaml.Unmarshal(data, &doc); err != nil {
		list.AddAt(findings.Rejection, findings.RulePSPSchema, "", fmt.Sprintf("not valid YAML: %v", err), path, 0)
		return nil, false
	}
	obj, ok := normalizeYAML(doc).(map[string]any)
	if !ok {
		list.AddAt(findings.Rejection, findings.RulePSPSchema, "",
			"the file must hold a single support package object", path, 0)
		return nil, false
	}

	schema, err := compiledSchema()
	if err != nil {
		list.AddAt(findings.Rejection, findings.RulePSPSchema, "", err.Error(), path, 0)
		return obj, false
	}
	if err := schema.Validate(obj); err != nil {
		var ve *jsonschema.ValidationError
		if ok := asValidationError(err, &ve); ok {
			for _, cause := range flatten(ve) {
				list.AddAt(findings.Rejection, findings.RulePSPSchema, cause.where, cause.what, path, 0)
			}
		} else {
			list.AddAt(findings.Rejection, findings.RulePSPSchema, "", err.Error(), path, 0)
		}
		return obj, false
	}
	return obj, true
}

type schemaCause struct{ where, what string }

// flatten turns a nested validation error into one finding per leaf cause, so a
// package with three problems reports three, not one wrapped in two.
func flatten(ve *jsonschema.ValidationError) []schemaCause {
	if len(ve.Causes) == 0 {
		loc := "/" + strings.Join(ve.InstanceLocation, "/")
		if loc == "/" {
			loc = "(root)"
		}
		// ErrorKind.LocalizedString requires a printer and panics on nil; the error's
		// own message says the same thing, with the location prefix trimmed off since
		// it is reported separately.
		what := ve.Error()
		if i := strings.LastIndex(what, "]: "); i >= 0 {
			what = what[i+3:]
		}
		return []schemaCause{{where: loc, what: strings.TrimSpace(what)}}
	}
	var out []schemaCause
	for _, c := range ve.Causes {
		out = append(out, flatten(c)...)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].where < out[j].where })
	return out
}

func asValidationError(err error, target **jsonschema.ValidationError) bool {
	ve, ok := err.(*jsonschema.ValidationError)
	if ok {
		*target = ve
	}
	return ok
}

// normalizeYAML converts YAML's map[any]any into the map[string]any the JSON Schema
// validator expects, and JSON-compatible numbers.
func normalizeYAML(v any) any {
	switch t := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, val := range t {
			out[k] = normalizeYAML(val)
		}
		return out
	case map[any]any:
		out := make(map[string]any, len(t))
		for k, val := range t {
			out[fmt.Sprint(k)] = normalizeYAML(val)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, val := range t {
			out[i] = normalizeYAML(val)
		}
		return out
	case int:
		return json.Number(fmt.Sprint(t))
	case int64:
		return json.Number(fmt.Sprint(t))
	case float64:
		return json.Number(fmt.Sprint(t))
	default:
		return v
	}
}
