package lab

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"testing"
)

// inspectArgsFor is the one command line presence is read from.
func inspectArgsFor(ref string) []string {
	return []string{"docker", "image", "inspect", "--format", "{{.Id}}", ref}
}

// The three outcomes the real tool has, each read as presence, absence or
// an error, and the command line asserted exactly: nothing pulls, tags or removes.
func TestDockerImagesPresence(t *testing.T) {
	const ref = "ceos:4.32.0.2F"

	t.Run("held", func(t *testing.T) {
		f := &fakeRunner{replies: map[string][]reply{"image": {{
			stdout: []byte("sha256:58c3600aacc0c1bd385817e8028fb12f2abb850136ccd9791cec846da82633d4\n"),
		}}}}
		present, err := DockerImages{Runner: f}.Present(context.Background(), ref)
		if err != nil || !present {
			t.Fatalf("Present = %v, %v; want true and no error", present, err)
		}
		if len(f.calls) != 1 || !reflect.DeepEqual(f.calls[0].args, inspectArgsFor(ref)) || f.calls[0].env != nil {
			t.Errorf("runner saw %+v, want exactly %v with no environment override", f.calls, inspectArgsFor(ref))
		}
	})

	t.Run("not held", func(t *testing.T) {
		f := &fakeRunner{replies: map[string][]reply{"image": {{
			stderr: []byte("Error response from daemon: No such image: " + ref + "\n"), exit: 1,
		}}}}
		present, err := DockerImages{Runner: f}.Present(context.Background(), ref)
		if err != nil || present {
			t.Fatalf("Present = %v, %v; want false and no error: an absent image is an answer", present, err)
		}
		if len(f.calls) != 1 || !reflect.DeepEqual(f.calls[0].args, inspectArgsFor(ref)) {
			t.Errorf("runner saw %+v, want exactly %v", f.calls, inspectArgsFor(ref))
		}
	})

	t.Run("the runtime did not answer", func(t *testing.T) {
		f := &fakeRunner{replies: map[string][]reply{"image": {{
			stderr: []byte("Cannot connect to the Docker daemon at unix:///var/run/docker.sock.\n"), exit: 1,
		}}}}
		present, err := DockerImages{Runner: f}.Present(context.Background(), ref)
		if present || err == nil {
			t.Fatalf("Present = %v, %v; want false and an error", present, err)
		}
		// The message carries the command and what the runtime said, so the host check's
		// operational failure names both.
		if !strings.Contains(err.Error(), "docker image inspect --format {{.Id}} "+ref) ||
			!strings.Contains(err.Error(), "Cannot connect to the Docker daemon") {
			t.Errorf("error %q does not name the command and what docker said", err)
		}
	})

	t.Run("docker could not be run", func(t *testing.T) {
		want := errors.New("exec: \"docker\": executable file not found in $PATH")
		f := &fakeRunner{replies: map[string][]reply{"image": {{err: want}}}}
		present, err := DockerImages{Runner: f}.Present(context.Background(), ref)
		if present || !errors.Is(err, want) {
			t.Fatalf("Present = %v, %v; want false and the runner's error wrapped", present, err)
		}
	})
}
