#!/bin/bash
# Tier 3: nine cases in one run, making nine twins, through the workflow service and the
# operator's worker, leaving the host as it found it. Run by `make test-e2e` from the
# repository root. Never runs in CI and never gates a PR. No case makes a Schedule: a twin is
# frozen at its snapshot, and moves only when a step takes it (019).
#
# Every command reaches the core through its API (M13): the script starts a core server of
# its own from the tree, on a port of its own, with a token it makes for the run and with no
# INFRAHUB_* variable and no default scope in its environment, since the core reads no
# source of truth (020, D-065), and stops it in its trap. Every command that names a branch
# or a stage, or steps a twin to a stage, is the orchestrator's, fylgja-cli (020, FR-029): it
# runs its flow in its own process on Prefect's ephemeral server, its home under the run's
# outputs, with an orchestrator state root of the run's own, and the flow reads Infrahub
# through the adapter and calls the script's core server. The rest is fylgja's. Each fylgja
# command runs with PATH, HOME and the API's address and token, and nothing else of the
# script's environment; each fylgja-cli command with those, Infrahub's address and token,
# the default scope and its two roots, and nothing else, so no platform is named and none is
# reached. The script's own reads (gnmic, Docker, containerlab, twin.json, the store), the
# boot half and the fixture tool stay direct, with the full environment, and so does case
# 3's short-lived worker. Case 9's two rehearsals are no command of the script's: the check
# fylgja-twin asks them from inside Infrahub's task workers of the orchestrator's platform
# on the host's Docker bridge, whose runner's flow drives the operator's core server on
# loopback (015, 020).
#
# After every create and every step that changes a node: each device's first cabled
# interface reads, over the gNMI its own package declares, the description its staged
# artifact sets (bootstrap sets none), n1's ethernet-1/2 admin-state is what the artifact
# says, and twin.json's checksums are Infrahub's. Every node is ready inside its own
# package's readiness budget, which differs per platform, a probe's host inside its probe
# package's (016). Every artifact carries a marker in its header, where the template writes
# the device's description (017); it is found in no output, record, document, history or
# worker log. Every create files the snapshot it was sent under the core's snapshots/, names
# it in twin.json, and writes no CTM sidecar (018); the orchestrator filed the same snapshot
# under its own snapshots/ (020). No token or password is found there either, nor in the
# bundle store or either snapshot store, which hold the marker by design. After
# every destroy, no probe's host container (clab-fylgja-<probe>-a or -b) is left (016).
#
#   1. create from fylgja-fixture; the conformance suite's boot half reads that twin (M6:
#      host name, every cabled port enabled, discovering and seeing the far end the bundle's
#      link names, the version listed, readiness under budget); twin verify finds it
#      conforming (M12); twin show names the snapshot beside the bundle (018), the scope
#      tag:fylgja and the mapping that read it (017); a second create, refused naming that
#      twin; destroy
#   2. the branch read --at T, T fixed at the start, and the twin created from that snapshot
#      (fylgja-cli takes no --at on a create, 020): another reference, another bundle_id;
#      destroy
#   3. a one-node lab fylgja deployed by hand outside the state root: a short-lived worker
#      of the script's own names it an orphan at start, a dry-run create is refused naming
#      it, and destroy clears it
#   4. read --at T again and created from it: case 2's snapshot and bundle_id; destroy
#   5. a throwaway branch seeded; its dry run with the probe file n1-loop (016) lists the
#      probe's two hosts among the nodes; create from it with that file, under --scope
#      tag:fylgja named (017), its snapshot carrying the probe and the twin its two hosts;
#      the boot half reads its three devices, skips n1's two probe ports' neighbours on the
#      probe's synthesized links and names the two hosts it does not read (016), and twin
#      show names the snapshot it was built from; twin verify holds the probe's
#      burst; an artifact-only change (n1:ethernet-1/2 disabled, then generated) leaves the
#      twin frozen (019): over five minutes and a half no run starts, and twin.json, the
#      containers and twin show's kind line do not move; a step to a snapshot of the changed
#      branch with the probe, by file, and the node reads disable, and twin verify skips that
#      port and its link (M12), and the probe's two links at both ends, holds the burst and
#      names the snapshot; the branch's topology changed, its snapshot filed in the core's
#      store by a dry run of the step by file, and the step to it by id;
#      each step's document and twin.json carry the probe's loss, measured, on the
#      container's basis (016); twin show names it, stepped from the first; destroy; the
#      branch deleted
#   6. a throwaway branch seeded with the mixed fixture (M7): one twin of two platforms,
#      s1 on SR Linux and e1, e2 on EOS, each node read back over its own package's gNMI;
#      the boot half reads this twin too, and twin verify reads each node over its own
#      transport (M12); twin show names each node's package; destroy; the branch deleted
#   7. a throwaway branch seeded and a draft proposed change opened on it (014): stage
#      seeded marked, a third link added, stage third-link marked; stage plan names four
#      stages, the branch point refused scope.empty (main holds no tagged device), three
#      snapshot ids, three bundle ids and three steps, the last unchanged; stage list names
#      them; create --stage seeded deploys the snapshot and bundle the plan printed, the
#      orchestrator's record names the stage and twin.json 12 none (020), and stage list
#      marks it; a step with no target to third-link, the link re-cabled live, and a second
#      to the head, unchanged, the record moving and each step's sides naming the plan's
#      snapshots (018); destroy; the stages, the proposed change and the
#      branch deleted, after which stage list lists none and stage plan refuses the branch
#   8. a throwaway branch seeded with the mixed fixture and a draft proposed change opened on
#      it (M11, 014): stage seeded, a link s1:ethernet-1/3 <-> e1:Ethernet3 added, stage
#      mixed-link; the probe e1-loop written into FylgjaProbe on main, which every read from
#      then on carries with no file (016); create --stage seeded, pushed by replace, its
#      snapshot carrying the probe and the twin its two hosts; the step with no target to
#      mixed-link refused without --allow-restart, dry run and run, naming e1; taken with it:
#      e1 restarted in place, s1 re-cabled live and e2 untouched (their containers say so),
#      both pushed, the new link seen from both ends over gNMI, twin.json 12 naming the step
#      and its wait settled (M12) with the burst held, the orchestrator's record the stage,
#      and the step's document and twin.json naming the probe's loss across e1's restart,
#      more than none (016); the step back with
#      --stage seeded, settled too; destroy; the probe deleted from main, which then holds
#      none; the stages, the proposed change and the branch deleted
#   9. a throwaway branch seeded, the probe n1-loop written into FylgjaProbe on main, which
#      the checks read since they send no file (016), and a draft proposed change opened on
#      it (015): at the draft's creation the check fylgja-twin skipped it and fylgja-step
#      passed, and no comment was posted; stage seeded, a third link, stage third-link;
#      marked ready and the user checks run again: fylgja-twin rehearsed it on a twin and
#      passed, its message saying rehearsal ok and third-link's loss, one comment in a
#      thread of the proposed change, which its overview shows, holding the table with its
#      loss column, the drawing and the stages, the flow run it names completed on the
#      platform, its runs of the core's read from its log, and no twin left;
#      n1:ethernet-1/10, the probe's first port, disabled, generated, stage
#      probe-port-down, the checks run again: fylgja-twin failed, naming probe-port-down's
#      burst (verify.burst), the earlier stages passed with their loss figures, a second
#      comment in a second thread holding the fylgja-cli commands that reproduce it and the
#      head not reached; the branch deleted, and with its proposed change the threads, their
#      comments and the validators; the probe deleted from main. The stage probe-port-down took the place of 015's bad-port: a stage that
#      fails stops the run, so a push refused at a fourth stage would never be reached, and
#      one before it would leave probe-port-down unreached.
#
# Needs, all running from this directory: `make temporal-dev`, `make worker` (restarted
# after every rebuild, since case 1's refusal is worded by the worker and the steps of cases
# 5, 7 and 8 run on it), Docker, containerlab, the SR Linux image, the imported cEOS image
# (never pulled; docs/development.md says how to import it), the probe package's image
# (probes/ping.yaml's, alpine:3.24.2, which no command pulls: docker pull it), go (cases 1,
# 5 and 6 run the boot half as go test; cases 5 to 9 seed their branches with
# cmd/fylgja-fixture), the orchestrator's venv (make orchestrator-venv: fylgja-cli, which
# starts Prefect's ephemeral server under the run's outputs for each command, and the
# platform's client), and Infrahub with fylgja-fixture seeded and the kind FylgjaProbe on
# main holding no probe, since every read with no probe file carries what it holds (016)
# (local/.env, which must set FYLGJA_DEFAULT_SCOPE="tag:fylgja", the scope every case's
# fixtures are tagged into, for fylgja-cli to read under; 017).
# Every command reaches the script's own core server, whose port is one the system
# chooses. Case 9 needs more, checked before anything starts, none of which the script
# starts or stops: the checks fylgja-step and fylgja-twin on main, pushed to origin's main
# and imported (specs/015-proposed-change-rehearsal/quickstart.md §6), at a commit whose
# checks are this tree's; the orchestrator's platform on the Docker bridge
# (PREFECT_API_URL and PREFECT_API_AUTH_STRING in local/.env), answering from inside each of
# Infrahub's task workers its health and the deployment twin-rehearse/main to the
# credential the override gives them, and the core's port 7650 unreachable from there
# (020, FR-005); the runner, fylgja-orchestrator serve, from this tree's source under
# local/orchestrator/prefect and reading under the default scope tag:fylgja; and the
# operator's core server from this tree on 127.0.0.1:7650, local/.env's token, holding no
# Infrahub variable, which the runner's flows drive (scripts/bring-up.sh starts all three).
# Optional: WORKER_LOG names that worker's log, which the credential greps then cover too.
# Optional: PLATFORMS narrows the run to a list of shipped packages (the stems of psp/*.yaml,
# separated by commas or spaces): a case runs when every package it needs is in the list and
# each account-gated image it needs is present, and is skipped, saying why, otherwise. Unset
# or empty, every case runs and every package's image is required first. A name no package
# has, or a list that selects no case, is refused before anything starts.
# It took about 36 to 37 minutes before 020, case 5's frozen wait among them: 2,236.6s at
# 016's first whole run, and 2,171.8s once case 5 ran the boot half too, which adds about 10s
# (10.0s, and 12.4s by hand; both 2026-10-29); each fylgja-cli command adds its ephemeral
# server's start, about 17s warm and 40s the first (020's research §5.19), so expect several
# minutes more until T043 measures it; run it on a quiet host (docs/development.md).
#
# Exit 0 prints E2E-OK when every case ran, or, when PLATFORMS skipped one, E2E-PARTIAL naming
# the list, the cases that ran and each case skipped with its reason. Any failed check exits 1
# after the trap's destroy, which cancels a step in flight and waits for its record (a
# rehearsal in flight is the platform's, which the check cancels at its own deadline),
# and its deletion of the throwaway branches of cases 5 to 9 (7's, 8's and 9's with their
# stages and proposed changes, 9's threads and validators going with its proposed change),
# and of the probes cases 8 and 9 wrote on main; a lab, a twin directory, a probe's host
# container or Schedule fylgja-follow left behind after that destroy exits 99.
# This build makes no such Schedule; the check catches one kept by a host upgraded with a
# following twin up (019).
set -euo pipefail

fail() {
  echo "e2e: FAILED: $*" >&2
  exit 1
}

# The packages each case needs, read by case_runs and the list's refusals alone: every
# case boots SR Linux, and 6 and 8 boot EOS beside it.
declare -A CASE_PACKAGES=([1]=nokia_srlinux [2]=nokia_srlinux [3]=nokia_srlinux [4]=nokia_srlinux
  [5]=nokia_srlinux [6]="nokia_srlinux arista_eos" [7]=nokia_srlinux [8]="nokia_srlinux arista_eos"
  [9]=nokia_srlinux)
mapfile -t KNOWN_PACKAGES < <(for f in psp/*.yaml; do basename "$f" .yaml; done | LC_ALL=C sort)
# PLATFORMS, split; empty for a default run. Checked here, before local/.env is read and
# before anything starts, so a refused list leaves nothing behind.
PLATFORMS=${PLATFORMS:-}
read -ra PLATFORM_LIST <<< "${PLATFORMS//,/ }"
RAN=() SKIPPED=()
if [ "${#PLATFORM_LIST[@]}" -gt 0 ]; then
  for name in "${PLATFORM_LIST[@]}"; do
    [[ " ${KNOWN_PACKAGES[*]} " == *" $name "* ]] ||
      fail "PLATFORMS names $name, which no shipped package has; known: ${KNOWN_PACKAGES[*]}"
  done
  selected=0 common=" ${KNOWN_PACKAGES[*]} "
  for n in "${!CASE_PACKAGES[@]}"; do
    missing=0
    for pkg in ${CASE_PACKAGES[$n]}; do
      [[ " ${PLATFORM_LIST[*]} " == *" $pkg "* ]] || missing=1
    done
    [ "$missing" -eq 1 ] || selected=1
    # The packages every case needs: what a list must name to select any.
    for pkg in $common; do
      [[ " ${CASE_PACKAGES[$n]} " == *" $pkg "* ]] || common=${common/ $pkg / }
    done
  done
  common=${common% }
  [ "$selected" -eq 1 ] || fail "PLATFORMS=$PLATFORMS selects no case: every case needs$common"
fi

FYLGJA_STATE_ROOT="$(pwd)/local"
export FYLGJA_STATE_ROOT
# Each image's published default login. The worker holds its own
# copy; the script's server needs these for the dry run's presence check, which it makes in
# its own process (D-041), and the greps below need the value. No client reads them. The
# two platforms name different variables, so one environment carries both.
export FYLGJA_SRLINUX_USERNAME=admin FYLGJA_SRLINUX_PASSWORD='NokiaSrl1!'
export FYLGJA_EOS_USERNAME=admin FYLGJA_EOS_PASSWORD=admin
set -a
# shellcheck disable=SC1091
. local/.env
set +a
: "${INFRAHUB_ADDRESS:?local/.env must set INFRAHUB_ADDRESS}"
: "${INFRAHUB_API_TOKEN:?local/.env must set INFRAHUB_API_TOKEN}"
# The scope every fylgja-cli command reads under but case 5's create, which names it: the
# fixtures' devices are tagged into it (017), and the orchestrator reads the default, never
# the core (020).
[ "${FYLGJA_DEFAULT_SCOPE:-}" = tag:fylgja ] ||
  fail "local/.env must set FYLGJA_DEFAULT_SCOPE=\"tag:fylgja\", the scope fylgja-cli reads every case's fixtures under"

FYLGJA=./bin/fylgja
# The orchestrator's client (020), from this tree's venv, which installs the orchestrator
# editable, so it runs this tree's source.
FYLGJA_CLI=./orchestrator/.venv/bin/fylgja-cli
BRANCH=fylgja-fixture
export BRANCH
TWIN="$FYLGJA_STATE_ROOT/twin"
TEMPORAL_ADDRESS="${FYLGJA_TEMPORAL_ADDRESS:-localhost:7233}"
OUT=$(mktemp -d "${TMPDIR:-/tmp}/fylgja-e2e.XXXXXX")
# Resolved, so the orphan's topology path compares with containerlab's absLabPath.
OUT=$(realpath "$OUT")
echo "e2e: outputs in $OUT"
# fylgja-cli's two roots, the run's own (R-16): the orchestrator's state root, its snapshots/
# and its record, twin.json, and the home of Prefect's ephemeral server, which each command
# starts for its flow, since no PREFECT_API_URL reaches it. Both are under $OUT, so the greps
# cover them.
ORCH_ROOT="$OUT/orchestrator"
ORCH_RECORD="$ORCH_ROOT/twin.json"
E2E_PREFECT_HOME="$OUT/prefect"
mkdir -p "$ORCH_ROOT" "$E2E_PREFECT_HOME"

# The API's token for this run alone: made here, given to the script's server
# and to each command, never printed, and searched for in everything the run produced. A
# token in local/.env is not used. 24 bytes are 32 characters of base64, no padding.
API_TOKEN=$(head -c 24 /dev/urandom | base64)
[ -n "$API_TOKEN" ] || { echo "e2e: FAILED: no API token could be made from /dev/urandom" >&2; exit 1; }
# The server's address, read from the listen line of its start-up report;
# the bound only stops a server that never reports from holding the run.
API_ADDRESS=""
SERVER_LISTEN_WAIT_S=15

# Case 5's frozen wait (019): counted from the moment its branch's change is visible to a
# read, five minutes and a half, longer than the 5-minute default interval of the check a
# following build ran.
FROZEN_WAIT_S=330
# The Schedule a following build made and this build never makes, read by the trap's leak
# check alone.
FOLLOW_SCHEDULE=fylgja-follow

# The probe package every probe of this tier is built with (016), read for its image, its
# readiness budget and its burst's count rather than repeating them. HOSTS is the probe hosts
# a case's twin carries beside its three devices, two per probe: set before a probed create,
# 0 again after its destroy.
PROBE_PACKAGE=probes/ping.yaml
HOSTS=0
export HOSTS

# The short-lived worker's host line is on stdout about 0.22s after exec;
# the bound only stops a worker that never reports from holding the run.
WORKER_HOST_LINE_WAIT_S=15

# expect FILE FILTER: the document satisfies the jq filter, or the run stops and shows it.
expect() {
  if ! jq -e "$2" "$1" > /dev/null; then
    echo "e2e: FAILED: $1 does not satisfy: $2" >&2
    cat "$1" >&2
    exit 1
  fi
}

# now_ns and since START_NS: wall time in seconds, to a tenth.
now_ns() { date +%s%N; }
since() {
  local ns=$(( $(now_ns) - $1 ))
  printf '%d.%d' $(( ns / 1000000000 )) $(( ns / 100000000 % 10 ))
}

# no_credential NAME VALUE PATH...: VALUE appears in no file under the paths. Names the
# files, never the matching line, so a leak is not printed while being reported.
no_credential() {
  local name=$1 value=$2
  shift 2
  if grep -rqsF -- "$value" "$@"; then
    echo "e2e: LEAK: $name found in:" >&2
    grep -rlsF -- "$value" "$@" >&2 || true
    exit 1
  fi
}

# no_credential_contextual NAME VALUE PATH...: VALUE in a shape that would be a leak,
# rather than the value alone. The cEOS image's published default login is `admin`, a word
# far too common to search for on its own; what would leak it is a command line or a
# payload carrying it as a password. Names the files, never the line.
no_credential_contextual() {
  local name=$1 value=$2
  shift 2
  local pattern="(-p $value|$value:$value|password=$value|\"password\": ?\"$value\")([^[:alnum:]_]|\$)"
  if grep -rqsE -- "$pattern" "$@"; then
    echo "e2e: LEAK: $name found in:" >&2
    grep -rlsE -- "$pattern" "$@" >&2 || true
    exit 1
  fi
}

# no_infrahub_request NAME LOG [FROM]: the core's request log, from byte FROM (0 when not
# given), names none of the five operations that read Infrahub, which are the
# orchestrator's (020, FR-029): a line a request, `msg=request operation=<op> outcome=…`.
INFRAHUB_OPERATIONS='intent\.read|stage\.list|stage\.plan|twin\.rehearse|schema\.check'
no_infrahub_request() {
  local found
  found=$(tail -c "+$(( ${3:-0} + 1 ))" "$2" | grep -oE "msg=request operation=($INFRAHUB_OPERATIONS) " |
    sed 's/^msg=request operation=//; s/ $//' | LC_ALL=C sort | uniq -c | awk '{print $2 " " $1 "x"}' | paste -sd ',' - || true)
  [ -z "$found" ] || fail "$1 was asked operations that read Infrahub, which the core no longer serves (020): $found; see $2"
}

# psp_scalar FILE KEY: the value of the one `  key: value` line in a support package, less
# its trailing comment. The keys read here — `ref` under image, `timeout_s` under
# readiness — each appear once at that indent, and the script reads them from the package
# rather than repeating them, so a package that moves moves this tier with it.
psp_scalar() {
  sed -n "s/^  $2: *\([^ #]*\).*/\1/p" "$1" | head -1
}

# probe_containers: every container Docker holds, running or not, named as a probe's host is,
# clab-fylgja-<probe>-a or -b, one per line (016). No device of the fixtures is so named.
# Docker is asked rather than containerlab, so a host containerlab no longer reports is
# found too; a docker that does not answer fails the call.
probe_containers() {
  local names
  names=$(docker ps -a --format '{{.Names}}') || return 1
  grep -E '^clab-fylgja-.+-[ab]$' <<< "$names" || true
}

# no_probe_containers CASE: no probe's host container is left after a destroy.
no_probe_containers() {
  local left
  left=$(probe_containers) || fail "case $1: docker ps failed while looking for a probe's host container"
  [ -z "$left" ] || fail "case $1: a probe's host container is left after the destroy: $(paste -sd ' ' - <<< "$left")"
}

# write_probes CASE FILE NAME: FILE's one probe, NAME, written into FylgjaProbe on main
# through the fixture tool (016, R-26), which every read with no probe file then carries;
# PROBES_ON_MAIN is set first, so the trap deletes it should the run stop before the case
# does.
write_probes() {
  PROBES_ON_MAIN=1
  fixture -probes "$2" > "$OUT/probes-$1.out" 2> "$OUT/probes-$1.err" ||
    fail "case $1: -probes $2 failed; see $OUT/probes-$1.err"
  grep -qxF "wrote 1 probe to FylgjaProbe on main: $3" "$OUT/probes-$1.out" ||
    fail "case $1: -probes $2 did not report writing $3; see $OUT/probes-$1.out"
}

# delete_probes CASE: every probe on main deleted, one, after which FylgjaProbe counts 0.
delete_probes() {
  fixture -delete-probes > "$OUT/delete-probes-$1.out" 2> "$OUT/delete-probes-$1.err" ||
    fail "case $1: -delete-probes failed, leaving a probe on main; see $OUT/delete-probes-$1.err"
  grep -qxF "deleted 1 probe of FylgjaProbe on main" "$OUT/delete-probes-$1.out" ||
    fail "case $1: -delete-probes did not report deleting the one probe; see $OUT/delete-probes-$1.out"
  gql "" '{ FylgjaProbe { count } }' > "$OUT/probes-after-$1.json" 2> "$OUT/probes-after-$1.err" ||
    fail "case $1: reading FylgjaProbe on main failed; see $OUT/probes-after-$1.err"
  expect "$OUT/probes-after-$1.json" '.FylgjaProbe.count == 0'
  unset PROBES_ON_MAIN
}

# case_runs N: whether case N runs, recording it in RAN when it does. A default run runs
# every case. With PLATFORMS, a case runs when every package it needs is in the list and
# each such package whose image is account_gated has that image present; otherwise
# SKIP_REASON names the first package that stops it, and how.
case_runs() {
  local pkg why ref
  SKIP_REASON=""
  if [ "${#PLATFORM_LIST[@]}" -gt 0 ]; then
    for pkg in ${CASE_PACKAGES[$1]}; do
      why=""
      [[ " ${PLATFORM_LIST[*]} " == *" $pkg "* ]] || why="not in PLATFORMS"
      if [ "$(psp_scalar "psp/$pkg.yaml" acquisition)" = account_gated ]; then
        ref=$(psp_scalar "psp/$pkg.yaml" ref)
        docker image inspect "$ref" > /dev/null 2>&1 || why="${why:+$why; }image $ref absent"
      fi
      if [ -n "$why" ]; then
        SKIP_REASON="needs $pkg: $why"
        return 1
      fi
    done
  fi
  RAN+=("$1")
}

# skip_case N: case N is skipped, said where it would start and recorded for the run's end.
skip_case() {
  echo "e2e: case $1: skipped ($SKIP_REASON)"
  SKIPPED+=("$1 ($SKIP_REASON)")
}

# ran N: case N ran.
ran() {
  [[ " ${RAN[*]} " == *" $1 "* ]]
}

# fylgja ARGS...: a client's command, through the script's server (contracts/cli.md
# "Tier 3"): run with PATH, HOME, FYLGJA_API_ADDRESS and FYLGJA_API_TOKEN, and nothing else of
# the script's environment, so a command that still read Infrahub's variables, a login or the
# state root fails here rather than passing on the script's copy. It is env -i's environment
# without env -i's arguments, which would carry the token for an instant: the subshell
# unexports every variable (PATH named too, so the list is never empty) and exports the four,
# so the token is in no process's arguments, as gql keeps Infrahub's out of curl's.
fylgja() {
  (
    # shellcheck disable=SC2046
    export -n PATH $(compgen -e)
    # shellcheck disable=SC2030 # the command's token, for this subshell alone
    export PATH HOME FYLGJA_API_ADDRESS="$API_ADDRESS" FYLGJA_API_TOKEN="$API_TOKEN"
    exec "$FYLGJA" "$@"
  )
}

# fylgja_cli ARGS...: the orchestrator's command (020, R-16), as fylgja runs the core's: with
# PATH, HOME, the API's address and token, which its flows call the script's core server
# with, and Infrahub's address and token and the default scope, which its adapter reads
# Infrahub with, for it alone; and its two roots, the run's own. Nothing else of the
# script's environment: no PREFECT_API_URL, which local/.env carries for the operator's
# platform, so the flow runs on Prefect's ephemeral server under E2E_PREFECT_HOME, and no
# login, the core's. The tokens are in no process's arguments, as fylgja keeps the API's.
fylgja_cli() {
  (
    # shellcheck disable=SC2046
    export -n PATH $(compgen -e)
    # shellcheck disable=SC2030,SC2031 # the command's tokens, for this subshell alone
    export PATH HOME FYLGJA_API_ADDRESS="$API_ADDRESS" FYLGJA_API_TOKEN="$API_TOKEN" \
      INFRAHUB_ADDRESS INFRAHUB_API_TOKEN FYLGJA_DEFAULT_SCOPE \
      FYLGJA_ORCHESTRATOR_ROOT="$ORCH_ROOT" PREFECT_HOME="$E2E_PREFECT_HOME"
    exec "$FYLGJA_CLI" "$@"
  )
}

