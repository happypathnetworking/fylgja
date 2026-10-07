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
	"regexp"
	"strconv"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The framing commands of an explicit commit: the artifact's `set` lines
// exist only in a candidate datastore, and nothing lands until the commit. Under mode
// replace (M11 D-033) the candidate is first reset to the
// baseline containerlab left on the node, and the device is asked for its own diff before
// the commit:
//
//   - cmdLoadStartup loads the startup configuration into the private candidate, which
//     also clears what a refused push left in it.
//   - cmdDiffFlat answers the candidate's difference from running, in the device's words.
//   - cmdCommitValidate checks the private candidate a refused replace left, and commits
//     nothing: it is how a refusal whose reason the node cut is asked again (D-034).
//
// M5's `delete /` replace is gone: it took the probe node dark, and no package shipped it.
const (
	cmdEnterCandidate = "enter candidate private"
	cmdLoadStartup    = "load startup"
	cmdDiffFlat       = "diff flat"
	cmdCommitNow      = "commit now"
	cmdCommitValidate = "commit validate"
)

// jsonRPCAnswerLimit bounds how much of a node's answer is read. A mechanism constant: an
// answer echoes the commands sent, so it is about the size of the artifact.
const jsonRPCAnswerLimit = 4 << 20

// pushJSONRPC sends the configuration to the node as one JSON-RPC `cli` request and
// says whether it was committed, returning under mode replace the device's diff: the
// request's whole text output, which the node answers as one {"text": …} entry when no
// output-format is asked for. A refusal by the node is a *nodeRefusal; a login
// that cannot be read or a combination with no command list is a *setupError; anything
// else is the transport's or the status's, with the password redacted from it.
//
// A replace the node refuses without a reason Fylgja can read is asked once more, by
// validateRefused, before the refusal is returned (D-034). The path that commits stays
// one request (D-033).
func (a *Activities) pushJSONRPC(ctx context.Context, log *slog.Logger, url string, in wire.PushInput, content pushBody) (string, error) {
	cmds, err := jsonRPCCommands(content, in.Push.Mode, in.Push.Commit)
	if err != nil {
		return "", err
	}
	username, password, err := a.pushLogin(in)
	if err != nil {
		return "", err
	}

	answer, status, err := jsonRPCCall(ctx, url, in, username, password, texts(cmds))
	if err != nil {
		return "", err
	}
	switch {
	case answer.Error != nil:
		refusal := refusalFrom(answer.Error.Message, cmds)
		if refusal.withheld && in.Push.Mode == "replace" {
			return "", validateRefused(ctx, log, url, in, username, password)
		}
		return "", refusal
	case len(answer.Result) == 0 || string(answer.Result) == "null":
		return "", fmt.Errorf("%s answered HTTP %s with neither a result nor an error", url, status)
	}
	if in.Push.Mode != "replace" {
		return "", nil
	}
	return jsonRPCText(answer.Result), nil
}

// validateRefused asks the node why it refused a replace whose answer gave no reason
// (D-034). A json_rpc node may cut its error message inside its
// echo of the commands, and a replace's echo (the load, the bootstrap and the artifact)
// can run past the cut, so the reason never arrives: the node cuts its message at about
// 1 KiB. `commit validate` checks the private candidate the refused request
// left against the schema's constraints without committing it, and its echo is
// two commands, so the reason it gives fits. It does not run the checks the node makes
// only as a commit applies: a port out of its package's range passes it and is refused
// only at `commit now`.
//
// The answer is read as the first one was, by refusalFrom, re-based on its own two
// commands, and the refusal it returns is always the finding's. When that answer gives
// no reason either, the refusal says so in one of two sentences (D-035): the candidate
// validates (the node checks what it refused only as a commit applies, or the first
// refusal came at parse time and left part of the content), or the answer is cut,
// refused in a shape Fylgja does not read, or never comes back. It runs on the push's
// own budget, is never retried and commits nothing; the candidate is left as the refused
// request left it, for the next replace's `load startup` to clear. Its outcome is
// logged, never the answer's text.
func validateRefused(ctx context.Context, log *slog.Logger, url string, in wire.PushInput, username, password string) *nodeRefusal {
	cmds := []pushCommand{{text: cmdEnterCandidate}, {text: cmdCommitValidate}}
	answer, _, err := jsonRPCCall(ctx, url, in, username, password, texts(cmds))
	switch {
	case err != nil:
		log.Warn("the refused replace's reason could not be asked for", "command", cmdCommitValidate, "err", err.Error())
		return &nodeRefusal{withheld: true, reason: reasonNotGivenAgain}
	case answer.Error == nil:
		log.Info("the refused replace's candidate validates, so the node gave no reason", "command", cmdCommitValidate)
		return &nodeRefusal{withheld: true, reason: reasonValidates}
	}
	r := refusalFrom(answer.Error.Message, cmds)
	if r.withheld {
		log.Info("the refused replace's reason was asked for and not given", "command", cmdCommitValidate)
		return &nodeRefusal{withheld: true, reason: reasonNotGivenAgain}
	}
	log.Info("the refused replace's reason was asked for and given", "command", cmdCommitValidate)
	return r
}

