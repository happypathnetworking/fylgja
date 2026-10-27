package server

import (
	"encoding/json"
	"fmt"
	"slices"
	"sort"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The kinds an argument's value has on the wire (api.schema.json's $defs/args): a flag's
// string as given, a boolean flag, or a list of words.
const (
	argString  = "a string"
	argBool    = "a boolean"
	argStrings = "an array of strings"
)

// operationArgs are the arguments each operation takes, by the name the request gives each,
// and the kind of its value. An argument that is absent is a flag that was
// not given; one that is present was given, whatever its value. From 018 twin.compile takes
// snapshot in place of ctm, and a request carrying ctm is refused as any argument not taken,
// pre-1.0, as 014 renamed series to stage.
var operationArgs = map[string]map[string]string{
	findings.OpTwinCreate: {"branch": argString, "at": argString, "stage": argString, "interval": argString,
		"no_follow": argBool, "dry_run": argBool, "scope": argString, "snapshot": argString},
	findings.OpTwinProvision: {"bundle": argString, "dry_run": argBool},
	findings.OpTwinStep:      {"stage": argString, "allow_restart": argBool, "dry_run": argBool, "wait": argString},
	findings.OpTwinDestroy:   {},
	findings.OpTwinShow:      {},
	findings.OpTwinVerify:    {"wait": argString, "args": argStrings},
	findings.OpCompile:       {"snapshot": argString, "out": argString},
	findings.OpStageList:     {"branch": argString, "scope": argString},
	findings.OpStagePlan:     {"branch": argString, "scope": argString},
	findings.OpIntentRead:    {"branch": argString, "at": argString, "stage": argString, "out": argString, "scope": argString},
	findings.OpSchemaCheck:   {"branch": argString},
	findings.OpPSPValidate:   {"files": argStrings},
	findings.OpTwinRehearse:  {"branch": argString, "scope": argString},
}

// args are one request's arguments, read strictly: checkArgs has refused a name the
// operation does not take and a value of another kind before the answer began, so a request
// the server cannot read is 400 and never a document (contracts/api.md).
type args map[string]json.RawMessage

// checkArgs refuses an argument op does not take, or one whose value is not of its kind.
// The sentence names the argument and never its value.
func checkArgs(op string, given map[string]json.RawMessage) error {
	takes := operationArgs[op]
	names := make([]string, 0, len(given))
	for name := range given {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		kind, ok := takes[name]
		if !ok {
			return fmt.Errorf("the request is not one: %s takes no argument %q", op, name)
		}
		var err error
		switch kind {
		case argString:
			var v string
			err = json.Unmarshal(given[name], &v)
		case argBool:
			var v bool
			err = json.Unmarshal(given[name], &v)
		case argStrings:
			// Pointers, so a null element is told from an empty string.
			var v []*string
			err = json.Unmarshal(given[name], &v)
			if err == nil && (v == nil || slices.Contains(v, nil)) {
				err = fmt.Errorf("null")
			}
		}
		if err != nil || string(given[name]) == "null" {
			return fmt.Errorf("the request is not one: %s's argument %q is not %s", op, name, kind)
		}
	}
	return nil
}

// given is whether the flag named was given.
func (a args) given(name string) bool {
	_, ok := a[name]
	return ok
}

// string is a string flag's value as given, "" when it was not given.
func (a args) string(name string) string {
	var v string
	if raw, ok := a[name]; ok {
		_ = json.Unmarshal(raw, &v)
	}
	return v
}

// bool is a boolean flag, false when it was not given.
func (a args) bool(name string) bool {
	var v bool
	if raw, ok := a[name]; ok {
		_ = json.Unmarshal(raw, &v)
	}
	return v
}

// strings is a list of words, nil when it was not given.
func (a args) strings(name string) []string {
	var v []string
	if raw, ok := a[name]; ok {
		_ = json.Unmarshal(raw, &v)
	}
	return v
}

