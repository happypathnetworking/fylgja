package intent

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

// The two REST endpoints differ in exactly one thing, and it is load-bearing: the object
// store has a time axis and the schema endpoint does not.
//
// Sending `at` to the schema endpoint would be harmless — it ignores one — but the read
// would then be making a request nobody verified, and the envelope's
// schema_hash would look as though it were the schema as of `at`, which it is not.
// Leaving `at` off the content fetch would be worse: a pinned read would verify the
// checksum the listing gave at `at` against whatever bytes are current.
//
// Pinning both URLs is the cheapest way to keep the pair from drifting.
func TestRequestURLsCarryAtOnlyWhereThereIsATimeAxis(t *testing.T) {
	const (
		storageID = "18d67d7e-a006-995e-2cfe-c5124cbde270"
		at        = "2026-09-18T16:51:32.118490+00:00"
		// The `+` of a timezone offset, URL encoded. Unencoded it is read as a space
		// and the request is refused — the reason Config.endpoint encodes it too.
		atEncoded = "2026-09-18T16%3A51%3A32.118490%2B00%3A00"
	)

	for _, tc := range []struct {
		name, at string
		want     map[string]string // path -> the whole RequestURI Infrahub should see
	}{
		{
			name: "unpinned",
			at:   "",
			want: map[string]string{
				"schema":  "/api/schema?branch=fylgja-fixture",
				"storage": "/api/storage/object/" + storageID,
			},
		},
		{
			name: "pinned",
			at:   at,
			want: map[string]string{
				"schema":  "/api/schema?branch=fylgja-fixture",
				"storage": "/api/storage/object/" + storageID + "?at=" + atEncoded,
			},
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var got string
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				got = r.URL.RequestURI()
				w.WriteHeader(http.StatusOK)
				// Enough of a schema document for SchemaInfo to succeed; this test is
				// about the URL, not the body.
				_, _ = w.Write([]byte(`{"main":"fixture","generics":[],"nodes":[]}`))
			}))
			defer srv.Close()

			c := New(Config{Address: srv.URL, Token: "sentinel-token", Branch: "fylgja-fixture", At: tc.at})

			if _, err := c.SchemaInfo(t.Context()); err != nil {
				t.Fatalf("reading the schema: %v", err)
			}
			if got != tc.want["schema"] {
				t.Errorf("schema request %q, want %q", got, tc.want["schema"])
			}

			if _, _, err := c.getAt(t.Context(), storageObjectPath(storageID)); err != nil {
				t.Fatalf("fetching the object: %v", err)
			}
			if got != tc.want["storage"] {
				t.Errorf("storage request %q, want %q", got, tc.want["storage"])
			}
		})
	}
}
