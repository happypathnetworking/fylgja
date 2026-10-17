//go:build ignore

// rewrite-stage rewrites the three recorded step histories' record blocks from M10's
// waypoint to 014's stage (research R-10): every "waypoint" object inside a JSON payload,
// {series, sequence, description, at_source}, at any depth, becomes a "stage" object,
// {proposed_change: {id, branch}, label, description, at_source}, in the same place, with
// the proposed change fylgja-test-pause-pc on the series' branch and the label s<sequence>.
// Nothing else moves: the payload keeps the bytes the SDK wrote around each object, and the
// history file keeps its own text around each payload's base64 string. It was run once, from
// the repository root:
//
//	go run internal/provision/testdata/rewrite-stage.go
//
// and checks, before it writes, that each rewritten payload decodes to the original with its
// waypoint objects, and nothing else, replaced. A second run finds no waypoint and writes
// nothing.
package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"maps"
	"os"
	"reflect"
	"slices"
	"strconv"
	"strings"
)

// The histories rewritten when no path is given.
var histories = []string{
	"internal/provision/testdata/step-cancelled.history.json",
	"internal/provision/testdata/step-diverged.history.json",
	"internal/provision/testdata/step-wait-cancelled.history.json",
}

// proposedChange is the id every rewritten stage names.
const proposedChange = "fylgja-test-pause-pc"

// jsonPlain is the payload encoding the rewrite reads: the SDK's JSON converter's.
const jsonPlain = "json/plain"

func main() {
	paths := os.Args[1:]
	if len(paths) == 0 {
		paths = histories
	}
	for _, path := range paths {
		if err := rewrite(path); err != nil {
			fmt.Fprintf(os.Stderr, "%s: %v\n", path, err)
			os.Exit(1)
		}
	}
}

// rewrite rewrites one history file in place and reports what moved.
func rewrite(path string) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var history any
	if err := json.Unmarshal(raw, &history); err != nil {
		return err
	}
	text := string(raw)
	payloads, objects := 0, 0
	seen := map[string]bool{}
	for _, data := range jsonPayloads(history) {
		if seen[data] {
			continue
		}
		seen[data] = true
		decoded, err := base64.StdEncoding.DecodeString(data)
		if err != nil {
			return fmt.Errorf("payload %.16s…: %w", data, err)
		}
		rewritten, n, err := rewritePayload(decoded)
		if err != nil {
			return fmt.Errorf("payload %.16s…: %w", data, err)
		}
		if n == 0 {
			continue
		}
		if err := check(decoded, rewritten, n); err != nil {
			return fmt.Errorf("payload %.16s…: %w", data, err)
		}
		old, repl := `"`+data+`"`, `"`+base64.StdEncoding.EncodeToString(rewritten)+`"`
		count := strings.Count(text, old)
		if count == 0 {
			return fmt.Errorf("payload %.16s… is not in the file's text as decoded", data)
		}
		text = strings.ReplaceAll(text, old, repl)
		payloads += count
		objects += n * count
	}
	fmt.Printf("%s: %d payloads, %d waypoint objects rewritten\n", path, payloads, objects)
	if payloads == 0 {
		return nil
	}
	info, err := os.Stat(path)
	if err != nil {
		return err
	}
	return os.WriteFile(path, []byte(text), info.Mode().Perm())
}

// jsonPayloads is the data of every json/plain payload in a decoded history, in document
// order: each object holding a metadata.encoding and a data string.
func jsonPayloads(v any) []string {
	var out []string
	switch v := v.(type) {
	case map[string]any:
		if meta, ok := v["metadata"].(map[string]any); ok {
			enc, _ := meta["encoding"].(string)
			data, isData := v["data"].(string)
			if b, err := base64.StdEncoding.DecodeString(enc); err == nil && string(b) == jsonPlain && isData {
				out = append(out, data)
			}
		}
		for _, k := range slices.Sorted(maps.Keys(v)) {
			out = append(out, jsonPayloads(v[k])...)
		}
	case []any:
		for _, e := range v {
			out = append(out, jsonPayloads(e)...)
		}
	}
	return out
}

