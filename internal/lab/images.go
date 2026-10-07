package lab

import (
	"context"
	"fmt"
	"strings"
)

// dockerImageInspect asks the container runtime whether it holds an image, by reference.
// The one command presence is read from, and a mechanism constant: it
// prints the image's id and exits 0 when the reference is held, and exits 1 saying
// noSuchImage when it is not. Nothing here pulls, tags or removes an image.
const dockerImageInspect = "docker image inspect --format {{.Id}}"

// noSuchImage is what `docker image inspect` says of a reference the host does not hold,
// beside exit 1. A reference held under another tag is not held.
const noSuchImage = "No such image"

// Images reports whether the host already holds an image under exactly the reference a
// support package declares. The host check looks through it for every node whose package
// says its image is not obtained from a public registry, so a create that would otherwise
// fail a minute into the deploy, with a registry error and no word about how the image is
// obtained, is refused before anything is staged.
type Images interface {
	// Present reports whether the host holds an image under exactly ref. An error is the
	// runtime failing to answer, never an image that is absent.
	Present(ctx context.Context, ref string) (bool, error)
}

// DockerImages asks Docker through the same Runner containerlab is driven through, so a
// tier-1 test substitutes the recorded behaviour of the real tool and needs no Docker
// (D-017).
type DockerImages struct {
	Runner Runner
}

// Present implements Images. It reads presence and nothing else: exit 0 is held, exit 1
// saying noSuchImage is not held, and anything else — a daemon that is not running, a
// docker that cannot be started — is an error, which the host check reports as an
// operational failure rather than as an absent image.
func (d DockerImages) Present(ctx context.Context, ref string) (bool, error) {
	args := append(strings.Fields(dockerImageInspect), ref)
	command := strings.Join(args, " ")
	_, stderr, exit, err := d.Runner.Run(ctx, nil, args...)
	switch {
	case err != nil:
		return false, fmt.Errorf("%s: %w", command, err)
	case exit == 0:
		return true, nil
	case strings.Contains(string(stderr), noSuchImage):
		return false, nil
	default:
		msg := strings.TrimSpace(string(stderr))
		if msg == "" {
			msg = "no message on stderr"
		}
		return false, fmt.Errorf("%s exited %d: %s", command, exit, msg)
	}
}
