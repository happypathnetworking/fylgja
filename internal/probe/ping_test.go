package probe

import (
	"strconv"
	"strings"
	"testing"
)

// busybox's ping -c 3 -i 0.2, as research §1.2 recorded it.
const busyboxThree = `PING 127.0.0.1 (127.0.0.1): 56 data bytes
64 bytes from 127.0.0.1: seq=0 ttl=64 time=0.136 ms
64 bytes from 127.0.0.1: seq=1 ttl=64 time=0.087 ms
64 bytes from 127.0.0.1: seq=2 ttl=64 time=0.091 ms

--- 127.0.0.1 ping statistics ---
3 packets transmitted, 3 packets received, 0% packet loss
round-trip min/avg/max = 0.087/0.104/0.136 ms
`

// busybox's ping -i 0.2 sent SIGINT after 1.1 s: six replies and the same summary.
const busyboxInterrupted = `PING 10.1.11.2 (10.1.11.2): 56 data bytes
64 bytes from 10.1.11.2: seq=0 ttl=63 time=0.210 ms
64 bytes from 10.1.11.2: seq=1 ttl=63 time=0.118 ms
64 bytes from 10.1.11.2: seq=2 ttl=63 time=0.101 ms
64 bytes from 10.1.11.2: seq=3 ttl=63 time=0.122 ms
64 bytes from 10.1.11.2: seq=4 ttl=63 time=0.097 ms
64 bytes from 10.1.11.2: seq=5 ttl=63 time=0.103 ms

--- 10.1.11.2 ping statistics ---
6 packets transmitted, 6 packets received, 0% packet loss
round-trip min/avg/max = 0.097/0.125/0.210 ms
`

// busybox replies for the sequence numbers given, out of sent, with its summary.
func busybox(sent int, answered ...int) string {
	var b strings.Builder
	b.WriteString("PING 10.1.11.2 (10.1.11.2): 56 data bytes\n")
	for _, n := range answered {
		b.WriteString("64 bytes from 10.1.11.2: seq=")
		b.WriteString(strconv.Itoa(n))
		b.WriteString(" ttl=63 time=0.1 ms\n")
	}
	b.WriteString("\n--- 10.1.11.2 ping statistics ---\n")
	b.WriteString(strconv.Itoa(sent) + " packets transmitted, " + strconv.Itoa(len(answered)) + " packets received, x% packet loss\n")
	return b.String()
}

func TestParsePing(t *testing.T) {
	iputils := `PING 10.1.11.2 (10.1.11.2) 56(84) bytes of data.
64 bytes from 10.1.11.2: icmp_seq=1 ttl=63 time=0.211 ms
64 bytes from 10.1.11.2: icmp_seq=4 ttl=63 time=0.140 ms
64 bytes from 10.1.11.2: icmp_seq=5 ttl=63 time=0.121 ms

--- 10.1.11.2 ping statistics ---
5 packets transmitted, 3 received, 40% packet loss, time 812ms
rtt min/avg/max/mdev = 0.121/0.157/0.211/0.039 ms
`
	duplicate := `PING 10.1.11.2 (10.1.11.2): 56 data bytes
64 bytes from 10.1.11.2: seq=0 ttl=63 time=0.1 ms
64 bytes from 10.1.11.2: seq=0 ttl=63 time=0.2 ms (DUP!)
64 bytes from 10.1.11.2: seq=2 ttl=63 time=0.1 ms

--- 10.1.11.2 ping statistics ---
3 packets transmitted, 2 packets received, +1 duplicates, 33% packet loss
`
	for _, tc := range []struct {
		name   string
		output string
		want   PingSummary
	}{
		{"busybox, three of three", busyboxThree, PingSummary{Sent: 3, Received: 3}},
		{"busybox, six after SIGINT", busyboxInterrupted, PingSummary{Sent: 6, Received: 6}},
		{"iputils, a gap of two from 1", iputils, PingSummary{Sent: 5, Received: 3, Lost: 2, LongestGapS: 0.4}},
		{"a gap in the middle", busybox(10, 0, 1, 2, 6, 7, 8, 9), PingSummary{Sent: 10, Received: 7, Lost: 3, LongestGapS: 0.6}},
		{"the longest of two gaps", busybox(10, 0, 3, 4, 9), PingSummary{Sent: 10, Received: 4, Lost: 6, LongestGapS: 0.8}},
		{"a gap at the start", busybox(6, 4, 5), PingSummary{Sent: 6, Received: 2, Lost: 4, LongestGapS: 0.8}},
		{"a gap at the end", busybox(6, 0, 1, 2), PingSummary{Sent: 6, Received: 3, Lost: 3, LongestGapS: 0.6}},
		{"nothing lost", busybox(4, 0, 1, 2, 3), PingSummary{Sent: 4, Received: 4}},
		{"every packet lost", busybox(274), PingSummary{Sent: 274, Received: 0, Lost: 274, LongestGapS: 54.8}},
		{"a duplicate reply counts once", duplicate, PingSummary{Sent: 3, Received: 2, Lost: 1, LongestGapS: 0.2}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := ParsePing([]byte(tc.output), 0.2)
			if err != nil {
				t.Fatal(err)
			}
			if got != tc.want {
				t.Errorf("got %+v, want %+v", got, tc.want)
			}
		})
	}
}

// Output with no summary measured nothing: an error naming what was read.
func TestParsePingWithNoSummaryIsAnError(t *testing.T) {
	for _, tc := range []struct {
		name, output, says string
	}{
		{"empty", "", "read 0 bytes, 0 replies"},
		{"cut off before its counters", "PING 10.1.11.2 (10.1.11.2): 56 data bytes\n64 bytes from 10.1.11.2: seq=0 ttl=63 time=0.1 ms\n",
			"1 replies"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, err := ParsePing([]byte(tc.output), 0.2)
			if err == nil {
				t.Fatal("no error")
			}
			if !strings.Contains(err.Error(), "no summary") || !strings.Contains(err.Error(), tc.says) {
				t.Errorf("error %q, want it to say there is no summary and %q", err, tc.says)
			}
		})
	}
}