// The two sentences a refused replace is worded with when neither request gave a reason
// (D-035). The first request's message ended before any reason Fylgja reads; nothing of
// it is quoted. `commit validate` passing does not say why the commit was refused: the
// node may check what it refused only as a commit applies, as it checks a port's
// range.
const (
	reasonValidates     = "the node's message ends before any reason Fylgja can read, and the candidate it refused passes `commit validate`, which does not run every check a commit does (D-035)"
	reasonNotGivenAgain = "the node's message ends before any reason Fylgja can read, and asking again with `commit validate` gave none (D-035)"
)

// jsonRPCCall makes one JSON-RPC `cli` request and returns the node's answer: POST to the
// endpoint with basic auth, the commands run in order, TLS unverified and no keep-alive,
// the answer bounded by jsonRPCAnswerLimit, with the HTTP status it came under. A status
// that is not 2xx, or a body that is not a JSON-RPC answer, is an error that never quotes
// the body.
func jsonRPCCall(ctx context.Context, url string, in wire.PushInput, username, password string, commands []string) (jsonRPCAnswer, string, error) {
	body, err := json.Marshal(jsonRPCRequest{JSONRPC: "2.0", ID: 1, Method: "cli", Params: jsonRPCParams{Commands: commands}})
	if err != nil {
		return jsonRPCAnswer{}, "", err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return jsonRPCAnswer{}, "", redact(err, password)
	}
	req.Header.Set("Content-Type", "application/json")
	req.SetBasicAuth(username, password)

	// Skipping verification is deliberate: the node's certificate is generated at boot,
	// as the readiness probe accepts it.
	transport := &http.Transport{
		TLSClientConfig:   &tls.Config{InsecureSkipVerify: true}, //nolint:gosec // a twin node's boot-time certificate
		DisableKeepAlives: true,
	}
	defer transport.CloseIdleConnections()
	resp, err := (&http.Client{Transport: transport}).Do(req)
	if err != nil {
		return jsonRPCAnswer{}, "", redact(err, password)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, jsonRPCAnswerLimit))
	if err != nil {
		return jsonRPCAnswer{}, "", redact(fmt.Errorf("reading the answer from %s: %w", url, err), password)
	}
	// The body is never quoted: a node's answer echoes the commands, and so the artifact.
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		if resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden {
			return jsonRPCAnswer{}, "", fmt.Errorf("%s answered HTTP %s to the login %s/%s", url, resp.Status, in.Push.UsernameEnv, in.Push.PasswordEnv)
		}
		return jsonRPCAnswer{}, "", fmt.Errorf("%s answered HTTP %s", url, resp.Status)
	}
	var answer jsonRPCAnswer
	if err := json.Unmarshal(raw, &answer); err != nil {
		return jsonRPCAnswer{}, "", fmt.Errorf("%s answered HTTP %s with a body that is not a JSON-RPC answer", url, resp.Status)
	}
	return answer, resp.Status, nil
}

// jsonRPCText is the text output a `cli` answer carries: the text of each {"text": …}
// entry of its result, in order. A node answers a request with no output-format as one
// such entry holding every command's output. A result of another shape carries no
// text to take, and gives "": the commit landed, and the diff is the history's, not a
// condition of the push.
func jsonRPCText(result json.RawMessage) string {
	var entries []struct {
		Text string `json:"text"`
	}
	if json.Unmarshal(result, &entries) != nil {
		return ""
	}
	var b strings.Builder
	for _, e := range entries {
		b.WriteString(e.Text)
	}
	return b.String()
}

