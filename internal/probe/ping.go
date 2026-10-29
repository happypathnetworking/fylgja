package probe

import (
	"bufio"
	"bytes"
	"fmt"
	"math"
	"regexp"
	"strconv"
)

// PingSummary is what one ping flow or burst measured: the echoes sent and answered, the
// difference, and the longest run of unanswered echoes in seconds.
type PingSummary struct {
	Sent        int
	Received    int
	Lost        int
	LongestGapS float64
}

var (
	// pingTotals is the summary's counters line: busybox writes "3 packets transmitted, 3
	// packets received, 0% packet loss", iputils "3 packets transmitted, 3 received, 0%
	// packet loss, time 2003ms" (research §1.2).
	pingTotals = regexp.MustCompile(`(\d+) packets transmitted, (\d+) (?:packets )?received`)
	// pingReply is one reply's sequence number: busybox's seq=, counted from 0, or iputils'
	// icmp_seq=, counted from 1.
	pingReply = regexp.MustCompile(`\b(icmp_)?seq=(\d+)`)
)

// ParsePing reads ping's output (R-14): Sent and Received from the summary's counters, Lost
// the difference, and LongestGapS the longest run of unanswered sequence numbers among
// those sent, from the start or to the end when the first or last were lost, times
// interval; 0 when nothing was lost. A duplicate reply counts once. Output with no summary
// is an error naming what was read, since a flow cut off before its counters measured
// nothing.
//
// Pure: it reads bytes a mechanism fetched and returns numbers.
func ParsePing(output []byte, interval float64) (PingSummary, error) {
	var s PingSummary
	var replies int
	answered := map[int]bool{}
	base := 0
	summarised := false
	sc := bufio.NewScanner(bytes.NewReader(output))
	for sc.Scan() {
		line := sc.Text()
		if m := pingTotals.FindStringSubmatch(line); m != nil {
			s.Sent, _ = strconv.Atoi(m[1])
			s.Received, _ = strconv.Atoi(m[2])
			summarised = true
			continue
		}
		if m := pingReply.FindStringSubmatch(line); m != nil {
			n, err := strconv.Atoi(m[2])
			if err != nil {
				continue
			}
			if m[1] != "" {
				base = 1
			}
			answered[n] = true
			replies++
		}
	}
	if !summarised {
		return PingSummary{}, fmt.Errorf("ping's output holds no summary (no \"packets transmitted\" line): read %d bytes, %d replies", len(output), replies)
	}
	s.Lost = max(s.Sent-s.Received, 0)
	if s.Lost == 0 {
		return s, nil
	}
	longest, run := 0, 0
	for seq := base; seq < base+s.Sent; seq++ {
		if answered[seq] {
			run = 0
			continue
		}
		run++
		longest = max(longest, run)
	}
	s.LongestGapS = math.Round(float64(longest)*interval*1000) / 1000
	return s, nil
}
