package lab

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"

	"go.temporal.io/sdk/activity"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// eapiPath is the endpoint the node's command API serves.
const eapiPath = "/command-api"

// The framing commands of an eAPI push. A command list
// enters privileged mode, opens a configuration context, and closes it:
//
//   - cmdEnable must come first: a `configure` without it is refused for want of
//     privileged mode, and the whole list lands nowhere.
//   - commit explicit opens a configuration session by name and commits it, which is
//     atomic: a refused line leaves the session pending and the running configuration
//     untouched, and cmdAbort removes it.
//   - commit implicit opens the configuration directly and ends it, which is not atomic:
//     the lines before a refused one stay applied. Nothing shipped declares it.
//
// Under mode replace (M11 D-033) the session is
// first made exactly the baseline containerlab left on the node, and the device is asked
// for its own diff before the commit:
//
//   - cmdRollbackClean empties the session, and cmdCopyStartup loads the startup
//     configuration into it: the pair that makes the session the baseline.
//   - cmdSessionDiff answers the session's difference from running, in the device's words.
//     It has no JSON model, so a request carrying it is sent as eapiFormatText: under
//     eapiFormatJSON the whole request fails with code 1003 and leaves its session
//     pending.
//     Under merge the request stays M7's eapiFormatJSON.
const (
	cmdEnable        = "enable"
	cmdConfigure     = "configure"
	cmdSession       = "configure session "
	cmdRollbackClean = "rollback clean-config"
	cmdCopyStartup   = "copy startup-config session-config"
	cmdSessionDiff   = "show session-config diffs"
	cmdCommit        = "commit"
	cmdEnd           = "end"
	cmdAbort         = "abort"
)

// The answer formats a command-API request asks for: JSON, M7's, and text,
// which every command answers as {"output": …}. M7's parser reads either, since a refusal,
// a warning and a result entry carry the same keys under both.
const (
	eapiFormatJSON = "json"
	eapiFormatText = "text"
)

// eapiSessionPrefix names Fylgja's own sessions, so an operator reading the node's
// session list can tell them from anything else on the node.
const eapiSessionPrefix = "fylgja-"

// pushEAPI sends the node its configuration as one command-API request and
// says whether it was committed, returning under mode replace the device's diff: the
// output of the diff command's result entry, "" when the session equals running.
//
// A refusal by the node is an *eapiRefusal, carrying the line refused and the node's own
// reason with the echoed command dropped; a login that cannot be read, or a mode with no
// command list, is a *setupError; anything else is the transport's or the status's, with
// the password redacted from it. The node's answer is never quoted: it echoes the
// commands it was sent, and so the configuration (Constitution X).
func (a *Activities) pushEAPI(ctx context.Context, log *slog.Logger, url string, in wire.PushInput, body pushBody) (string, error) {
	session := eapiSession(ctx)
	cmds, err := eapiCommands(body, in.Push.Mode, in.Push.Commit, session)
	if err != nil {
		return "", err
	}
	username, password, err := a.pushLogin(in)
	if err != nil {
		return "", err
	}

	format := eapiFormatJSON
	if in.Push.Mode == "replace" {
		format = eapiFormatText
	}
	answer, err := eapiRequest(ctx, url, in, username, password, texts(cmds), format)
	if err != nil {
		return "", err
	}
	switch {
	case answer.Error != nil:
		// With commit explicit nothing landed, and the session the attempt named is left
		// pending, holding a name that cannot be reused; it is removed best effort and
		// the outcome logged, never returned.
		if in.Push.Commit == "explicit" {
			a.eapiAbort(ctx, log, url, in, session, username, password)
		}
		return "", eapiRefusalFrom(answer.Error, cmds)
	case len(answer.Result) == 0:
		return "", fmt.Errorf("%s answered with neither a result nor an error", url)
	}
	// Warnings are the node's own words about a command it accepted, so they are counted
	// and their lines named, never quoted, and they are not a finding: the push succeeded.
	// The node warns, and commits, when a command names an interface inside its range that the
	// twin's chassis does not have, which the compiler already warns about by name.
	for _, sentence := range eapiWarnings(answer.Result, cmds, in.Node, artifactName(in)) {
		log.Warn(sentence)
	}
	return eapiDiff(answer.Result, cmds), nil
}

