package lab

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"errors"
	"fmt"
	"math"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// The push mechanisms this build implements: DeliveryJSONRPC from M5 and
// DeliveryEAPI from M7. A package declaring any other is refused at load
// (psp.config.delivery.unimplemented), so the dispatch below has two arms and a guard.
//
// Each is a mechanism keyed by a format value, never by a platform (Constitution II): the
// code below asks the package's config.delivery which protocol to speak, and nothing here
// knows whose package it is.
const (
	DeliveryJSONRPC = "json_rpc"
	DeliveryEAPI    = "eapi"
)

// pushCommand is one command of a push's list: the text sent to the node, and the line of
// the file it came from, so a refusal can name the line the node refused under the file
// that line belongs to. A framing command belongs to no file and carries line 0.
type pushCommand struct {
	text      string
	line      int
	bootstrap bool // the line is the bootstrap's, not the artifact's
}

// pushBody is what one push sends the node: the artifact's bytes, and the bootstrap's
// when the staged manifest says the push applies them or the package's
// mode is replace. Neither is ever logged or returned.
type pushBody struct {
	bootstrap []byte
	artifact  []byte
}

// commands are the body's configuration commands in the order they are sent: the
// bootstrap's first, so the node has its name and its ports before the artifact's lines
// reach it, then the artifact's. Lines are sent as they are, comments kept and empty
// lines dropped, as M5 sent an artifact's.
func (b pushBody) commands() []pushCommand {
	return append(configCommands(b.bootstrap, true), configCommands(b.artifact, false)...)
}

// configCommands are one file's lines as commands, numbered from 1 in that file. An empty
// line is dropped but still counted, so a number always names the line of the file an
// operator can open.
func configCommands(content []byte, bootstrap bool) []pushCommand {
	var out []pushCommand
	for i, l := range strings.Split(string(content), "\n") {
		l = strings.TrimRight(l, "\r")
		if strings.TrimSpace(l) == "" {
			continue
		}
		out = append(out, pushCommand{text: l, line: i + 1, bootstrap: bootstrap})
	}
	return out
}

// texts are the commands as they go on the wire.
func texts(cmds []pushCommand) []string {
	out := make([]string, len(cmds))
	for i, c := range cmds {
		out[i] = c.text
	}
	return out
}

// pushLogin reads the push login by the variable names the package gives. Names cross the
// queue, values never do (Constitution VIII); a variable unset on this worker is a push
// that no retry can make, which the host check refuses first.
func (a *Activities) pushLogin(in wire.PushInput) (username, password string, err error) {
	getenv := a.getenv()
	username, ok := getenv(in.Push.UsernameEnv)
	if !ok || username == "" {
		return "", "", &setupError{fmt.Sprintf("push login variable %s is unset on this worker", in.Push.UsernameEnv)}
	}
	password, ok = getenv(in.Push.PasswordEnv)
	if !ok || password == "" {
		return "", "", &setupError{fmt.Sprintf("push login variable %s is unset on this worker", in.Push.PasswordEnv)}
	}
	return username, password, nil
}

// DiffLimit bounds the device's diff a push returns. A mechanism
// constant: the diff is the activity's result, which must stay under the workflow
// service's payload limit (2 MB) while an answer may be up to jsonRPCAnswerLimit (4 MiB).
// A longer diff is cut at a character boundary and closed with diffCutNote.
const DiffLimit = 256 << 10

// diffCutNote closes a diff cut at DiffLimit, so a reader of the history knows it is not
// the whole of what the device said.
const diffCutNote = "\n… [cut at 256 KiB]"

// cutDiff returns diff whole when it is within DiffLimit, else its first DiffLimit bytes,
// backed off to a character boundary, with diffCutNote after them.
func cutDiff(diff string) string {
	if len(diff) <= DiffLimit {
		return diff
	}
	cut := DiffLimit
	for cut > 0 && !utf8.RuneStart(diff[cut]) {
		cut--
	}
	return diff[:cut] + diffCutNote
}