# stop_server: SIGTERM to the script's server, its exit status in SERVER_STATUS. It closes
# every connection and exits 0. Does nothing once it is stopped.
stop_server() {
  [ -n "${SERVER_PID:-}" ] || return 0
  kill -TERM "$SERVER_PID" 2> /dev/null || true
  SERVER_STATUS=0
  wait "$SERVER_PID" 2> /dev/null || SERVER_STATUS=$?
  unset SERVER_PID
}

# fixture ARGS...: the development tool that writes to Infrahub, with local/.env's credentials.
fixture() {
  go run -tags fixture ./cmd/fylgja-fixture "$@"
}

# gql BRANCH QUERY: Infrahub's GraphQL answer's data on the branch, or on the default branch
# through the unnamed endpoint when BRANCH is "", as the adapter asks it. The token goes
# to curl as a header file, so it is in no process's arguments.
gql() {
  local body
  body=$(jq -cn --arg q "$2" '{query: $q}')
  curl -sS --fail-with-body -H @<(printf 'X-INFRAHUB-KEY: %s\n' "$INFRAHUB_API_TOKEN") \
    -H 'Content-Type: application/json' -d "$body" "$INFRAHUB_ADDRESS/graphql${1:+/$1}" | jq -e '.data'
}

# platform_get PATH and platform_post PATH BODY: the orchestrator's platform's answer at PATH
# under local/.env's PREFECT_API_URL, read by case 9 alone (020). The basic-auth string goes
# to curl as a header file, base64 reading it on its input, so it is in no process's
# arguments, as gql keeps Infrahub's token out of them.
platform_get() {
  curl -sS --fail-with-body --max-time 30 \
    -H @<(printf 'Authorization: Basic %s\n' "$(printf %s "$PREFECT_API_AUTH_STRING" | base64 -w0)") \
    "${PREFECT_API_URL%/}$1"
}
platform_post() {
  curl -sS --fail-with-body --max-time 30 \
    -H @<(printf 'Authorization: Basic %s\n' "$(printf %s "$PREFECT_API_AUTH_STRING" | base64 -w0)") \
    -H 'Content-Type: application/json' -d "$2" "${PREFECT_API_URL%/}$1"
}

# infrahub_holds_none CASE BRANCH: a deleted throwaway branch left nothing in Infrahub
# (FR-029): read on the default branch, writing nothing, the branch is absent from Branch,
# and no proposed change in any state has it as its source. Infrahub refuses a proposed
# change's delete while a stage names it, so with none left no stage of one is left either.
infrahub_holds_none() {
  gql "" "{ Branch(name: \"$2\") { name } CoreProposedChange(source_branch__value: \"$2\") { count } }" \
    > "$OUT/infrahub-after-$1.json" 2> "$OUT/infrahub-after-$1.err" ||
    fail "case $1: reading Infrahub after $2's delete failed; see $OUT/infrahub-after-$1.err"
  expect "$OUT/infrahub-after-$1.json" '(.Branch | length) == 0 and .CoreProposedChange.count == 0'
}

# artifacts_of BRANCH FILE: each device's device-config artifact on the branch, read from
# the schema library's DcimDevice as the read does, as {device: {status, checksum}}. Only
# the identity is asked for: the content carries the marker.
artifacts_of() {
  gql "$1" '{ DcimDevice { edges { node { name { value }
    ... on CoreArtifactTarget { artifacts { edges { node { status { value } checksum { value }
      definition { node { ... on CoreArtifactDefinition { artifact_name { value } } } } } } } } } } } }' |
    jq '[.DcimDevice.edges[].node | {key: .name.value, value: ([.artifacts.edges[].node
      | select(.definition.node.artifact_name.value=="device-config")
      | {status: .status.value, checksum: .checksum.value}] | first)}] | from_entries' > "$2"
}

# await_checksums_moved CASE BRANCH BEFORE_FILE DEVICE...: a generate call returns before
# a changed artifact is rewritten, and an existing artifact stays Ready throughout,
# so the wait is for each named device's checksum to differ from BEFORE's
# with every artifact Ready.
#
# 240s bounds it. M5 set 90s from a regeneration's 7.6s on an idle host; this wait is the one the
# script makes with a twin running, and on a host carrying one it was exceeded while the
# rendering itself was correct — measured at 13s idle on the same branch shape, against a
# create of the same bundle that took 129s one time and 557s another. The bound is
# patience for the host, not a claim about Infrahub: what is
# asserted is still that the checksum moves and every artifact is Ready.
await_checksums_moved() {
  local case=$1 branch=$2 before=$3 start
  shift 3
  start=$(now_ns)
  while :; do
    artifacts_of "$branch" "$OUT/artifacts-$case.json" 2> "$OUT/artifacts-$case.err" &&
      jq -e --slurpfile b "$before" --args 'all(.[]; .status=="Ready")
        and (. as $now | all($ARGS.positional[]; $now[.].checksum != $b[0][.].checksum))' "$@" < "$OUT/artifacts-$case.json" > /dev/null &&
      break
    [ "$(( ($(now_ns) - start) / 1000000000 ))" -lt 240 ] ||
      fail "case $case: the artifacts of $* on $branch did not move within 240s of the generate; see $OUT/artifacts-$case.json"
    sleep 0.5
  done
  echo "e2e: case $case: the artifacts of $* on $branch moved, Ready, $(since "$start")s after the generate returned"
}

# gnmi_get CASE TARGET TRANSPORT USER PASS PATH: the one value a gNMI Get of PATH returns
# from TARGET (host:port), over the transport flag, login and port the node's own support
# package declares. The encoding is stated and never defaulted: a default-encoding Get is
# answered Unimplemented by SR Linux (CLAUDE.md).
gnmi_get() {
  local out
  out="$OUT/gnmi-$1-${2//[:.]/_}-$(tr -c 'a-z0-9' _ <<< "$6").json"
  gnmic -a "$2" -u "$4" -p "$5" "$3" -e json_ietf \
    get --path "$6" > "$out" 2> "$out.err" || fail "case $1: gnmic get $6 from $2 failed; see $out.err"
  jq -er '[.. | objects | select(has("values")) | .values[]] | first' "$out" ||
    fail "case $1: gnmic get $6 from $2 returned no value; see $out"
}

# gnmi_value CASE ADDR PATH: from an SR Linux node — TLS on 57400, accepted unverified as
# the readiness probe accepts it (M5).
gnmi_value() {
  gnmi_get "$1" "$2:57400" --skip-verify "$FYLGJA_SRLINUX_USERNAME" "$FYLGJA_SRLINUX_PASSWORD" "$3"
}

# gnmi_value_eos CASE ADDR PATH: from an EOS node — plaintext on 6030, since that
# transport has no SSL profile and a TLS dial is refused at the handshake.
gnmi_value_eos() {
  gnmi_get "$1" "$2:6030" --insecure "$FYLGJA_EOS_USERNAME" "$FYLGJA_EOS_PASSWORD" "$3"
}

# eos_first_description FILE: the first interface an EOS artifact gives a description, and
# that description, as "<node name> <text>". The rendering writes `interface <name>` then
# `description <text>` for each cabled port.
eos_first_description() {
  awk '/^ *interface /{ n = $2; next }
       /^ *description /{ sub(/^ *description +/, ""); print n, $0; exit }' "$1"
}

# readback CASE BRANCH N1_E12_STATE [HELD]: the running twin runs its artifacts. For each
# device in twin.json: the ethernet-1/1 description over gNMI is the
# staged artifact's, and its recorded checksum is Infrahub's on the branch; n1's
# ethernet-1/2 admin-state reads N1_E12_STATE. A probe's host (016) has no artifact and no
# gNMI, so it is none of these. The staged artifact is read in place and its line never
# copied into $OUT, where the marker grep looks.
#
# Infrahub's checksums are read now, or taken from HELD, an artifacts_of file read when the
# twin's pinned reference was marked. Case 7's first stage needs it: the branch has moved on
# since, and the twin runs what Infrahub held then.
readback() {
  local case=$1 branch=$2 want_state=$3 held=${4:-} name addr file want got
  if [ -z "$held" ]; then
    held="$OUT/artifacts-readback-$case.json"
    artifacts_of "$branch" "$held" 2> "$OUT/artifacts-readback-$case.err" ||
      fail "case $case: reading the artifacts of $branch from Infrahub failed; see $OUT/artifacts-readback-$case.err"
  fi
  jq -e --slurpfile tw "$TWIN/twin.json" '. as $inf | [$tw[0].nodes[] | select(.probe == null)]
    | length == 3 and all(.[]; .artifact.checksum == $inf[.name].checksum and $inf[.name].status == "Ready")' \
    "$held" > /dev/null ||
    fail "case $case: twin.json's checksums are not Infrahub's on $branch; compare $TWIN/twin.json with $held"
  while read -r name addr file; do
    want=$(sed -n 's|^set / interface ethernet-1/1 description "\(.*\)"$|\1|p' "$TWIN/bundle/$file")
    [ -n "$want" ] || fail "case $case: $TWIN/bundle/$file sets no description on ethernet-1/1"
    got=$(gnmi_value "$case" "$addr" '/interface[name=ethernet-1/1]/description')
    [ "$got" = "$want" ] || fail "case $case: node $name's ethernet-1/1 description reads \"$got\", its artifact sets \"$want\""
  done < <(jq -r --slurpfile m "$TWIN/bundle/manifest.json" \
    '.nodes[] | select(.probe == null) as $n | "\($n.name) \($n.mgmt_ipv4) \($m[0].nodes[] | select(.name==$n.name) | .artifact.file)"' "$TWIN/twin.json")
  addr=$(jq -r '.nodes[] | select(.name=="n1") | .mgmt_ipv4' "$TWIN/twin.json")
  got=$(gnmi_value "$case" "$addr" '/interface[name=ethernet-1/2]/admin-state')
  [ "$got" = "$want_state" ] || fail "case $case: n1's ethernet-1/2 admin-state reads $got, not $want_state"
  echo "e2e: case $case: every node runs its artifact; n1 ethernet-1/2 $got; checksums are Infrahub's"
}

# readback_mixed CASE BRANCH [HELD]: the mixed twin runs its artifacts, each device read over
# the transport its own support package declares, and a probe's host, as readback says,
# none. twin.json's checksums are Infrahub's on the branch, as readback checks; then, per
# device, by the package twin.json records: an SR Linux node as readback reads it, and an
# EOS node by its host name and by the description its artifact sets on the first interface
# the rendering describes. The staged artifact is read in place and its lines are never
# copied into $OUT, where the marker grep looks.
#
# Infrahub's checksums are read now, or taken from HELD, as readback takes them: case 8's
# twin at its first stage runs what Infrahub held when that stage was marked (M11, 014).
readback_mixed() {
  local case=$1 branch=$2 held=${3:-} name addr pspid file want got port
  if [ -z "$held" ]; then
    held="$OUT/artifacts-readback-$case.json"
    artifacts_of "$branch" "$held" 2> "$OUT/artifacts-readback-$case.err" ||
      fail "case $case: reading the artifacts of $branch from Infrahub failed; see $OUT/artifacts-readback-$case.err"
  fi
  jq -e --slurpfile tw "$TWIN/twin.json" '. as $inf | [$tw[0].nodes[] | select(.probe == null)]
    | length == 3 and all(.[]; .artifact.checksum == $inf[.name].checksum and $inf[.name].status == "Ready")' \
    "$held" > /dev/null ||
    fail "case $case: twin.json's checksums are not Infrahub's on $branch; compare $TWIN/twin.json with $held"
  while read -r name addr pspid file; do
    case "$pspid" in
      nokia_srlinux)
        want=$(sed -n 's|^set / interface ethernet-1/1 description "\(.*\)"$|\1|p' "$TWIN/bundle/$file")
        [ -n "$want" ] || fail "case $case: $TWIN/bundle/$file sets no description on ethernet-1/1"
        got=$(gnmi_value "$case" "$addr" '/interface[name=ethernet-1/1]/description')
        [ "$got" = "$want" ] ||
          fail "case $case: node $name's ethernet-1/1 description reads \"$got\", its artifact sets \"$want\""
        ;;
      arista_eos)
        port="" want=""
        read -r port want < <(eos_first_description "$TWIN/bundle/$file") || true
        { [ -n "$port" ] && [ -n "$want" ]; } ||
          fail "case $case: $TWIN/bundle/$file describes no interface"
        got=$(gnmi_value_eos "$case" "$addr" "/interfaces/interface[name=$port]/state/description")
        [ "$got" = "$want" ] ||
          fail "case $case: node $name's $port description reads \"$got\", its artifact sets \"$want\""
        got=$(gnmi_value_eos "$case" "$addr" /system/state/hostname)
        [ "$got" = "$name" ] || fail "case $case: node $name reports host name \"$got\", not its own"
        ;;
      *)
        fail "case $case: node $name runs support package $pspid, which this read-back does not know how to read"
        ;;
    esac
    echo "e2e: case $case: $name ($pspid) runs its artifact"
  done < <(jq -r --slurpfile m "$TWIN/bundle/manifest.json" \
    '.nodes[] | select(.probe == null) as $n | "\($n.name) \($n.mgmt_ipv4) \($n.psp.id) \($m[0].nodes[] | select(.name==$n.name) | .artifact.file)"' "$TWIN/twin.json")
  echo "e2e: case $case: every node runs its artifact, each read over its own platform; checksums are Infrahub's"
}

# verify_twin CASE [WAIT]: twin verify on the running twin, with --wait=WAIT when given: exit
# 0, status ok and zero findings, every non-skipped assertion held. The
# document is kept in $OUT, so the greps below cover it. Held counts the four kinds read
# from the twin, a probe's burst among them (016); the record's claims are counted apart,
# since they are the record's and never read. Sets VERIFY_TOOK.
verify_twin() {
  local case=$1 wait=${2:-} start status=0 args=() held skipped bursts
  [ -z "$wait" ] || args=(--wait="$wait")
  start=$(now_ns)
  fylgja twin verify "${args[@]}" --json > "$OUT/verify-$case.json" 2> "$OUT/verify-$case.err" || status=$?
  VERIFY_TOOK=$(since "$start")
  [ "$status" -eq 0 ] || fail "case $case: twin verify exited $status; see $OUT/verify-$case.json and $OUT/verify-$case.err"
  expect "$OUT/verify-$case.json" '.status=="ok" and .operation=="twin.verify" and .findings==[]'
  held=$(jq '.verify.counts | .host_name.held + .port_enabled.held + .neighbor.held + .burst.held' "$OUT/verify-$case.json")
  bursts=$(jq '.verify.counts.burst.held' "$OUT/verify-$case.json")
  skipped=$(jq '.verify.counts | (.port_enabled.skipped // 0) + (.neighbor.skipped // 0)' "$OUT/verify-$case.json")
  echo "e2e: case $case: twin verify ${VERIFY_TOOK}s, $held held ($bursts bursts), $skipped skipped"
}