type jsonRPCRequest struct {
	JSONRPC string        `json:"jsonrpc"`
	ID      int           `json:"id"`
	Method  string        `json:"method"`
	Params  jsonRPCParams `json:"params"`
}

type jsonRPCParams struct {
	Commands []string `json:"commands"`
}

type jsonRPCAnswer struct {
	Result json.RawMessage `json:"result"`
	Error  *struct {
		Code    int    `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

// jsonRPCCommands is the command list for the configuration, and for each command the
// file line it came from (0 for a framing command). The lines are sent as they are,
// comments kept and empty lines dropped; with commit explicit they are framed by
// `enter candidate private` and `commit now`. Mode replace loads
// the startup configuration into the candidate first and asks for `diff flat` before the
// commit. Replace with an implicit commit has no command list
// (psp.config.push.missing refuses it at load; this is the second lock).
//
// The bootstrap's lines, when the push sends them, go inside the candidate ahead of the
// artifact's, so one commit lands both. Under replace PushConfig
// always sends them.
func jsonRPCCommands(content pushBody, mode, commit string) ([]pushCommand, error) {
	if commit != "explicit" && commit != "implicit" {
		return nil, &setupError{fmt.Sprintf("commit %q is not one this build pushes by", commit)}
	}
	if mode != "merge" && mode != "replace" {
		return nil, &setupError{fmt.Sprintf("mode %q is neither merge nor replace", mode)}
	}
	if mode == "replace" && commit == "implicit" {
		return nil, replaceImplicit(DeliveryJSONRPC)
	}
	var cmds []pushCommand
	frame := func(c string) { cmds = append(cmds, pushCommand{text: c}) }
	if commit == "explicit" {
		frame(cmdEnterCandidate)
		if mode == "replace" {
			frame(cmdLoadStartup)
		}
	}
	cmds = append(cmds, content.commands()...)
	if commit == "explicit" {
		if mode == "replace" {
			frame(cmdDiffFlat)
		}
		frame(cmdCommitNow)
	}
	return cmds, nil
}

// replaceImplicit is the setup error of mode replace with an implicit commit, worded as
// psp.config.push.missing words it at load.
func replaceImplicit(delivery string) *setupError {
	return &setupError{fmt.Sprintf("mode replace with commit implicit has no command list for delivery %s: "+
		"the reset loads the baseline into a candidate and commits it, which an implicit commit has none of", delivery)}
}

// nodeRefusal is the node's own account of why it refused the artifact: where, and the
// node's reason with the echoed commands dropped. It never holds a byte of the
// artifact beyond what the node's reason quotes of the refused value.
type nodeRefusal struct {
	line      int    // the file line the node refused; 0 when it refused a framing command or said nothing of where
	bootstrap bool   // the line is the bootstrap's, not the artifact's
	command   string // the framing command it refused, when it was one
	reason    string
	withheld  bool // the message was not of the known shape, so reason says it is withheld (D-034 asks again)
}

func (r *nodeRefusal) Error() string {
	return "node refused the configuration" + r.where() + ": " + r.reason
}

// where says where the node refused: " at line 10", " at bootstrap line 3",
// " at its `commit now`", or nothing.
func (r *nodeRefusal) where() string {
	switch {
	case r.line > 0 && r.bootstrap:
		return fmt.Sprintf(" at bootstrap line %d", r.line)
	case r.line > 0:
		return fmt.Sprintf(" at line %d", r.line)
	case r.command != "":
		return fmt.Sprintf(" at its `%s`", r.command)
	}
	return ""
}

// setupError is a push that cannot be made however often it is retried: a login variable
// unset, a mode and commit with no command list. The host check and the package's load
// refuse each first; this is the second lock.
type setupError struct{ msg string }

func (e *setupError) Error() string { return e.msg }

// refusedAt finds the node's reason and the command it names in SR Linux's JSON-RPC error,
// `Error: Cli commands '<every command>' failed with error 1: At line 11: Error:
// <reason>`.
// The last "' failed with error " before the message's first empty line is taken,
// since the echoed commands before it are the artifact's and may contain anything.
var refusedAt = regexp.MustCompile(`(?s)^At line (\d+): (.*)$`)

// refusalFrom turns the node's error message into a refusal, re-basing its line number,
// which counts the command list, onto the file lines the commands came from. A message
// not of the known shape is withheld whole: it may echo the configuration.
//
// The node's reason ends at its first empty line. Under a replace the message goes on
// past it with the request's output so far, `diff flat`'s lines included, and
// those are configuration: everything from the empty line on is dropped, and so is any
// line of the reason itself that reads as a diff line (reasonOnly). The marker is looked
// for before that line alone. No command sent is empty (configCommands), so the echo ends
// before it, and a marker after it is the output's, where a value of the configuration
// may carry it. A message with no marker before its first empty line is withheld whole.
func refusalFrom(message string, cmds []pushCommand) *nodeRefusal {
	const marker = "' failed with error "
	i := strings.LastIndex(beforeEmptyLine(message), marker)
	if i < 0 {
		return &nodeRefusal{withheld: true,
			reason: "the node's message is not of the shape Fylgja strips the echoed commands from, so it is withheld"}
	}
	rest := message[i+len(marker):]
	if _, after, ok := strings.Cut(rest, ": "); ok {
		rest = after
	}
	r := &nodeRefusal{reason: reasonOnly(rest)}
	if m := refusedAt.FindStringSubmatch(rest); m != nil {
		r.reason = strings.TrimPrefix(reasonOnly(m[2]), "Error: ")
		if n, err := strconv.Atoi(m[1]); err == nil && n >= 1 && n <= len(cmds) {
			c := cmds[n-1]
			r.line, r.bootstrap = c.line, c.bootstrap
			if c.line == 0 {
				r.command = c.text
			}
		}
	}
	return r
}

// beforeEmptyLine is text up to its first empty line, as reasonOnly reads one: a line that
// is blank once trimmed. Text with none is returned whole.
func beforeEmptyLine(text string) string {
	n := 0
	for _, l := range strings.SplitAfter(text, "\n") {
		if strings.TrimSpace(l) == "" {
			return text[:n]
		}
		n += len(l)
	}
	return text
}

// diffLinePrefixes begin the lines of `diff flat`'s output: each is one change
// to the candidate, and so configuration.
var diffLinePrefixes = []string{"insert /", "delete /", "update /", "replace /"}

// reasonOnly is the node's reason out of a refusal's text: up to its first empty line,
// without any line that begins as a diff line does, trimmed.
func reasonOnly(text string) string {
	var kept []string
	for _, l := range strings.Split(text, "\n") {
		if strings.TrimSpace(l) == "" {
			break
		}
		if isDiffLine(l) {
			continue
		}
		kept = append(kept, l)
	}
	return strings.TrimSpace(strings.Join(kept, "\n"))
}

func isDiffLine(l string) bool {
	l = strings.TrimSpace(l)
	for _, p := range diffLinePrefixes {
		if strings.HasPrefix(l, p) {
			return true
		}
	}
	return false
}

// jsonRPCURL is the node's JSON-RPC endpoint on its management address.
func jsonRPCURL(in wire.PushInput) string {
	return fmt.Sprintf("%s://%s/jsonrpc", in.Push.Scheme, net.JoinHostPort(in.MgmtIPv4, strconv.Itoa(in.Push.Port)))
}

// jsonRPCByHand is the push as an operator can repeat it, with the login named by its
// variables and the files by their staged paths, never their content (Constitution X).
func jsonRPCByHand(in wire.PushInput, files []string) string {
	pre, post := `[]`, `[]`
	if in.Push.Commit == "explicit" {
		pre, post = `["`+cmdEnterCandidate+`"]`, `["`+cmdCommitNow+`"]`
		if in.Push.Mode == "replace" {
			pre = `["` + cmdEnterCandidate + `","` + cmdLoadStartup + `"]`
			post = `["` + cmdDiffFlat + `","` + cmdCommitNow + `"]`
		}
	}
	return fmt.Sprintf(`jq -Rs '{jsonrpc:"2.0",id:1,method:"cli",params:{commands:(%s+(split("\n")|map(select(test("\\S"))))+%s)}}' %s | curl -sk -u "$%s:$%s" %s -d @-`, // gitleaks:allow: a format string for the remedy's curl line, which names the login's variables, never a value
		pre, post, byHandFiles(files), in.Push.UsernameEnv, in.Push.PasswordEnv, jsonRPCURL(in))
}