// PushConfig pushes one node its configuration artifact from the staged bundle, after the
// node answered its readiness probe. It reads the file the manifest
// names, checks it still hashes to the manifest's checksum, and sends it by the mechanism
// its package declares, within the package's push_timeout_s.
//
// Under mode replace the request resets the node to the baseline containerlab left on it,
// sends the bootstrap and the artifact, asks the device for its own diff and commits, in
// one request with one atomic commit (M11 D-033). The diff is returned as
// PushResult.Diff, the result's one content field and the diff's only home: it is the
// device's words about what the commit changed, never the commands, and it is logged by
// its length alone.
//
// Only paths and identities cross the queue: the bytes are read here, sent to the node,
// and neither logged nor returned (Constitution VIII). A refusal by the node is
// push.refused and final; a push that could not be made is push.failed and retried, since
// a retry sends the same bytes and the node commits the same state.
func (a *Activities) PushConfig(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
	start := time.Now()
	name := artifactName(in)
	log := a.logger().With("node", in.Node)

	// One request makes the push, so it heartbeats before sending as well as every
	// HeartbeatInterval while it waits: a cancellation reaches it either way.
	if activity.IsActivity(ctx) {
		activity.RecordHeartbeat(ctx)
	}
	stop := heartbeat(ctx)
	defer stop()

	failed := func(retryable bool, format string, args ...any) error {
		msg := fmt.Sprintf("node %s did not take artifact %s (checksum %s): ", in.Node, name, in.Checksum) +
			fmt.Sprintf(format, args...)
		f := findings.Finding{Severity: findings.Rejection, Rule: findings.RulePushFailed, Object: in.Node, Message: msg, Step: findings.StepPush}
		if !retryable {
			return temporal.NewNonRetryableApplicationError(msg, findings.RulePushFailed, nil, f)
		}
		return temporal.NewApplicationError(msg, findings.RulePushFailed, f)
	}

	file := filepath.Join(in.TwinDir, "bundle", filepath.FromSlash(in.Artifact))
	content, err := os.ReadFile(file)
	if err != nil {
		return wire.PushResult{}, failed(false, "reading the staged file %s: %v", file, err)
	}
	// bundle.Verify checked this file against the entry before the run, and the staged
	// bundle hashed to its bundle_id when it was staged, so a mismatch here can only be a
	// file touched since; it is named rather than pushed, the second lock
	// after bundle.Verify.
	if sum := md5.Sum(content); hex.EncodeToString(sum[:]) != in.Checksum {
		return wire.PushResult{}, failed(false, "the staged file %s hashes to %s, not the manifest's checksum; it was changed after staging",
			file, hex.EncodeToString(sum[:]))
	}

	body := pushBody{artifact: content}
	// Whether the bootstrap goes through the push is the staged manifest's answer and the
	// package's mode, never the delivery's. A node whose package says bootstrap_via push
	// carries no startup-config in the topology, so its bootstrap reaches it only here, ahead
	// of the artifact in the same request. And under mode replace the
	// reset takes the node back to containerlab's baseline, which holds no bootstrap Fylgja
	// wrote and to which containerlab's reconcile never applies a changed startup snippet,
	// so the push sends the bootstrap after the reset whatever bootstrap_via says. The
	// manifest is read beside the artifact, as RecordTwin reads it, so no
	// path had to be added to the queue's types.
	bundleDir := filepath.Join(in.TwinDir, "bundle")
	manifest, err := readManifest(bundleDir)
	if err != nil {
		return wire.PushResult{}, failed(false, "%v", err)
	}
	entry, named := manifestNode(manifest, in.Node)
	if !named {
		return wire.PushResult{}, failed(false, "the staged manifest does not name node %s", in.Node)
	}
	sent := []string{file}
	if entry.Bootstrap.Via == psp.BootstrapViaPush || in.Push.Mode == psp.ModeReplace {
		// bundle.Verify held every node's bootstrap.file to a regular file inside the
		// bundle before the run, so a read that fails here is a staged copy changed since.
		bootstrapFile := filepath.Join(bundleDir, filepath.FromSlash(entry.Bootstrap.File))
		if body.bootstrap, err = os.ReadFile(bootstrapFile); err != nil {
			return wire.PushResult{}, failed(false, "reading the staged bootstrap %s: %v", bootstrapFile, err)
		}
		sent = []string{bootstrapFile, file}
	}

	if in.Push.Delivery != DeliveryJSONRPC && in.Push.Delivery != DeliveryEAPI {
		return wire.PushResult{}, failed(false, "delivery %q is not a mechanism this build pushes by (only %s and %s are)",
			in.Push.Delivery, DeliveryJSONRPC, DeliveryEAPI)
	}
	url := pushURL(in)
	log.Debug("push", "url", url, "artifact", name, "delivery", in.Push.Delivery, "mode", in.Push.Mode,
		"commit", in.Push.Commit, "bootstrap_via", entry.Bootstrap.Via, "by_hand", pushByHand(in, sent))

	// The request's deadline is the package's budget from the activity's start; the
	// activity's own start-to-close carries the mechanism's margin past it.
	budget := time.Duration(in.Push.TimeoutS) * time.Second
	reqCtx, cancel := context.WithDeadline(ctx, start.Add(budget))
	defer cancel()
	var diff string
	if in.Push.Delivery == DeliveryEAPI {
		diff, err = a.pushEAPI(reqCtx, log, url, in, body)
	} else {
		diff, err = a.pushJSONRPC(reqCtx, log, url, in, body)
	}

	// A refusal by the node itself: each mechanism words where and why from its own
	// protocol's answer, and the dispatch reports them alike.
	refused := func(where, reason string) error {
		msg := fmt.Sprintf("node %s refused artifact %s (checksum %s)%s: %s", in.Node, name, in.Checksum, where, reason)
		log.Warn("push refused", "artifact", name, "checksum", in.Checksum, "where", where)
		return StepFailure(findings.StepPush, findings.RulePushRefused, in.Node, msg)
	}
	var jsonRPC *nodeRefusal
	var eapi *eapiRefusal
	switch {
	case err == nil:
	case ctx.Err() != nil:
		return wire.PushResult{}, interrupted(ctx, findings.StepPush, findings.RulePushFailed, in.Node,
			fmt.Sprintf("the push of artifact %s (checksum %s) to %s", name, in.Checksum, in.Node))
	// A refusal is told before the budget: a request made after the node refused (the
	// json_rpc arm asking for the reason, D-034; the eapi arm's abort) may run the
	// budget out, and the node's refusal stays a refusal all the same, never retried.
	case errors.As(err, &jsonRPC):
		return wire.PushResult{}, refused(jsonRPC.where(), jsonRPC.reason)
	case errors.As(err, &eapi):
		return wire.PushResult{}, refused(eapi.where(), eapi.reason)
	case errors.Is(err, context.DeadlineExceeded) || reqCtx.Err() != nil:
		return wire.PushResult{}, failed(true, "%s did not answer within %ds (push_timeout_s)", url, in.Push.TimeoutS)
	default:
		var setup *setupError
		if errors.As(err, &setup) {
			return wire.PushResult{}, failed(false, "%v", err)
		}
		return wire.PushResult{}, failed(true, "%v", err)
	}

	after := math.Round(time.Since(start).Seconds()*1000) / 1000
	// The diff's length, never its text: it is configuration.
	log.Info("pushed", "addr", url, "artifact", name, "checksum", in.Checksum, "size", len(content), "pushed_in_s", after,
		"diff_bytes", len(diff))
	return wire.PushResult{Node: in.Node, PushedInS: after, Checksum: in.Checksum, Size: len(content), Diff: cutDiff(diff)}, nil
}