# step_loss_measured CASE PROBE [FILTER]: the step just taken measured PROBE's flow across it,
# the one probe both its bundles carry (016): its document's step.loss and twin.json's, alike,
# on the container's basis, one entry, measured, more than none sent, from the probe's first
# host's container to its second's, and nothing added or dropped; FILTER, a jq condition on
# the entry, holds too. Sets LOSS_FIGURE, which is recorded, not asserted.
step_loss_measured() {
  export LOSS_PROBE=$2
  local filter='.step.loss.basis == "container" and .step.loss.added == [] and .step.loss.dropped == []
    and (.step.loss.probes | length) == 1
    and (.step.loss.probes[0] | .probe == env.LOSS_PROBE and .outcome == "measured" and .sent > 0
      and .from == "clab-fylgja-" + env.LOSS_PROBE + "-a" and .to == "clab-fylgja-" + env.LOSS_PROBE + "-b"'
  filter+=" and (${3:-true}))"
  expect "$OUT/step-$1.json" "$filter"
  expect "$TWIN/twin.json" "$filter"
  [ "$(jq -S .step.loss "$OUT/step-$1.json")" = "$(jq -S .step.loss "$TWIN/twin.json")" ] ||
    fail "case $1: the step's document and twin.json name different losses; compare their step.loss in $OUT/step-$1.json and $TWIN/twin.json"
  LOSS_FIGURE=$(jq -r '.step.loss.probes[0] | "\(.lost)/\(.sent) lost, longest gap \(.longest_gap_s)s"' "$TWIN/twin.json")
  echo "e2e: case $1: $2 $LOSS_FIGURE across the step (container timing)"
}

# schedule_state: present or absent as the workflow service answers for Schedule
# fylgja-follow, or unknown when it gave no answer. describe exits 1 on an absent Schedule
# and says "not found". Read by the trap's leak check alone (019).
schedule_state() {
  if temporal schedule describe --address "$TEMPORAL_ADDRESS" --schedule-id "$FOLLOW_SCHEDULE" > /dev/null 2> "$OUT/schedule-describe.err"; then
    echo present
  elif grep -qi 'not found' "$OUT/schedule-describe.err"; then
    echo absent
  else
    echo unknown
  fi
}

# history_of NAME WORKFLOW_ID RUN_ID: the run's history as the service holds it, and its
# payloads decoded beside it, so the credential greps read what a payload carries rather
# than its base64.
history_of() {
  temporal workflow show --address "$TEMPORAL_ADDRESS" -w "$2" -r "$3" -o json > "$OUT/history-$1.json" 2> "$OUT/history-$1.err" ||
    fail "temporal workflow show $2 $3 failed; see $OUT/history-$1.err"
  jq -r '.. | objects | .data? | strings | try @base64d catch empty' "$OUT/history-$1.json" > "$OUT/history-$1.decoded"
}

store_digest() {
  find "$FYLGJA_STATE_ROOT/bundles" -type f | LC_ALL=C sort | xargs sha256sum | sha256sum
}

# compiled_id CASE ARGS...: fylgja-cli intent read --branch $BRANCH ARGS, which writes a
# snapshot and files it under the orchestrator's snapshots/, then fylgja twin compile
# --snapshot of it (018, 020); sets COMPILED_ID and COMPILED_SNAPSHOT. A run's bundle is the
# one they compile (D-024), and its snapshot the one they read, since two reads of one intent
# differ in observed_at alone (D-061).
compiled_id() {
  local case=$1
  shift
  fylgja_cli intent read --branch "$BRANCH" "$@" --out "$OUT/snapshot-$case.json" > "$OUT/read-$case.out" 2> "$OUT/read-$case.err" ||
    fail "case $case: fylgja-cli intent read failed; see $OUT/read-$case.out and $OUT/read-$case.err"
  fylgja twin compile --snapshot "$OUT/snapshot-$case.json" --out "$OUT/compiled-$case" --json > "$OUT/compile-$case.json" 2> "$OUT/compile-$case.err" ||
    fail "case $case: twin compile failed; see $OUT/compile-$case.err"
  COMPILED_ID=$(jq -r .bundle_id "$OUT/compile-$case.json")
  COMPILED_SNAPSHOT=$(jq -r .snapshot_id "$OUT/compile-$case.json")
  [ -f "$ORCH_ROOT/snapshots/$COMPILED_SNAPSHOT.json" ] ||
    fail "case $case: fylgja-cli intent read filed no snapshot $COMPILED_SNAPSHOT under $ORCH_ROOT/snapshots"
}

# ready_to_record HISTORY: seconds from the last readiness step's completion to the
# record's, from the run's own history; the pushes fall between. --json prints
# no progress lines, so the service's event times stand in for them.
ready_to_record() {
  jq -r '
    def secs: capture("^(?<s>[^.Z]+)(?<f>\\.[0-9]+)?Z$") | (.s + "Z" | fromdate) + ((.f // "0") | tonumber);
    (.events | map({key: .eventId, value: .}) | from_entries) as $e
    | [.events[] | select(.eventType=="EVENT_TYPE_ACTIVITY_TASK_COMPLETED")
        | {t: (.eventTime | secs),
           a: $e[.activityTaskCompletedEventAttributes.scheduledEventId].activityTaskScheduledEventAttributes.activityType.name}]
    | ([.[] | select(.a=="AwaitReadiness") | .t] | max) as $r
    | ([.[] | select(.a=="RecordTwin") | .t] | max) as $d
    | if $r and $d then ($d - $r) * 10 | round / 10 | tostring else "?" end' "$1"
}

# READBACK names the function create_twin calls to read the twin back: the
# SR Linux fixture's readback, and nothing for case 6, whose mixed twin is read by
# readback_mixed after the create.
READBACK=readback

# create_twin CASE ARGS...: fylgja-cli twin create --branch $BRANCH ARGS, or --stage
# $CREATE_REF in place of the branch when CREATE_REF is set (cases 7 and 8), or fylgja twin
# create --snapshot $CREATE_SNAPSHOT ARGS when that is set (cases 2 and 4, a snapshot read
# --at T, since fylgja-cli's create takes no --at; 020), ending with three ready devices and
# $HOSTS ready probe hosts (016), the twin recorded from the snapshot the core was sent, that
# snapshot stored under its id in both stores, the core's and the orchestrator's, version 2
# and carrying one probe for each two hosts, the bundle stored and staged as its id, no CTM
# sidecar written (018), and each device running its artifact; the orchestrator's record
# naming the stage after a create from one, and gone after a create from a branch, whose twin
# names no stage (020); sets and exports SID, BID and RUN_ID, and sets CREATE_TOOK.
CREATE_TIMES=()
create_twin() {
  local case=$1
  shift
  local start status=0 took ref=(--branch "$BRANCH") began="$OUT/began-$case"
  [ -z "${CREATE_REF:-}" ] || ref=(--stage "$CREATE_REF")
  NODES=$((3 + HOSTS))
  export NODES
  # The case's start, for the sidecar check below: the store keeps the sidecars of every
  # read before 018, so what is asserted is that this create wrote none.
  touch "$began"
  start=$(now_ns)
  if [ -n "${CREATE_SNAPSHOT:-}" ]; then
    fylgja twin create --snapshot "$CREATE_SNAPSHOT" "$@" --json > "$OUT/create-$case.json" 2> "$OUT/create-$case.err" || status=$?
  else
    fylgja_cli twin create "${ref[@]}" "$@" --json > "$OUT/create-$case.json" 2> "$OUT/create-$case.err" || status=$?
  fi
  took=$(since "$start")
  CREATE_TOOK=$took
  echo "e2e: case $case: create took ${took}s (exit $status)"
  expect "$OUT/create-$case.json" '.status=="ok" and (.twin.nodes|length)==(env.NODES|tonumber)'
  jq -r '.twin.nodes[] | "e2e:   \(.name)  \(.mgmt_ipv4)  ready after \(.ready_after_s)s"' "$OUT/create-$case.json"

  SID=$(jq -r .snapshot_id "$OUT/create-$case.json")
  BID=$(jq -r .bundle_id "$OUT/create-$case.json")
  RUN_ID=$(jq -r .subject.run_id "$OUT/create-$case.json")
  export SID BID RUN_ID
  echo "e2e: case $case: snapshot_id $SID, bundle_id $BID, run $RUN_ID"

  clab inspect --all --format json > "$OUT/inspect-create-$case.json"
  expect "$OUT/inspect-create-$case.json" '.fylgja | length == (env.NODES|tonumber) and all(.state=="running")'

  # The core read nothing: it was sent the snapshot, by fylgja-cli's flow or by the script, so
  # the twin is a snapshot's (018, 020), and its record names no stage (twin.json 12).
  expect "$TWIN/twin.json" '.snapshot_id==env.SID and .bundle_id==env.BID and .source=="snapshot" and .observed_at != null
    and .stage==null and .run.workflow_id=="fylgja-provision" and .run.run_id==env.RUN_ID
    and (.nodes|length)==(env.NODES|tonumber)'
  # A probe's host (016) is recorded with its probe in place of a package and an artifact,
  # in the container containerlab names after it, <probe>-<endpoint>.
  expect "$TWIN/twin.json" '[.nodes[] | select(.probe != null)] | length == (env.HOSTS|tonumber)
    and all(.[]; .psp == null and .artifact == null and .name == .probe.name + "-" + .probe.endpoint
      and .container == "clab-fylgja-" + .name)'

  # Every node ready inside its own package's readiness budget, read from that package: a
  # mixed twin's nodes are held to different ones, and a probe's host to its probe
  # package's (016). For cases 1-5's devices, all SR Linux, this is the 60s a single bound
  # asserted before M7.
  local name pkg ready budget
  while read -r name pkg ready; do
    budget=$(psp_scalar "$pkg" timeout_s)
    [ -n "$budget" ] || fail "case $case: $pkg states no readiness timeout_s"
    awk -v r="$ready" -v b="$budget" 'BEGIN { exit !(r < b) }' ||
      fail "case $case: node $name ($pkg) was ready after ${ready}s, its package's readiness budget is ${budget}s"
  done < <(jq -r '.nodes[] | "\(.name) \(if .probe != null then "probes/\(.probe.package.id)" else "psp/\(.psp.id)" end).yaml \(.ready_after_s)"' "$TWIN/twin.json")

  [ -f "$FYLGJA_STATE_ROOT/snapshots/$SID.json" ] || fail "case $case: the core's snapshot store holds no entry for $SID"
  [ -f "$ORCH_ROOT/snapshots/$SID.json" ] || fail "case $case: the orchestrator's snapshot store holds no entry for $SID"
  # The orchestrator's record follows the twin as twin show names it (020, R-09): the stage
  # a create from one names, and none after a create from a branch. A create from a snapshot
  # is the core's alone, and the record is not the core's to touch.
  if [ -n "${CREATE_REF:-}" ]; then
    [ -f "$ORCH_RECORD" ] || fail "case $case: fylgja-cli twin create --stage $CREATE_REF wrote no record at $ORCH_RECORD"
    export CREATE_REF
    expect "$ORCH_RECORD" '.record_version=="1" and .flow=="twin-create" and .snapshot_id==env.SID
      and .stage.branch + "/" + .stage.label == env.CREATE_REF and (.flow_run_id | length) > 0'
  elif [ -z "${CREATE_SNAPSHOT:-}" ]; then
    [ ! -e "$ORCH_RECORD" ] || fail "case $case: a create from branch $BRANCH left the orchestrator's record $ORCH_RECORD, which names a stage this twin does not stand at"
  fi
  # The snapshot is a 2 (016), its probes the ones the twin's hosts are built for. Its version
  # and its probes' names alone are copied out, since its CTM carries the marker.
  jq '{snapshot_version, probes: [.probes[].name]}' "$FYLGJA_STATE_ROOT/snapshots/$SID.json" > "$OUT/probes-snapshot-$case.json"
  expect "$OUT/probes-snapshot-$case.json" '.snapshot_version == "2" and (.probes | length) * 2 == (env.HOSTS|tonumber)'
  [ -d "$FYLGJA_STATE_ROOT/bundles/$BID" ] || fail "case $case: the bundle store holds no entry for $BID"
  local sidecars
  sidecars=$(find "$FYLGJA_STATE_ROOT/bundles" -maxdepth 1 -name '*.ctm.json' -newer "$began")
  [ -z "$sidecars" ] || fail "case $case: the create wrote a CTM sidecar, which 018 retired: $sidecars"
  local staged
  staged=$( cd "$TWIN/bundle" && find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1 )
  [ "$staged" = "$BID" ] || fail "case $case: the staged copy hashes to $staged, not $BID"

  # The twin directory goes with the destroy, so it is searched now. containerlab's own
  # working directory is not Fylgja's output and is left out of the password search.
  no_credential "the Infrahub token" "$INFRAHUB_API_TOKEN" "$TWIN/bundle" "$TWIN/twin.json"
  no_credential "the API's token" "$API_TOKEN" "$TWIN/bundle" "$TWIN/twin.json"
  no_credential "the probe password" "$FYLGJA_SRLINUX_PASSWORD" "$TWIN/bundle" "$TWIN/twin.json"
  # The staged bundle carries the marker, which is where it belongs; the record does not.
  no_credential "the artifact marker" "$MARKER" "$TWIN/twin.json"
  cp "$TWIN/twin.json" "$OUT/twin-$case.json"

  [ -z "$READBACK" ] || "$READBACK" "$case" "$BRANCH" enable
  history_of "provision-$case" fylgja-provision "$RUN_ID"
  CREATE_TIMES+=("case $case ${took}s, last node ready to record written $(ready_to_record "$OUT/history-provision-$case.json")s")
}

# destroy_twin CASE TEARDOWN UNSTAGE: twin destroy reports TEARDOWN and UNSTAGE, in under
# 60s, leaving no lab, no probe's host container (016), no twin directory and the bundle
# store as it was; sets DESTROY_TOOK.
destroy_twin() {
  local case=$1 teardown=$2 unstage=$3
  local before start status=0 took
  before=$(store_digest)
  start=$(now_ns)
  fylgja twin destroy --json > "$OUT/destroy-$case.json" 2> "$OUT/destroy-$case.err" || status=$?
  took=$(since "$start")
  DESTROY_TOOK=$took
  echo "e2e: case $case: destroy took ${took}s (exit $status)"
  expect "$OUT/destroy-$case.json" ".status==\"ok\" and .cleanup.teardown==\"$teardown\" and .cleanup.unstage==\"$unstage\" and (.cleanup.remaining|length)==0"
  [ "${took%.*}" -lt 60 ] || fail "case $case: destroy took ${took}s, over 60s"
  [ "$(clab inspect --all --format json)" = "{}" ] || fail "case $case: containerlab still reports a lab after destroy"
  no_probe_containers "$case"
  [ ! -e "$TWIN" ] || fail "case $case: $TWIN is still present after destroy"
  [ "$before" = "$(store_digest)" ] || fail "case $case: destroy changed the bundle store"
}

# whatever happened, the host is left clean. A destroy that cannot leave it clean
# is a leak, not a flake (docs/development.md).
cleanup() {
  local status=$?
  # A failure while the short-lived worker serves (case 3) must not leave it running.
  if [ -n "${WORKER_PID:-}" ] && kill -0 "$WORKER_PID" 2> /dev/null; then
    kill -TERM "$WORKER_PID" 2> /dev/null || true
    wait "$WORKER_PID" 2> /dev/null || true
  fi
  # A request to the script's server, which the success path has already stopped once nothing
  # was left.
  if [ -n "${SERVER_PID:-}" ]; then
    fylgja twin destroy --json > "$OUT/trap-destroy.json" 2> "$OUT/trap-destroy.err" || true
  fi
  # The throwaway branches of cases 5 to 9, when they were made and not yet deleted; -delete
  # removes the stages and proposed changes of cases 7, 8 and 9 before their branches, case
  # 9's comments and validators with its proposed change. A failure is reported, not fatal.
  # The destroy above cancels a step in flight and waits for its record. A rehearsal in
  # flight, case 9's check's, is a flow on the operator's platform (020): the destroy cancels
  # the core's run it is in and clears the twin, and the flow's own destroy then finds
  # nothing; the report it posts goes with its proposed change, or finds none to go on.
  local branch
  for branch in "${FB:-}" "${FM:-}" "${FP:-}" "${FS:-}" "${FR:-}"; do
    [ -n "$branch" ] || continue
    if ! fixture -branch "$branch" -delete > "$OUT/trap-delete-$branch.out" 2>&1; then
      echo "e2e: branch $branch was not deleted; remove it with: go run -tags fixture ./cmd/fylgja-fixture -branch $branch -delete" >&2
    fi
  done
  # The probe case 8 or 9 wrote on main and had not yet deleted (016), which every read with
  # no probe file would go on carrying. A failure is reported, not fatal.
  if [ -n "${PROBES_ON_MAIN:-}" ] && ! fixture -delete-probes > "$OUT/trap-delete-probes.out" 2>&1; then
    echo "e2e: the probes on main were not deleted; remove them with: go run -tags fixture ./cmd/fylgja-fixture -delete-probes" >&2
  fi
  # The server goes before the checks below, any of which may exit: an exit inside this trap
  # runs no trap after it.
  stop_server
  local labs
  if ! labs=$(clab inspect --all --format json 2> "$OUT/trap-inspect.err"); then
    echo "e2e: LEAK?: clab inspect failed after the trap's destroy; see $OUT/trap-inspect.err" >&2
    exit 99
  fi
  if jq -e 'has("fylgja")' <<< "$labs" > /dev/null; then
    echo "e2e: LEAK: lab fylgja still present" >&2
    exit 99
  fi
  # A probe's host containerlab no longer reports is a container all the same (016).
  local hosts
  if ! hosts=$(probe_containers 2> "$OUT/trap-probe-containers.err"); then
    echo "e2e: LEAK?: docker ps failed after the trap's destroy; see $OUT/trap-probe-containers.err" >&2
    exit 99
  fi
  if [ -n "$hosts" ]; then
    echo "e2e: LEAK: a probe's host container still present: $(paste -sd ' ' - <<< "$hosts")" >&2
    exit 99
  fi
  if [ -e "$TWIN" ]; then
    echo "e2e: LEAK: $TWIN still present" >&2
    exit 99
  fi
  # No command of this build makes Schedule fylgja-follow (019), so one present was kept by a
  # host upgraded with a following twin up, which starts a workflow no worker of this build
  # serves.
  case "$(schedule_state)" in
    present)
      echo "e2e: LEAK: Schedule $FOLLOW_SCHEDULE still present" >&2
      exit 99
      ;;
    unknown)
      echo "e2e: LEAK?: temporal schedule describe gave no answer after the trap's destroy; see $OUT/schedule-describe.err" >&2
      exit 99
      ;;
  esac
  exit "$status"
}

# Every artifact carries this in its header, where the template writes the device's
# description (testsupport.MarkerPrefix; 017 research R-15); it may sit in the staged
# bundle, the bundle and snapshot stores and a read's snapshot, and nowhere else.
MARKER='FYLGJA-MARKER'

RUN_START=$(now_ns)
# T: whole seconds after fylgja-fixture was seeded with its artifacts Ready, and before any
# twin of this run. A pinned read at a T before the artifacts
# were Ready is refused, so the script sees them first.
artifacts_of "$BRANCH" "$OUT/artifacts-fixture.json" 2> "$OUT/artifacts-fixture.err" ||
  fail "reading $BRANCH's artifacts from Infrahub failed; see $OUT/artifacts-fixture.err"
expect "$OUT/artifacts-fixture.json" 'length == 3 and all(.[]; .status == "Ready")'
sleep 1
T=$(date -u +%Y-%m-%dT%H:%M:%SZ)
export T
echo "e2e: T=$T"

# --- preconditions: fail fast, with the remedy, before anything is created ------------

[ -x "$FYLGJA" ] || fail "$FYLGJA is missing: run make build (make test-e2e does)"
[ -x "$FYLGJA_CLI" ] ||
  fail "$FYLGJA_CLI is missing: run make orchestrator-venv (every command naming a branch or a stage is the orchestrator's, 020)"
command -v gnmic > /dev/null || fail "gnmic is not on PATH: every create's read-back uses it"
command -v go > /dev/null || fail "go is not on PATH: case 5 seeds its branch with go run -tags fixture ./cmd/fylgja-fixture; install Go or add it to PATH"
# The Temporal CLI, from the PATH or else where its installer, run by scripts/bring-up.sh,
# puts it and leaves it off the PATH.
PATH="$PATH:$HOME/.temporalio/bin"
command -v temporal > /dev/null || fail "the Temporal CLI is neither on PATH nor in ~/.temporalio/bin, where scripts/bring-up.sh installs it"
if ! temporal operator cluster health --address "$TEMPORAL_ADDRESS" > "$OUT/health.out" 2>&1; then
  fail "the workflow service is not answering at $TEMPORAL_ADDRESS: start it with make temporal-dev"
fi

# The probes (016), which cases 5, 8 and 9 boot. Case 5 needs nokia_srlinux alone, which every
# list that selects a case names, so they are required whenever any case runs. The image is
# the probe package's, verified present and never pulled by any command (research R-12), so
# the run pulls it no more than the product would. The kind FylgjaProbe on main, which cases
# 8 and 9 write into: present, and holding no probe, since every read with no probe file
# carries what it holds, and every other case's twin would gain its hosts.
PROBE_IMAGE=$(psp_scalar "$PROBE_PACKAGE" ref)
[ -n "$PROBE_IMAGE" ] || fail "$PROBE_PACKAGE states no image ref"
docker image inspect "$PROBE_IMAGE" > /dev/null 2>&1 ||
  fail "image $PROBE_IMAGE, $PROBE_PACKAGE's, is absent: docker pull $PROBE_IMAGE (no command pulls it)"
gql "" '{ FylgjaProbe { count } }' > "$OUT/probes-main.json" 2> "$OUT/probes-main.err" ||
  fail "main has no kind FylgjaProbe, or reading it failed (see $OUT/probes-main.err): load it with .venv/bin/infrahubctl schema load --branch main schema/fylgja-probe.yaml"
probes_on_main=$(jq -r '.FylgjaProbe.count' "$OUT/probes-main.json")
[ "$probes_on_main" = 0 ] ||
  fail "main holds $probes_on_main FylgjaProbe objects, which every case's read with no probe file would carry: delete them with go run -tags fixture ./cmd/fylgja-fixture -delete-probes"
echo "e2e: the probe image $PROBE_IMAGE is present, and FylgjaProbe on main holds no probe"

# Case 9's rehearsals are asked from inside Infrahub (015's R-19) of the orchestrator's
# platform, whose runner's flow drives the operator's core (020), so what serves them is
# outside the script and required first. Case 9 needs nokia_srlinux alone, which every list
# that selects a case names, so it runs whenever any case does.
#
# The checks, on main: the registration fylgja imports them from origin's main, each with the
# timeout its class declares. A branch runs the definitions main held at its creation, and
# case 9 seeds its own, so an import any time before the run is enough.
gql "" '{ CoreCheckDefinition { edges { node { name { value } timeout { value } } } } }' \
  > "$OUT/check-definitions.json" 2> "$OUT/check-definitions.err" ||
  fail "reading the check definitions on main failed; see $OUT/check-definitions.err"
jq -e '[.CoreCheckDefinition.edges[].node | {name: .name.value, timeout: .timeout.value}]
  | any(.[]; . == {name: "fylgja-step", timeout: 300}) and any(.[]; . == {name: "fylgja-twin", timeout: 4260})' \
  "$OUT/check-definitions.json" > /dev/null ||
  fail "case 9 needs the checks fylgja-step (timeout 300) and fylgja-twin (timeout 4260) on main, which holds $(jq -r '[.CoreCheckDefinition.edges[].node | "\(.name.value) (timeout \(.timeout.value))"] | if length == 0 then "none" else join(", ") end' "$OUT/check-definitions.json"): push them to origin's main and import them, as specs/015-proposed-change-rehearsal/quickstart.md §6 does"
# The definitions' names and timeouts pass for an earlier import too, and case 9 asserts on
# the Python the task workers run, which must be this tree's, as the runner's source and the
# core's binary must be below: the registration fylgja's imported commit, read on main, is one this clone knows,
# and infrahub/ and .infrahub.yml in the working tree are as that commit holds them.
gql "" '{ CoreReadOnlyRepository(name__value: "fylgja") { edges { node { commit { value } } } } }' \
  > "$OUT/registration.json" 2> "$OUT/registration.err" ||
  fail "reading the registration fylgja on main failed; see $OUT/registration.err"
IMPORTED=$(jq -r '.CoreReadOnlyRepository.edges[0].node.commit.value // ""' "$OUT/registration.json")
IMPORT_REMEDY="push them to origin's main and import them, as specs/015-proposed-change-rehearsal/quickstart.md §6 does"
[ -n "$IMPORTED" ] ||
  fail "case 9 needs the registration fylgja on main, with the commit it imported, and main holds none; register it and $IMPORT_REMEDY"
git cat-file -e "$IMPORTED^{commit}" 2> /dev/null ||
  fail "case 9 needs the checks the registration fylgja imported, at commit $IMPORTED, to be this tree's, and this clone does not know that commit: fetch origin (git fetch origin) and run again, as specs/015-proposed-change-rehearsal/quickstart.md §6 says"
git diff --quiet "$IMPORTED" -- infrahub .infrahub.yml ||
  fail "case 9 needs the checks the registration fylgja imported, at commit $IMPORTED, to be this tree's, and $(git diff --name-only "$IMPORTED" -- infrahub .infrahub.yml | paste -sd ' ' -) differ here; $IMPORT_REMEDY"

# The platform the task workers reach (020, R-12, R-16): the orchestrator's Prefect server on
# the Docker bridge, where the Compose override points them (host.docker.internal:4200) with
# FYLGJA_ORCHESTRATOR_AUTH. Asked from inside each task worker, as the checks ask it and as
# tier 2's precheck (internal/checks' platformReached) does, on the worker's own Python and
# httpx: its health, which answers anyone, and the deployment twin-rehearse/main, which
# answers the credential and says the runner serves the flow; and the core's port 7650 there,
# which must not answer, since the core listens on loopback alone (FR-005, R-18). The probe
# reads the two variables in the worker's own environment and prints statuses and the
# address, never a value.
PLATFORM_REMEDY="start the platform and the runner as scripts/bring-up.sh's orchestrator part does, and give Infrahub's task workers the override's two variables with docker compose up -d, as CLAUDE.md says"
PLATFORM_PROBE='
import os, httpx
address = os.environ.get("FYLGJA_ORCHESTRATOR_ADDRESS", "")
auth = os.environ.get("FYLGJA_ORCHESTRATOR_AUTH", "")
if not address or not auth:
    print("unset", "FYLGJA_ORCHESTRATOR_ADDRESS" if not address else "FYLGJA_ORCHESTRATOR_AUTH")
    raise SystemExit
base = (address if address.startswith(("http://", "https://")) else "http://" + address).rstrip("/") + "/api"
user, _, password = auth.partition(":")
try:
    health = httpx.get(base + "/health", timeout=10, trust_env=False).status_code
    deployment = httpx.get(base + "/deployments/name/twin-rehearse/main", auth=(user, password), timeout=10,
                           trust_env=False).status_code
except Exception as exc:
    print("unreachable", address, type(exc).__name__)
    raise SystemExit
try:
    core = str(httpx.post("http://host.docker.internal:7650/v1/twin/show", json={}, timeout=10, trust_env=False).status_code)
except Exception as exc:
    core = type(exc).__name__
print("answered", address, health, deployment, core)
'
COMPOSE_PROJECT=${COMPOSE_PROJECT_NAME:-fylgja-infrahub}
mapfile -t TASK_WORKERS < <(docker ps --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
  --filter label=com.docker.compose.service=task-worker --format '{{.Names}}' 2> "$OUT/task-workers.err" | LC_ALL=C sort)
[ "${#TASK_WORKERS[@]}" -gt 0 ] ||
  fail "case 9 needs Infrahub's task workers, which run the checks, and docker lists none of the Compose project $COMPOSE_PROJECT; see $OUT/task-workers.err"
for worker in "${TASK_WORKERS[@]}"; do
  docker exec "$worker" python -c "$PLATFORM_PROBE" > "$OUT/platform-probe-$worker.out" 2> "$OUT/platform-probe-$worker.err" ||
    fail "case 9: the platform's precheck could not run in $worker; see $OUT/platform-probe-$worker.err"
  said="" address="" health="" deployment="" core=""
  read -r said address health deployment core < "$OUT/platform-probe-$worker.out" || true
  case $said in
    unset) fail "case 9 needs $address in $worker's environment, which the Compose override gives the task workers; $PLATFORM_REMEDY" ;;
    unreachable) fail "case 9 needs the orchestrator's platform at $address to answer $worker, and it does not ($health); $PLATFORM_REMEDY" ;;
    answered) ;;
    *) fail "case 9: the platform's precheck in $worker said something else; see $OUT/platform-probe-$worker.out" ;;
  esac
  { [ "$health" = 200 ] && [ "$deployment" = 200 ]; } ||
    fail "case 9 needs the platform at $address to answer $worker GET /api/health 200 and the deployment twin-rehearse/main 200, and it answered $health and $deployment: a 401 is a credential not the platform's, a 404 a runner serving no flows; $PLATFORM_REMEDY"
  [[ ! $core =~ ^[0-9]+$ ]] ||
    fail "case 9 needs the core's port 7650 unreachable from Infrahub's task workers, and host.docker.internal:7650 answered $worker $core: the core listens on loopback alone (020, FR-005); restart it with CLAUDE.md's start line, which names no bridge listener"
done
echo "e2e: case 9: the platform answers ${TASK_WORKERS[*]} its health and twin-rehearse/main, and the core's 7650 does not ($core)"

# The platform from this host, for the flow runs case 9 reads (rehearsal_run): local/.env's
# PREFECT_API_URL and PREFECT_API_AUTH_STRING, the deployment the checks trigger by name.
{ [ -n "${PREFECT_API_URL:-}" ] && [ -n "${PREFECT_API_AUTH_STRING:-}" ]; } ||
  fail "case 9 needs local/.env's PREFECT_API_URL and PREFECT_API_AUTH_STRING, the orchestrator's platform, whose flow runs it reads; add them as .env.example says"
platform_get /deployments/name/twin-rehearse/main > "$OUT/deployment-twin-rehearse.json" 2> "$OUT/deployment-twin-rehearse.err" ||
  fail "case 9 needs the platform at $PREFECT_API_URL to answer this host the deployment twin-rehearse/main to local/.env's auth string; see $OUT/deployment-twin-rehearse.err; $PLATFORM_REMEDY"
REHEARSE_DEPLOYMENT=$(jq -r '.id // ""' "$OUT/deployment-twin-rehearse.json")
[ -n "$REHEARSE_DEPLOYMENT" ] || fail "case 9: the platform's deployment twin-rehearse/main names no id; see $OUT/deployment-twin-rehearse.json"
export REHEARSE_DEPLOYMENT

# The runner, fylgja-orchestrator serve, which runs the flow the check triggers: this tree's
# venv's, under the platform's home as scripts/bring-up.sh and make orchestrator-serve start
# it (a runner a test started, under a home of its own, is not it), started after the
# orchestrator's source last changed, since the package is installed editable and a running
# runner holds the code it started with; and reading under the default scope tag:fylgja,
# since the checks send no scope (017, FR-021). Each variable is one NUL-ended line.
ORCH_VENV="$(pwd)/orchestrator/.venv"
PLATFORM_HOME="$(pwd)/local/orchestrator/prefect"
runner_pid=""
for pid in $(pgrep -f -- "$ORCH_VENV/bin/fylgja-orchestrator" || true); do
  mapfile -d '' -t args < "/proc/$pid/cmdline" 2> /dev/null || continue
  { [ "${args[1]:-}" = "$ORCH_VENV/bin/fylgja-orchestrator" ] && [ "${args[2]:-}" = serve ]; } || continue
  grep -qxzF "PREFECT_HOME=$PLATFORM_HOME" "/proc/$pid/environ" 2> /dev/null || continue
  runner_pid=$pid
  break
done
[ -n "$runner_pid" ] ||
  fail "case 9 needs the runner, $ORCH_VENV/bin/fylgja-orchestrator serve under PREFECT_HOME=$PLATFORM_HOME, and none runs; $PLATFORM_REMEDY"
runner_started=$(( $(date +%s) - $(ps -o etimes= -p "$runner_pid" | tr -d ' ') ))
newer=$(find orchestrator/src -name '*.py' -newermt "@$runner_started" -print -quit)
[ -z "$newer" ] ||
  fail "case 9 needs the runner to run this tree's orchestrator, and pid $runner_pid started before $newer last changed: restart it; $PLATFORM_REMEDY"
grep -qxzF 'FYLGJA_DEFAULT_SCOPE=tag:fylgja' "/proc/$runner_pid/environ" 2> /dev/null ||
  fail "case 9 needs the runner to read under the default scope tag:fylgja, and pid $runner_pid's environment sets no FYLGJA_DEFAULT_SCOPE=tag:fylgja: add FYLGJA_DEFAULT_SCOPE=\"tag:fylgja\" to local/.env; $PLATFORM_REMEDY"
# The core the runner's flows drive: its FYLGJA_API_ADDRESS, by name, else the default.
runner_core=$(tr '\0' '\n' < "/proc/$runner_pid/environ" | sed -n 's/^FYLGJA_API_ADDRESS=//p' | tail -1)
runner_core=${runner_core:-127.0.0.1:7650}
[ "$runner_core" = 127.0.0.1:7650 ] ||
  fail "case 9 needs the runner's flows to drive the core on 127.0.0.1:7650, CLAUDE.md's, and pid $runner_pid names FYLGJA_API_ADDRESS=$runner_core"

# The core the runner's flows drive: the operator's server on loopback, with local/.env's
# token, which curl reads from a header file so that it is in no process's arguments. It must
# be this tree's build, as the script's own server is, since the rehearsals it serves are what
# case 9 asserts, writing its log to local/server.log, which the greps read, and holding none
# of Infrahub's variables and no default scope, since the core reads no source of truth (020,
# FR-004).
BUILD=$("$FYLGJA" --version | sed -n 's/^fylgja version //p')
CORE_LOG="$FYLGJA_STATE_ROOT/server.log"
SERVE_REMEDY="start it from this tree with CLAUDE.md's start line, fylgja serve --listen 127.0.0.1:7650, from a shell that has loaded local/.env and with no INFRAHUB_* or FYLGJA_DEFAULT_SCOPE"
# shellcheck disable=SC2031 # local/.env's token, not the one fylgja() sets in its subshell
[ -n "${FYLGJA_API_TOKEN:-}" ] ||
  fail "case 9 needs local/.env's FYLGJA_API_TOKEN, the token of the core the runner's flows drive; set it and $SERVE_REMEDY"
# shellcheck disable=SC2031
core_status=$(curl -sS -o "$OUT/core-show.ndjson" -D "$OUT/core-show.headers" -w '%{http_code}' \
  -H @<(printf 'Authorization: Bearer %s\n' "$FYLGJA_API_TOKEN") -H 'Content-Type: application/json' \
  -d '{}' "http://$runner_core/v1/twin/show" 2> "$OUT/core-show.err") || core_status="nothing"
core_build=$(sed -n 's/^Fylgja-Build: *\([^[:space:]]*\).*/\1/Ip' "$OUT/core-show.headers" 2> /dev/null | tail -1)
{ [ "$core_status" = 200 ] && [ "$core_build" = "$BUILD" ]; } ||
  fail "case 9 needs the core the runner's flows drive, at http://$runner_core, from this tree (build $BUILD) and with local/.env's token: it answered $core_status${core_build:+, build $core_build}; $SERVE_REMEDY"
# Every unstamped build is the same version, so the build header alone proves no tree: the
# server's process, the fylgja serve that listens on $runner_core by its arguments (or by
# naming no --listen, whose default it is), must run this tree's binary itself, neither
# replaced, (deleted), nor another file. A /proc entry this shell cannot read, as for a
# server started under sg docker, is said and not compared.
core_pid=""
for pid in $(pgrep -x fylgja || true); do
  mapfile -d '' -t args < "/proc/$pid/cmdline" 2> /dev/null || continue
  [ "${args[1]:-}" = serve ] || continue
  listens=0 named=0
  for (( i = 2; i < ${#args[@]}; i++ )); do
    case ${args[i]} in
      --listen=*) named=1; [ "${args[i]#--listen=}" != "$runner_core" ] || listens=1 ;;
      --listen) named=1; [ "${args[i + 1]:-}" != "$runner_core" ] || listens=1 ;;
    esac
  done
  [ "$named" -eq 1 ] || listens=1
  if [ "$listens" -eq 1 ]; then
    core_pid=$pid
    break
  fi
done
[ -n "$core_pid" ] ||
  fail "case 9 needs the core on $runner_core to run this tree's $FYLGJA, and no fylgja serve process listens there by its arguments; $SERVE_REMEDY"
core_binary="its binary not compared"
if core_exe=$(readlink "/proc/$core_pid/exe" 2> /dev/null); then
  case $core_exe in
    *" (deleted)") fail "case 9 needs the core on $runner_core to run this tree's $FYLGJA, and pid $core_pid runs a replaced binary ($core_exe): restart it; $SERVE_REMEDY" ;;
  esac
  [ "/proc/$core_pid/exe" -ef "$FYLGJA" ] ||
    fail "case 9 needs the core on $runner_core to run this tree's $FYLGJA, and pid $core_pid runs $core_exe; $SERVE_REMEDY"
  core_binary="this tree's $FYLGJA (pid $core_pid)"
  [ "$(readlink "/proc/$core_pid/fd/2" 2> /dev/null)" = "$CORE_LOG" ] ||
    fail "case 9 needs the core on $runner_core to log to $CORE_LOG, which the greps read, and pid $core_pid logs elsewhere; $SERVE_REMEDY"
  # The three names the core would read a source of truth by, read by name alone, never a
  # value, as scripts/bring-up.sh starts it without them.
  held=$(tr '\0' '\n' < "/proc/$core_pid/environ" |
    sed -n 's/^\(INFRAHUB_ADDRESS\|INFRAHUB_API_TOKEN\|FYLGJA_DEFAULT_SCOPE\)=.*/\1/p' | paste -sd ' ' -)
  [ -z "$held" ] ||
    fail "case 9 needs the core on $runner_core to read no source of truth (020), and pid $core_pid's environment names $held; $SERVE_REMEDY"
