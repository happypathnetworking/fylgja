package intent

import (
	"context"
	"fmt"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
)

// Stamps is when a branch's intent and its artifacts were last written, as one read at
// the client's (branch, at) returned them (014; research R-06, R-07; D-046). It reads
// stamps and never a value of intent but the names that key them and the platform that
// picks each device's package. Every stamp is kept as the string Infrahub returned;
// each comparison parses it.
type Stamps struct {
	// Latest is the latest stamp the read returned: every device's, interface's and
	// link's, and every artifact's checksum's. The head's `at` is it plus one
	// microsecond. "" when the branch holds nothing stamped.
	Latest string
	// Devices holds each device's own stamps by its name.
	Devices map[string]DeviceStamps
}

// DeviceStamps is one device's side of the staleness rule (D-046).
type DeviceStamps struct {
	// Platform picks the device's package from the registry, whose config.artifact_name
	// names which of Artifacts is its configuration (Constitution II).
	Platform ctm.Platform
	// Intent is the latest stamp of the device's own intent: its name, role and site,
	// its platform edge, each interface's edge and its name, iftype, mgmt_only, enabled,
	// link edge and parent edge, and every endpoints edge of each link one of its
	// interfaces terminates.
	Intent string
	// Artifacts maps each of the device's artifacts by name to its checksum.updated_at,
	// which moves only when Infrahub stores bytes that differ; "" when Infrahub returned
	// no stamp for it. Two artifacts of one name keep the later, which the read refuses
	// as artifact.ambiguous anyway.
	Artifacts map[string]string
}

// The generated node types, named for the walk below as project.go names the read's.
type (
	stampDeviceNode = IntentStampsFylgjaDevicePaginatedFylgjaDeviceEdgesEdgedFylgjaDeviceNodeFylgjaDevice
	stampLinkNode   = IntentStampsFylgjaLinkPaginatedFylgjaLinkEdgesEdgedFylgjaLinkNodeFylgjaLink
)

// Stamps reads the branch's stamps at the client's `at`, which is sent on every page
// iff it is set, as the read sends it, and aggregates them per device. Devices and
// links are paged together until both are read.
func (c *Client) Stamps(ctx context.Context) (Stamps, error) {
	r := stampReader{devices: map[string]*deviceFold{}}
	var links []stampFold
	var linkDevices [][]string
	for offset := 0; ; offset += pageSize {
		resp, err := IntentStamps(ctx, c.gql, pageSize, offset)
		if err != nil {
			return Stamps{}, c.wrap(err, "reading stamps")
		}
		devicePage, linkPage := resp.GetFylgjaDevice(), resp.GetFylgjaLink()
		for _, edge := range devicePage.GetEdges() {
			if n := edge.GetNode(); n != nil {
				r.device(n)
			}
		}
		for _, edge := range linkPage.GetEdges() {
			if n := edge.GetNode(); n != nil {
				fold, devices := r.link(n)
				links = append(links, fold)
				linkDevices = append(linkDevices, devices)
			}
		}
		if offset+pageSize >= max(devicePage.GetCount(), linkPage.GetCount()) {
			break
		}
	}
	if r.err != nil {
		return Stamps{}, fmt.Errorf("reading stamps %s: %w", c.cfg.describe(), r.err)
	}

	// A link's endpoint edges are both its devices' intent, and no third's: a re-cabling
	// that writes no attribute still moves them (research §2.8).
	for i, fold := range links {
		if fold.stamp == "" {
			continue
		}
		for _, name := range linkDevices[i] {
			if d, ok := r.devices[name]; ok {
				d.intent.take(fold.stamp, fold.at)
			}
		}
	}

	out := Stamps{Latest: r.all.stamp, Devices: make(map[string]DeviceStamps, len(r.devices))}
	for name, d := range r.devices {
		artifacts := make(map[string]string, len(d.artifacts))
		for a, fold := range d.artifacts {
			artifacts[a] = fold.stamp
		}
		out.Devices[name] = DeviceStamps{Platform: d.platform, Intent: d.intent.stamp, Artifacts: artifacts}
	}
	return out, nil
}

// stampFold keeps the latest of the stamps it is shown, as the string Infrahub returned.
// Two stamps naming one instant keep the first.
type stampFold struct {
	stamp string
	at    time.Time
}

func (f *stampFold) take(stamp string, at time.Time) {
	if f.stamp == "" || at.After(f.at) {
		f.stamp, f.at = stamp, at
	}
}

