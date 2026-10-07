package psp

import (
	"reflect"
	"testing"
)

// testProfile builds a package in the test, so the engine is exercised on every kind of
// rule the format has without depending on any shipped file: one-to-one with the
// node's own name differing, many-to-one, a spreading and a collapsing breakout, and the
// management rule.
func testProfile(t *testing.T, rules ...Rule) *Profile {
	t.Helper()
	p := &PSP{Platform: Identity{ID: "testos"}, Interfaces: Interfaces{Rules: rules}}
	prof, err := NewProfile(p)
	if err != nil {
		t.Fatalf("NewProfile: %v", err)
	}
	return prof
}

var (
	ruleFront = Rule{Name: "front", Match: "Ethernet1/{port}", Ranges: map[string][2]int{"port": {1, 52}},
		Port: "eth{port}", NodeName: "Ethernet{port}"}
	ruleLinecard = Rule{Name: "linecard", Match: "Ethernet{slot}/{port}",
		Ranges: map[string][2]int{"slot": {2, 4}, "port": {1, 48}},
		Port:   "eth{port}", NodeName: "Ethernet{port}", Lossy: true}
	ruleCollapse = Rule{Name: "breakout", Match: "Ethernet{slot}/{port}/{sub}",
		Ranges: map[string][2]int{"slot": {1, 1}, "port": {49, 52}, "sub": {1, 4}},
		Port:   "eth{port}", NodeName: "Ethernet{port}", Lossy: true,
		Breakout: &Breakout{Parent: "Ethernet{slot}/{port}"}}
	ruleSpread = Rule{Name: "spread", Match: "ethernet-{slot}/{port}/{sub}",
		Ranges: map[string][2]int{"slot": {1, 1}, "port": {1, 58}, "sub": {1, 4}},
		Port:   "e{slot}-{port}-{sub}", NodeName: "ethernet-{slot}/{port}/{sub}",
		Breakout: &Breakout{Parent: "ethernet-{slot}/{port}"}}
	ruleSame = Rule{Name: "ethernet", Match: "ethernet-{slot}/{port}",
		Ranges: map[string][2]int{"slot": {1, 1}, "port": {1, 58}},
		Port:   "e{slot}-{port}", NodeName: "ethernet-{slot}/{port}"}
	ruleFree = Rule{Name: "free", Match: "xe-{port}", Port: "xe{port}", NodeName: "xe-{port}"}
	ruleMgmt = Rule{Name: "management", Management: true, Port: "eth0", NodeName: "Management0"}
)

func TestApplyEveryOutcome(t *testing.T) {
	prof := testProfile(t, ruleFront, ruleLinecard, ruleCollapse, ruleSpread, ruleSame, ruleFree, ruleMgmt)
	tried := []string{"front", "linecard", "breakout", "spread", "ethernet", "free"}

	cases := []struct {
		name     string
		mgmtOnly bool
		want     Outcome
	}{
		// One-to-one, the node's own name differing from the production name.
		{"Ethernet1/7", false, Outcome{Kind: Mapped, Rule: "front", Port: "eth7", NodeName: "Ethernet7"}},
		// One-to-one with the same name.
		{"ethernet-1/3", false, Outcome{Kind: Mapped, Rule: "ethernet", Port: "e1-3", NodeName: "ethernet-1/3"}},
		// Many-to-one: the slot is dropped, and the rule says so.
		{"Ethernet3/7", false, Outcome{Kind: Mapped, Rule: "linecard", Port: "eth7", NodeName: "Ethernet7", Lossy: true}},
		// A collapsing breakout: the child lands on its parent's port, and names it.
		{"Ethernet1/49/2", false, Outcome{Kind: Mapped, Rule: "breakout", Port: "eth49", NodeName: "Ethernet49",
			Lossy: true, Parent: "Ethernet1/49"}},
		// A spreading breakout: the child has a port of its own.
		{"ethernet-1/49/1", false, Outcome{Kind: Mapped, Rule: "spread", Port: "e1-49-1", NodeName: "ethernet-1/49/1",
			Parent: "ethernet-1/49"}},
		// The management rule decides a mgmt_only interface whatever it is called.
		{"Management1", true, Outcome{Kind: Mapped, Rule: "management", Port: "eth0", NodeName: "Management0"}},
		{"Ethernet1/1", true, Outcome{Kind: Mapped, Rule: "management", Port: "eth0", NodeName: "Management0"}},
		// No rule: every data rule tried, in order, the management rule left out.
		{"Port-Channel1", false, Outcome{Kind: NoRule, Tried: tried}},
		{"Management1", false, Outcome{Kind: NoRule, Tried: tried}},
		// Out of range: a value outside, a value that is not an integer, and the first of
		// two placeholders outside in the rule's match order.
		{"Ethernet1/53", false, Outcome{Kind: OutOfRange, Rule: "front", Placeholder: "port", Value: "53", Range: [2]int{1, 52}}},
		{"Ethernet1/x", false, Outcome{Kind: OutOfRange, Rule: "front", Placeholder: "port", Value: "x", Range: [2]int{1, 52}}},
		{"Ethernet9/99", false, Outcome{Kind: OutOfRange, Rule: "linecard", Placeholder: "slot", Value: "9", Range: [2]int{2, 4}}},
		{"Ethernet3/49", false, Outcome{Kind: OutOfRange, Rule: "linecard", Placeholder: "port", Value: "49", Range: [2]int{1, 48}}},
		{"ethernet-2/1", false, Outcome{Kind: OutOfRange, Rule: "ethernet", Placeholder: "slot", Value: "2", Range: [2]int{1, 1}}},
		// A placeholder with no range accepts anything.
		{"xe-anything", false, Outcome{Kind: Mapped, Rule: "free", Port: "xeanything", NodeName: "xe-anything"}},
	}
	for _, tc := range cases {
		got := prof.Apply(tc.name, tc.mgmtOnly)
		if !reflect.DeepEqual(got, tc.want) {
			t.Errorf("Apply(%q, mgmt_only=%v)\n got %+v\nwant %+v", tc.name, tc.mgmtOnly, got, tc.want)
		}
	}
}