else
  echo "e2e: note: the core on $runner_core is pid $core_pid, whose /proc/$core_pid/exe this shell cannot read, as for a server started under sg docker: its binary is not compared with $FYLGJA, only its build"
fi
# What the core is asked during the run is read from here on (no Infrahub request, SC-008).
[ -r "$CORE_LOG" ] || fail "case 9 needs the core's log $CORE_LOG, as CLAUDE.md's start line writes it, to be readable"
CORE_LOG_FROM=$(stat -c %s "$CORE_LOG")
echo "e2e: case 9's checks are on main, imported at this tree's ${IMPORTED:0:12}; the runner (pid $runner_pid) serves twin-rehearse/main on $PREFECT_API_URL; the core on $runner_core answers, build $BUILD, $core_binary"

# The script's own core server, from the tree, in the script's environment less every
# INFRAHUB_* variable, Infrahub's address and token, which no core reads (020, FR-004), and
# its Compose secrets, which local/.env carries for Compose alone, the admin token among them
# with the API token's value; less the default scope, which no core reads; and less the
# platform's credential, which no core holds (FR-005): both logins, the state root, and docker and
# containerlab on its PATH, which it reads at each request. Asked for port 0, it listens on
# one the system chose and names it in its listen line, so no port is taken from another
# process, nor one taken between a check and the listen. Started by a subshell that execs it,
# so that $! is the server itself, as case 3's worker is. Its report and its request log go
# to server.log, which the greps below search.
(
  # shellcheck disable=SC2046 # one name a word
  export -n $(compgen -e | grep '^INFRAHUB_') FYLGJA_DEFAULT_SCOPE PREFECT_API_AUTH_STRING FYLGJA_ORCHESTRATOR_AUTH
  FYLGJA_API_TOKEN="$API_TOKEN" exec "$FYLGJA" serve --listen 127.0.0.1:0
) > "$OUT/server.log" 2>&1 &
SERVER_PID=$!
trap stop_server EXIT
start=$(now_ns)
while :; do
  API_ADDRESS=$(sed -n 's/^fylgja serve: listening on \([^ ]*\) (.*/\1/p' "$OUT/server.log" | head -1)
  [ -z "$API_ADDRESS" ] || break
  kill -0 "$SERVER_PID" 2> /dev/null || fail "the API's server exited before it listened; see $OUT/server.log"
  [ "$(( ($(now_ns) - start) / 1000000000 ))" -lt "$SERVER_LISTEN_WAIT_S" ] ||
    fail "the API's server did not listen within ${SERVER_LISTEN_WAIT_S}s; see $OUT/server.log"
  sleep 0.1
done
echo "e2e: the API's server listens on $API_ADDRESS, after $(since "$start")s"
# Its environment, read by name alone, never a value: no INFRAHUB_* variable, no default
# scope and no platform credential.
held=$(tr '\0' '\n' < "/proc/$SERVER_PID/environ" |
  sed -n 's/^\(INFRAHUB_[A-Z_]*\|FYLGJA_DEFAULT_SCOPE\|PREFECT_API_AUTH_STRING\|FYLGJA_ORCHESTRATOR_AUTH\)=.*/\1/p' | paste -sd ' ' -)
[ -z "$held" ] || fail "the API's server holds $held in its environment, which no core reads (020)"

# The dry run touches nothing but the snapshot stores and the bundle store: fylgja-cli files
# the snapshot it takes, and the core the snapshot it is sent and the bundle it compiles.
# Refused means the host already holds a twin this script did not make: say so rather than
# destroy it.
dry_status=0
fylgja_cli twin create --branch "$BRANCH" --dry-run --json > "$OUT/dry.json" 2> "$OUT/dry.err" || dry_status=$?
if jq -e '.dry_run.verdict=="refused"' "$OUT/dry.json" > /dev/null 2>&1; then
  fail "the host is not clear ($(jq -r '[.findings[] | select(.severity=="rejection") | .rule] | join(", ")' "$OUT/dry.json")): run fylgja twin destroy first"
fi
expect "$OUT/dry.json" '.status=="ok" and .operation=="twin.create" and .dry_run.verdict=="clear" and (.dry_run.nodes|length)==3'
[ "$dry_status" -eq 0 ] || fail "dry run exited $dry_status with a clear verdict"

# An image pull inside the run counts against the deploy budget (psp/nokia_srlinux.yaml).
for image in $(jq -r '[.dry_run.nodes[].image] | unique | .[]' "$OUT/dry.json"); do
  docker image inspect "$image" > /dev/null 2>&1 ||
    fail "image $image is absent: docker pull $image"
done

# Case 6's image is never pulled: its package says account_gated, and a create naming it on
# a host that does not hold it is refused at the host check. Read from the
# package, so this names the one reference that check will look for. A default run alone:
# with PLATFORMS, an absent image skips the cases that need it (case_runs).
if [ "${#PLATFORM_LIST[@]}" -eq 0 ]; then
  CEOS_REF=$(psp_scalar psp/arista_eos.yaml ref)
  [ -n "$CEOS_REF" ] || fail "psp/arista_eos.yaml states no image ref"
  docker image inspect "$CEOS_REF" > /dev/null 2>&1 ||
    fail "image $CEOS_REF is absent: import it as docs/development.md says; it is never pulled"
fi

# From here on, anything on the host is this run's own.
trap cleanup EXIT

# --- case 1: a second create is refused naming the twin ------------------------
if case_runs 1; then

create_twin 1
SID1=$SID BID1=$BID RUN1=$RUN_ID
export SID1 BID1 RUN1
expect "$TWIN/twin.json" '.provenance.branch==env.BRANCH and (.provenance | has("at") | not)
  and .provenance.scope=="tag:fylgja"
  and .provenance.mapping=={reader: "infrahub-dcim", model: "opsmill/schema-library", version: "26336e9"}'

# twin show names the snapshot the twin was built from beside its bundle (018), the scope
# the twin's read was made under, fylgja-cli's default, and the mapping that read it (017;
# contracts/cli.md, twin show's record line).
fylgja twin show > "$OUT/show-1.out" 2> "$OUT/show-1.err" ||
  fail "case 1: twin show exited non-zero; see $OUT/show-1.err"
grep -qF "snapshot $SID1, bundle_id $BID1" "$OUT/show-1.out" ||
  fail "case 1: twin show names no snapshot $SID1, bundle_id $BID1; see $OUT/show-1.out"
grep -qF 'scope tag:fylgja, read by infrahub-dcim from opsmill/schema-library@26336e9' "$OUT/show-1.out" ||
  fail "case 1: twin show names no scope tag:fylgja read by infrahub-dcim from opsmill/schema-library@26336e9; see $OUT/show-1.out"

compiled_id 1
[ "$BID1" = "$COMPILED_ID" ] || fail "case 1: the run deployed $BID1, but fylgja-cli intent read | twin compile gives $COMPILED_ID"
[ "$SID1" = "$COMPILED_SNAPSHOT" ] || fail "case 1: the run was built from snapshot $SID1, but fylgja-cli intent read | twin compile gives $COMPILED_SNAPSHOT"

# The conformance suite's boot half on this twin. It reads each node by gNMI
# and changes nothing, so the refused create below still finds the twin as the run left
# it. Anchored, so the faked tier-1 test is not run here too.
start=$(now_ns)
go test -count=1 -tags e2e ./internal/conformance -run '^TestBootHalf$' -v > "$OUT/boot-half.out" 2>&1 ||
  fail "case 1: the conformance suite's boot half failed; see $OUT/boot-half.out"
BOOT_HALF_TOOK=$(since "$start")
echo "e2e: case 1: boot half passed in ${BOOT_HALF_TOOK}s"

# twin verify on the same twin, under the product's own reader: three
# host names, the six cabled ports and the six link ends held, and the record's three claims;
# the fixture disables nothing, so nothing is skipped. It changes nothing either.
verify_twin 1
VERIFY1_TOOK=$VERIFY_TOOK
expect "$OUT/verify-1.json" '.verify.counts.host_name.held==3 and .verify.counts.port_enabled.held==6
  and .verify.counts.neighbor.held==6 and .verify.counts.record.held==3 and .verify.skipped==[]
  and .verify.twin.bundle_id==env.BID1'

clab inspect --all --format json > "$OUT/inspect-1a.json"
twin_before=$(sha256sum < "$TWIN/twin.json")
start=$(now_ns)
refused_status=0
fylgja_cli twin create --branch "$BRANCH" --json > "$OUT/refused-1.json" 2> "$OUT/refused-1.err" || refused_status=$?
echo "e2e: case 1: second create refused after $(since "$start")s (exit $refused_status)"
clab inspect --all --format json > "$OUT/inspect-1b.json"
[ "$refused_status" -eq 1 ] || fail "case 1: the second create exited $refused_status, not 1; see $OUT/refused-1.json"
# The comma straight after the branch is the proof that an unpinned twin is named with no at.
# host.memory.unbudgeted is a host.* warning too, and names no twin; only the two refusals do.
export TWIN_PHRASE1="the twin of branch $BRANCH, bundle_id $BID1, provisioned by run fylgja-provision $RUN1, 3 nodes recorded"
expect "$OUT/refused-1.json" '.status=="rejected"
  and any(.findings[]; .rule=="host.lab.present") and any(.findings[]; .rule=="host.twin.present")'
jq -e 'all(.findings[] | select(.rule=="host.lab.present" or .rule=="host.twin.present"); .message | contains(env.TWIN_PHRASE1))' "$OUT/refused-1.json" > /dev/null ||
  fail "case 1: the refusals in $OUT/refused-1.json do not name $TWIN_PHRASE1; a worker started before the last build words them as the old binary did: restart make worker"
# status is containerlab's uptime text ("Up 2 minutes"); everything else must not move.
[ "$(jq -S 'map_values(map(del(.status)))' "$OUT/inspect-1a.json")" = "$(jq -S 'map_values(map(del(.status)))' "$OUT/inspect-1b.json")" ] ||
  fail "case 1: containerlab's state changed across the refused create; compare $OUT/inspect-1a.json and $OUT/inspect-1b.json"
[ "$twin_before" = "$(sha256sum < "$TWIN/twin.json")" ] || fail "case 1: the refused create changed twin.json"

destroy_twin 1 "done" "done"
destroy_twin 1-again "nothing" "nothing"
else
  skip_case 1
fi

# --- case 2: destroy then create from another reference ------------------------
if case_runs 2; then

# fylgja-cli's create reads the branch as it stands, and takes no --at (020): a pinned
# reference is read by intent read --at, and the twin created from that snapshot by the core,
# which reads nothing. The record's provenance names T all the same, from the envelope.
fylgja_cli intent read --branch "$BRANCH" --at "$T" --out "$OUT/snapshot-2-at.json" > "$OUT/read-2-at.out" 2> "$OUT/read-2-at.err" ||
  fail "case 2: fylgja-cli intent read --at $T failed; see $OUT/read-2-at.out and $OUT/read-2-at.err"
CREATE_SNAPSHOT="$OUT/snapshot-2-at.json"
create_twin 2
unset CREATE_SNAPSHOT
SID2=$SID BID2=$BID RUN2=$RUN_ID
export BID2 RUN2
[ "$BID2" != "$BID1" ] || fail "case 2: the create from a read --at $T gave case 1's bundle_id $BID1"
expect "$TWIN/twin.json" '.provenance.branch==env.BRANCH and .provenance.at==env.T and .bundle_id==env.BID2'
expect "$FYLGJA_STATE_ROOT/bundles/$BID2/manifest.json" '.provenance.at==env.T'
{ [ -d "$FYLGJA_STATE_ROOT/bundles/$BID1" ] && [ -d "$FYLGJA_STATE_ROOT/bundles/$BID2" ]; } ||
  fail "case 2: the store does not hold both bundles $BID1 and $BID2"

compiled_id 2 --at "$T"
[ "$BID2" = "$COMPILED_ID" ] || fail "case 2: the run deployed $BID2, but fylgja-cli intent read --at $T | twin compile gives $COMPILED_ID"
[ "$SID2" = "$COMPILED_SNAPSHOT" ] || fail "case 2: the run was built from snapshot $SID2, but fylgja-cli intent read --at $T | twin compile gives $COMPILED_SNAPSHOT"

destroy_twin 2 "done" "done"
else
  skip_case 2
fi

# --- case 3: an orphan lab is named at worker start and create, and cleared -----
if case_runs 3; then

# Made only now, on the host case 2's destroy left clean: the orphan and a twin never
# coexist. One node on the image the tier already needs, outside the state root,
# so no twin directory exists for it.
mkdir "$OUT/orphan"
ORPHAN_TOPO="$OUT/orphan/topology.clab.yml"
export ORPHAN_TOPO
cat > "$ORPHAN_TOPO" << YAML
name: fylgja
topology:
  nodes:
    n1:
      kind: nokia_srlinux
      image: $(jq -r '.dry_run.nodes[0].image' "$OUT/dry.json")
YAML
start=$(now_ns)
orphan_status=0
(cd "$OUT/orphan" && clab deploy --topo topology.clab.yml --format json > "$OUT/orphan-deploy.json" 2> "$OUT/orphan-deploy.err") || orphan_status=$?
echo "e2e: case 3: orphan deploy took $(since "$start")s (exit $orphan_status)"
[ "$orphan_status" -eq 0 ] || fail "case 3: clab deploy of the orphan exited $orphan_status; see $OUT/orphan-deploy.err"
clab inspect --all --format json > "$OUT/inspect-orphan.json"
expect "$OUT/inspect-orphan.json" '.fylgja | length == 1 and .[0].state=="running" and .[0].absLabPath==env.ORPHAN_TOPO'
[ ! -e "$TWIN" ] || fail "case 3: $TWIN exists beside the orphan"

# A worker of the script's own, from the script's environment, on the one queue.
# Started as a simple command so that $! is the worker itself: a & after an && list
# backgrounds a subshell, and the kill misses the worker. Nothing is in
# flight while it serves, so it takes no task; once stopped it is listed as a poller for
# about five minutes, which is harmless.
"$FYLGJA" worker run > "$OUT/worker-orphan.out" 2> "$OUT/worker-orphan.err" &
WORKER_PID=$!
start=$(now_ns)
host_line=""
while :; do
  host_line=$(grep -s -m1 '^fylgja worker: host: ' "$OUT/worker-orphan.out" || true)
  [ -z "$host_line" ] || break
  kill -0 "$WORKER_PID" 2> /dev/null ||
    fail "case 3: the short-lived worker exited before its host line; see $OUT/worker-orphan.err"
  [ "$(( ($(now_ns) - start) / 1000000000 ))" -lt "$WORKER_HOST_LINE_WAIT_S" ] ||
    fail "case 3: no host line from the short-lived worker within ${WORKER_HOST_LINE_WAIT_S}s; see $OUT/worker-orphan.out"
  sleep 0.1
done
echo "e2e: case 3: worker host line after $(since "$start")s"
kill -TERM "$WORKER_PID" 2> /dev/null || true
worker_status=0
wait "$WORKER_PID" || worker_status=$?
unset WORKER_PID
[ "$worker_status" -eq 0 ] || fail "case 3: the short-lived worker exited $worker_status on SIGTERM, not 0; see $OUT/worker-orphan.err"
expected_line="fylgja worker: host: lab fylgja present (1 node); twin directory absent; an orphan: no twin.json records it; deployed from $ORPHAN_TOPO; fylgja twin destroy clears it"
[ "$host_line" = "$expected_line" ] ||
  fail "case 3: the short-lived worker's host line is
  $host_line
not
  $expected_line"

dry_orphan_status=0
fylgja_cli twin create --branch "$BRANCH" --dry-run --json > "$OUT/dry-orphan.json" 2> "$OUT/dry-orphan.err" || dry_orphan_status=$?
[ "$dry_orphan_status" -eq 1 ] || fail "case 3: the dry run beside the orphan exited $dry_orphan_status, not 1; see $OUT/dry-orphan.json"
export ORPHAN_REFUSAL="lab fylgja is present (1 node), an orphan: no twin.json records it; deployed from $ORPHAN_TOPO; one twin exists at a time, and fylgja twin destroy clears it"
expect "$OUT/dry-orphan.json" '.status=="rejected" and .dry_run.verdict=="refused"
  and [.findings[] | select(.severity=="rejection") | .rule] == ["host.lab.present"]
  and (.findings[] | select(.rule=="host.lab.present") | .message) == env.ORPHAN_REFUSAL'

destroy_twin 3 "done" "nothing"
expect "$OUT/destroy-3.json" 'any(.cleanup.removed[]; . == "lab fylgja (1 container)")'
[ ! -e "$OUT/orphan/clab-fylgja" ] || fail "case 3: destroy left the orphan's $OUT/orphan/clab-fylgja"
else
  skip_case 3
fi

# --- case 4: the pinned reference again, the same bundle -----------------------
if case_runs 4; then

# The branch read --at T again, as case 2 read it, and created from: the same snapshot, which
# the stores hold already, and the same bundle (M3).
fylgja_cli intent read --branch "$BRANCH" --at "$T" --out "$OUT/snapshot-4-at.json" > "$OUT/read-4-at.out" 2> "$OUT/read-4-at.err" ||
  fail "case 4: fylgja-cli intent read --at $T failed; see $OUT/read-4-at.out and $OUT/read-4-at.err"
CREATE_SNAPSHOT="$OUT/snapshot-4-at.json"
create_twin 4
unset CREATE_SNAPSHOT
BID4=$BID RUN4=$RUN_ID
[ "$BID4" = "$BID2" ] || fail "case 4: the create from a read --at $T gave $BID4, but case 2 gave $BID2"
[ "$SID" = "$SID2" ] || fail "case 4: the read --at $T took snapshot $SID, but case 2 took $SID2"
[ "$RUN4" != "$RUN2" ] || fail "case 4: the create from a read --at $T reports case 2's run $RUN2"
expect "$TWIN/twin.json" '.provenance.at==env.T and .bundle_id==env.BID2'

destroy_twin 4 "done" "done"
destroy_twin 4-again "nothing" "nothing"
else
  skip_case 4
fi

# --- case 5: a twin from a branch is frozen at its snapshot, and stepped (019) ---
if case_runs 5; then

# A throwaway branch: fylgja-fixture is never changed. Set before seeding, so the
# trap deletes a branch the seed left half made.
# The pid and a random number: the seed's marker description carries the branch name, so
# no two runs share one.
FB="fylgja-test-e2e-$$-$RANDOM"
export FB
start=$(now_ns)
seed_status=0
fixture -branch "$FB" > "$OUT/seed-5.out" 2> "$OUT/seed-5.err" || seed_status=$?
SEED_TOOK=$(since "$start")
echo "e2e: case 5: seeding $FB took ${SEED_TOOK}s (exit $seed_status)"
[ "$seed_status" -eq 0 ] || fail "case 5: seeding $FB exited $seed_status; see $OUT/seed-5.err"
# 150s, raised from 60s. The seed is a `go run` compile plus a branch's worth of writes
# to Infrahub, so it is the dev tool's speed and the host's, not a claim about the product:
# 28.0s, 46.9s and 49.6s on a quiet host, and 65.7s on a busy one, which tripped the old
# bound after four cases had passed.
[ "${SEED_TOOK%.*}" -lt 150 ] || fail "case 5: seeding $FB took ${SEED_TOOK}s, over 150s"

BRANCH=$FB
# The probe file (016): n1-loop across n1, from ethernet-1/10 to ethernet-1/11, the seed's two
# probe-ready ports, routed through n1 by their addresses, which the template renders. Its
# second host's address is where the first's burst goes.
PROBES5=testdata/probes/n1-loop.json
PROBE5_FAR=$(jq -r '.probes[0].endpoints[1].address | split("/")[0]' "$PROBES5")
BURST_COUNT=$(psp_scalar "$PROBE_PACKAGE" count)
[ -n "$BURST_COUNT" ] || fail "$PROBE_PACKAGE states no burst count"

# The dry run with the file lists the probe's two hosts among the nodes, after the three
# devices' lines, each on the probe package's image and naming its format where a device
# names its package, with nothing pushed (contracts/cli.md, "016: probes"): the core's
# lines, which fylgja-cli prints on stdout as they arrive (020).
dry5_status=0
fylgja_cli twin create --branch "$FB" --scope tag:fylgja --probes "$PROBES5" --dry-run > "$OUT/dry-5.out" 2> "$OUT/dry-5.err" || dry5_status=$?
[ "$dry5_status" -eq 0 ] || fail "case 5: the dry run with --probes exited $dry5_status; see $OUT/dry-5.out and $OUT/dry-5.err"
awk '/^nodes:$/ { on = 1; next } on && /^  / { print; next } on { exit }' "$OUT/dry-5.out" > "$OUT/dry-5-nodes.txt"
[ "$(wc -l < "$OUT/dry-5-nodes.txt")" -eq 5 ] ||
  fail "case 5: the dry run's nodes: lines name $(wc -l < "$OUT/dry-5-nodes.txt") nodes, not three devices and two hosts; see $OUT/dry-5.out"
for host in n1-loop-a n1-loop-b; do
  grep -qE "^  $host  ${PROBE_IMAGE//./\\.}  ping host  [0-9]+ MiB\$" "$OUT/dry-5-nodes.txt" ||
    fail "case 5: the dry run's nodes: lines name no $host, a ping host on $PROBE_IMAGE pushed nothing; see $OUT/dry-5.out"
done
grep -qx 'verdict: clear' "$OUT/dry-5.out" || fail "case 5: the dry run with --probes is not clear; see $OUT/dry-5.out"
echo "e2e: case 5: the dry run with $PROBES5 lists n1-loop-a and n1-loop-b among the nodes"

# The scope named, fylgja-cli's default (017). The create follows nothing (019): its
# document carries no following block. The file's probe is in its snapshot, and its two hosts
# beside the devices.
HOSTS=2
create_twin 5 --scope tag:fylgja --probes "$PROBES5"
SID5=$SID BID5=$BID RUN5=$RUN_ID
export SID5 BID5 RUN5
expect "$OUT/create-5.json" 'has("following") | not'
expect "$TWIN/twin.json" '.provenance.branch==env.FB and (.provenance | has("at") | not) and .provenance.scope=="tag:fylgja"
  and [.nodes[] | select(.probe != null) | .name] == ["n1-loop-a", "n1-loop-b"]'
expect "$OUT/probes-snapshot-5.json" '.probes == ["n1-loop"]'

# The conformance suite's boot half on this probed twin (016): it reads the three devices as
# case 1's, but for n1's two probe ports' neighbours, skipped with verify's reason since the
# probe's links are synthesized and a host speaks no discovery protocol, and names the two
# hosts it does not read, having no package to read them by. It changes nothing.
start=$(now_ns)
go test -count=1 -tags e2e ./internal/conformance -run '^TestBootHalf$' -v > "$OUT/boot-half-5.out" 2>&1 ||
  fail "case 5: the conformance suite's boot half failed; see $OUT/boot-half-5.out"
BOOT_HALF5_TOOK=$(since "$start")
grep -qF 'boot half: 3 nodes [n1 n2 n3] of run ' "$OUT/boot-half-5.out" ||
  fail "case 5: the boot half read other nodes than n1, n2 and n3; see $OUT/boot-half-5.out"
grep -qF 'boot half: 2 probe hosts not read, having no package to read them by: [n1-loop-a n1-loop-b]' "$OUT/boot-half-5.out" ||
  fail "case 5: the boot half names no hosts n1-loop-a and n1-loop-b not read; see $OUT/boot-half-5.out"
for end in a:10 b:11; do
  grep -qF "skipped: link n1-loop-${end%%:*}:eth1|n1:ethernet-1/${end#*:} is synthesized: n1-loop-${end%%:*} speaks no discovery protocol" "$OUT/boot-half-5.out" ||
    fail "case 5: the boot half skipped no neighbour of n1:ethernet-1/${end#*:} on its synthesized link; see $OUT/boot-half-5.out"
done
grep -qE '^ +boot_e2e_test\.go:[0-9]+: node n1 \(.*\): booted; .*; 2 skipped on synthesized links; ' "$OUT/boot-half-5.out" ||
  fail "case 5: n1's boot-half line counts no 2 skipped on synthesized links; see $OUT/boot-half-5.out"
echo "e2e: case 5: boot half passed in ${BOOT_HALF5_TOOK}s, n1-loop-a and n1-loop-b not read"

