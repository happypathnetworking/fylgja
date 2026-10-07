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
// not given; one that is present was given, whatever its value.
var operationArgs = map[string]map[string]string{
	findings.OpTwinCreate: {"branch": argString, "at": argString, "waypoint": argString, "interval": argString,
		"no_follow": argBool, "dry_run": argBool},
	findings.OpTwinProvision: {"bundle": argString, "dry_run": argBool},
	findings.OpTwinStep:      {"waypoint": argString, "allow_restart": argBool, "dry_run": argBool, "wait": argString},
	findings.OpTwinDestroy:   {},
	findings.OpTwinShow:      {},
	findings.OpTwinVerify:    {"wait": argString, "args": argStrings},
	findings.OpCompile:       {"ctm": argString, "out": argString},
	findings.OpWaypointList:  {"series": argString},
	findings.OpWaypointPlan:  {"series": argString},
	findings.OpIntentRead:    {"branch": argString, "at": argString, "waypoint": argString, "out": argString},
	findings.OpSchemaCheck:   {"branch": argString},
	findings.OpPSPValidate:   {"files": argStrings},
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

// handlers are the twelve operations' runs: each fills the flags M12's command filled from
// the request's arguments, a key's presence standing for cobra's Changed, and calls M12's
// logic, which keeps its guards, their order, their identifiers and their words.
var handlers = map[string]func(*call) error{
	findings.OpTwinCreate: func(c *call) error {
		a := args(c.req.Args)
		return runCreate(c.ctx, c.options(), &createFlags{
			branch: a.string("branch"), at: a.string("at"),
			waypoint: a.string("waypoint"), waypointGiven: a.given("waypoint"),
			interval: a.string("interval"), intervalGiven: a.given("interval"),
			noFollow: a.bool("no_follow"), dryRun: a.bool("dry_run"),
		})
	},
	findings.OpTwinProvision: func(c *call) error {
		a := args(c.req.Args)
		return runTwinProvision(c.ctx, c.options(), &provisionFlags{dryRun: a.bool("dry_run")}, a.string("bundle"), c.req.Files)
	},
	findings.OpTwinStep: func(c *call) error {
		a := args(c.req.Args)
		return runTwinStep(c.ctx, c.options(), &stepFlags{
			waypoint: a.string("waypoint"), waypointGiven: a.given("waypoint"),
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
		return runCompile(c.options(), &compileFlags{ctmPath: a.string("ctm"), out: a.string("out")}, c.req.Files)
	},
	findings.OpWaypointList: func(c *call) error {
		a := args(c.req.Args)
		return runWaypointList(c.ctx, c.options(), &waypointFlags{series: a.string("series"), seriesGiven: a.given("series")})
	},
	findings.OpWaypointPlan: func(c *call) error {
		a := args(c.req.Args)
		return runWaypointPlan(c.ctx, c.options(), &waypointFlags{series: a.string("series"), seriesGiven: a.given("series")})
	},
	findings.OpIntentRead: func(c *call) error {
		a := args(c.req.Args)
		return runRead(c.ctx, c.options(), &readFlags{
			branch: a.string("branch"), at: a.string("at"),
			waypoint: a.string("waypoint"), waypointGiven: a.given("waypoint"),
			out: a.string("out"),
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

// takesFiles are the operations a request's files belong to.
var takesFiles = []string{findings.OpCompile, findings.OpTwinProvision, findings.OpPSPValidate}

// checkFiles refuses files on an operation that takes none.
func checkFiles(op string, n int) error {
	if n > 0 && !slices.Contains(takesFiles, op) {
		return fmt.Errorf("the request is not one: %s takes no files", op)
	}
	return nil
}