// eapiDiff is the output of the diff command's result entry: the device's diff of the
// session against running. A list without the command, or an answer with no entry for
// it, gives "".
func eapiDiff(results []eapiCommandResult, cmds []pushCommand) string {
	for i, c := range cmds {
		if c.line == 0 && c.text == cmdSessionDiff && i < len(results) {
			return results[i].Output
		}
	}
	return ""
}

// eapiSession is the name of the configuration session one attempt commits under:
// fylgja-<attempt>-<unix nanoseconds>. A committed name cannot be reused,
// so the name carries the attempt; and an attempt whose commit landed after its own
// deadline must not collide with itself, so it carries the moment it was built too.
func eapiSession(ctx context.Context) string {
	attempt := int32(1)
	if activity.IsActivity(ctx) {
		attempt = activity.GetInfo(ctx).Attempt
	}
	return fmt.Sprintf("%s%d-%d", eapiSessionPrefix, attempt, time.Now().UnixNano())
}

// eapiCommands is the command list for the body, and for each command the file line it
// came from: privileged mode, the configuration context, the
// bootstrap's lines when the push sends them, the artifact's, and the close. Mode replace
// makes the session the baseline before the lines and asks for the
// session's diff before the commit; it has a list only with an explicit commit, since
// the session is what the reset loads.
func eapiCommands(body pushBody, mode, commit, session string) ([]pushCommand, error) {
	if commit != "explicit" && commit != "implicit" {
		return nil, &setupError{fmt.Sprintf("commit %q is not one this build pushes by", commit)}
	}
	switch mode {
	case "merge":
	case "replace":
		if commit == "implicit" {
			return nil, replaceImplicit(DeliveryEAPI)
		}
	default:
		return nil, &setupError{fmt.Sprintf("mode %q is neither merge nor replace", mode)}
	}
	var cmds []pushCommand
	frame := func(c string) { cmds = append(cmds, pushCommand{text: c}) }
	frame(cmdEnable)
	if commit == "explicit" {
		frame(cmdSession + session)
	} else {
		frame(cmdConfigure)
	}
	if mode == "replace" {
		frame(cmdRollbackClean)
		frame(cmdCopyStartup)
	}
	cmds = append(cmds, body.commands()...)
	if mode == "replace" {
		frame(cmdSessionDiff)
	}
	if commit == "explicit" {
		frame(cmdCommit)
	} else {
		frame(cmdEnd)
	}
	return cmds, nil
}

// eapiAbort removes the configuration session a refused push left pending, best effort
// and on the push's own budget: if nothing is left of it, the request fails at once and
// the outcome is logged. It is how a refused replace leaves the node ready for a later
// push, and best effort is enough. After a create's refusal, M2's cleanup
// tears the twin down. After a step's, the twin is diverged and accepts only twin
// destroy,
// so nothing in M11 pushes to that node again; and a later push opens a
// session under its own name, beside any the abort could not remove. So the abort
// is never a step that can fail the run.
func (a *Activities) eapiAbort(ctx context.Context, log *slog.Logger, url string, in wire.PushInput, session, username, password string) {
	_, err := eapiRequest(ctx, url, in, username, password, []string{cmdEnable, cmdSession + session, cmdAbort}, eapiFormatJSON)
	if err != nil {
		log.Warn("the refused push's session could not be aborted", "session", session, "err", err.Error())
		return
	}
	log.Info("the refused push's session was aborted", "session", session)
}