# twin verify holds the probe's burst, from its first host to its second's address (016):
# the document by node, and the text's host line and counts line. The probe's two links are
# skipped at both ends, since a host speaks no discovery protocol; nothing else is.
verify_twin 5
expect "$OUT/verify-5.json" '.verify.counts.burst.held==1 and .verify.counts.burst.failed==0
  and .verify.counts.neighbor.skipped==4 and (.verify.counts.port_enabled.skipped // 0)==0
  and ([.verify.nodes[] | select(.probe != null) | {node, bursts: [.bursts[] | {probe, from, to, outcome}]}]
    == [{node: "n1-loop-a", bursts: [{probe: "n1-loop", from: "n1-loop-a", to: "n1-loop-b", outcome: "held"}]},
        {node: "n1-loop-b", bursts: []}])'
fylgja twin verify > "$OUT/verify-5.out" 2> "$OUT/verify-5.err" ||
  fail "case 5: twin verify exited non-zero; see $OUT/verify-5.out and $OUT/verify-5.err"
grep -qE "^n1-loop-a \(ping host, [0-9.]+\): burst n1-loop $BURST_COUNT of $BURST_COUNT replies from n1-loop-b at ${PROBE5_FAR//./\\.} held; " "$OUT/verify-5.out" ||
  fail "case 5: twin verify names no burst n1-loop of $BURST_COUNT replies from n1-loop-b at $PROBE5_FAR held; see $OUT/verify-5.out"
grep -qE '^held: .*; burst 1 held; failed: none; unread: none$' "$OUT/verify-5.out" ||
  fail "case 5: twin verify's counts line holds no burst 1 held, with nothing failed or unread; see $OUT/verify-5.out"
echo "e2e: case 5: the twin carries n1-loop's two hosts, and twin verify holds its burst"

# twin show names the snapshot the twin was built from, and its kind line says so, read at
# the create's read since the reference names no at (019). The line is kept: it must not
# move while the twin is frozen.
fylgja twin show --json > "$OUT/show-5-created.json" 2> "$OUT/show-5-created.err" ||
  fail "case 5: twin show exited non-zero after the create; see $OUT/show-5-created.err"
expect "$OUT/show-5-created.json" '.show.kind=="snapshot" and .show.record.snapshot_id==env.SID5 and .show.record.bundle_id==env.BID5'
fylgja twin show > "$OUT/show-5-created.out" 2> "$OUT/show-5-created.err" ||
  fail "case 5: twin show exited non-zero after the create; see $OUT/show-5-created.err"
printf 'kind: snapshot %s… (branch %s, read at %s)\n' "${SID5:0:8}" "$FB" "$(jq -r .observed_at "$TWIN/twin.json")" > "$OUT/kind-5.txt"
grep '^kind: ' "$OUT/show-5-created.out" | cmp -s "$OUT/kind-5.txt" - ||
  fail "case 5: twin show's kind line is not $(cat "$OUT/kind-5.txt"); see $OUT/show-5-created.out"

# What a following build's check would have rebuilt, taken now: twin.json, the lab's
# containers, found by containerlab's own label containerlab=fylgja, and the instant after
# which no run of any type may start. UTC to the nanosecond, a form the workflow service's
# list query takes.
twin_before=$(sha256sum < "$TWIN/twin.json")
containers_before=$(docker ps -q --no-trunc --filter label=containerlab=fylgja | LC_ALL=C sort)
[ "$(grep -c . <<< "$containers_before")" -eq "$NODES" ] ||
  fail "case 5: docker lists $(grep -c . <<< "$containers_before") containers of lab fylgja, not $NODES"
CREATED5=$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)

# The artifact-only change: n1's ethernet-1/2 disabled, which the compiler does not see,
# then generated. Once the checksum has moved the change is visible to a read, where a
# following build's next check could first have seen it; FROZEN_WAIT_S from there, nothing
# has moved and nothing has started.
artifacts_of "$FB" "$OUT/artifacts-5a-before.json" 2> "$OUT/artifacts-5a-before.err" ||
  fail "case 5: reading $FB's artifacts failed; see $OUT/artifacts-5a-before.err"
fixture -branch "$FB" -disable-port n1:ethernet-1/2 -generate > "$OUT/disable-port-5.out" 2> "$OUT/disable-port-5.err" ||
  fail "case 5: -disable-port n1:ethernet-1/2 -generate on $FB failed; see $OUT/disable-port-5.err"
await_checksums_moved 5a "$FB" "$OUT/artifacts-5a-before.json" n1
MOVED5=$(now_ns)
echo "e2e: case 5: the twin frozen, waiting ${FROZEN_WAIT_S}s from the change"
sleep "$FROZEN_WAIT_S"
FROZEN5_TOOK=$(since "$MOVED5")
[ "$twin_before" = "$(sha256sum < "$TWIN/twin.json")" ] || fail "case 5: twin.json changed while the twin was frozen"
[ "$containers_before" = "$(docker ps -q --no-trunc --filter label=containerlab=fylgja | LC_ALL=C sort)" ] ||
  fail "case 5: lab fylgja's containers changed while the twin was frozen"
fylgja twin show > "$OUT/show-5-frozen.out" 2> "$OUT/show-5-frozen.err" ||
  fail "case 5: twin show exited non-zero after the frozen wait; see $OUT/show-5-frozen.err"
grep '^kind: ' "$OUT/show-5-frozen.out" | cmp -s "$OUT/kind-5.txt" - ||
  fail "case 5: twin show's kind line moved while the twin was frozen; compare $OUT/kind-5.txt with $OUT/show-5-frozen.out"
temporal workflow list --address "$TEMPORAL_ADDRESS" --query "StartTime > '$CREATED5'" -o json \
  > "$OUT/runs-5-frozen.json" 2> "$OUT/runs-5-frozen.err" || fail "case 5: temporal workflow list failed; see $OUT/runs-5-frozen.err"
expect "$OUT/runs-5-frozen.json" 'length == 0'
echo "e2e: case 5: ${FROZEN5_TOOK}s after the change, twin.json, the containers and the kind line had not moved, and no run had started since $CREATED5"

# A step to a snapshot of the changed branch, by file (019): fylgja-cli intent read --out
# writes it, with the probe file, so it carries the twin's probe (016), and twin compile
# names its bundle, which the step deploys with nothing read from Infrahub. The record then names that
# snapshot and bundle, still no stage, and keeps its source; the step's document and the
# record name the probe's flow across it, measured on the container's basis.
compiled_id 5a --probes "$PROBES5"
SID5A=$COMPILED_SNAPSHOT BID5A=$COMPILED_ID
export SID5A BID5A
[ "$BID5A" != "$BID5" ] || fail "case 5: the artifact-only change left the compiled bundle_id at $BID5"
echo "e2e: case 5: n1:ethernet-1/2 disabled on $FB; snapshot $SID5A compiles to $BID5A"
start=$(now_ns)
step5a_status=0
fylgja twin step --snapshot "$OUT/snapshot-5a.json" --json > "$OUT/step-5a.json" 2> "$OUT/step-5a.err" || step5a_status=$?
STEP5A_TOOK=$(since "$start")
echo "e2e: case 5: step to snapshot ${SID5A:0:8}… by file took ${STEP5A_TOOK}s (exit $step5a_status)"
[ "$step5a_status" -eq 0 ] || fail "case 5: twin step --snapshot exited $step5a_status; see $OUT/step-5a.json and $OUT/step-5a.err"
expect "$OUT/step-5a.json" '.status=="ok" and .operation=="twin.step" and .snapshot_id==env.SID5A and .bundle_id==env.BID5A
  and .step.outcome=="stepped" and .step.state=="ready" and .step.run.workflow_id=="fylgja-step"
  and .step.from.stage==null and .step.from.snapshot_id==env.SID5 and .step.from.bundle_id==env.BID5
  and .step.to.stage==null and .step.to.snapshot_id==env.SID5A and .step.to.bundle_id==env.BID5A
  and any(.step.pushed[]; .node=="n1") and all(.step.pushed[]; .outcome=="landed")'
RUN5A=$(jq -r .subject.run_id "$OUT/step-5a.json")
export RUN5A
expect "$TWIN/twin.json" '.twin_version=="12" and .rehearsal==null and .state=="ready" and .source=="snapshot" and .stage==null
  and .snapshot_id==env.SID5A and .bundle_id==env.BID5A
  and .provenance.branch==env.FB and (.provenance | has("at") | not) and .provenance.scope=="tag:fylgja"
  and .step.outcome=="stepped" and .step.run.run_id==env.RUN5A and .step.phase==null
  and .step.from.stage==null and .step.from.snapshot_id==env.SID5 and .step.from.bundle_id==env.BID5
  and .step.to.stage==null and .step.to.snapshot_id==env.SID5A and .step.to.bundle_id==env.BID5A
  and all(.nodes[]; .holds==env.BID5A)'
cp "$TWIN/twin.json" "$OUT/twin-5a.json"
step_loss_measured 5a n1-loop
LOSS5A=$LOSS_FIGURE
no_credential "the artifact marker" "$MARKER" "$TWIN/twin.json"
jq -e --slurpfile a "$OUT/artifacts-5a.json" '(.nodes[] | select(.name=="n1") | .artifact.checksum) == $a[0].n1.checksum' "$TWIN/twin.json" > /dev/null ||
  fail "case 5: twin.json does not carry n1's new checksum $(jq -r .n1.checksum "$OUT/artifacts-5a.json")"
readback 5a "$FB" disable
history_of step-5a fylgja-step "$RUN5A"

# twin verify on the stepped twin: intent disables n1:ethernet-1/2, so that port and its
# link's two ends are skipped, each named with its reason, and nothing is found. The
# bundle's mapping row carries enabled false; the node reads disable. The probe's two links
# are skipped at both ends, as at the create, and its burst holds (016). The twin is named
# by the snapshot its staged bundle was compiled from (019).
verify_twin 5a
VERIFY5_TOOK=$VERIFY_TOOK
expect "$OUT/verify-5a.json" '.verify.counts.port_enabled.skipped==1 and .verify.counts.neighbor.skipped==6
  and .verify.counts.burst.held==1
  and ([.verify.skipped[] | "\(.node):\(.port) \(.link)"] | sort)
    == ["n1-loop-a:eth1 n1-loop-a:eth1|n1:ethernet-1/10", "n1-loop-b:eth1 n1-loop-b:eth1|n1:ethernet-1/11",
        "n1:ethernet-1/10 n1-loop-a:eth1|n1:ethernet-1/10", "n1:ethernet-1/11 n1-loop-b:eth1|n1:ethernet-1/11",
        "n1:ethernet-1/2 n1:ethernet-1/2|n3:ethernet-1/2", "n1:ethernet-1/2 null", "n3:ethernet-1/2 n1:ethernet-1/2|n3:ethernet-1/2"]
  and .verify.twin.snapshot_id==env.SID5A and .verify.twin.bundle_id==env.BID5A'

# The topology change: a third link, which moves n1's and n3's artifacts too; the
# fixture tool generates after it. fylgja-cli intent read --out files its snapshot in the
# orchestrator's store, which the core does not read (020), so a dry run of the step by file
# files it in the core's, beside the twin, changing nothing else; the step then names it by
# that id: the link re-cabled live on n1 and n3, as case 7's.
cp "$OUT/artifacts-5a.json" "$OUT/artifacts-5b-before.json"
fixture -branch "$FB" -add-link > "$OUT/add-link-5.out" 2> "$OUT/add-link-5.err" ||
  fail "case 5: -add-link on $FB failed; see $OUT/add-link-5.err"
await_checksums_moved 5b "$FB" "$OUT/artifacts-5b-before.json" n1 n3
compiled_id 5b --probes "$PROBES5"
SID5B=$COMPILED_SNAPSHOT BID5B=$COMPILED_ID
export SID5B BID5B
[ "$BID5B" != "$BID5A" ] || fail "case 5: the branch change left the compiled bundle_id at $BID5A"
twin_before=$(sha256sum < "$TWIN/twin.json")
dry5b_status=0
fylgja twin step --snapshot "$OUT/snapshot-5b.json" --dry-run --json > "$OUT/step-5b-dry.json" 2> "$OUT/step-5b-dry.err" || dry5b_status=$?
[ "$dry5b_status" -eq 0 ] || fail "case 5: twin step --snapshot $OUT/snapshot-5b.json --dry-run exited $dry5b_status; see $OUT/step-5b-dry.json"
expect "$OUT/step-5b-dry.json" '.status=="ok" and .operation=="twin.step" and .dry_run.verdict=="clear"
  and .snapshot_id==env.SID5B and .bundle_id==env.BID5B and (.step | has("run") | not)'
[ "$twin_before" = "$(sha256sum < "$TWIN/twin.json")" ] || fail "case 5: the step's dry run changed twin.json"
[ -f "$FYLGJA_STATE_ROOT/snapshots/$SID5B.json" ] || fail "case 5: the step's dry run by file filed no snapshot $SID5B in the core's store"
echo "e2e: case 5: $FB changed; snapshot $SID5B compiles to $BID5B, filed in the core's store by the step's dry run"
start=$(now_ns)
step5b_status=0
fylgja twin step --snapshot "$SID5B" --json > "$OUT/step-5b.json" 2> "$OUT/step-5b.err" || step5b_status=$?
STEP5B_TOOK=$(since "$start")
echo "e2e: case 5: step to snapshot ${SID5B:0:8}… by id took ${STEP5B_TOOK}s (exit $step5b_status)"
[ "$step5b_status" -eq 0 ] || fail "case 5: twin step --snapshot $SID5B exited $step5b_status; see $OUT/step-5b.json and $OUT/step-5b.err"
expect "$OUT/step-5b.json" '.status=="ok" and .operation=="twin.step" and .snapshot_id==env.SID5B and .bundle_id==env.BID5B
  and .subject.snapshot==env.SID5B and .step.outcome=="stepped" and .step.state=="ready"
  and .step.from.stage==null and .step.from.snapshot_id==env.SID5A and .step.from.bundle_id==env.BID5A
  and .step.to.stage==null and .step.to.snapshot_id==env.SID5B and .step.to.bundle_id==env.BID5B
  and (.step.reconcile.links_added | length) == 1 and all(.step.pushed[]; .outcome=="landed")'
RUN5B=$(jq -r .subject.run_id "$OUT/step-5b.json")
export RUN5B
expect "$TWIN/twin.json" '.state=="ready" and .source=="snapshot" and .stage==null
  and .snapshot_id==env.SID5B and .bundle_id==env.BID5B and .provenance.branch==env.FB
  and .step.outcome=="stepped" and .step.run.run_id==env.RUN5B
  and .step.from.snapshot_id==env.SID5A and .step.to.snapshot_id==env.SID5B
  and all(.nodes[]; .holds==env.BID5B)'
cp "$TWIN/twin.json" "$OUT/twin-5b.json"
step_loss_measured 5b n1-loop
LOSS5B=$LOSS_FIGURE
no_credential "the artifact marker" "$MARKER" "$TWIN/twin.json"
readback 5b "$FB" disable
history_of step-5b fylgja-step "$RUN5B"

# twin show names the snapshot the twin was stepped to, read at that snapshot's read, and
# the step from 5a's (019).
fylgja twin show --json > "$OUT/show-5-stepped.json" 2> "$OUT/show-5-stepped.err" ||
  fail "case 5: twin show exited non-zero after the steps; see $OUT/show-5-stepped.err"
expect "$OUT/show-5-stepped.json" '.show.kind=="snapshot" and .show.record.snapshot_id==env.SID5B and .show.record.bundle_id==env.BID5B
  and .show.record.step.outcome=="stepped"'
fylgja twin show > "$OUT/show-5-stepped.out" 2> "$OUT/show-5-stepped.err" ||
  fail "case 5: twin show exited non-zero after the steps; see $OUT/show-5-stepped.err"
KIND5B="kind: snapshot ${SID5B:0:8}… (branch $FB, read at $(jq -r .observed_at "$TWIN/twin.json")) (stepped from snapshot ${SID5A:0:8}… by run fylgja-step $RUN5B, ended "
grep -qF -- "$KIND5B" "$OUT/show-5-stepped.out" ||
  fail "case 5: twin show's kind line does not begin $KIND5B; see $OUT/show-5-stepped.out"

destroy_twin 5 "done" "done"
DESTROY5_TOOK=$DESTROY_TOOK
HOSTS=0

if fixture -branch "$FB" -delete > "$OUT/delete-branch-5.out" 2>&1; then
  unset FB
else
  echo "e2e: case 5: branch $FB was not deleted; remove it with: go run -tags fixture ./cmd/fylgja-fixture -branch $FB -delete" >&2
fi
else
  skip_case 5
fi

# --- case 6: one twin of two platforms (M7) ------------------------------------
if case_runs 6; then

# A throwaway branch of its own, seeded with the mixed fixture: s1 on SR Linux, e1 and e2
# on EOS, with one link of each kind between them. Made on the host case 5's
# destroy left clean, and set before seeding so the trap deletes a branch a half-made seed
# left behind.
FM="fylgja-test-e2e-mixed-$$-$RANDOM"
export FM
start=$(now_ns)
seed_status=0
fixture -branch "$FM" -mixed > "$OUT/seed-6.out" 2> "$OUT/seed-6.err" || seed_status=$?
SEED6_TOOK=$(since "$start")
echo "e2e: case 6: seeding $FM took ${SEED6_TOOK}s (exit $seed_status)"
[ "$seed_status" -eq 0 ] || fail "case 6: seeding $FM with -mixed exited $seed_status; see $OUT/seed-6.err"

# One lab, two platforms, each node under its own package's budgets. The read-back is
# readback_mixed, which reads each node the way its own package says to.
BRANCH=$FM
READBACK=
create_twin 6
READBACK=readback
BID6=$BID RUN6=$RUN_ID
export BID6 RUN6
readback_mixed 6 "$FM"

# The conformance suite's boot half on this twin: it reads every node, so the
# EOS package's checks run against a booted node here. It changes nothing.
start=$(now_ns)
go test -count=1 -tags e2e ./internal/conformance -run '^TestBootHalf$' -v > "$OUT/boot-half-6.out" 2>&1 ||
  fail "case 6: the conformance suite's boot half failed; see $OUT/boot-half-6.out"
BOOT_HALF6_TOOK=$(since "$start")
echo "e2e: case 6: boot half passed in ${BOOT_HALF6_TOOK}s"

# twin verify on the mixed twin: each node read over its own package's
# transport, SR Linux's gNMI on 57400 and EOS's on 6030, and both cross-vendor adjacencies
# held from both ends.
verify_twin 6
VERIFY6_TOOK=$VERIFY_TOOK
# shellcheck disable=SC2016 # a jq filter, whose $psp is jq's
expect "$OUT/verify-6.json" '([.verify.nodes[] | {key: .node, value: .psp}] | from_entries) as $psp
  | ([.verify.nodes[] | {node, port: (.addr | split(":") | last)}] | sort_by(.node))
    == [{node: "e1", port: "6030"}, {node: "e2", port: "6030"}, {node: "s1", port: "57400"}]
  and ([.verify.links[] | select($psp[.a.node] != $psp[.b.node])] | length) == 2
  and all(.verify.links[]; .a.outcome=="held" and .b.outcome=="held")'

# twin show names the package each node runs under, which is how an operator tells the
# nodes of a mixed twin apart.
fylgja twin show --json > "$OUT/show-6.json" 2> "$OUT/show-6.err" ||
  fail "case 6: twin show exited non-zero; see $OUT/show-6.err"
expect "$OUT/show-6.json" '([.show.host.nodes[] | {name, psp}] | sort_by(.name))
  == [{name: "e1", psp: "arista_eos"}, {name: "e2", psp: "arista_eos"}, {name: "s1", psp: "nokia_srlinux"}]'

destroy_twin 6 "done" "done"

if fixture -branch "$FM" -delete > "$OUT/delete-branch-6.out" 2>&1; then
  unset FM
else
  echo "e2e: case 6: branch $FM was not deleted; remove it with: go run -tags fixture ./cmd/fylgja-fixture -branch $FM -delete" >&2
fi
else
  skip_case 6
fi

# --- case 7: a twin from a stage, stepped through its proposed change (014) -----
if case_runs 7; then

# A throwaway branch, set before seeding so the trap's -delete removes it and what hangs on
# it: its stages, then its proposed change, then the branch, since a stage outlives its
# branch and Infrahub refuses a proposed change's delete while a stage names it. Made on the
# host case 6's destroy left clean.
FP="fylgja-test-e2e-st-$$-$RANDOM"
export FP
start=$(now_ns)
seed_status=0
fixture -branch "$FP" > "$OUT/seed-7.out" 2> "$OUT/seed-7.err" || seed_status=$?
SEED7_TOOK=$(since "$start")
echo "e2e: case 7: seeding $FP took ${SEED7_TOOK}s (exit $seed_status)"
[ "$seed_status" -eq 0 ] || fail "case 7: seeding $FP exited $seed_status; see $OUT/seed-7.err"

# The draft proposed change. Its pipeline renders the branch's artifacts, and -propose waits
# for its validators, so the creation's rendering cannot land after the first mark.
start=$(now_ns)
fixture -branch "$FP" -propose > "$OUT/propose-7.out" 2> "$OUT/propose-7.err" ||
  fail "case 7: -propose on $FP failed; see $OUT/propose-7.err"
PROPOSE7_TOOK=$(since "$start")
echo "e2e: case 7: a draft proposed change opened on $FP, its validators concluded, in ${PROPOSE7_TOOK}s"

# Each stage is marked after the writes it seals and after their artifacts are rendered
# (schema/README.md); one marked before is refused stale. The seed waits for its artifacts
# to be Ready. -add-link's generate returns before n1's and n3's are rewritten, so the
# second mark waits for their checksums to move, as tier 2's does. What Infrahub held when
# the first was marked is kept: the twin at that stage is read back against it.
artifacts_of "$FP" "$OUT/artifacts-7-sealed-1.json" 2> "$OUT/artifacts-7-sealed-1.err" ||
  fail "case 7: reading $FP's artifacts failed; see $OUT/artifacts-7-sealed-1.err"
expect "$OUT/artifacts-7-sealed-1.json" 'length == 3 and all(.[]; .status == "Ready")'
fixture -branch "$FP" -stage seeded -description seeded > "$OUT/stage-7-seeded.out" 2> "$OUT/stage-7-seeded.err" ||
  fail "case 7: marking stage $FP/seeded failed; see $OUT/stage-7-seeded.err"
fixture -branch "$FP" -add-link > "$OUT/add-link-7.out" 2> "$OUT/add-link-7.err" ||
  fail "case 7: -add-link on $FP failed; see $OUT/add-link-7.err"
await_checksums_moved 7 "$FP" "$OUT/artifacts-7-sealed-1.json" n1 n3
fixture -branch "$FP" -stage third-link -description "third link" > "$OUT/stage-7-third-link.out" 2> "$OUT/stage-7-third-link.err" ||
  fail "case 7: marking stage $FP/third-link failed; see $OUT/stage-7-third-link.err"

# The plan, fylgja-cli's (020): no lab, no worker, no workflow service; the core compiles
# each stage and diffs each pair, and reads nothing. Four stages in order. The branch point
# is main at the branch's creation, which holds no tagged device on this install, so its
# read is refused scope.empty (017 R-20) and the plan exits 1. The two marks and the head
# compile to three ids, the head's at being its own. Three steps: the first not computed;
# the second the third link, with n1 and n3 re-rendered and re-bootstrapped for it (mapping
# may stand beside bootstrap, since the link gives both ends the interface ethernet-1/3);
# the third unchanged, since nothing was written after the second mark but the mark.
start=$(now_ns)
plan_status=0
fylgja_cli stage plan --branch "$FP" --json > "$OUT/plan-7.json" 2> "$OUT/plan-7.err" || plan_status=$?
PLAN7_TOOK=$(since "$start")
echo "e2e: case 7: plan took ${PLAN7_TOOK}s (exit $plan_status)"
[ "$plan_status" -eq 1 ] ||
  fail "case 7: stage plan --branch $FP exited $plan_status, not 1 for its refused branch point; see $OUT/plan-7.json and $OUT/plan-7.err"
expect "$OUT/plan-7.json" '.status=="rejected" and .operation=="stage.plan" and .plan.branch==env.FP
  and .plan.proposed_change.name==env.FP and .plan.proposed_change.branch==env.FP and .plan.proposed_change.draft
  and [.plan.stages[] | {ref, at_source}]
    == [{ref: (env.FP + "/branch-point"), at_source: "branch_point"}, {ref: (env.FP + "/seeded"), at_source: "written"},
        {ref: (env.FP + "/third-link"), at_source: "written"}, {ref: (env.FP + "/head"), at_source: "head"}]
  and [.findings[] | select(.severity=="rejection") | .rule] == ["scope.empty"]
  and (.plan.stages[0] | .branch=="main" and .snapshot_id==null and .bundle_id==null
    and [.findings[] | select(.severity=="rejection") | .rule] == ["scope.empty"])
  and all(.plan.stages[1:][]; .branch==env.FP and (.snapshot_id | type)=="string" and (.bundle_id | type)=="string"
    and (.findings | length)==0)
  and [.plan.stages[1:][].description] == ["seeded", "third link", ""]
  and ([.plan.stages[1:][].snapshot_id] | unique | length) == 3
  and ([.plan.stages[1:][].bundle_id] | unique | length) == 3
  and (.plan.steps | length) == 3'
