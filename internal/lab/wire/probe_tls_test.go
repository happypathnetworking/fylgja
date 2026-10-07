package wire

import (
	"encoding/json"
	"testing"
)

// Probe.TLS is a defaulted field, and the default has to survive a plan that was written
// before the field existed.
//
// Every NodePlan recorded in a Temporal history from M2 through M6 omits the key. A Go
// bool would decode those as false and dial plaintext on every replay, silently turning
// TLS off for every node of every earlier twin — which is exactly the kind of change a
// "defaulted field" is supposed not to be. The pointer is what makes the absence
// expressible, and this test is what holds it that way: it fails if the field is ever
// changed back to a bool, and it fails if a reader stops treating nil as TLS.
func TestAnAbsentTLSKeyMeansTLS(t *testing.T) {
	// An M2-era plan, as a recorded history carries one: no tls key anywhere.
	const recorded = `{
		"name": "n1",
		"psp_id": "nokia_srlinux",
		"image": "ghcr.io/nokia/srlinux:24.7.1",
		"probe": {
			"transport": "gnmi_get",
			"path": "/system/information",
			"encoding": "json_ietf",
			"port": 57400,
			"username_env": "FYLGJA_SRLINUX_USERNAME",
			"password_env": "FYLGJA_SRLINUX_PASSWORD"
		}
	}`
	var plan NodePlan
	if err := json.Unmarshal([]byte(recorded), &plan); err != nil {
		t.Fatal(err)
	}
	if plan.Probe.TLS != nil {
		t.Fatalf("an absent tls key decoded to %v, want nil: a non-nil false would dial plaintext", *plan.Probe.TLS)
	}
	if !ProbeTLS(plan.Probe) {
		t.Error("a plan with no tls key must be read as TLS, as every plan written before the field meant")
	}

	// A plan this build writes always states it, either way, so neither value is ever
	// inferred from an absence.
	for _, want := range []bool{true, false} {
		b, err := json.Marshal(Probe{TLS: &want})
		if err != nil {
			t.Fatal(err)
		}
		var got Probe
		if err := json.Unmarshal(b, &got); err != nil {
			t.Fatal(err)
		}
		if got.TLS == nil || *got.TLS != want {
			t.Errorf("tls %v did not round-trip: %v", want, got.TLS)
		}
		if ProbeTLS(got) != want {
			t.Errorf("ProbeTLS = %v, want %v", ProbeTLS(got), want)
		}
	}
}
