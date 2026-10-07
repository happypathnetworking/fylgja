//go:build contract || fixture

package testsupport

import (
	"fmt"
	"strings"
)

// TestSeriesPrefix begins every waypoint series a test writes. Every helper
// here refuses any other series before a request is made, so no test can write or remove
// a series an operator made; fylgja-fixture never gains a persistent one.
const TestSeriesPrefix = "fylgja-test-"

// WaypointRow is one waypoint as the harness reads it back.
type WaypointRow struct {
	ID       string
	Series   string
	Sequence int
	Branch   string
}

// testSeries refuses a series that is not a test's.
func testSeries(series string) error {
	if !strings.HasPrefix(series, TestSeriesPrefix) {
		return fmt.Errorf("series %q is not a test series: every series a test writes begins %q", series, TestSeriesPrefix)
	}
	return nil
}

// WriteWaypoint writes one waypoint naming branch as it stands now, on the default
// branch's GraphQL: the kind is branch-agnostic and lives there (D-028), so the harness
// names main where the product names no branch at all. An empty at leaves as_of
// unwritten, so the waypoint's at is the moment its branch attribute was written;
// write it after the writes it seals.
func (c *Client) WriteWaypoint(series string, sequence int, branch, at, description string) (string, error) {
	if err := testSeries(series); err != nil {
		return "", err
	}
	data := fmt.Sprintf(`{series: {value: %q}, sequence: {value: %d}, branch: {value: %q}`, series, sequence, branch)
	if at != "" {
		data += fmt.Sprintf(`, as_of: {value: %q}`, at)
	}
	if description != "" {
		data += fmt.Sprintf(`, description: {value: %q}`, description)
	}
	return c.create("main", "FylgjaWaypoint", data+"}")
}

// WaypointsNaming returns every test waypoint whose branch is the given one.
func (c *Client) WaypointsNaming(branch string) ([]WaypointRow, error) {
	rows, err := c.waypoints(fmt.Sprintf(`(branch__value: %q)`, branch))
	if err != nil {
		return nil, err
	}
	var out []WaypointRow
	for _, r := range rows {
		if strings.HasPrefix(r.Series, TestSeriesPrefix) {
			out = append(out, r)
		}
	}
	return out, nil
}

// DeleteWaypointSeries deletes every waypoint of a test series and returns how many.
func (c *Client) DeleteWaypointSeries(series string) (int, error) {
	if err := testSeries(series); err != nil {
		return 0, err
	}
	rows, err := c.waypoints(fmt.Sprintf(`(series__value: %q)`, series))
	if err != nil {
		return 0, err
	}
	return c.deleteWaypoints(rows)
}

// DeleteWaypointsNaming deletes every test waypoint naming a branch and returns how
// many: what the fixture tool's -delete does beside deleting the branch.
func (c *Client) DeleteWaypointsNaming(branch string) (int, error) {
	rows, err := c.WaypointsNaming(branch)
	if err != nil {
		return 0, err
	}
	return c.deleteWaypoints(rows)
}

// waypoints lists the waypoints a filter selects, on the default branch.
func (c *Client) waypoints(filter string) ([]WaypointRow, error) {
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`{ FylgjaWaypoint%s { edges { node { id series { value } sequence { value } branch { value } } } } }`, filter))
	if err != nil {
		return nil, fmt.Errorf("listing waypoints%s: %w", filter, err)
	}
	var r struct {
		FylgjaWaypoint struct {
			Edges []struct {
				Node struct {
					ID     string `json:"id"`
					Series struct {
						Value string `json:"value"`
					} `json:"series"`
					Sequence struct {
						Value int `json:"value"`
					} `json:"sequence"`
					Branch struct {
						Value string `json:"value"`
					} `json:"branch"`
				} `json:"node"`
			} `json:"edges"`
		}
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	var out []WaypointRow
	for _, e := range r.FylgjaWaypoint.Edges {
		out = append(out, WaypointRow{ID: e.Node.ID, Series: e.Node.Series.Value,
			Sequence: e.Node.Sequence.Value, Branch: e.Node.Branch.Value})
	}
	return out, nil
}

// deleteWaypoints deletes each row, refusing any that is not a test's.
func (c *Client) deleteWaypoints(rows []WaypointRow) (int, error) {
	n := 0
	for _, r := range rows {
		if err := testSeries(r.Series); err != nil {
			return n, err
		}
		raw, err := c.GraphQL("main", fmt.Sprintf(`mutation { FylgjaWaypointDelete(data: {id: %q}) { ok } }`, r.ID))
		if err != nil {
			return n, fmt.Errorf("deleting waypoint %s/%d: %w", r.Series, r.Sequence, err)
		}
		if err := okOf(raw, "FylgjaWaypointDelete", fmt.Sprintf("deleting waypoint %s/%d", r.Series, r.Sequence)); err != nil {
			return n, err
		}
		n++
	}
	return n, nil
}
