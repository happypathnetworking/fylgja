package intent

// The typed client is generated from Infrahub's own SDL, committed at
// schema/infrahub.graphql. Regenerating needs a live Infrahub only to refresh the SDL
// (`make sdl`); the build itself never does, which is what keeps the unit tier free
// of infrastructure (D-017).
//
// CI runs `go generate ./... && git diff --exit-code` in the contract job to prove the
// committed client still matches the committed SDL. That guard only works if a
// directive exists — without one `go generate` is a no-op and the check passes
// vacuously, which is worse than no check at all.
//
//go:generate go run github.com/Khan/genqlient