// handlers are the thirteen operations' runs: each fills the flags M12's command filled from
// the request's arguments, a key's presence standing for cobra's Changed, and calls M12's
// logic, which keeps its guards, their order, their identifiers and their words.
var handlers = map[string]func(*call) error{
	findings.OpTwinCreate: func(c *call) error {
		a := args(c.req.Args)
		return runCreate(c.ctx, c.options(), &createFlags{
			branch: a.string("branch"), at: a.string("at"),
			stage: a.string("stage"), stageGiven: a.given("stage"),
			interval: a.string("interval"), intervalGiven: a.given("interval"),
			noFollow: a.bool("no_follow"), dryRun: a.bool("dry_run"),
			scope: a.string("scope"), scopeGiven: a.given("scope"),
			snapshot: a.string("snapshot"), snapshotGiven: a.given("snapshot"),
		}, c.req.Files)
	},
	findings.OpTwinProvision: func(c *call) error {
		a := args(c.req.Args)
		return runTwinProvision(c.ctx, c.options(), &provisionFlags{dryRun: a.bool("dry_run")}, a.string("bundle"), c.req.Files)
	},
	findings.OpTwinStep: func(c *call) error {
		a := args(c.req.Args)
		return runTwinStep(c.ctx, c.options(), &stepFlags{
			stage: a.string("stage"), stageGiven: a.given("stage"),
			allowRestart: a.bool("allow_restart"), dryRun: a.bool("dry_run"),
			wait: a.string("wait"), waitGiven: a.given("wait"),
		})
	},
	findings.OpTwinDestroy: func(c *call) error {
		return runDestroy(c.ctx, c.options())
	},
	findings.OpTwinShow: func(c *call) error {
		return runShow(c.ctx, c.options())
	},
	findings.OpTwinVerify: func(c *call) error {
		a := args(c.req.Args)
		return runTwinVerify(c.ctx, c.options(), &verifyFlags{
			wait: a.string("wait"), waitGiven: a.given("wait"), args: a.strings("args"),
		})
	},
	findings.OpCompile: func(c *call) error {
		a := args(c.req.Args)
		return runCompile(c.options(), &compileFlags{snapshotPath: a.string("snapshot"), out: a.string("out")}, c.req.Files)
	},
	findings.OpStageList: func(c *call) error {
		a := args(c.req.Args)
		return runStageList(c.ctx, c.options(), &stageFlags{branch: a.string("branch"), branchGiven: a.given("branch"),
			scope: a.string("scope"), scopeGiven: a.given("scope")})
	},
	findings.OpStagePlan: func(c *call) error {
		a := args(c.req.Args)
		return runStagePlan(c.ctx, c.options(), &stageFlags{branch: a.string("branch"), branchGiven: a.given("branch"),
			scope: a.string("scope"), scopeGiven: a.given("scope")})
	},
	findings.OpIntentRead: func(c *call) error {
		a := args(c.req.Args)
		return runRead(c.ctx, c.options(), &readFlags{
			branch: a.string("branch"), at: a.string("at"),
			stage: a.string("stage"), stageGiven: a.given("stage"),
			out: a.string("out"), scope: a.string("scope"), scopeGiven: a.given("scope"),
		})
	},
	findings.OpSchemaCheck: func(c *call) error {
		a := args(c.req.Args)
		return runCheck(c.ctx, c.options(), &checkFlags{branch: a.string("branch")})
	},
	findings.OpPSPValidate: func(c *call) error {
		a := args(c.req.Args)
		return runPSPValidate(c.options(), a.strings("files"), c.req.Files)
	},
	findings.OpTwinRehearse: func(c *call) error {
		a := args(c.req.Args)
		return runTwinRehearse(c.ctx, c.options(), &rehearseFlags{branch: a.string("branch"), branchGiven: a.given("branch"),
			scope: a.string("scope"), scopeGiven: a.given("scope")})
	},
}

// checkRequest refuses an argument op does not take, a value of another kind, an argument
// required or left without the one it belongs to, or files on an operation that takes none.
func checkRequest(op string, req api.Request) error {
	if err := checkArgs(op, req.Args); err != nil {
		return err
	}
	if err := checkRequired(op, req.Args); err != nil {
		return err
	}
	return checkFiles(op, len(req.Files))
}

// checkRequired refuses the two requests no client's command can build, whose answers would
// name nothing or ignore an argument: twin.provision without its bundle
// directory, which M12's ExactArgs(1) made the command's, so every sentence would name ""
// as the directory; and twin.verify with "args" and no "wait", whose words only a bare
// --wait leaves behind and which verifyBudget reads only under it, as M12's cobra refused
// an argument without --wait. The sentence names the argument and never its value.
func checkRequired(op string, given map[string]json.RawMessage) error {
	a := args(given)
	switch {
	case op == findings.OpTwinProvision && !a.given("bundle"):
		return fmt.Errorf("the request is not one: %s takes the bundle directory as its argument %q", op, "bundle")
	case op == findings.OpTwinVerify && a.given("args") && !a.given("wait"):
		return fmt.Errorf("the request is not one: %s's argument %q is given without %q", op, "args", "wait")
	}
	return nil
}

// takesFiles are the operations a request's files belong to. twin.create takes one, a
// snapshot file beside --snapshot alone (018), which the create holds to that shape itself,
// as twin compile holds its snapshot, so a request carrying another is its operation.failed
// and not the transport's.
var takesFiles = []string{findings.OpCompile, findings.OpTwinProvision, findings.OpPSPValidate, findings.OpTwinCreate}

// checkFiles refuses files on an operation that takes none.
func checkFiles(op string, n int) error {
	if n > 0 && !slices.Contains(takesFiles, op) {
		return fmt.Errorf("the request is not one: %s takes no files", op)
	}
	return nil
}