PC7=$(jq -r '.plan.proposed_change.id' "$OUT/plan-7.json")
AT7B=$(jq -r '.plan.stages[0].at' "$OUT/plan-7.json")
PLAN7S=$(jq -r '.plan.stages[1].bundle_id' "$OUT/plan-7.json")
PLAN7T=$(jq -r '.plan.stages[2].bundle_id' "$OUT/plan-7.json")
PLAN7H=$(jq -r '.plan.stages[3].bundle_id' "$OUT/plan-7.json")
SNAP7S=$(jq -r '.plan.stages[1].snapshot_id' "$OUT/plan-7.json")
SNAP7T=$(jq -r '.plan.stages[2].snapshot_id' "$OUT/plan-7.json")
SNAP7H=$(jq -r '.plan.stages[3].snapshot_id' "$OUT/plan-7.json")
AT7S=$(jq -r '.plan.stages[1].at' "$OUT/plan-7.json")
AT7T=$(jq -r '.plan.stages[2].at' "$OUT/plan-7.json")
AT7H=$(jq -r '.plan.stages[3].at' "$OUT/plan-7.json")
export PC7 AT7B PLAN7S PLAN7T PLAN7H SNAP7S SNAP7T SNAP7H AT7S AT7T AT7H
expect "$OUT/plan-7.json" '(.plan.steps[0] | (.computed | not)
    and .from==(env.FP + "/branch-point") and .to==(env.FP + "/seeded"))
  and (.plan.steps[1] | .computed and (.unchanged | not)
    and .from==(env.FP + "/seeded") and .to==(env.FP + "/third-link")
    and .from_bundle_id==env.PLAN7S and .to_bundle_id==env.PLAN7T
    and .nodes.added == [] and .nodes.removed == []
    and [.nodes.changed[].node] == ["n1", "n3"]
    and all(.nodes.changed[]; any(.reasons[]; .=="bootstrap") and all(.reasons[]; .=="bootstrap" or .=="mapping"))
    and .links.removed == [] and (.links.added | length) == 1
    and ([.links.added[0].a.node, .links.added[0].b.node] | sort) == ["n1", "n3"]
    and [.artifacts.changed[].node] == ["n1", "n3"])
  and (.plan.steps[2] | .computed and .unchanged
    and .from==(env.FP + "/third-link") and .to==(env.FP + "/head")
    and .from_bundle_id==env.PLAN7T and .to_bundle_id==env.PLAN7H)'
echo "e2e: case 7: plan $FP/seeded $PLAN7S at $AT7S, $FP/third-link $PLAN7T at $AT7T, $FP/head $PLAN7H at $AT7H; the branch point refused; one link added, n1 and n3 changed; the head unchanged"

# The list, before any twin: the four stages, each resolving as the plan did, and no record:
# case 6's create, from a branch, left none.
fylgja_cli stage list --branch "$FP" --json > "$OUT/list-7-before.json" 2> "$OUT/list-7-before.err" ||
  fail "case 7: stage list --branch $FP exited non-zero; see $OUT/list-7-before.json and $OUT/list-7-before.err"
expect "$OUT/list-7-before.json" '.status=="ok" and .stages.branch==env.FP and .stages.record==null
  and [.stages.rows[] | {ref, branch, at, at_source, twin}]
    == [{ref: (env.FP + "/branch-point"), branch: "main", at: env.AT7B, at_source: "branch_point", twin: false},
        {ref: (env.FP + "/seeded"), branch: env.FP, at: env.AT7S, at_source: "written", twin: false},
        {ref: (env.FP + "/third-link"), branch: env.FP, at: env.AT7T, at_source: "written", twin: false},
        {ref: (env.FP + "/head"), branch: env.FP, at: env.AT7H, at_source: "head", twin: false}]
  and all(.stages.rows[]; .proposed_change.id==env.PC7)'

# The twin from the first mark: the plan's id, pinned at its at; twin.json 12 names no stage
# and no rehearsal, and the orchestrator's record names the stage and its proposed change
# (020, R-09). It is read back against what Infrahub held when the mark was made, since
# -add-link has moved n1's and n3's artifacts since.
BRANCH=$FP
READBACK=
CREATE_REF="$FP/seeded"
create_twin 7
CREATE7_TOOK=$CREATE_TOOK
[ "$BID" = "$PLAN7S" ] || fail "case 7: create --stage $FP/seeded deployed $BID, but the plan printed $PLAN7S"
# One stage taken twice, by the plan and by the create, is one snapshot (018, SC-002).
[ "$SID" = "$SNAP7S" ] || fail "case 7: create --stage $FP/seeded took snapshot $SID, but the plan printed $SNAP7S"
expect "$OUT/create-7.json" '.subject.stage==(env.FP + "/seeded") and .subject.branch==env.FP and .subject.at==env.AT7S
  and .stage == {ref: (env.FP + "/seeded"), branch: env.FP, label: "seeded",
    proposed_change: {id: env.PC7, name: env.FP, branch: env.FP, draft: true},
    at: env.AT7S, at_source: "written", description: "seeded"}'
expect "$TWIN/twin.json" '.twin_version=="12" and .rehearsal==null and .stage==null and .provenance.branch==env.FP
  and .provenance.at==env.AT7S and .step==null'
expect "$ORCH_RECORD" '.record_version=="1" and .flow=="twin-create" and .snapshot_id==env.SNAP7S
  and .stage == {branch: env.FP, label: "seeded", at: env.AT7S} and .proposed_change == {id: env.PC7, branch: env.FP}'
cp "$ORCH_RECORD" "$OUT/record-7.json"
readback 7 "$FP" enable "$OUT/artifacts-7-sealed-1.json"

fylgja twin show --json > "$OUT/show-7.json" 2> "$OUT/show-7.err" ||
  fail "case 7: twin show exited non-zero; see $OUT/show-7.err"
expect "$OUT/show-7.json" '.show.kind=="snapshot" and .show.record.snapshot_id==env.SNAP7S and .show.record.bundle_id==env.PLAN7S and .show.record.at==env.AT7S
  and .show.record.stage==null'

# The list marks the twin's stage from the orchestrator's record, trusted while twin show
# names its snapshot (020, R-09).
fylgja_cli stage list --branch "$FP" --json > "$OUT/list-7.json" 2> "$OUT/list-7.err" ||
  fail "case 7: stage list exited non-zero beside the twin; see $OUT/list-7.json and $OUT/list-7.err"
expect "$OUT/list-7.json" '.status=="ok"
  and .stages.record == {ref: (env.FP + "/seeded"), proposed_change: {id: env.PC7, branch: env.FP}, label: "seeded",
    branch: env.FP, at: env.AT7S, at_source: "written", state: "ready", towards: null}
  and [.stages.rows[] | select(.twin) | .ref] == [env.FP + "/seeded"]
  and ([.findings[] | select(.rule=="stage.twin.moved")] | length) == 0'

# A step with no target goes to the next stage of the record's, the second mark: fylgja-cli
# reads and files it, and the core steps to its snapshot (020): the third link re-cabled
# live on n1 and n3, which SR Linux's package allows with no restart, and both pushed by
# replace; n2 untouched. The branch has not moved since the mark, so Infrahub's artifacts
# now are the ones it sealed.
start=$(now_ns)
step7a_status=0
fylgja_cli twin step --json > "$OUT/step-7a.json" 2> "$OUT/step-7a.err" || step7a_status=$?
STEP7A_TOOK=$(since "$start")
echo "e2e: case 7: step to $FP/third-link took ${STEP7A_TOOK}s (exit $step7a_status)"
[ "$step7a_status" -eq 0 ] || fail "case 7: twin step exited $step7a_status; see $OUT/step-7a.json and $OUT/step-7a.err"
expect "$OUT/step-7a.json" '.status=="ok" and .operation=="twin.step" and .snapshot_id==env.SNAP7T and .bundle_id==env.PLAN7T
  and .subject.stage==(env.FP + "/third-link") and .stage.at==env.AT7T and .stage.at_source=="written"
  and .step.outcome=="stepped" and .step.state=="ready" and .step.run.workflow_id=="fylgja-step"
  and .step.from.snapshot_id==env.SNAP7S and (.step.to.snapshot_id | type)=="string" and .step.to.snapshot_id==env.SNAP7T'
RUN7A=$(jq -r .subject.run_id "$OUT/step-7a.json")
export RUN7A
expect "$TWIN/twin.json" '.twin_version=="12" and .rehearsal==null and .state=="ready" and .bundle_id==env.PLAN7T
  and .provenance.branch==env.FP and .provenance.at==env.AT7T and .stage==null
  and .step.outcome=="stepped" and .step.run.run_id==env.RUN7A and .step.phase==null
  and .snapshot_id==env.SNAP7T
  and .step.from.stage==null and .step.from.snapshot_id==env.SNAP7S and .step.from.bundle_id==env.PLAN7S
  and .step.to.stage==null and (.step.to.snapshot_id | type)=="string" and .step.to.snapshot_id==env.SNAP7T
  and .step.to.bundle_id==env.PLAN7T
  and .step.reconcile.restarted == [] and .step.reconcile.recreated == [] and .step.reconcile.added == []
  and (.step.reconcile.links_added | length) == 1
  and [.step.pushed[] | {node, outcome}] == [{node: "n1", outcome: "landed"}, {node: "n3", outcome: "landed"}]
  and all(.nodes[]; .holds==env.PLAN7T)'
cp "$TWIN/twin.json" "$OUT/twin-7a.json"
expect "$ORCH_RECORD" '.flow=="twin-step" and .snapshot_id==env.SNAP7T
  and .stage == {branch: env.FP, label: "third-link", at: env.AT7T} and .proposed_change == {id: env.PC7, branch: env.FP}'
no_credential "the artifact marker" "$MARKER" "$TWIN/twin.json"
readback 7a "$FP" enable
history_of step-7a fylgja-step "$RUN7A"

# A second step with no target goes to the head, the stage after the second mark. Nothing
# was written after the mark but the mark, so the two bundles differ in provenance alone:
# the step is unchanged, nothing is reconciled or pushed, and the record moves to the head
# (US2's second scenario). The list then marks the head, which has not moved.
start=$(now_ns)
step7b_status=0
fylgja_cli twin step --json > "$OUT/step-7b.json" 2> "$OUT/step-7b.err" || step7b_status=$?
STEP7B_TOOK=$(since "$start")
echo "e2e: case 7: step to $FP/head took ${STEP7B_TOOK}s (exit $step7b_status)"
[ "$step7b_status" -eq 0 ] || fail "case 7: the second twin step exited $step7b_status; see $OUT/step-7b.json and $OUT/step-7b.err"
expect "$OUT/step-7b.json" '.status=="ok" and .operation=="twin.step" and .snapshot_id==env.SNAP7H and .bundle_id==env.PLAN7H
  and .subject.stage==(env.FP + "/head") and .stage.at==env.AT7H and .stage.at_source=="head"
  and .step.outcome=="unchanged" and (.step.to.snapshot_id | type)=="string" and .step.to.snapshot_id==env.SNAP7H'
RUN7B=$(jq -r .subject.run_id "$OUT/step-7b.json")
export RUN7B
expect "$TWIN/twin.json" '.state=="ready" and .snapshot_id==env.SNAP7H and .bundle_id==env.PLAN7H and .provenance.at==env.AT7H
  and .stage==null and .step.outcome=="unchanged" and .step.run.run_id==env.RUN7B
  and .step.from.snapshot_id==env.SNAP7T and .step.from.bundle_id==env.PLAN7T
  and (.step.to.snapshot_id | type)=="string" and .step.to.snapshot_id==env.SNAP7H and .step.to.bundle_id==env.PLAN7H
  and .step.reconcile.skipped and (.step.pushed | length) == 0
  and all(.nodes[]; .holds==env.PLAN7H)'
cp "$TWIN/twin.json" "$OUT/twin-7b.json"
expect "$ORCH_RECORD" '.flow=="twin-step" and .snapshot_id==env.SNAP7H
  and .stage == {branch: env.FP, label: "head", at: env.AT7H} and .proposed_change == {id: env.PC7, branch: env.FP}'
no_credential "the artifact marker" "$MARKER" "$TWIN/twin.json"
history_of step-7b fylgja-step "$RUN7B"
fylgja_cli stage list --branch "$FP" --json > "$OUT/list-7b.json" 2> "$OUT/list-7b.err" ||
  fail "case 7: stage list exited non-zero beside the twin at the head; see $OUT/list-7b.json and $OUT/list-7b.err"
expect "$OUT/list-7b.json" '.status=="ok" and .stages.record.label=="head" and .stages.record.at==env.AT7H
  and .stages.record.state=="ready" and [.stages.rows[] | select(.twin) | .ref] == [env.FP + "/head"]
  and ([.findings[] | select(.rule=="stage.twin.moved")] | length) == 0'

destroy_twin 7 "done" "done"
unset CREATE_REF
READBACK=readback

# The branch goes with its stages and its proposed change, in that order, and -delete says
# so; Infrahub then holds none of them. The product then lists no stage of the branch, and
# plans none: no open proposed change has it as its source. The record outlives the destroy,
# which is the core's, and is distrusted now that twin show names no snapshot: the list says
# so and marks no row (020, R-09). A failed delete fails the case, and the trap tries it
# again.
if fixture -branch "$FP" -delete > "$OUT/delete-branch-7.out" 2>&1; then
  grep -qxF "deleted 2 stages, 1 proposed change, branch $FP" "$OUT/delete-branch-7.out" ||
    fail "case 7: -delete on $FP did not report its two stages and its proposed change; see $OUT/delete-branch-7.out"
  infrahub_holds_none 7 "$FP"
  fylgja_cli stage list --branch "$FP" --json > "$OUT/list-7-deleted.json" 2> "$OUT/list-7-deleted.err" ||
    fail "case 7: stage list --branch $FP exited non-zero after the delete; see $OUT/list-7-deleted.err"
  expect "$OUT/list-7-deleted.json" '.status=="ok" and .stages.branch==env.FP and .stages.rows == []
    and .stages.record==null and any(.findings[]; .rule=="record.twin.stale")'
  plan_status=0
  fylgja_cli stage plan --branch "$FP" --json > "$OUT/plan-7-deleted.json" 2> "$OUT/plan-7-deleted.err" || plan_status=$?
  [ "$plan_status" -eq 1 ] || fail "case 7: stage plan --branch $FP exited $plan_status after the delete, not 1; see $OUT/plan-7-deleted.json"
  expect "$OUT/plan-7-deleted.json" '.status=="rejected" and [.findings[] | select(.severity=="rejection") | .rule] == ["stage.unknown"]'
  unset FP
else
  fail "case 7: -delete on $FP failed, leaving its branch, stages or proposed change; see $OUT/delete-branch-7.out"
fi
else
  skip_case 7
fi

# --- case 8: a stage's twin steps through its proposed change (M11, 014) --------
if case_runs 8; then

# containers_of FILE: each node's container, its id and its start time, one line per node
# sorted by name, from docker rather than containerlab: a restart in place keeps the id and
# moves the start time, which is what tells it from a live re-cable.
containers_of() {
  local name container
  while read -r name container; do
    docker inspect -f "$name {{.Id}} {{.State.StartedAt}}" "$container" ||
      fail "case 8: docker inspect of $name's container $container failed"
  done < <(jq -r '.nodes[] | "\(.name) \(.container)"' "$TWIN/twin.json") | LC_ALL=C sort > "$1"
}

# container_line FILE NODE: the node's line of a containers_of file.
container_line() {
  awk -v n="$2" '$1 == n' "$1"
}

# gnmi_try OUT TARGET TRANSPORT USER PASS PATH: the leaf PATH ends in, from the first value a
# gNMI Get of PATH returns, or nothing. A path below a list whose key it leaves out comes back
# from SR Linux as one update at the list entry with the leaf inside it, and
# from EOS as the leaf, so the leaf is looked for by its name inside an object. It never fails
# the run, so a caller can wait for a value to appear.
gnmi_try() {
  gnmic -a "$2" -u "$4" -p "$5" "$3" -e json_ietf get --path "$6" > "$1" 2> "$1.err" || return 0
  jq -r --arg leaf "${6##*/}" '[.. | objects | select(has("values")) | .values[]] | first
    | if type == "object" or type == "array" then ([.. | objects | .[$leaf]? | strings] | first) else . end
    | values' "$1" 2> /dev/null || true
}

# await_neighbour NODE PORT FAR FAR_PORT: NODE's PORT sees FAR's FAR_PORT over LLDP, read over
# the gNMI NODE's own package declares, at the paths its conformance facet names (M6),
# within 120s of the step's return: a port re-cabled live or a node restarted forms its
# adjacency on LLDP's own timers, not before the step returns as a boot's does.
await_neighbour() {
  local node=$1 port=$2 far=$3 farport=$4 addr pspid out start name pid
  read -r addr pspid < <(jq -r --arg n "$node" '.nodes[] | select(.name==$n) | "\(.mgmt_ipv4) \(.psp.id)"' "$TWIN/twin.json")
  out="$OUT/lldp-8-$node-$(tr -c 'a-zA-Z0-9' _ <<< "$port")"
  start=$(now_ns)
  while :; do
    case "$pspid" in
      nokia_srlinux)
        name=$(gnmi_try "$out-name.json" "$addr:57400" --skip-verify "$FYLGJA_SRLINUX_USERNAME" "$FYLGJA_SRLINUX_PASSWORD" \
          "/system/lldp/interface[name=$port]/neighbor/system-name")
        pid=$(gnmi_try "$out-port.json" "$addr:57400" --skip-verify "$FYLGJA_SRLINUX_USERNAME" "$FYLGJA_SRLINUX_PASSWORD" \
          "/system/lldp/interface[name=$port]/neighbor/port-id")
        ;;
      arista_eos)
        name=$(gnmi_try "$out-name.json" "$addr:6030" --insecure "$FYLGJA_EOS_USERNAME" "$FYLGJA_EOS_PASSWORD" \
          "/lldp/interfaces/interface[name=$port]/neighbors/neighbor/state/system-name")
        pid=$(gnmi_try "$out-port.json" "$addr:6030" --insecure "$FYLGJA_EOS_USERNAME" "$FYLGJA_EOS_PASSWORD" \
          "/lldp/interfaces/interface[name=$port]/neighbors/neighbor/state/port-id")
        ;;
      *)
        fail "case 8: node $node runs support package $pspid, which this read does not know how to read"
        ;;
    esac
    { [ "$name" = "$far" ] && [ "$pid" = "$farport" ]; } && break
    [ "$(( ($(now_ns) - start) / 1000000000 ))" -lt 120 ] ||
      fail "case 8: $node $port does not see $far $farport over LLDP within 120s of the step; it reads \"$name\" \"$pid\"; see $out-*.json"
    sleep 2
  done
  echo "e2e: case 8: $node $port sees $far $farport, $(since "$start")s after the step returned"
}

# s1_new_port_description: the description s1's staged artifact sets on ethernet-1/3, the
# port -add-mixed-link cables, or nothing. Read in place, as readback_mixed reads it, and
# never copied into $OUT.
s1_new_port_description() {
  local file
  file=$(jq -r '.nodes[] | select(.name=="s1") | .artifact.file' "$TWIN/bundle/manifest.json")
  sed -n 's|^set / interface ethernet-1/3 description "\(.*\)"$|\1|p' "$TWIN/bundle/$file"
}

# gnmi_absent CASE ADDR PATH: an SR Linux node, read as gnmi_value reads it, answers the Get
# with no value. An absent value is no update and no error, so a Get that
# fails still fails the run, and only an answer that holds no value passes.
gnmi_absent() {
  local out
  out="$OUT/gnmi-$1-${2//[:.]/_}-$(tr -c 'a-z0-9' _ <<< "$3").json"
  gnmic -a "$2:57400" -u "$FYLGJA_SRLINUX_USERNAME" -p "$FYLGJA_SRLINUX_PASSWORD" --skip-verify -e json_ietf \
    get --path "$3" > "$out" 2> "$out.err" || fail "case $1: gnmic get $3 from $2 failed; see $out.err"
  jq -e '[.. | objects | select(has("values")) | .values[]] | length == 0' "$out" > /dev/null ||
    fail "case $1: gnmic get $3 from $2 returned a value where none should be; see $out"
}

# step_wait_settled CASE: the step just taken waited after its record and the twin settled:
# twin.json's step.wait and the step document's, both settled
# after at least one read, nothing failing. Sets WAIT_AFTER, the record's after_s.
step_wait_settled() {
  expect "$TWIN/twin.json" '.step.wait.outcome=="settled" and .step.wait.reads>=1 and .step.wait.failing==[]'
  expect "$OUT/step-$1.json" '.step.wait.outcome=="settled" and .step.wait.reads>=1'
  WAIT_AFTER=$(jq -r .step.wait.after_s "$TWIN/twin.json")
  echo "e2e: case 8: step $1's wait settled after ${WAIT_AFTER}s ($(jq -r '.step.wait.reads | if . == 1 then "1 read" else "\(.) reads" end' "$TWIN/twin.json"))"
}

# A throwaway branch seeded with the mixed fixture, set before seeding so the trap's -delete
# removes it with its stages and its proposed change, as case 7's. Made on the host case 7's
# destroy left clean.
FS="fylgja-test-e2e-step-$$-$RANDOM"
export FS
start=$(now_ns)
seed_status=0
fixture -branch "$FS" -mixed > "$OUT/seed-8.out" 2> "$OUT/seed-8.err" || seed_status=$?
SEED8_TOOK=$(since "$start")
echo "e2e: case 8: seeding $FS took ${SEED8_TOOK}s (exit $seed_status)"
[ "$seed_status" -eq 0 ] || fail "case 8: seeding $FS with -mixed exited $seed_status; see $OUT/seed-8.err"

# The draft proposed change, opened and waited for as case 7's.
start=$(now_ns)
fixture -branch "$FS" -propose > "$OUT/propose-8.out" 2> "$OUT/propose-8.err" ||
  fail "case 8: -propose on $FS failed; see $OUT/propose-8.err"
PROPOSE8_TOOK=$(since "$start")
echo "e2e: case 8: a draft proposed change opened on $FS, its validators concluded, in ${PROPOSE8_TOOK}s"

# The stages, as case 7 marks them: each after the writes it seals and after their artifacts
# are rendered. -add-mixed-link's generate returns before s1's and e1's are rewritten, so the
# second mark waits for their checksums to move. What Infrahub held when the first was
# marked is kept: the twin at seeded is read back against it.
artifacts_of "$FS" "$OUT/artifacts-8-sealed-1.json" 2> "$OUT/artifacts-8-sealed-1.err" ||
  fail "case 8: reading $FS's artifacts failed; see $OUT/artifacts-8-sealed-1.err"
expect "$OUT/artifacts-8-sealed-1.json" 'length == 3 and all(.[]; .status == "Ready")'
fixture -branch "$FS" -stage seeded -description seeded > "$OUT/stage-8-seeded.out" 2> "$OUT/stage-8-seeded.err" ||
  fail "case 8: marking stage $FS/seeded failed; see $OUT/stage-8-seeded.err"
fixture -branch "$FS" -add-mixed-link > "$OUT/add-mixed-link-8.out" 2> "$OUT/add-mixed-link-8.err" ||
  fail "case 8: -add-mixed-link on $FS failed; see $OUT/add-mixed-link-8.err"
await_checksums_moved 8 "$FS" "$OUT/artifacts-8-sealed-1.json" s1 e1
fixture -branch "$FS" -stage mixed-link -description "mixed link" > "$OUT/stage-8-mixed-link.out" 2> "$OUT/stage-8-mixed-link.err" ||
  fail "case 8: marking stage $FS/mixed-link failed; see $OUT/stage-8-mixed-link.err"

# The probe from the kind (016): e1-loop across e1, from Ethernet10 to Ethernet11, the mixed
# seed's probe-ready ports, written into FylgjaProbe on main, so every read from here on
# carries it with no file: the plan's, the create's and both steps'. It is branch-agnostic:
# no stage's at pins it, and both stages compile with it.
write_probes 8 testdata/probes/e1-loop.json e1-loop

# The plan (M10, 014), fylgja-cli's (020): four stages, the branch point refused as case 7's
# is, so the plan exits 1; the marks and the head compiled to three ids, and between the marks the link,
# with s1 re-bootstrapped for it and both ends' artifacts re-rendered. e1's bootstrap
# carries no per-port line, so e1 changes in its mapping alone, if at all; e2 not at all.
# The step to the head is unchanged. Each compiled stage carries warnings and no rejection:
# the mixed fixture's EOS artifacts name Management1, which the node calls Management0
# (artifact.interface.unrepresented, M7), as case 6's create does, warned once, at the
# core's compile, where the Go reader warned it at its read too (020's research §5.20).
plan_status=0
fylgja_cli stage plan --branch "$FS" --json > "$OUT/plan-8.json" 2> "$OUT/plan-8.err" || plan_status=$?
[ "$plan_status" -eq 1 ] ||
  fail "case 8: stage plan --branch $FS exited $plan_status, not 1 for its refused branch point; see $OUT/plan-8.json and $OUT/plan-8.err"
expect "$OUT/plan-8.json" '.status=="rejected" and .operation=="stage.plan" and .plan.branch==env.FS
  and [.plan.stages[].ref]
    == [env.FS + "/branch-point", env.FS + "/seeded", env.FS + "/mixed-link", env.FS + "/head"]
  and [.findings[] | select(.severity=="rejection") | .rule] == ["scope.empty"]
  and .plan.stages[0].bundle_id == null
  and all(.plan.stages[1:][]; .branch==env.FS and (.bundle_id | type)=="string"
    and all(.findings[]; .severity != "rejection"))
  and ([.plan.stages[1:][].bundle_id] | unique | length) == 3
  and (.plan.steps | length) == 3 and (.plan.steps[0].computed | not)
  and (.plan.steps[2] | .computed and .unchanged)'
P1=$(jq -r '.plan.stages[1].bundle_id' "$OUT/plan-8.json")
P2=$(jq -r '.plan.stages[2].bundle_id' "$OUT/plan-8.json")
export P1 P2
expect "$OUT/plan-8.json" '.plan.steps[1] | .computed and (.unchanged | not)
  and .from==(env.FS + "/seeded") and .to==(env.FS + "/mixed-link")
  and .from_bundle_id==env.P1 and .to_bundle_id==env.P2
  and .nodes.added == [] and .nodes.removed == []
  and any(.nodes.changed[]; .node=="s1" and any(.reasons[]; .=="bootstrap"))
  and all(.nodes.changed[]; (.node=="s1" or .node=="e1") and all(.reasons[]; .=="bootstrap" or .=="mapping"))
  and .links.removed == [] and (.links.added | length) == 1
  and ([.links.added[0].a.node, .links.added[0].b.node] | sort) == ["e1", "s1"]
  and [.artifacts.changed[].node] == ["e1", "s1"]'
echo "e2e: case 8: plan $FS/seeded $P1, $FS/mixed-link $P2; one link added between e1 and s1, both re-rendered"