// eapiRequest makes one command-API request and returns the node's answer: POST to the
// endpoint with basic auth, the command list run in order and answered in format, TLS
// unverified and no keep-alive, the answer bounded by jsonRPCAnswerLimit.
//
// Skipping verification is deliberate: the node's certificate is generated at boot, as
// the readiness probe accepts it. An answer longer than the limit does not parse and is
// reported as a body that is not an answer, retryable, rather than searched for a refusal
// it may no longer carry.
func eapiRequest(ctx context.Context, url string, in wire.PushInput, username, password string, cmds []string, format string) (eapiAnswer, error) {
	body, err := json.Marshal(eapiCall{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "runCmds",
		Params:  eapiParams{Version: 1, Commands: cmds, Format: format},
	})
	if err != nil {
		return eapiAnswer{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return eapiAnswer{}, redact(err, password)
	}
	req.Header.Set("Content-Type", "application/json")
	req.SetBasicAuth(username, password)

	transport := &http.Transport{
		TLSClientConfig:   &tls.Config{InsecureSkipVerify: true}, //nolint:gosec // a twin node's boot-time certificate
		DisableKeepAlives: true,
	}
	defer transport.CloseIdleConnections()
	resp, err := (&http.Client{Transport: transport}).Do(req)
	if err != nil {
		return eapiAnswer{}, redact(err, password)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, jsonRPCAnswerLimit))
	if err != nil {
		return eapiAnswer{}, redact(fmt.Errorf("reading the answer from %s: %w", url, err), password)
	}
	// The body is never quoted: a node's answer echoes the commands, and so the
	// configuration.
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		if resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden {
			return eapiAnswer{}, fmt.Errorf("%s answered HTTP %s to the login %s/%s", url, resp.Status, in.Push.UsernameEnv, in.Push.PasswordEnv)
		}
		return eapiAnswer{}, fmt.Errorf("%s answered HTTP %s", url, resp.Status)
	}
	var answer eapiAnswer
	if err := json.Unmarshal(raw, &answer); err != nil {
		return eapiAnswer{}, fmt.Errorf("%s answered HTTP %s with a body that is not a JSON-RPC answer", url, resp.Status)
	}
	return answer, nil
}

type eapiCall struct {
	JSONRPC string     `json:"jsonrpc"`
	ID      int        `json:"id"`
	Method  string     `json:"method"`
	Params  eapiParams `json:"params"`
}

type eapiParams struct {
	Version  int      `json:"version"`
	Commands []string `json:"cmds"`
	Format   string   `json:"format"`
}

// eapiAnswer is one command-API answer: one entry per command run, under result when the
// list succeeded and under error.data when it did not.
type eapiAnswer struct {
	Result []eapiCommandResult `json:"result"`
	Error  *eapiError          `json:"error"`
}

// eapiError is the answer to a command list the node would not run through. Code is
// decoded because the shape carries it, and read by nothing: which command failed decides
// whether the push was refused or the mechanism failed, not the number the node put on
// it.
// Message is decoded so that nothing else can mistake its absence for
// the field not existing, and it is never used: it echoes the command.
type eapiError struct {
	Code    int                 `json:"code"`
	Message string              `json:"message"`
	Data    []eapiCommandResult `json:"data"`
}

// eapiCommandResult is what the node said about one command. Errors and warnings are read
// for every command. Output, a command's text under eapiFormatText, is read for the diff
// command alone, and is the device's diff; everything else the node returns is
// a command's own output, never read.
type eapiCommandResult struct {
	Errors   []string `json:"errors"`
	Warnings []string `json:"warnings"`
	Output   string   `json:"output"`
}

// eapiRefusal is the node's own account of why it refused what it was sent: where, and
// the node's reason with the echoed command dropped. It never holds a byte
// of the configuration beyond what the node's reason quotes of the token it refused.
type eapiRefusal struct {
	line      int  // the file line the node refused; 0 when it said nothing of where
	bootstrap bool // the line is the bootstrap's, not the artifact's
	reason    string
}

func (r *eapiRefusal) Error() string {
	return "node refused the configuration" + r.where() + ": " + r.reason
}

// where says where the node refused: " at line 10", " at bootstrap line 3", or nothing.
func (r *eapiRefusal) where() string {
	switch {
	case r.line > 0 && r.bootstrap:
		return fmt.Sprintf(" at bootstrap line %d", r.line)
	case r.line > 0:
		return fmt.Sprintf(" at line %d", r.line)
	}
	return ""
}