// The first rule whose match fits decides, in range or out of it: Ethernet1/60 fits
// front (out of range) and would fit linecard's shape too, but never reaches it.
func TestFirstMatchWins(t *testing.T) {
	prof := testProfile(t, ruleFront, ruleLinecard, ruleMgmt)
	if got := prof.Apply("Ethernet1/7", false); got.Rule != "front" {
		t.Errorf("Ethernet1/7 decided by %q, want front (the first rule that fits)", got.Rule)
	}
	if got := prof.Apply("Ethernet1/60", false); got.Kind != OutOfRange || got.Rule != "front" {
		t.Errorf("Ethernet1/60 = %+v; an out-of-range match must not fall through to a later rule", got)
	}

	// The same two rules in the other order: linecard now fits Ethernet1/7 first, and its
	// range on slot refuses it.
	prof = testProfile(t, ruleLinecard, ruleFront, ruleMgmt)
	if got := prof.Apply("Ethernet1/7", false); got.Kind != OutOfRange || got.Rule != "linecard" || got.Placeholder != "slot" {
		t.Errorf("Ethernet1/7 under linecard-first = %+v, want out of range under linecard on {slot}", got)
	}
}

func TestContains(t *testing.T) {
	prof := testProfile(t, ruleFront, ruleLinecard, ruleCollapse, ruleMgmt)
	cases := []struct {
		rule, port, production string
		want                   bool
	}{
		{"linecard", "eth7", "Ethernet3/7", true},
		{"linecard", "eth7", "Ethernet4/7", true},
		{"linecard", "eth7", "Ethernet3/8", false},   // renders another port
		{"linecard", "eth7", "Ethernet5/7", false},   // the dropped slot is outside its range
		{"linecard", "eth7", "Ethernet3/x", false},   // not an integer
		{"linecard", "eth7", "Port-Channel1", false}, // does not match
		{"breakout", "eth49", "Ethernet1/49/4", true},
		{"breakout", "eth49", "Ethernet1/49/5", false}, // sub outside 1..4
		{"front", "eth7", "Ethernet1/7", true},
		{"nosuch", "eth7", "Ethernet1/7", false},
		{"management", "eth0", "Management1", false}, // the management rule contains nothing by name
	}
	for _, tc := range cases {
		if got := prof.Contains(tc.rule, tc.port, tc.production); got != tc.want {
			t.Errorf("Contains(%q, %q, %q) = %v, want %v", tc.rule, tc.port, tc.production, got, tc.want)
		}
	}
}

func TestManagementPort(t *testing.T) {
	if got := testProfile(t, ruleFront, ruleMgmt).ManagementPort(); got != "eth0" {
		t.Errorf("ManagementPort = %q, want eth0", got)
	}
}

// Rules is the package's order, management included: the suite's notes read it.
func TestRulesKeepsTheOrder(t *testing.T) {
	prof := testProfile(t, ruleLinecard, ruleMgmt, ruleFront)
	var names []string
	for _, r := range prof.Rules() {
		names = append(names, r.Name)
	}
	if want := []string{"linecard", "management", "front"}; !reflect.DeepEqual(names, want) {
		t.Errorf("Rules = %v, want %v", names, want)
	}
}