// artifactName is the artifact's name as the manifest's file gives it: the compiler writes
// configs/<node>.<artifact_name>, so the name is what follows the node.
func artifactName(in wire.PushInput) string {
	return strings.TrimPrefix(path.Base(in.Artifact), in.Node+".")
}

// manifestNode finds a node's entry in the staged manifest.
func manifestNode(m compiler.Manifest, node string) (compiler.ManifestNode, bool) {
	for _, n := range m.Nodes {
		if n.Name == node {
			return n, true
		}
	}
	return compiler.ManifestNode{}, false
}

// pushURL is the node's endpoint for the mechanism its package declares.
func pushURL(in wire.PushInput) string {
	if in.Push.Delivery == DeliveryEAPI {
		return eapiURL(in)
	}
	return jsonRPCURL(in)
}

// pushByHand is the push as an operator can repeat it, in the protocol the mechanism
// speaks, with the login named by its variables and the configuration by its staged
// paths, never its content (Constitution X). files are the staged files the push sends,
// in order: the bootstrap ahead of the artifact when the push sends both. It follows the
// mode's command list, so a push repeated by hand under replace resets and asks for the
// diff as the activity does.
func pushByHand(in wire.PushInput, files []string) string {
	if in.Push.Delivery == DeliveryEAPI {
		return eapiByHand(in, files)
	}
	return jsonRPCByHand(in, files)
}

// byHandFiles is files as a shell reads them: jq -Rs concatenates its files into the one
// string it splits into lines, so the bootstrap's lines come first, as the push sends them.
func byHandFiles(files []string) string {
	return strings.Join(files, " ")
}