// eapiRefusalFrom turns an error answer into a refusal, or into the mechanism's own
// failure when the command that failed was a framing command.
//
// The node returns one data entry per command it ran, the last being the one that failed,
// so its index re-bases onto the file line that command came from. Kept: that line, and
// the entry's errors, which are the node's reason. Dropped: the error's message, which
// echoes the command itself (Constitution X).
func eapiRefusalFrom(e *eapiError, cmds []pushCommand) error {
	n := len(e.Data)
	if n == 0 || n > len(cmds) {
		return &eapiRefusal{reason: "the node's answer does not say which command it refused, and its message is withheld because it echoes the command"}
	}
	reason := strings.Join(e.Data[n-1].Errors, "; ")
	if reason == "" {
		reason = "the node gave no reason, and its message is withheld because it echoes the command"
	}
	// A framing command that fails is the mechanism's own failure, not the
	// configuration's: retried, under a session name no commit has taken.
	if c := cmds[n-1]; c.line == 0 {
		return fmt.Errorf("the framing command `%s` failed: %s", c.text, reason)
	}
	return &eapiRefusal{line: cmds[n-1].line, bootstrap: cmds[n-1].bootstrap, reason: reason}
}

// eapiWarnings counts the commands the node warned on and names their file lines, one
// sentence per file, never the warning's text. A warning on a framing
// command names no line and is counted on its own.
func eapiWarnings(results []eapiCommandResult, cmds []pushCommand, node, artifact string) []string {
	var artifactLines, bootstrapLines []int
	framing := 0
	for i, r := range results {
		if len(r.Warnings) == 0 || i >= len(cmds) {
			continue
		}
		switch c := cmds[i]; {
		case c.line == 0:
			framing++
		case c.bootstrap:
			bootstrapLines = append(bootstrapLines, c.line)
		default:
			artifactLines = append(artifactLines, c.line)
		}
	}
	var out []string
	if len(artifactLines) > 0 {
		out = append(out, fmt.Sprintf("node %s warned on %s of artifact %s (%s)",
			node, plural(len(artifactLines), "line"), artifact, lineList(artifactLines)))
	}
	if len(bootstrapLines) > 0 {
		out = append(out, fmt.Sprintf("node %s warned on %s of its bootstrap (%s)",
			node, plural(len(bootstrapLines), "line"), lineList(bootstrapLines)))
	}
	if framing > 0 {
		out = append(out, fmt.Sprintf("node %s warned on %s", node, plural(framing, "framing command")))
	}
	return out
}

// lineList writes the lines a sentence names: "line 8" or "lines 8, 12".
func lineList(lines []int) string {
	parts := make([]string, len(lines))
	for i, l := range lines {
		parts[i] = strconv.Itoa(l)
	}
	if len(lines) == 1 {
		return "line " + parts[0]
	}
	return "lines " + strings.Join(parts, ", ")
}

// eapiURL is the node's command-API endpoint on its management address.
func eapiURL(in wire.PushInput) string {
	return fmt.Sprintf("%s://%s%s", in.Push.Scheme, net.JoinHostPort(in.MgmtIPv4, strconv.Itoa(in.Push.Port)), eapiPath)
}

// eapiByHand is the push as an operator can repeat it, with the login named by its
// variables and the configuration by its staged paths, never its content (Constitution X).
// The session is named by hand, since a committed name cannot be reused.
func eapiByHand(in wire.PushInput, files []string) string {
	pre, post, format := `["`+cmdEnable+`","`+cmdConfigure+`"]`, `["`+cmdEnd+`"]`, eapiFormatJSON
	if in.Push.Commit == "explicit" {
		pre, post = `["`+cmdEnable+`","`+cmdSession+`by-hand"]`, `["`+cmdCommit+`"]`
		if in.Push.Mode == "replace" {
			pre = `["` + cmdEnable + `","` + cmdSession + `by-hand","` + cmdRollbackClean + `","` + cmdCopyStartup + `"]`
			post = `["` + cmdSessionDiff + `","` + cmdCommit + `"]`
			format = eapiFormatText
		}
	}
	return fmt.Sprintf(`jq -Rs '{jsonrpc:"2.0",id:1,method:"runCmds",params:{version:1,cmds:(%s+(split("\n")|map(select(test("\\S"))))+%s),format:"%s"}}' %s | curl -sk -u "$%s:$%s" %s -d @-`, // gitleaks:allow: a format string for the remedy's curl line, which names the login's variables, never a value
		pre, post, format, byHandFiles(files), in.Push.UsernameEnv, in.Push.PasswordEnv, eapiURL(in))
}