// deviceFold is one device's stamps while the pages are read.
type deviceFold struct {
	platform  ctm.Platform
	intent    stampFold
	artifacts map[string]*stampFold
}

// stampReader folds one read's stamps: each into the branch's latest and into the folds
// it belongs to. The first stamp that does not parse is kept and returned after the
// read, so the walk below stays a walk.
type stampReader struct {
	all     stampFold
	devices map[string]*deviceFold
	err     error
}

// see folds one stamp. "" is a null, an unset relationship's edge, and is skipped.
func (r *stampReader) see(stamp string, into ...*stampFold) {
	if stamp == "" {
		return
	}
	at, err := parseStamp(stamp)
	if err != nil {
		if r.err == nil {
			r.err = err
		}
		return
	}
	r.all.take(stamp, at)
	for _, f := range into {
		f.take(stamp, at)
	}
}

// device folds one device node. Each generated getter returns a value, so each is held
// in a variable before its own getters are called, as project.go does.
func (r *stampReader) device(n stampDeviceNode) {
	nameAttr := n.GetName()
	name := nameAttr.GetValue()
	d, ok := r.devices[name]
	if !ok {
		d = &deviceFold{artifacts: map[string]*stampFold{}}
		r.devices[name] = d
	}
	role, site, platform := n.GetRole(), n.GetSite(), n.GetPlatform()
	platformEdge := platform.GetProperties()
	r.see(nameAttr.GetUpdated_at(), &d.intent)
	r.see(role.GetUpdated_at(), &d.intent)
	r.see(site.GetUpdated_at(), &d.intent)
	r.see(platformEdge.GetUpdated_at(), &d.intent)
	if p := platform.GetNode(); p != nil {
		d.platform = projectPlatform(p)
	}

	interfaces := n.GetInterfaces()
	for _, edge := range interfaces.GetEdges() {
		props := edge.GetProperties()
		r.see(props.GetUpdated_at(), &d.intent)
		in := edge.GetNode()
		if in == nil {
			continue
		}
		ifName, iftype, mgmtOnly, enabled := in.GetName(), in.GetIftype(), in.GetMgmt_only(), in.GetEnabled()
		link, parent := in.GetLink(), in.GetParent()
		linkEdge, parentEdge := link.GetProperties(), parent.GetProperties()
		for _, stamp := range []string{
			ifName.GetUpdated_at(), iftype.GetUpdated_at(), mgmtOnly.GetUpdated_at(), enabled.GetUpdated_at(),
			linkEdge.GetUpdated_at(), parentEdge.GetUpdated_at(),
		} {
			r.see(stamp, &d.intent)
		}
	}

	// The artifacts come through the fragment's own interface, never a concrete device
	// kind (Constitution III), as the read's do. A checksum's stamp is the branch's latest
	// and the artifact's, never the device's intent.
	target, ok := any(n).(ArtifactStamps)
	if !ok {
		return
	}
	artifacts := target.GetArtifacts()
	for _, edge := range artifacts.GetEdges() {
		a := edge.GetNode()
		artifactName, checksum := a.GetName(), a.GetChecksum()
		fold, ok := d.artifacts[artifactName.GetValue()]
		if !ok {
			fold = &stampFold{}
			d.artifacts[artifactName.GetValue()] = fold
		}
		r.see(checksum.GetUpdated_at(), fold)
	}
}

// link folds one link node's endpoint edges and returns their latest with the devices
// its endpoints name, which take it once every device is read.
func (r *stampReader) link(n stampLinkNode) (stampFold, []string) {
	var fold stampFold
	var devices []string
	endpoints := n.GetEndpoints()
	for _, edge := range endpoints.GetEdges() {
		props := edge.GetProperties()
		r.see(props.GetUpdated_at(), &fold)
		in := edge.GetNode()
		if in == nil {
			continue
		}
		device := in.GetDevice()
		if dn := device.GetNode(); dn != nil {
			dname := dn.GetName()
			devices = append(devices, dname.GetValue())
		}
	}
	return fold, devices
}

// parseStamp reads a stamp Infrahub returned: RFC 3339, six fractional digits as
// Infrahub writes them, the offset +00:00 or Z.
func parseStamp(s string) (time.Time, error) {
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		return time.Time{}, fmt.Errorf("the stamp %q Infrahub returned is not an RFC 3339 time", s)
	}
	return t, nil
}
