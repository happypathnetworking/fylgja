package lab

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/probe"
)

// DockerBurster runs a probe's burst inside its first host (016, research R-15): `docker exec
// <container> <burst.command>`, the command as verify rendered it from the host's probe
// package, through the Runner containerlab is driven through, so tier 1 records it. The
// output is ping's, and its summary, parsed by probe.ParsePing, is what the burst sent and
// what was answered.
//
// A ping that lost replies may exit non-zero, and still prints its counters: a summary read
// is the burst's answer whatever the exit status, so a lost reply is counted, never an
// error. An exec that could not run, or whose output holds no summary, is the error, worded
// with what docker exec said. The command carries the hosts' addresses and nothing else: no
// login, no token and no configuration is read or logged.
type DockerBurster struct {
	Runner Runner
	Log    *slog.Logger // nil discards
}

// Burst runs one burst and counts it.
func (b DockerBurster) Burst(ctx context.Context, container string, command []string) (sent, received int, err error) {
	if b.Runner == nil {
		return 0, 0, errors.New("no runner reaches docker")
	}
	args := append(strings.Fields(dockerExec), container)
	args = append(args, command...)
	stdout, stderr, exit, err := b.Runner.Run(ctx, nil, args...)
	if err != nil {
		return 0, 0, err
	}
	s, perr := probe.ParsePing(stdout, 0)
	if perr != nil {
		if why := execFailure(stderr, exit, nil); why != "" {
			return 0, 0, errors.New(why)
		}
		return 0, 0, fmt.Errorf("the burst's output holds no summary: %v", perr)
	}
	log := b.Log
	if log == nil {
		log = slog.New(slog.DiscardHandler)
	}
	log.Info("the probe's burst ran", "container", container, "sent", s.Sent, "received", s.Received, "exit", exit,
		"by_hand", strings.Join(args, " "))
	return s.Sent, s.Received, nil
}