// NewProfile is the guard for a package built by hand that skipped validation.
func TestNewProfileRefusesWhatValidationWould(t *testing.T) {
	for name, rules := range map[string][]Rule{
		"no management rule":   {ruleFront},
		"two management rules": {ruleFront, ruleMgmt, ruleMgmt},
		"port uses an uncaptured placeholder": {
			{Name: "bad", Match: "Ethernet{port}", Port: "eth{slot}", NodeName: "Ethernet{port}"}, ruleMgmt},
		"parent uses an uncaptured placeholder": {
			{Name: "bad", Match: "e{port}/{sub}", Port: "e{port}-{sub}", NodeName: "e{port}/{sub}",
				Breakout: &Breakout{Parent: "e{slot}"}}, ruleMgmt},
		"empty match": {{Name: "bad", Port: "e1", NodeName: "e1"}, ruleMgmt},
	} {
		p := &PSP{Platform: Identity{ID: "testos"}, Interfaces: Interfaces{Rules: rules}}
		if _, err := NewProfile(p); err == nil {
			t.Errorf("%s: NewProfile accepted it", name)
		}
	}
}

// A data rule that can render the management port or node name is refused at load, and
// NewProfile refuses it too, in psp.management.collides's words: no interface of any
// intent may land on the management port or take its name.
func TestNewProfileRefusesAManagementPortOrNameADataRuleRenders(t *testing.T) {
	// No range on front's port: eth0 is one of the ports it renders.
	wide := Rule{Name: "front", Match: "Ethernet1/{port}", Port: "eth{port}", NodeName: "Ethernet{port}"}
	for _, tc := range []struct {
		name  string
		rules []Rule
		want  string
	}{
		{"port", []Rule{wide, ruleMgmt},
			`platform testos: management port "eth0" is also rendered by rule "front" (port "eth{port}", {port} = 0); one port would mean two things`},
		{"node name", []Rule{ruleFront, {Name: "management", Management: true, Port: "eth0", NodeName: "Ethernet7"}},
			`platform testos: management node name "Ethernet7" is also rendered by rule "front" (node_name "Ethernet{port}", {port} = 7); one name would mean two things`},
		{"literal port", []Rule{{Name: "one", Match: "Ethernet1/1", Port: "eth0", NodeName: "Ethernet1"}, ruleMgmt},
			`platform testos: management port "eth0" is also rendered by rule "one" (port "eth0"); one port would mean two things`},
	} {
		p := &PSP{Platform: Identity{ID: "testos"}, Interfaces: Interfaces{Rules: tc.rules}}
		_, err := NewProfile(p)
		if err == nil || err.Error() != tc.want {
			t.Errorf("%s: NewProfile error\n got  %v\n want %s", tc.name, err, tc.want)
		}
	}
	// Inside the ranges only: front's port range starts at 1, so eth0 is no port of it.
	if _, err := NewProfile(&PSP{Platform: Identity{ID: "testos"}, Interfaces: Interfaces{Rules: []Rule{ruleFront, ruleLinecard, ruleMgmt}}}); err != nil {
		t.Errorf("a management port no rule renders inside its ranges was refused: %v", err)
	}
}

// RendersWithin tries every parse of a name, so abutting placeholders cannot hide a
// render a regular expression's one parse would miss.
func TestRendersWithin(t *testing.T) {
	ranges := map[string][2]int{"slot": {1, 1}, "port": {1, 58}}
	for _, tc := range []struct {
		pattern, name string
		want          []PlaceholderValue
		ok            bool
	}{
		{"e{slot}-{port}", "e1-1", []PlaceholderValue{{"slot", "1"}, {"port", "1"}}, true},
		{"e{slot}-{port}", "e1-59", nil, false},
		{"e{slot}-{port}", "mgmt0", nil, false},
		// A greedy parse takes slot=12, port=3 and refuses; slot=1, port=23 renders.
		{"eth{slot}{port}", "eth123", []PlaceholderValue{{"slot", "1"}, {"port", "23"}}, true},
		// A placeholder is one path segment.
		{"e{port}", "e1/2", nil, false},
		// No range: any value.
		{"xe{free}", "xe-anything", []PlaceholderValue{{"free", "-anything"}}, true},
		// A placeholder used twice takes one value.
		{"e{port}-{port}", "e3-3", []PlaceholderValue{{"port", "3"}}, true},
		{"e{port}-{port}", "e3-4", nil, false},
		{"mgmt0", "mgmt0", []PlaceholderValue{}, true},
	} {
		got, ok := RendersWithin(tc.pattern, ranges, tc.name)
		if ok != tc.ok || (ok && !reflect.DeepEqual(got, tc.want)) {
			t.Errorf("RendersWithin(%q, %q) = %v, %v; want %v, %v", tc.pattern, tc.name, got, ok, tc.want, tc.ok)
		}
	}
}

func TestInRange(t *testing.T) {
	for _, tc := range []struct {
		v    string
		want bool
	}{
		{"1", true}, {"58", true}, {"0", false}, {"59", false},
		{"", false}, {"x", false}, {"-1", false}, {"+1", false}, {"1a", false},
		{"99999999999999999999999", false},
	} {
		if got := inRange(tc.v, [2]int{1, 58}); got != tc.want {
			t.Errorf("inRange(%q, 1..58) = %v, want %v", tc.v, got, tc.want)
		}
	}
}