# The twin at seeded, pushed by replace: the plan's id, a 12 record of no rehearsal and no
# stage that has not stepped, every node holding seeded's bundle, and the orchestrator's
# record naming the stage (020); created with no probe file, its snapshot carries the kind's
# probe, and the twin its two hosts on e1 (016).
BRANCH=$FS
READBACK=
CREATE_REF="$FS/seeded"
HOSTS=2
create_twin 8
CREATE8_TOOK=$CREATE_TOOK
[ "$BID" = "$P1" ] || fail "case 8: create --stage $FS/seeded deployed $BID, but the plan printed $P1"
expect "$TWIN/twin.json" '.twin_version=="12" and .rehearsal==null and .state=="ready" and .step==null
  and .stage==null and all(.nodes[]; .holds==env.P1)
  and [.nodes[] | select(.probe != null) | .name] == ["e1-loop-a", "e1-loop-b"]'
expect "$ORCH_RECORD" '.flow=="twin-create" and .stage.branch==env.FS and .stage.label=="seeded"
  and .proposed_change.branch==env.FS'
expect "$OUT/probes-snapshot-8.json" '.probes == ["e1-loop"]'
readback_mixed 8 "$FS" "$OUT/artifacts-8-sealed-1.json"
containers_of "$OUT/containers-8-created.txt"
[ "$(wc -l < "$OUT/containers-8-created.txt")" -eq "$NODES" ] ||
  fail "case 8: docker names $(wc -l < "$OUT/containers-8-created.txt") containers of the twin, not $NODES"

# The step with no target goes to the next stage of the record's, mixed-link, which
# fylgja-cli reads and files. It restarts e1, so the core refuses it without
# --allow-restart: the dry run says so and touches nothing; the run is refused before it
# starts, and touches nothing, the orchestrator's record included.
twin_before=$(sha256sum < "$TWIN/twin.json")
record_before=$(sha256sum < "$ORCH_RECORD")
dry8_status=0
fylgja_cli twin step --dry-run --json > "$OUT/step-8-dry.json" 2> "$OUT/step-8-dry.err" || dry8_status=$?
[ "$dry8_status" -eq 1 ] || fail "case 8: twin step --dry-run exited $dry8_status, not 1; see $OUT/step-8-dry.json"
expect "$OUT/step-8-dry.json" '.status=="rejected" and .operation=="twin.step" and .dry_run.verdict=="refused"
  and .subject.stage==(env.FS + "/mixed-link")
  and [.findings[] | select(.severity=="rejection") | .rule] == ["step.restart.required"]
  and (.findings[] | select(.rule=="step.restart.required") | .object)=="e1"
  and .stage.label=="mixed-link" and .stage.branch==env.FS
  and .step.from.stage==null and .step.from.bundle_id==env.P1
  and .step.to.stage==null and .step.to.bundle_id==env.P2
  and .step.reconcile.restarted == ["e1"]
  and [.step.push_plan[].node] == ["e1", "s1"]
  and (.step | has("run") | not)'
refused8_status=0
fylgja_cli twin step --json > "$OUT/step-8-refused.json" 2> "$OUT/step-8-refused.err" || refused8_status=$?
[ "$refused8_status" -eq 1 ] || fail "case 8: twin step without --allow-restart exited $refused8_status, not 1; see $OUT/step-8-refused.json"
expect "$OUT/step-8-refused.json" '.status=="rejected"
  and [.findings[] | select(.severity=="rejection") | .rule] == ["step.restart.required"]
  and (.findings[] | select(.rule=="step.restart.required") | .object)=="e1"
  and (.step | has("run") | not)'
[ "$twin_before" = "$(sha256sum < "$TWIN/twin.json")" ] || fail "case 8: a refused step changed twin.json"
[ "$record_before" = "$(sha256sum < "$ORCH_RECORD")" ] || fail "case 8: a refused step changed the orchestrator's record"
containers_of "$OUT/containers-8-refused.txt"
cmp -s "$OUT/containers-8-created.txt" "$OUT/containers-8-refused.txt" ||
  fail "case 8: a refused step changed the twin's containers; compare $OUT/containers-8-created.txt and $OUT/containers-8-refused.txt"
echo "e2e: case 8: the step to $FS/mixed-link refused step.restart.required naming e1, dry run and run; nothing touched"

# The step to mixed-link: e1 restarted in place, its id kept and its start time moved; s1
# re-cabled live and e2 untouched, their containers as they were; both pushed by replace.
start=$(now_ns)
step8a_status=0
fylgja_cli twin step --allow-restart --json > "$OUT/step-8a.json" 2> "$OUT/step-8a.err" || step8a_status=$?
STEP8A_TOOK=$(since "$start")
echo "e2e: case 8: step to $FS/mixed-link took ${STEP8A_TOOK}s (exit $step8a_status)"
[ "$step8a_status" -eq 0 ] || fail "case 8: twin step --allow-restart exited $step8a_status; see $OUT/step-8a.json and $OUT/step-8a.err"
expect "$OUT/step-8a.json" '.status=="ok" and .operation=="twin.step" and .bundle_id==env.P2
  and .step.outcome=="stepped" and .step.state=="ready" and .step.run.workflow_id=="fylgja-step"'
RUN8A=$(jq -r .subject.run_id "$OUT/step-8a.json")
export RUN8A
expect "$TWIN/twin.json" '.twin_version=="12" and .rehearsal==null and .state=="ready" and .bundle_id==env.P2
  and .stage==null and .run.workflow_id=="fylgja-provision"
  and .step.outcome=="stepped" and .step.run.run_id==env.RUN8A and .step.phase==null
  and .step.from.bundle_id==env.P1 and .step.to.bundle_id==env.P2
  and .step.reconcile.restarted == ["e1"] and .step.reconcile.recreated == [] and .step.reconcile.added == []
  and ([.step.pushed[] | {node, reasons, outcome}]
    == [{node: "e1", reasons: ["artifact", "restarted"], outcome: "landed"},
        {node: "s1", reasons: ["artifact", "bootstrap"], outcome: "landed"}])
  and all(.nodes[]; .holds==env.P2)'
cp "$TWIN/twin.json" "$OUT/twin-8a.json"
expect "$ORCH_RECORD" '.flow=="twin-step" and .stage.branch==env.FS and .stage.label=="mixed-link"'
no_credential "the artifact marker" "$MARKER" "$TWIN/twin.json"
containers_of "$OUT/containers-8a.txt"
for node in s1 e2; do
  [ "$(container_line "$OUT/containers-8-created.txt" $node)" = "$(container_line "$OUT/containers-8a.txt" $node)" ] ||
    fail "case 8: the step to $FS/mixed-link changed $node's container; compare $OUT/containers-8-created.txt and $OUT/containers-8a.txt"
done
read -r _ e1_id_before e1_started_before < <(container_line "$OUT/containers-8-created.txt" e1)
read -r _ e1_id_after e1_started_after < <(container_line "$OUT/containers-8a.txt" e1)
[ "$e1_id_before" = "$e1_id_after" ] || fail "case 8: the step to $FS/mixed-link replaced e1's container, where containerlab restarts it in place"
[ "$(date -d "$e1_started_after" +%s%N)" -gt "$(date -d "$e1_started_before" +%s%N)" ] ||
  fail "case 8: e1's container started at $e1_started_after, not after the create's $e1_started_before: it was not restarted"
echo "e2e: case 8: e1 restarted in place; s1 and e2 untouched"
readback_mixed 8a "$FS"
# The replace's removal, first half: s1 is re-cabled live and never restarted, so
# only the push changes its configuration, and mixed-link's artifact describes the new port.
S1_ADDR=$(jq -r '.nodes[] | select(.name=="s1") | .mgmt_ipv4' "$TWIN/twin.json")
want=$(s1_new_port_description)
[ -n "$want" ] || fail "case 8: s1's artifact at $FS/mixed-link sets no description on ethernet-1/3, the port the step cabled"
got=$(gnmi_value 8a "$S1_ADDR" '/interface[name=ethernet-1/3]/description')
[ "$got" = "$want" ] || fail "case 8: s1's ethernet-1/3 description reads \"$got\", its artifact at $FS/mixed-link sets \"$want\""
echo "e2e: case 8: s1 ethernet-1/3 carries the description its artifact at $FS/mixed-link sets"
await_neighbour s1 ethernet-1/3 e1 Ethernet3
await_neighbour e1 Ethernet3 s1 ethernet-1/3
# The step's own wait after its record: the record and the step's
# document say it settled; await_neighbour above stays the independent read. after_s is
# recorded, not asserted. Its last read held e1-loop's burst through e1, restarted, and the
# probe's flow, across the restart, lost more than none (016).
step_wait_settled 8a
WAIT8A_AFTER=$WAIT_AFTER
expect "$OUT/step-8a.json" '.step.wait_counts.burst.held==1 and .step.wait_counts.burst.failed==0'
step_loss_measured 8a e1-loop '.lost > 0'
LOSS8A=$LOSS_FIGURE
history_of step-8a fylgja-step "$RUN8A"

fylgja twin show --json > "$OUT/show-8a.json" 2> "$OUT/show-8a.err" ||
  fail "case 8: twin show exited non-zero after the step; see $OUT/show-8a.err"
expect "$OUT/show-8a.json" '.show.kind=="snapshot" and .show.record.bundle_id==env.P2
  and .show.record.state=="ready" and .show.record.step.outcome=="stepped"'
fylgja_cli stage list --branch "$FS" --json > "$OUT/list-8a.json" 2> "$OUT/list-8a.err" ||
  fail "case 8: stage list exited non-zero beside the stepped twin; see $OUT/list-8a.json and $OUT/list-8a.err"
expect "$OUT/list-8a.json" '.status=="ok" and .stages.record.proposed_change.branch==env.FS
  and .stages.record.label=="mixed-link" and .stages.record.state=="ready" and .stages.record.towards==null
  and [.stages.rows[] | select(.twin) | .ref] == [env.FS + "/mixed-link"]'

# The step back to seeded, named: the link's endpoints deleted, e1 restarted again, s1
# re-cabled live; the twin runs what Infrahub held when seeded was marked, and e2 is still
# the create's.
start=$(now_ns)
step8b_status=0
fylgja_cli twin step --stage "$FS/seeded" --allow-restart --json > "$OUT/step-8b.json" 2> "$OUT/step-8b.err" || step8b_status=$?
STEP8B_TOOK=$(since "$start")
echo "e2e: case 8: step back to $FS/seeded took ${STEP8B_TOOK}s (exit $step8b_status)"
[ "$step8b_status" -eq 0 ] || fail "case 8: twin step --stage $FS/seeded exited $step8b_status; see $OUT/step-8b.json and $OUT/step-8b.err"
expect "$OUT/step-8b.json" '.status=="ok" and .bundle_id==env.P1 and .step.outcome=="stepped"'
RUN8B=$(jq -r .subject.run_id "$OUT/step-8b.json")
export RUN8B
expect "$TWIN/twin.json" '.state=="ready" and .bundle_id==env.P1 and .stage==null
  and .step.outcome=="stepped" and .step.run.run_id==env.RUN8B
  and .step.from.bundle_id==env.P2
  and .step.reconcile.restarted == ["e1"] and all(.nodes[]; .holds==env.P1)'
cp "$TWIN/twin.json" "$OUT/twin-8b.json"
expect "$ORCH_RECORD" '.flow=="twin-step" and .stage.branch==env.FS and .stage.label=="seeded"'
no_credential "the artifact marker" "$MARKER" "$TWIN/twin.json"
containers_of "$OUT/containers-8b.txt"
[ "$(container_line "$OUT/containers-8-created.txt" e2)" = "$(container_line "$OUT/containers-8b.txt" e2)" ] ||
  fail "case 8: e2's container changed since the create; compare $OUT/containers-8-created.txt and $OUT/containers-8b.txt"
readback_mixed 8b "$FS" "$OUT/artifacts-8-sealed-1.json"
# The replace's removal, second half: seeded's artifact never describes ethernet-1/3, and
# s1, never restarted, no longer carries the description mixed-link's push set.
[ -z "$(s1_new_port_description)" ] || fail "case 8: s1's artifact at $FS/seeded sets a description on ethernet-1/3, so its absence would show nothing"
gnmi_absent 8b "$S1_ADDR" '/interface[name=ethernet-1/3]/description'
echo "e2e: case 8: s1 ethernet-1/3 carries no description after the step back to $FS/seeded: the replace removed what mixed-link added"
step_wait_settled 8b
WAIT8B_AFTER=$WAIT_AFTER
expect "$OUT/step-8b.json" '.step.wait_counts.burst.held==1 and .step.wait_counts.burst.failed==0'
step_loss_measured 8b e1-loop
LOSS8B=$LOSS_FIGURE
echo "e2e: case 8: settled after ${WAIT8A_AFTER}s and ${WAIT8B_AFTER}s"
history_of step-8b fylgja-step "$RUN8B"

destroy_twin 8 "done" "done"
unset CREATE_REF
READBACK=readback
HOSTS=0
# The probe goes from main, which then holds none, so no later read carries it.
delete_probes 8

# The branch goes with its stages and its proposed change, as case 7's, and Infrahub then
# holds none of them; the product then lists no stage of it, and plans none.
if fixture -branch "$FS" -delete > "$OUT/delete-branch-8.out" 2>&1; then
  grep -qxF "deleted 2 stages, 1 proposed change, branch $FS" "$OUT/delete-branch-8.out" ||
    fail "case 8: -delete on $FS did not report its two stages and its proposed change; see $OUT/delete-branch-8.out"
  infrahub_holds_none 8 "$FS"
  fylgja_cli stage list --branch "$FS" --json > "$OUT/list-8-deleted.json" 2> "$OUT/list-8-deleted.err" ||
    fail "case 8: stage list --branch $FS exited non-zero after the delete; see $OUT/list-8-deleted.err"
  expect "$OUT/list-8-deleted.json" '.status=="ok" and .stages.branch==env.FS and .stages.rows == []'
  plan_status=0
  fylgja_cli stage plan --branch "$FS" --json > "$OUT/plan-8-deleted.json" 2> "$OUT/plan-8-deleted.err" || plan_status=$?
  [ "$plan_status" -eq 1 ] || fail "case 8: stage plan --branch $FS exited $plan_status after the delete, not 1; see $OUT/plan-8-deleted.json"
  expect "$OUT/plan-8-deleted.json" '.status=="rejected" and [.findings[] | select(.severity=="rejection") | .rule] == ["stage.unknown"]'
  unset FS
else
  fail "case 8: -delete on $FS failed, leaving its branch, stages or proposed change; see $OUT/delete-branch-8.out"
fi
else
  skip_case 8
fi

# --- case 9: a proposed change rehearsed from inside Infrahub (015) -----------------
if case_runs 9; then

# user_checks NAME PC: the proposed change's user checks as test support's UserChecksOf reads
# them, each CoreStandardCheck under a CoreUserValidator with its validator's state, a
# validator with no check read as one row of its definition's name, sorted by name. Written
# to $OUT/checks-NAME.json, where the credential and marker greps read each message.
user_checks() {
  gql "" "{ CoreUserValidator(proposed_change__ids: [\"$2\"]) { edges { node {
    state { value } conclusion { value }
    check_definition { node { name { value } } }
    checks { edges { node { name { value } conclusion { value } severity { value } message { value } } } } } } } }" |
    jq '[.CoreUserValidator.edges[].node
      | (.check_definition.node.name.value // "") as $def | .state.value as $state
      | if (.checks.edges | length) == 0
        then {name: $def, conclusion: .conclusion.value, severity: null, message: null, validator_state: $state}
        else .checks.edges[].node
          | {name: (if (.name.value // "") == "" then $def else .name.value end), conclusion: .conclusion.value,
             severity: .severity.value, message: .message.value, validator_state: $state}
        end] | sort_by(.name)' > "$OUT/checks-$1.json"
}

# comments_of NAME PC: the comments the proposed change's overview shows, each comment of each
# of its threads, as test support's CommentsOf reads them (research §5.9), [{id, thread, text}]
# in Infrahub's order, written to $OUT/comments-NAME.json, where the greps read each text.
comments_of() {
  gql "" "{ CoreProposedChange(ids: [\"$2\"]) { edges { node { threads { edges { node { id comments { edges { node { id text { value } } } } } } } } } } }" |
    jq '[.CoreProposedChange.edges[].node.threads.edges[].node | .id as $t | .comments.edges[].node | {id, thread: $t, text: .text.value}]' \
      > "$OUT/comments-$1.json"
}

# rehearsal_run CASE FILE: the run a rehearsal's comment names in its second paragraph, Run
# `fylgja-rehearse <id>`, which is the flow run the check triggered on the platform (020);
# sets REHEARSAL_RUN and REHEARSAL_USED, the time it used against its deadline. The flow run
# is read from the platform with local/.env's auth string: completed, of the deployment
# twin-rehearse/main, asked of the case's branch. Its out lines, from its log, name each run
# of the core's it started, its provision, its steps and its destroy, whose histories are
# fetched as the greps read them (SC-008), a step's push results carrying the device's diff
# by design, as cases 7 and 8's do.
rehearsal_run() {
  # shellcheck disable=SC2016 # the backticks are the markdown's code span, read literally
  REHEARSAL_RUN=$(sed -n 's/^Run `fylgja-rehearse \([^`]*\)`.*/\1/p' "$2")
  # shellcheck disable=SC2016
  REHEARSAL_USED=$(sed -n 's/^Run `fylgja-rehearse [^`]*`, .* \([0-9.]*s of the [0-9]*s deadline\).*/\1/p' "$2")
  [ -n "$REHEARSAL_RUN" ] || fail "case $1: the comment names no fylgja-rehearse run; see $2"
  platform_get "/flow_runs/$REHEARSAL_RUN" > "$OUT/flow-run-$1.json" 2> "$OUT/flow-run-$1.err" ||
    fail "case $1: the platform answered no flow run $REHEARSAL_RUN; see $OUT/flow-run-$1.err"
  expect "$OUT/flow-run-$1.json" '.state_type == "COMPLETED" and .deployment_id == env.REHEARSE_DEPLOYMENT
    and .parameters.branch == env.FR'
  # The run's log, page by page as the checks read it, and its out lines: the records of the
  # logger prefect.flow_runs.fylgja (research §5.21).
  local offset=0 page body
  : > "$OUT/flow-run-lines-$1.txt"
  while :; do
    body=$(jq -cn --arg id "$REHEARSAL_RUN" --argjson offset "$offset" \
      '{logs: {flow_run_id: {any_: [$id]}}, sort: "TIMESTAMP_ASC", limit: 200, offset: $offset}')
    page="$OUT/flow-run-log-$1-$offset.json"
    platform_post /logs/filter "$body" > "$page" 2> "$OUT/flow-run-log-$1.err" ||
      fail "case $1: reading flow run $REHEARSAL_RUN's log failed; see $OUT/flow-run-log-$1.err"
    jq -r '.[] | select(.name == "prefect.flow_runs.fylgja") | .message' "$page" >> "$OUT/flow-run-lines-$1.txt"
    [ "$(jq length "$page")" -eq 200 ] || break
    offset=$((offset + 200))
  done
  sed -nE 's/^run (fylgja-(provision|step|destroy)) ([^ ]+)$/\1 \3/p' "$OUT/flow-run-lines-$1.txt" | awk '!seen[$0]++' \
    > "$OUT/children-rehearse-$1.txt"
  if ! grep -q '^fylgja-provision ' "$OUT/children-rehearse-$1.txt" || ! grep -q '^fylgja-destroy ' "$OUT/children-rehearse-$1.txt"; then
    fail "case $1: flow run $REHEARSAL_RUN's log names no provision or no destroy of the core's; see $OUT/flow-run-lines-$1.txt"
  fi
  local n=0 workflow run
  while read -r workflow run; do
    n=$((n + 1))
    history_of "rehearse-$1-$n-$workflow" "$workflow" "$run"
  done < "$OUT/children-rehearse-$1.txt"
}

# no_twin CASE: the rehearsal's own destroy left the host clear, as twin show reports it and as
# containerlab, Docker, for a probe's host (016), and the state root say.
no_twin() {
  fylgja twin show --json > "$OUT/show-$1.json" 2> "$OUT/show-$1.err" ||
    fail "case $1: twin show exited non-zero after the rehearsal; see $OUT/show-$1.err"
  expect "$OUT/show-$1.json" '.show.kind == "none" and (.show.host.lab_present | not)
    and (.show.host.twin_dir_present | not) and .show.in_flight == []'
  [ "$(clab inspect --all --format json)" = "{}" ] || fail "case $1: containerlab reports a lab after the rehearsal"
  no_probe_containers "$1"
  [ ! -e "$TWIN" ] || fail "case $1: $TWIN is present after the rehearsal"
}

# stage_lines CASE ERE...: fylgja-twin's message in $OUT/checks-CASE.json, written to
# $OUT/message-CASE.txt, holds exactly one line matching each ERE: the report's text gives one
# line per stage after the run, which ends with its verdict (FR-030), and the plan's lines and
# the run's progress name the stages too, each in another shape.
stage_lines() {
  local case=$1 re n
  shift
  jq -r '.[] | select(.name == "fylgja-twin") | .message // ""' "$OUT/checks-$case.json" > "$OUT/message-$case.txt"
  for re in "$@"; do
    n=$(grep -cE -- "$re" "$OUT/message-$case.txt" || true)
    [ "$n" -eq 1 ] || fail "case $case: fylgja-twin's message holds $n lines matching $re, want one; see $OUT/message-$case.txt"
  done
}

# run_checks_named CASE CONCLUSION: -run-checks user's output, $OUT/run-checks-CASE.out, names
# fylgja-twin with its conclusion, as contracts/fixture-tool.md gives the line.
# comment_stages: the case's comment holds one table row per stage and nothing more, in the
# plan's order, each with its verdict, and lists each stage's reference under **Stages** in
# the same order (FR-030, SC-001). Each argument is a stage's label and its verdict cell, as
# label=verdict; a row is read by its first cell and its last.
comment_stages() {
  local case=$1 md pair want_rows="" want_refs="" rows refs
  shift
  md=$OUT/comment-$case.md
  for pair in "$@"; do
    want_rows+="$FR/${pair%%=*} | ${pair#*=}"$'\n'
    want_refs+="$FR/${pair%%=*}"$'\n'
  done
  rows=$(grep -E '^\| ' "$md" | grep -vE '^\| stage \|' | sed -E 's/^\| ([^|]*) \|.*\| ([^|]*) \|$/\1 | \2/' || true)
  # shellcheck disable=SC2016 # the backticks are the markdown's code spans, read literally by sed
  refs=$(awk '/^\*\*Stages\*\*/ { on = 1; next } on && /^\*\*/ { exit } on' "$md" | sed -nE 's/^- `([^`]*)` .*/\1/p')
  [ "$rows"$'\n' = "$want_rows" ] ||
    fail "case $case: the comment's table rows read $(tr '\n' ';' <<< "$rows"), not $(tr '\n' ';' <<< "$want_rows") in order; see $md"
  [ "$refs"$'\n' = "$want_refs" ] ||
    fail "case $case: the comment's stages list $(tr '\n' ' ' <<< "$refs"), not $(tr '\n' ' ' <<< "$want_refs") in order; see $md"
}

run_checks_named() {
  grep -qE "^check fylgja-twin: $2 \(message [0-9,]+ characters\)\$" "$OUT/run-checks-$1.out" ||
    fail "case 9: -run-checks user names no check fylgja-twin concluding $2; see $OUT/run-checks-$1.out"
}

# LOSS9 is a stage line's loss naming n1-loop's flow as measured (016): its requests lost of
# those sent, and its longest gap; an extended regular expression. LOSS9_CELL is the table's
# cell, which drops the gap when the comment is shortened to Infrahub's bound.
LOSS9='n1-loop [0-9]+/[0-9]+, gap [0-9]+\.[0-9]s'
LOSS9_CELL='n1-loop [0-9]+/[0-9]+(, gap [0-9]+\.[0-9]s)?'

# loss_cells CASE LABEL=ERE...: the case's comment's loss column (016), the table's eighth
# cell, matches ERE whole in the row of each stage $FR/LABEL.
loss_cells() {
  local case=$1 pair cell md
  shift
  md=$OUT/comment-$case.md
  for pair in "$@"; do
    cell=$(awk -F'|' -v ref="$FR/${pair%%=*}" '/^\| / { c = $2; gsub(/^ +| +$/, "", c)
      if (c == ref) { l = $9; gsub(/^ +| +$/, "", l); print l; exit } }' "$md")
    grep -qxE -- "${pair#*=}" <<< "$cell" ||
      fail "case $case: the comment's loss cell for $FR/${pair%%=*} reads \"$cell\", not ${pair#*=}; see $md"
  done
}

# overview_threads NAME PC: the threads the proposed change's overview lists, oldest first, as
# test support's OverviewThreads reads them from Infrahub's event log: each thread-created
# event whose primary node is the proposed change names its thread first among its related
# nodes (research §5.9). Written to $OUT/overview-NAME.json.
overview_threads() {
  gql "" "{ InfrahubEvent(primary_node__ids: [\"$2\"], event_type: [\"infrahub.proposed_change_thread.created\"], order: ASC, limit: 50) {
    edges { node { related_nodes { id } } } } }" |
    jq '[.InfrahubEvent.edges[].node.related_nodes[0].id // empty]' > "$OUT/overview-$1.json"
}

# rehearsal.Caveat, the markdown's last line, which every comment keeps (FR-014).
CAVEAT="*Fidelity is asserted, not measured: the twin's containers forward in software and keep their own timing; a loss figure is the container's, never a hardware forwarder's.*"
export CAVEAT

# A throwaway branch, set before seeding so the trap's -delete removes it and what hangs on
# it: its stages, then its proposed change, which takes its comments and its validators with
# it (research §1.6), then the branch. Seeded after the import of the checks, which the
# preconditions required, so the branch runs them.
FR="fylgja-test-e2e-rh-$$-$RANDOM"
export FR
start=$(now_ns)
seed_status=0
fixture -branch "$FR" > "$OUT/seed-9.out" 2> "$OUT/seed-9.err" || seed_status=$?
SEED9_TOOK=$(since "$start")
echo "e2e: case 9: seeding $FR took ${SEED9_TOOK}s (exit $seed_status)"
[ "$seed_status" -eq 0 ] || fail "case 9: seeding $FR exited $seed_status; see $OUT/seed-9.err"