// waypointKey is the key the rewrite looks for in a payload the SDK wrote compact: a key
// can only be preceded by the object's opening brace or a comma, and a quote inside a string
// is escaped, so the bytes cannot match inside a string value.
var waypointKey = []byte(`"waypoint":`)

// waypoint is M10's record block, its values kept as the bytes the SDK wrote.
type waypoint struct {
	Series      json.RawMessage `json:"series"`
	Sequence    json.RawMessage `json:"sequence"`
	Description json.RawMessage `json:"description"`
	AtSource    json.RawMessage `json:"at_source"`
}

// rewritePayload replaces each "waypoint" object in one payload with its "stage" object,
// byte for byte in place, and returns the payload and how many it replaced.
func rewritePayload(p []byte) ([]byte, int, error) {
	var out bytes.Buffer
	n := 0
	for {
		i := bytes.Index(p, waypointKey)
		if i < 0 {
			out.Write(p)
			return out.Bytes(), n, nil
		}
		if i == 0 || (p[i-1] != '{' && p[i-1] != ',') {
			return nil, 0, fmt.Errorf("%q at offset %d is not a key", waypointKey, i)
		}
		start := i + len(waypointKey)
		dec := json.NewDecoder(bytes.NewReader(p[start:]))
		dec.DisallowUnknownFields()
		var w waypoint
		if err := dec.Decode(&w); err != nil {
			return nil, 0, fmt.Errorf("the waypoint at offset %d: %w", i, err)
		}
		end := start + int(dec.InputOffset())
		if w.Series == nil || w.Sequence == nil || w.Description == nil || w.AtSource == nil {
			return nil, 0, fmt.Errorf("the waypoint at offset %d lacks a field: %s", i, p[start:end])
		}
		seq, err := strconv.Atoi(string(w.Sequence))
		if err != nil || seq < 1 {
			return nil, 0, fmt.Errorf("the waypoint at offset %d has sequence %s", i, w.Sequence)
		}
		out.Write(p[:i])
		fmt.Fprintf(&out, `"stage":{"proposed_change":{"id":"%s","branch":%s},"label":"s%d","description":%s,"at_source":%s}`,
			proposedChange, w.Series, seq, w.Description, w.AtSource)
		p = p[end:]
		n++
	}
}

// check holds a rewritten payload to the original: decoded, it equals the original decoded
// with each waypoint object replaced by its stage, and holds no waypoint key. The word in a
// recorded message, the run's own result's finding, is the recording's and stays.
func check(original, rewritten []byte, n int) error {
	before, err := decode(original)
	if err != nil {
		return err
	}
	after, err := decode(rewritten)
	if err != nil {
		return fmt.Errorf("the rewritten payload does not decode: %w", err)
	}
	want, replaced := toStage(before)
	if replaced != n {
		return fmt.Errorf("the decode found %d waypoint objects, the rewrite %d", replaced, n)
	}
	if !reflect.DeepEqual(after, want) {
		return fmt.Errorf("the rewritten payload differs from the original beyond its waypoint objects")
	}
	if bytes.Contains(rewritten, waypointKey) {
		return fmt.Errorf("the rewritten payload still has a waypoint key")
	}
	return nil
}

func decode(b []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return v, nil
}

// toStage is a decoded payload with each "waypoint" key's object replaced by a "stage" key's,
// and the count it replaced.
func toStage(v any) (any, int) {
	switch v := v.(type) {
	case map[string]any:
		out, n := map[string]any{}, 0
		for k, e := range v {
			if w, ok := e.(map[string]any); ok && k == "waypoint" {
				out["stage"] = map[string]any{
					"proposed_change": map[string]any{"id": proposedChange, "branch": w["series"]},
					"label":           "s" + w["sequence"].(json.Number).String(),
					"description":     w["description"],
					"at_source":       w["at_source"],
				}
				n++
				continue
			}
			c, m := toStage(e)
			out[k] = c
			n += m
		}
		return out, n
	case []any:
		out, n := make([]any, len(v)), 0
		for i, e := range v {
			c, m := toStage(e)
			out[i] = c
			n += m
		}
		return out, n
	}
	return v, 0
}
