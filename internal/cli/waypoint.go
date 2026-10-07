package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The noun waypoint (M10): the waypoints the operator
// wrote in Infrahub, listed and planned. The server dials Infrahub for both, and nothing
// else: no workflow service, no worker, no containerlab, no host budget.
func newWaypointCmd(opts *options) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "waypoint",
		Short: "List and plan the waypoints written in Infrahub",
	}
	cmd.AddCommand(newWaypointListCmd(opts), newWaypointPlanCmd(opts))
	return cmd
}

type waypointFlags struct {
	series string
	// seriesGiven is whether --series was given at all, apart from its value: an explicit
	// empty one is a series refused, not one left out (M4's --interval= precedent).
	seriesGiven bool
}

func newWaypointListCmd(opts *options) *cobra.Command {
	f := &waypointFlags{}
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List every waypoint and the reference each resolves to",
		Long: "List the waypoints written in Infrahub, read from its default branch, sorted by\n" +
			"series then sequence, each with the branch and at it resolves to and where the at\n" +
			"came from. The waypoint the host's twin was built from is marked. Nothing is\n" +
			"refused: a later waypoint whose at is earlier, and a twin whose waypoint has since\n" +
			"moved, are warnings. The API's server reads them, and needs Infrahub and nothing\n" +
			"else for it.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.seriesGiven = cmd.Flags().Changed("series")
			return runWaypointList(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.series, "series", "", "list this series alone")
	return cmd
}

func newWaypointPlanCmd(opts *options) *cobra.Command {
	f := &waypointFlags{}
	cmd := &cobra.Command{
		Use:   "plan",
		Short: "Read and compile each waypoint of a series, and print the step between each pair",
		Long: "Read and compile each waypoint of one series, in sequence order, on the pipeline\n" +
			"intent read and twin compile run, and file each bundle and its CTM in the store.\n" +
			"Between each consecutive pair, print what differs: nodes and links, then the\n" +
			"configuration artifacts by checksum, never by content. A waypoint that is refused\n" +
			"is reported and the plan goes on. The API's server reads, compiles and files them in\n" +
			"its bundle store, and needs Infrahub and the store for it: no workflow service,\n" +
			"worker, containerlab or host budget.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.seriesGiven = cmd.Flags().Changed("series")
			return runWaypointPlan(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.series, "series", "", "the series to plan (required)")
	return cmd
}

// waypointArgs are --series as given: present whenever the flag was, an empty one included.
func waypointArgs(f *waypointFlags) given {
	a := given{}
	if f.seriesGiven {
		a["series"] = f.series
	}
	return a
}

// runWaypointList is waypoint list as one request.
func runWaypointList(ctx context.Context, opts *options, f *waypointFlags) error {
	return send(ctx, opts, findings.OpWaypointList, waypointArgs(f), nil, handlers{})
}

// runWaypointPlan is waypoint plan as one request: the server reads,
// compiles and files each waypoint of the series, and prints each as it is known.
func runWaypointPlan(ctx context.Context, opts *options, f *waypointFlags) error {
	return send(ctx, opts, findings.OpWaypointPlan, waypointArgs(f), nil, handlers{})
}