# The probe the checks read (016): they send no file, so theirs is the kind's on main, which
# holds n1-loop from before the draft's checks to after the branch's delete. Every stage the
# rehearsals compile carries it.
write_probes 9 testdata/probes/n1-loop.json n1-loop

# The draft. Its creation runs both checks after the rest of the pipeline, which -propose
# waits for, so they are awaited here, bounded as tier 2's test bounds them: fylgja-twin
# skips a draft, asking nothing of Fylgja, and fylgja-step plans the branch point and the
# head, the branch point's scope.empty, for want of a tagged device on main, excepted. No
# comment is
# posted on a draft.
start=$(now_ns)
fixture -branch "$FR" -propose > "$OUT/propose-9.out" 2> "$OUT/propose-9.err" ||
  fail "case 9: -propose on $FR failed; see $OUT/propose-9.err"
PROPOSE9_TOOK=$(since "$start")
PC9=$(sed -n 's/^proposed change \([^ ]*\) opened on .*/\1/p' "$OUT/propose-9.out")
[ -n "$PC9" ] || fail "case 9: -propose named no proposed change; see $OUT/propose-9.out"
export PC9
start=$(now_ns)
until user_checks 9-draft "$PC9" 2> "$OUT/checks-9-draft.err" &&
  jq -e '[.[] | select(.validator_state == "completed" and (.conclusion // "") != "") | .name] as $done
    | all("fylgja-step", "fylgja-twin"; IN($done[]))' "$OUT/checks-9-draft.json" > /dev/null; do
  [ "$(( ($(now_ns) - start) / 1000000000 ))" -lt 360 ] ||
    fail "case 9: the draft's checks did not conclude within 360s of its pipeline; see $OUT/checks-9-draft.json"
  sleep 5
done
DRAFT9_TOOK=$(since "$start")
echo "e2e: case 9: a draft proposed change $PC9 opened on $FR in ${PROPOSE9_TOOK}s, its checks concluded ${DRAFT9_TOOK}s after"
expect "$OUT/checks-9-draft.json" '(map(select(.name == "fylgja-twin")) | length == 1 and (.[0] | .conclusion == "success"
    and ((.message // "") | contains("skipped: proposed change " + env.PC9 + " is a draft"))))
  and (map(select(.name == "fylgja-step")) | length == 1 and .[0].conclusion == "success")'
comments_of 9-draft "$PC9" 2> "$OUT/comments-9-draft.err" ||
  fail "case 9: reading $PC9's comments failed; see $OUT/comments-9-draft.err"
expect "$OUT/comments-9-draft.json" 'length == 0'

# The two marks, each after the writes it seals and their rendering, as case 7 makes them,
# then the proposed change marked ready, which starts nothing: the checks are run again.
artifacts_of "$FR" "$OUT/artifacts-9-sealed-1.json" 2> "$OUT/artifacts-9-sealed-1.err" ||
  fail "case 9: reading $FR's artifacts failed; see $OUT/artifacts-9-sealed-1.err"
expect "$OUT/artifacts-9-sealed-1.json" 'length == 3 and all(.[]; .status == "Ready")'
fixture -branch "$FR" -stage seeded -description seeded > "$OUT/stage-9-seeded.out" 2> "$OUT/stage-9-seeded.err" ||
  fail "case 9: marking stage $FR/seeded failed; see $OUT/stage-9-seeded.err"
fixture -branch "$FR" -add-link > "$OUT/add-link-9.out" 2> "$OUT/add-link-9.err" ||
  fail "case 9: -add-link on $FR failed; see $OUT/add-link-9.err"
await_checksums_moved 9 "$FR" "$OUT/artifacts-9-sealed-1.json" n1 n3
fixture -branch "$FR" -stage third-link -description "third link" > "$OUT/stage-9-third-link.out" 2> "$OUT/stage-9-third-link.err" ||
  fail "case 9: marking stage $FR/third-link failed; see $OUT/stage-9-third-link.err"
fixture -branch "$FR" -ready > "$OUT/ready-9.out" 2> "$OUT/ready-9.err" ||
  fail "case 9: -ready on $FR failed; see $OUT/ready-9.err"

# The rehearsal, every stage passing. -run-checks waits until both checks have run again to
# completed; fylgja-twin's run is the rehearsal: the baseline seeded built and verified,
# third-link and the head stepped to, and the twin destroyed, then its comment and its
# conclusion. Its message is the report's text, its comment the report's markdown.
start=$(now_ns)
fixture -branch "$FR" -run-checks user > "$OUT/run-checks-9a.out" 2> "$OUT/run-checks-9a.err" ||
  fail "case 9: -run-checks user on $FR failed; see $OUT/run-checks-9a.err"
REHEARSE9A_TOOK=$(since "$start")
echo "e2e: case 9: the ready proposed change's checks concluded in ${REHEARSE9A_TOOK}s"
run_checks_named 9a success
user_checks 9a "$PC9" 2> "$OUT/checks-9a.err" || fail "case 9: reading $PC9's checks failed; see $OUT/checks-9a.err"
expect "$OUT/checks-9a.json" '(map(select(.name == "fylgja-twin")) | length == 1 and (.[0] | .conclusion == "success"
    and .validator_state == "completed" and ((.message // "") | contains("rehearsal ok"))))
  and (map(select(.name == "fylgja-step")) | length == 1 and .[0].conclusion == "success")'
stage_lines 9a "^stage $FR/branch-point: refused \\(scope\\.empty\\)\$" "^stage $FR/seeded: created; .*; baseline\$" \
  "^stage $FR/third-link: stepped .*; loss $LOSS9; passed\$" "^stage $FR/head: .*; passed\$"
comments_of 9a "$PC9" 2> "$OUT/comments-9a.err" || fail "case 9: reading $PC9's comments failed; see $OUT/comments-9a.err"
expect "$OUT/comments-9a.json" 'length == 1 and (.[0].text | contains("Status **ok**")
  and contains("| stage | at | snapshot | bundle | step | wait | verify | loss | new verification failures | verdict |")
  and contains("```mermaid") and contains("**Stages**") and endswith("\n\n" + env.CAVEAT + "\n"))'
jq -r '.[0].text' "$OUT/comments-9a.json" > "$OUT/comment-9a.md"
comment_stages 9a "branch-point=refused (scope.empty)" seeded=baseline third-link=passed head=passed
# The loss column: — where no step read a flow, the branch point refused and the baseline
# created, and n1-loop's figures where third-link stepped (016).
loss_cells 9a "branch-point=—" "seeded=—" "third-link=$LOSS9_CELL"
COMMENT9A=$(jq -r '.[0].id' "$OUT/comments-9a.json")
export COMMENT9A
rehearsal_run 9a "$OUT/comment-9a.md"
RUN9A=$REHEARSAL_RUN USED9A=$REHEARSAL_USED
echo "e2e: case 9: rehearsal run $RUN9A passed, $USED9A; one comment, holding the table, the drawing and the stages"
no_twin 9a

# A stage made to fail on the probe (016): n1:ethernet-1/10, the probe's first port, disabled
# and rendered into n1's artifact, which the step pushes. Its flow is cut there and its
# burst finds no reply, so the stage's wait expires with verify.burst failing, which the
# baseline did not have, and the gate fails the stage by the rule that fails it on any such
# finding; the port's own state is skipped, since intent disables it, and its link's ends are
# never asserted. The rehearsal builds the baseline, steps to third-link, which passes with
# its loss, and fails at probe-port-down; the head is not reached. 015's bad-port, a push
# refused, stood here: a failed stage stops the run, so it could stand neither before
# probe-port-down nor after it.
artifacts_of "$FR" "$OUT/artifacts-9b-before.json" 2> "$OUT/artifacts-9b-before.err" ||
  fail "case 9: reading $FR's artifacts failed; see $OUT/artifacts-9b-before.err"
fixture -branch "$FR" -disable-port n1:ethernet-1/10 -generate > "$OUT/disable-port-9.out" 2> "$OUT/disable-port-9.err" ||
  fail "case 9: -disable-port n1:ethernet-1/10 -generate on $FR failed; see $OUT/disable-port-9.err"
await_checksums_moved 9b "$FR" "$OUT/artifacts-9b-before.json" n1
fixture -branch "$FR" -stage probe-port-down -description "the probe's first port down" > "$OUT/stage-9-probe-port-down.out" 2> "$OUT/stage-9-probe-port-down.err" ||
  fail "case 9: marking stage $FR/probe-port-down failed; see $OUT/stage-9-probe-port-down.err"
start=$(now_ns)
fixture -branch "$FR" -run-checks user > "$OUT/run-checks-9b.out" 2> "$OUT/run-checks-9b.err" ||
  fail "case 9: -run-checks user on $FR failed; see $OUT/run-checks-9b.err"
REHEARSE9B_TOOK=$(since "$start")
echo "e2e: case 9: the checks concluded again in ${REHEARSE9B_TOOK}s"
run_checks_named 9b failure
user_checks 9b "$PC9" 2> "$OUT/checks-9b.err" || fail "case 9: reading $PC9's checks failed; see $OUT/checks-9b.err"
expect "$OUT/checks-9b.json" '(map(select(.name == "fylgja-twin")) | length == 1 and (.[0] | .conclusion == "failure"
    and .validator_state == "completed" and ((.message // "")
      | contains("stage " + env.FR + "/probe-port-down failed: verify.burst n1-loop"))))
  and (map(select(.name == "fylgja-step")) | length == 1 and .[0].conclusion == "success")'
stage_lines 9b "^stage $FR/branch-point: refused \\(scope\\.empty\\)\$" "^stage $FR/seeded: created; .*; baseline\$" \
  "^stage $FR/third-link: stepped .*; loss $LOSS9; passed\$" \
  "^stage $FR/probe-port-down: stepped .*; expired after .*; loss $LOSS9; failed: verify\\.burst n1-loop\$" "^stage $FR/head: not reached\$"
comments_of 9b "$PC9" 2> "$OUT/comments-9b.err" || fail "case 9: reading $PC9's comments failed; see $OUT/comments-9b.err"
# The failure's comment: its table, its drawing, the five commands that reproduce it in order
# (FR-015), each fylgja-cli's as the orchestrator renders them (020's R-13), the create naming
# the scope every stage was read under, the runner's default (017's T104), and the caveat
# last.
# shellcheck disable=SC2016 # the backticks are the markdown's fences, read literally by jq
expect "$OUT/comments-9b.json" 'length == 2 and any(.[]; .id == env.COMMENT9A) and (map(.thread) | unique | length == 2)
  and (map(select(.id != env.COMMENT9A)) | length == 1 and (.[0].text | contains("Status **nonconforming**")
    and contains("| stage | at | snapshot | bundle | step | wait | verify | loss | new verification failures | verdict |")
    and contains("```mermaid") and contains("**Reproduce by hand**:\n\n```\n"
      + "fylgja-cli twin create --stage " + env.FR + "/seeded --scope tag:fylgja\n"
      + "fylgja-cli twin step --stage " + env.FR + "/third-link --allow-restart\n"
      + "fylgja-cli twin step --stage " + env.FR + "/probe-port-down --allow-restart\n"
      + "fylgja-cli twin verify\nfylgja-cli twin destroy\n```\n")
    and endswith("\n\n" + env.CAVEAT + "\n")))'
jq -r '.[] | select(.id != env.COMMENT9A) | .text' "$OUT/comments-9b.json" > "$OUT/comment-9b.md"
COMMENT9B=$(jq -r '.[] | select(.id != env.COMMENT9A) | .id' "$OUT/comments-9b.json")
THREADS9=$(jq -c 'map(.thread)' "$OUT/comments-9b.json")
comment_stages 9b "branch-point=refused (scope.empty)" seeded=baseline third-link=passed probe-port-down=failed \
  "head=not reached"
# The earlier stages passed with their loss figures, and the failed one names its loss too: a
# figure is advisory, and the burst is what fails the stage (016, SC-002).
loss_cells 9b "seeded=—" "third-link=$LOSS9_CELL" "probe-port-down=$LOSS9_CELL" "head=—"
# Both threads are listed in the proposed change's overview, the reason D-053 made each
# comment a thread (SC-007), once Infrahub's event log has them: it lags its writes by a few
# seconds (D-048), so the read is repeated for a minute, as tier 2's test waits.
start=$(now_ns)
until overview_threads 9 "$PC9" 2> "$OUT/overview-9.err" &&
  jq -e --argjson want "$THREADS9" '. as $listed | all($want[]; IN($listed[]))' "$OUT/overview-9.json" > /dev/null; do
  [ "$(( ($(now_ns) - start) / 1000000000 ))" -lt 60 ] ||
    fail "case 9: after 60s the overview of $PC9 lists threads $(jq -c . "$OUT/overview-9.json" 2> /dev/null || echo none), not each of $THREADS9; see $OUT/overview-9.err"
  sleep 2
done
echo "e2e: case 9: both threads listed in $PC9's overview after $(since "$start")s"
rehearsal_run 9b "$OUT/comment-9b.md"
RUN9B=$REHEARSAL_RUN USED9B=$REHEARSAL_USED
[ "$RUN9B" != "$RUN9A" ] || fail "case 9: the second comment names the first rehearsal's run $RUN9A"
echo "e2e: case 9: rehearsal run $RUN9B failed at $FR/probe-port-down on n1-loop's burst, $USED9B; a second comment, with the commands that reproduce it"
no_twin 9b

# The branch goes with its stages and its proposed change, the threads with their comments and
# the validators going with the proposed change, and Infrahub then holds nothing of it.
if fixture -branch "$FR" -delete > "$OUT/delete-branch-9.out" 2>&1; then
  grep -qxF "deleted 3 stages, 1 proposed change, branch $FR" "$OUT/delete-branch-9.out" ||
    fail "case 9: -delete on $FR did not report its three stages and its proposed change; see $OUT/delete-branch-9.out"
  infrahub_holds_none 9 "$FR"
  gql "" "{ CoreChangeThread(ids: $THREADS9) { count } CoreThreadComment(ids: [\"$COMMENT9A\", \"$COMMENT9B\"]) { count }
    CoreUserValidator(proposed_change__ids: [\"$PC9\"]) { count } }" \
    > "$OUT/infrahub-after-9-comments.json" 2> "$OUT/infrahub-after-9-comments.err" ||
    fail "case 9: reading Infrahub after $FR's delete failed; see $OUT/infrahub-after-9-comments.err"
  expect "$OUT/infrahub-after-9-comments.json" '.CoreChangeThread.count == 0 and .CoreThreadComment.count == 0
    and .CoreUserValidator.count == 0'
  unset FR
else
  fail "case 9: -delete on $FR failed, leaving its branch, stages or proposed change; see $OUT/delete-branch-9.out"
fi
# The probe goes from main last, once nothing is left to read it, and main then holds none.
delete_probes 9
else
  skip_case 9
fi

# --- credential hygiene over everything the run produced -----------------------

# The script's server is stopped first, so its log is whole when it is searched. Every twin
# is destroyed by now, so the trap has nothing to ask it.
stop_server
[ "$SERVER_STATUS" -eq 0 ] || fail "the API's server exited $SERVER_STATUS on SIGTERM, not 0; see $OUT/server.log"

# The core reads no source of truth (020, FR-029, SC-008): the script's server was asked
# every case's creates, steps and compiles, and no operation that reads Infrahub, which
# fylgja-cli's flows asked through the adapter instead; nor was the operator's core, from
# where case 9's precheck read its log, by the runner's flows that drove it.
no_infrahub_request "the script's core server" "$OUT/server.log"
grep -q 'msg=request operation=twin\.create ' "$OUT/server.log" ||
  fail "the script's core server was asked no twin.create; see $OUT/server.log"
if ran 9; then
  no_infrahub_request "the operator's core server" "$CORE_LOG" "$CORE_LOG_FROM"
  tail -c "+$((CORE_LOG_FROM + 1))" "$CORE_LOG" | grep -q 'msg=request operation=twin\.create ' ||
    fail "case 9's rehearsals asked the operator's core on $runner_core no twin.create; see $CORE_LOG from byte $CORE_LOG_FROM"
fi
echo "e2e: the core's servers were asked no operation that reads Infrahub"

# $OUT holds the short-lived worker's stdout and stderr, the orphan's deploy output, every
# twin show document, every create's provision history, decoded, both boot halves' output
# (boot-half.out, boot-half-6.out), the plan and list documents of cases 7 and 8 (plan-*.json,
# list-*.json), the step documents, record copies and step histories of cases 5, 7 and 8,
# decoded (step-5*.json, step-7*.json, step-8*.json, twin-5*.json, twin-7*.json, twin-8*.json,
# history-step-*), the workflow service's list of runs over case 5's frozen wait
# (runs-5-frozen.json),
# every twin verify document (verify-*.json), case 9's checks with their messages
# (checks-9*.json), its proposed change's comments (comments-9*.json, comment-9*.md), its two
# flow runs as the platform answers them and their logs (flow-run-*), and the histories of
# each run of the core's they started, its provision, its steps and its destroy, decoded
# (history-rehearse-*), the overview's threads (overview-9.json), the platform's precheck
# from inside each task worker (platform-probe-*) and the answers of the platform and of the
# operator's core to this host (deployment-twin-rehearse.*, core-show.*), and the API's
# server's report and request log (server.log). A step history's push results
# carry the device's diff by design, so they are searched for the marker and the
# credentials, not for configuration lines; so do a rehearsal's step children's.
# fylgja-cli's own (020): every document it printed (dry*.json, create-*.json, read-*,
# plan-*.json, list-*.json, step-*.json), the orchestrator's state root ($OUT/orchestrator:
# its snapshots and its record, record-7.json the copy of one) and the ephemeral server's
# home ($OUT/prefect: its database of every flow run, their logs and their artifacts).
# Case 9's flows ran on the operator's platform and drove the operator's core, not the
# script's: the core's log, local/server.log by CLAUDE.md's start line, the platform's,
# local/prefect.log, and the runner's, local/orchestrator.log, are searched too, and the
# platform's home, local/orchestrator/prefect, for the credentials (SC-008).
# The probes add case 5's text dry run and twin verify (dry-5.out, verify-5.out), the fixture
# tool's probe writes and deletes (probes-*.out, delete-probes-*.out) and each create's
# snapshot's probe names (probes-snapshot-*.json), all under $OUT, and nothing else: a
# flow's and a burst's output stays in its host and reaches a document only as figures, so
# the targets do not move (016).
# The worker's log is searched when WORKER_LOG names it, and the line after the greps says
# whether it was. The bundle store holds every bundle the host compiled, and the snapshot
# stores every snapshot the core was sent and the orchestrator took, each read's CTM with
# every device's rendered configuration in it, filed beside its bundle as a sidecar before
# 018 (FR-006): all are searched for the credentials, and none for the marker, which each
# holds by design.
scan=("$OUT" "$FYLGJA_STATE_ROOT/bundles" "$FYLGJA_STATE_ROOT/snapshots")
searched="the run's outputs, fylgja-cli's state root and Prefect home, the bundle store and the core's snapshot store"
logs=()
if ran 9; then
  for log in "$CORE_LOG" "$FYLGJA_STATE_ROOT/prefect.log" "$FYLGJA_STATE_ROOT/orchestrator.log"; do
    [ -r "$log" ] ||
      fail "case 9 went through the orchestrator's platform and the operator's core, and $log, as scripts/bring-up.sh and CLAUDE.md's start lines write it, is not readable"
    logs+=("$log")
  done
  scan+=("${logs[@]}")
  [ ! -d "$PLATFORM_HOME" ] || scan+=("$PLATFORM_HOME")
  searched+=", the operator's core's, platform's and runner's logs (${logs[*]}) and the platform's home ($PLATFORM_HOME)"
fi
if [ -n "${WORKER_LOG:-}" ]; then
  [ -r "$WORKER_LOG" ] || fail "WORKER_LOG=$WORKER_LOG is not readable"
  scan+=("$WORKER_LOG")
  logs+=("$WORKER_LOG")
  searched+=" and the worker's log ($WORKER_LOG)"
else
  searched+=", and not the worker's log, since WORKER_LOG is unset"
fi
no_credential "the Infrahub token" "$INFRAHUB_API_TOKEN" "${scan[@]}"
no_credential "the API's token" "$API_TOKEN" "${scan[@]}"
# The operator's own token, when local/.env carries one: the run does not use it, but every
# process the script starts directly, the worker it greps included, has it in its environment.
# shellcheck disable=SC2031 # local/.env's token, not the one fylgja() sets in its subshell
if [ -n "${FYLGJA_API_TOKEN:-}" ]; then
  no_credential "local/.env's API token" "$FYLGJA_API_TOKEN" "${scan[@]}"
fi
# The platform's auth string (020, FR-005), which the checks send as FYLGJA_ORCHESTRATOR_AUTH
# and the runner as PREFECT_API_AUTH_STRING, one value, user:password: its password, which
# any form that carries it holds, and the basic-auth header's base64 of the whole.
for secret in PREFECT_API_AUTH_STRING FYLGJA_ORCHESTRATOR_AUTH; do
  if [ -n "${!secret:-}" ]; then
    no_credential "local/.env's $secret" "${!secret#*:}" "${scan[@]}"
    no_credential "local/.env's $secret, as a basic-auth header carries it" "$(printf %s "${!secret}" | base64 -w0)" "${scan[@]}"
  fi
done
no_credential "the probe password" "$FYLGJA_SRLINUX_PASSWORD" "${scan[@]}"
# Infrahub's own secrets, which Compose reads from local/.env and Fylgja never does: the task
# workers that run the checks hold them (SC-008), so the comments, the messages and every
# output are searched for each that local/.env sets.
for secret in INFRAHUB_SECURITY_SECRET_KEY INFRAHUB_INITIAL_AGENT_TOKEN INFRAHUB_INITIAL_ADMIN_PASSWORD; do
  if [ -n "${!secret:-}" ]; then
    no_credential "local/.env's $secret" "${!secret}" "${scan[@]}"
  fi
done
# The EOS password is the image's published default, `admin`: too common a word for the
# strong grep, so it is searched for in the shapes that would be a leak.
no_credential_contextual "the EOS password" "$FYLGJA_EOS_PASSWORD" "${scan[@]}"

# The marker: every output, record copy, twin show document, check result,
# history, flow run, the ephemeral server's home, the servers', the platform's and the
# runner's logs and the worker log. A read's snapshot (snapshot-*.json), the orchestrator's
# snapshot store ($OUT/orchestrator/snapshots) and a compiled bundle (compiled-*/) carry the
# artifact by design, as the core's snapshot and bundle stores do, so they are left out, and
# the stores with them.
marker_excluded=(--exclude='snapshot-*.json' --exclude-dir='compiled-*' --exclude-dir=snapshots)
if grep -rqsF "${marker_excluded[@]}" -- "$MARKER" "$OUT" ${logs[@]+"${logs[@]}"}; then
  echo "e2e: LEAK: the artifact marker found in:" >&2
  grep -rlsF "${marker_excluded[@]}" -- "$MARKER" "$OUT" ${logs[@]+"${logs[@]}"} >&2 || true
  exit 1
fi
echo "e2e: no credential and no marker in $searched"

# The timings are recorded, not asserted: a slow host is the host's.
for t in "${CREATE_TIMES[@]}"; do
  echo "e2e: create $t"
done
# A case's line only when it ran: a skipped case set none of its variables, which set -u
# would refuse. Cases 1 and 5 need nokia_srlinux alone, which every list that selects a case
# names, so they run whenever any case does.
if ran 5; then
  echo "e2e: case 5: seed ${SEED_TOOK}s, frozen wait ${FROZEN5_TOOK}s from the change, step 5a ${STEP5A_TOOK}s and step 5b ${STEP5B_TOOK}s, destroy ${DESTROY5_TOOK}s; n1-loop $LOSS5A at 5a and $LOSS5B at 5b"
fi
if ran 6; then
  echo "e2e: case 6: seed ${SEED6_TOOK}s, mixed twin $BID6 under run $RUN6"
fi
if ran 7; then
  echo "e2e: case 7: proposed change ${PROPOSE7_TOOK}s, plan ${PLAN7_TOOK}s, create ${CREATE7_TOOK}s, steps ${STEP7A_TOOK}s and ${STEP7B_TOOK}s; runs $RUN7A and $RUN7B"
fi
if ran 8; then
  echo "e2e: case 8: proposed change ${PROPOSE8_TOOK}s, steps ${STEP8A_TOOK}s and ${STEP8B_TOOK}s, create ${CREATE8_TOOK}s; runs $RUN8A and $RUN8B; e1-loop $LOSS8A and $LOSS8B"
fi
if ran 9; then
  echo "e2e: case 9: seed ${SEED9_TOOK}s, proposed change ${PROPOSE9_TOOK}s and its checks ${DRAFT9_TOOK}s; checks with the rehearsals ${REHEARSE9A_TOOK}s ($USED9A) and ${REHEARSE9B_TOOK}s ($USED9B); runs $RUN9A and $RUN9B"
fi
line="e2e: verify ${VERIFY1_TOOK}s (case 1), ${VERIFY5_TOOK}s (case 5)"
if ran 6; then line+=", ${VERIFY6_TOOK}s (case 6)"; fi
if ran 8; then line+="; case 8 settled after ${WAIT8A_AFTER}s and ${WAIT8B_AFTER}s"; fi
echo "$line"
line="e2e: wall time $(since "$RUN_START")s, boot half ${BOOT_HALF_TOOK}s (case 1)"
if ran 5; then line+=", ${BOOT_HALF5_TOOK}s (case 5)"; fi
if ran 6; then line+=" and ${BOOT_HALF6_TOOK}s (case 6)"; fi
echo "$line"
if [ "${#SKIPPED[@]}" -eq 0 ]; then
  echo E2E-OK
else
  echo "E2E-PARTIAL: platforms ${PLATFORM_LIST[*]}; ran ${RAN[*]}; skipped ${SKIPPED[*]}"
fi
