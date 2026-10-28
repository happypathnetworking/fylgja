// Package fylgja embeds the data Fylgja ships with: the schema library's DCIM, vendored
// at the commit the Infrahub reader reads (schema/dcim/, D-057), the stage and probe kinds,
// the platform support packages, and the probe packages (probes/, 016).
//
// Embedding is not tidiness. Lab-host workers ship as a single static binary
// (D-005); without embedding, every host would need these files delivered alongside
// the binary, which is the files-on-every-host problem the static binary exists to
// avoid (D-018). A runtime override directory covers local and experimental
// packages without a rebuild.
package fylgja

import "embed"

// Data holds the shipped schema, platform support packages and probe packages, each set
// beside its format's JSON Schema. The library's licence ships beside its files.
//
//go:embed schema/*.yaml schema/dcim/*.yml schema/dcim/LICENSE.txt psp/*.yaml psp/*.json probes/*.yaml probes/*.json
var Data embed.FS
