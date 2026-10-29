package lab

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"testing"
)

// What busybox's ping 1.37.0 prints for `ping -c 5 -i 0.2 -W 2 <far>` inside a host, in the
// form research §1.2 recorded it: a reply per echo answered, then the statistics, exit 0;
// with a reply lost, ping still prints its counters.
const (
	burstAllAnswered = `PING 10.1.11.2 (10.1.11.2): 56 data bytes
64 bytes from 10.1.11.2: seq=0 ttl=63 time=0.412 ms
64 bytes from 10.1.11.2: seq=1 ttl=63 time=0.288 ms
64 bytes from 10.1.11.2: seq=2 ttl=63 time=0.301 ms
64 bytes from 10.1.11.2: seq=3 ttl=63 time=0.297 ms
64 bytes from 10.1.11.2: seq=4 ttl=63 time=0.310 ms

--- 10.1.11.2 ping statistics ---
5 packets transmitted, 5 packets received, 0% packet loss
round-trip min/avg/max = 0.288/0.321/0.412 ms
`
	burstOneLost = `PING 10.1.11.2 (10.1.11.2): 56 data bytes
64 bytes from 10.1.11.2: seq=0 ttl=63 time=0.412 ms
64 bytes from 10.1.11.2: seq=1 ttl=63 time=0.288 ms
64 bytes from 10.1.11.2: seq=3 ttl=63 time=0.297 ms
64 bytes from 10.1.11.2: seq=4 ttl=63 time=0.310 ms

--- 10.1.11.2 ping statistics ---
5 packets transmitted, 4 packets received, 20% packet loss
round-trip min/avg/max = 0.288/0.326/0.412 ms
`
	burstNoneAnswered = `PING 10.1.11.2 (10.1.11.2): 56 data bytes

--- 10.1.11.2 ping statistics ---
5 packets transmitted, 0 packets received, 100% packet loss
`
)

var burstCommand = []string{"ping", "-c", "5", "-i", "0.2", "-W", "2", "10.1.11.2"}

// The burst is `docker exec <container> <command>` through the Runner, its counters read
// from ping's summary whatever ping exits with, so a lost reply is counted, never an error.
func TestDockerBursterCountsTheReplies(t *testing.T) {
	for _, c := range []struct {
		name           string
		reply          reply
		sent, received int
	}{
		{"every reply", reply{stdout: []byte(burstAllAnswered)}, 5, 5},
		{"one lost, ping exits 1", reply{stdout: []byte(burstOneLost), exit: 1}, 5, 4},
		{"none answered, ping exits 1", reply{stdout: []byte(burstNoneAnswered), exit: 1}, 5, 0},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := &fakeRunner{replies: map[string][]reply{"exec": {c.reply}}}
			sent, received, err := DockerBurster{Runner: r}.Burst(context.Background(), "clab-fylgja-n1-loop-a", burstCommand)
			if err != nil || sent != c.sent || received != c.received {
				t.Errorf("Burst = %d sent, %d received, %v; want %d, %d", sent, received, err, c.sent, c.received)
			}
			want := append([]string{"docker", "exec", "clab-fylgja-n1-loop-a"}, burstCommand...)
			if len(r.calls) != 1 || !reflect.DeepEqual(r.calls[0].args, want) {
				t.Errorf("calls %+v, want one: %q", r.calls, want)
			}
		})
	}
}

// A burst that could not be run is the error: the Runner's own, docker exec's exit and its
// stderr, or output with no summary, each naming why.
func TestDockerBursterErrors(t *testing.T) {
	for _, c := range []struct {
		name  string
		reply reply
		want  string
	}{
		{"the runner fails", reply{err: errors.New("exec: \"docker\": executable file not found in $PATH")}, "executable file not found"},
		{"the container is not running", reply{exit: 1,
			stderr: []byte("Error response from daemon: container 3c1e0a7b9d21 is not running\n")},
			"docker exec exited 1: Error response from daemon: container 3c1e0a7b9d21 is not running"},
		{"no summary", reply{stdout: []byte("PING 10.1.11.2 (10.1.11.2): 56 data bytes\n")}, "the burst's output holds no summary"},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := &fakeRunner{replies: map[string][]reply{"exec": {c.reply}}}
			_, _, err := DockerBurster{Runner: r}.Burst(context.Background(), "clab-fylgja-n1-loop-a", burstCommand)
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Errorf("Burst error %v, want one naming %q", err, c.want)
			}
		})
	}
}
