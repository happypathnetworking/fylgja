package findings

import (
	"bytes"
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// frozenContractCopies is how many frozen contract files the packages' testdata holds.
// Fewer means a directory moved or was dropped, and the glob below would then pass over
// copies it no longer sees.
const frozenContractCopies = 31

// An older milestone's published schema is frozen under each package that validates
// against it, at testdata/contracts/<feature>/<name>, so one file can sit in up to four
// packages. The copies are one file in several places: a copy edited in one package would
// hold that package's documents to a contract the others no longer agree with, and no
// other test would notice. This holds every copy of one <feature>/<name> byte-equal.
func TestFrozenContractCopiesAgree(t *testing.T) {
	paths, err := filepath.Glob(filepath.Join("..", "*", "testdata", "contracts", "*", "*.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) < frozenContractCopies {
		t.Fatalf("found %d frozen contract copies under ../*/testdata/contracts/, want %d: %v",
			len(paths), frozenContractCopies, paths)
	}
	byFile := map[string][]string{}
	for _, p := range paths {
		key := filepath.Join(filepath.Base(filepath.Dir(p)), filepath.Base(p))
		byFile[key] = append(byFile[key], p)
	}
	keys := make([]string, 0, len(byFile))
	for k := range byFile {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, key := range keys {
		copies := byFile[key]
		first, err := os.ReadFile(copies[0])
		if err != nil {
			t.Fatal(err)
		}
		for _, p := range copies[1:] {
			b, err := os.ReadFile(p)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(first, b) {
				t.Errorf("%s and %s differ; they are frozen copies of %s, which no copy may change", copies[0], p, key)
			}
		}
	}
}
