#!/bin/bash
# Tier 3: eight cases in one run, making eight twins, through the workflow service and the
# operator's worker, leaving the host as it found it. Run by `make test-e2e` from the
# repository root. Never runs in CI and never gates a PR. M3's four cases create with
# --no-follow, so nothing checks their twins.
#
# Every fylgja command but worker run goes through the API (M13): the script starts a server
# of its own from the tree, on a port of its own, with a token it makes for the run, and
# stops it in its trap. Each command runs with PATH, HOME and the API's address and token,
# and nothing else of the script's environment. The script's own reads (gnmic, Docker,
# containerlab, twin.json, the store), the boot half and the fixture tool stay direct, with
# the full environment, and so does case 3's short-lived worker.
#
# After every create and every rebuild: each node's first cabled interface reads,
# over the gNMI its own package declares, the description its staged artifact sets (bootstrap
# sets none), n1's ethernet-1/2 admin-state is what the artifact says, and twin.json's
# checksums are Infrahub's. Every node is ready inside its own package's readiness budget,
# which differs per platform. Every artifact carries a marker in its role comment; it is found
# in no output, record, document, history or worker log.
#
#   1. create from fylgja-fixture; the conformance suite's boot half reads that twin (M6:
#      host name, every cabled port enabled, discovering and seeing the far end the bundle's
#      link names, the version listed, readiness under budget); twin verify finds it
#      conforming (M12); a second create, refused naming that twin; destroy
#   2. create --at T, T fixed at the start: another reference, another bundle_id; destroy
#   3. a one-node lab fylgja deployed by hand outside the state root: a short-lived worker
#      of the script's own names it an orphan at start, a dry-run create is refused naming
#      it, and destroy clears it
#   4. create --at T again: case 2's bundle_id; destroy
#   5. a throwaway branch seeded; create following it every 15s; a check leaves the twin
#      untouched; an artifact-only change (n1:ethernet-1/2 disabled, then generated) rebuilds
#      the twin with no command and the node reads disable, and twin verify skips that port
#      and its link (M12); the branch's topology changed; the twin rebuilt again; twin show
#      says so; destroy stops following; the branch deleted
#   6. a throwaway branch seeded with the mixed fixture (M7): one twin of two platforms,
#      s1 on SR Linux and e1, e2 on EOS, each node read back over its own package's gNMI;
#      the boot half reads this twin too, and twin verify reads each node over its own
#      transport (M12); twin show names each node's package; destroy; the branch deleted
#   7. a throwaway branch seeded and a test series of the same name (M10): waypoint 1 written,
#      a third link added, waypoint 2 written; waypoint plan names two ids and the step
#      between them; waypoint list names both; create --waypoint from each in turn deploys
#      the id the plan printed, records the waypoint in twin.json 3, and twin show and
#      waypoint list name it; destroy each; the branch and its series deleted
#   8. a throwaway branch seeded with the mixed fixture and a test series of the same name
#      (M11): waypoint 1, a link s1:ethernet-1/3 <-> e1:Ethernet3 added, waypoint 2; create
#      --waypoint from 1, pushed by replace; the step to 2 refused without --allow-restart,
#      dry run and run, naming e1; taken with it: e1 restarted in place, s1 re-cabled live
#      and e2 untouched (their containers say so), both pushed, the new link seen from both
#      ends over gNMI, twin.json 5 naming the step and its wait settled (M12); the step back
#      to 1, settled too; destroy; the branch and its series deleted
#
# Needs, all running from this directory: `make temporal-dev`, `make worker` (restarted
# after every rebuild, since case 1's refusal is worded by the worker and case 5's checks
# run on it), Docker, containerlab, the SR Linux image, the imported cEOS image (never
# pulled; docs/development.md says how to import it), go (cases 1 and 6 run the boot half as
# go test; cases 5 and 6 seed their branches with cmd/fylgja-fixture), and Infrahub with
# fylgja-fixture seeded (local/.env). The API's server is the script's own, so no server the
# operator runs is needed, and none is used: its port is one the system chooses.
# Optional: WORKER_LOG names that worker's log, which the credential greps then cover too.
# Optional: PLATFORMS narrows the run to a list of shipped packages (the stems of psp/*.yaml,
# separated by commas or spaces): a case runs when every package it needs is in the list and
# each account-gated image it needs is present, and is skipped, saying why, otherwise. Unset
# or empty, every case runs and every package's image is required first. A name no package
# has, or a list that selects no case, is refused before anything starts.
# It takes minutes; run it on a quiet host (docs/development.md).
#
# Exit 0 prints E2E-OK when every case ran, or, when PLATFORMS skipped one, E2E-PARTIAL naming
# the list, the cases that ran and each case skipped with its reason. Any failed check exits 1
# after the trap's destroy and its deletion of the throwaway branches of cases 5, 6, 7 and 8
# (7's and 8's with their series); a lab, a twin directory or Schedule fylgja-follow
# left behind after that destroy exits 99.
set -euo pipefail

fail() {
  echo "e2e: FAILED: $*" >&2
  exit 1
}

# The packages each case needs, read by case_runs and the list's refusals alone: every
# case boots SR Linux, and 6 and 8 boot EOS beside it.
declare -A CASE_PACKAGES=([1]=nokia_srlinux [2]=nokia_srlinux [3]=nokia_srlinux [4]=nokia_srlinux
  [5]=nokia_srlinux [6]="nokia_srlinux arista_eos" [7]=nokia_srlinux [8]="nokia_srlinux arista_eos")
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
: "${INFRAHUB_API_TOKEN:?local/.env must set INFRAHUB_API_TOKEN}"

FYLGJA=./bin/fylgja
BRANCH=fylgja-fixture
export BRANCH
TWIN="$FYLGJA_STATE_ROOT/twin"
TEMPORAL_ADDRESS="${FYLGJA_TEMPORAL_ADDRESS:-localhost:7233}"
OUT=$(mktemp -d "${TMPDIR:-/tmp}/fylgja-e2e.XXXXXX")
# Resolved, so the orphan's topology path compares with containerlab's absLabPath.
OUT=$(realpath "$OUT")
echo "e2e: outputs in $OUT"

# The API's token for this run alone: made here, given to the script's server
# and to each command, never printed, and searched for in everything the run produced. A
# token in local/.env is not used. 24 bytes are 32 characters of base64, no padding.
API_TOKEN=$(head -c 24 /dev/urandom | base64)
[ -n "$API_TOKEN" ] || { echo "e2e: FAILED: no API token could be made from /dev/urandom" >&2; exit 1; }
# The server's address, read from the listen line of its start-up report;
# the bound only stops a server that never reports from holding the run.
API_ADDRESS=""
SERVER_LISTEN_WAIT_S=15

# Case 5's interval: the floor is 10s (provision.MinInterval), and three intervals bound the
# wait for an unchanged check.
FOLLOW_INTERVAL_S=15
FOLLOW_SCHEDULE=fylgja-follow
export FOLLOW_INTERVAL_S

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

# psp_scalar FILE KEY: the value of the one `  key: value` line in a support package, less
# its trailing comment. The keys read here — `ref` under image, `timeout_s` under
# readiness — each appear once at that indent, and the script reads them from the package
# rather than repeating them, so a package that moves moves this tier with it.
psp_scalar() {
  sed -n "s/^  $2: *\([^ #]*\).*/\1/p" "$1" | head -1
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

# gql BRANCH QUERY: Infrahub's GraphQL answer's data on the branch. The token goes to curl
# as a header file, so it is in no process's arguments.
gql() {
  local body
  body=$(jq -cn --arg q "$2" '{query: $q}')
  curl -sS --fail-with-body -H @<(printf 'X-INFRAHUB-KEY: %s\n' "$INFRAHUB_API_TOKEN") \
    -H 'Content-Type: application/json' -d "$body" "$INFRAHUB_ADDRESS/graphql/$1" | jq -e '.data'
}

# artifacts_of BRANCH FILE: each device's device-config artifact on the branch, read through
# the generic as the read does, as {device: {status, checksum}}. Only the
# identity is asked for: the content carries the marker.
artifacts_of() {
  gql "$1" '{ FylgjaDevice { edges { node { name { value }
    ... on CoreArtifactTarget { artifacts { edges { node { status { value } checksum { value }
      definition { node { ... on CoreArtifactDefinition { artifact_name { value } } } } } } } } } } } }' |
    jq '[.FylgjaDevice.edges[].node | {key: .name.value, value: ([.artifacts.edges[].node
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
# node in twin.json: the ethernet-1/1 description over gNMI is the
# staged artifact's, and its recorded checksum is Infrahub's on the branch; n1's
# ethernet-1/2 admin-state reads N1_E12_STATE. The staged artifact is read in place and
# its line never copied into $OUT, where the marker grep looks.
#
# Infrahub's checksums are read now, or taken from HELD, an artifacts_of file read when the
# twin's pinned reference was written. Case 7's first waypoint needs it: the branch has
# moved on since, and the twin runs what Infrahub held then.
readback() {
  local case=$1 branch=$2 want_state=$3 held=${4:-} name addr file want got
  if [ -z "$held" ]; then
    held="$OUT/artifacts-readback-$case.json"
    artifacts_of "$branch" "$held" 2> "$OUT/artifacts-readback-$case.err" ||
      fail "case $case: reading the artifacts of $branch from Infrahub failed; see $OUT/artifacts-readback-$case.err"
  fi
  jq -e --slurpfile tw "$TWIN/twin.json" '. as $inf | ($tw[0].nodes | length) == 3
    and all($tw[0].nodes[]; .artifact.checksum == $inf[.name].checksum and $inf[.name].status == "Ready")' \
    "$held" > /dev/null ||
    fail "case $case: twin.json's checksums are not Infrahub's on $branch; compare $TWIN/twin.json with $held"
  while read -r name addr file; do
    want=$(sed -n 's|^set / interface ethernet-1/1 description "\(.*\)"$|\1|p' "$TWIN/bundle/$file")
    [ -n "$want" ] || fail "case $case: $TWIN/bundle/$file sets no description on ethernet-1/1"
    got=$(gnmi_value "$case" "$addr" '/interface[name=ethernet-1/1]/description')
    [ "$got" = "$want" ] || fail "case $case: node $name's ethernet-1/1 description reads \"$got\", its artifact sets \"$want\""
  done < <(jq -r --slurpfile m "$TWIN/bundle/manifest.json" \
    '.nodes[] as $n | "\($n.name) \($n.mgmt_ipv4) \($m[0].nodes[] | select(.name==$n.name) | .artifact.file)"' "$TWIN/twin.json")
  addr=$(jq -r '.nodes[] | select(.name=="n1") | .mgmt_ipv4' "$TWIN/twin.json")
  got=$(gnmi_value "$case" "$addr" '/interface[name=ethernet-1/2]/admin-state')
  [ "$got" = "$want_state" ] || fail "case $case: n1's ethernet-1/2 admin-state reads $got, not $want_state"
  echo "e2e: case $case: every node runs its artifact; n1 ethernet-1/2 $got; checksums are Infrahub's"
}

# readback_mixed CASE BRANCH [HELD]: the mixed twin runs its artifacts, each node read over the
# transport its own support package declares. twin.json's checksums are
# Infrahub's on the branch, as readback checks; then, per node, by the package twin.json
# records: an SR Linux node as readback reads it, and an EOS node by its host name and by
# the description its artifact sets on the first interface the rendering describes. The
# staged artifact is read in place and its lines are never copied into $OUT, where the
# marker grep looks.
#
# Infrahub's checksums are read now, or taken from HELD, as readback takes them: case 8's
# twin at its first waypoint runs what Infrahub held when that waypoint was written (M11).
readback_mixed() {
  local case=$1 branch=$2 held=${3:-} name addr pspid file want got port
  if [ -z "$held" ]; then
    held="$OUT/artifacts-readback-$case.json"
    artifacts_of "$branch" "$held" 2> "$OUT/artifacts-readback-$case.err" ||
      fail "case $case: reading the artifacts of $branch from Infrahub failed; see $OUT/artifacts-readback-$case.err"
  fi
  jq -e --slurpfile tw "$TWIN/twin.json" '. as $inf | ($tw[0].nodes | length) == 3
    and all($tw[0].nodes[]; .artifact.checksum == $inf[.name].checksum and $inf[.name].status == "Ready")' \
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
    '.nodes[] as $n | "\($n.name) \($n.mgmt_ipv4) \($n.psp.id) \($m[0].nodes[] | select(.name==$n.name) | .artifact.file)"' "$TWIN/twin.json")
  echo "e2e: case $case: every node runs its artifact, each read over its own platform; checksums are Infrahub's"
}

# verify_twin CASE [WAIT]: twin verify on the running twin, with --wait=WAIT when given: exit
# 0, status ok and zero findings, every non-skipped assertion held. The
# document is kept in $OUT, so the greps below cover it. Held counts the three kinds read
# from a node; the record's claims are counted apart, since they are the record's and never
# read. Sets VERIFY_TOOK.
verify_twin() {
  local case=$1 wait=${2:-} start status=0 args=() held skipped
  [ -z "$wait" ] || args=(--wait="$wait")
  start=$(now_ns)
  fylgja twin verify "${args[@]}" --json > "$OUT/verify-$case.json" 2> "$OUT/verify-$case.err" || status=$?
  VERIFY_TOOK=$(since "$start")
  [ "$status" -eq 0 ] || fail "case $case: twin verify exited $status; see $OUT/verify-$case.json and $OUT/verify-$case.err"
  expect "$OUT/verify-$case.json" '.status=="ok" and .operation=="twin.verify" and .findings==[]'
  held=$(jq '.verify.counts | .host_name.held + .port_enabled.held + .neighbor.held' "$OUT/verify-$case.json")
  skipped=$(jq '.verify.counts | (.port_enabled.skipped // 0) + (.neighbor.skipped // 0)' "$OUT/verify-$case.json")
  echo "e2e: case $case: twin verify ${VERIFY_TOOK}s, $held held, $skipped skipped"
}

# schedule_state: present or absent as the workflow service answers for Schedule
# fylgja-follow, or unknown when it gave no answer. describe exits 1 on an absent Schedule
# and says "not found".
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

# compiled_id CASE ARGS...: the stage commands on the same branch, intent read ARGS then
# twin compile; sets COMPILED_ID. A run's bundle is the one they compile (D-024).
compiled_id() {
  local case=$1
  shift
  fylgja intent read --branch "$BRANCH" "$@" --out "$OUT/ctm-$case.json" > "$OUT/read-$case.out" 2> "$OUT/read-$case.err" ||
    fail "case $case: intent read failed; see $OUT/read-$case.err"
  fylgja twin compile --ctm "$OUT/ctm-$case.json" --out "$OUT/compiled-$case" --json > "$OUT/compile-$case.json" 2> "$OUT/compile-$case.err" ||
    fail "case $case: twin compile failed; see $OUT/compile-$case.err"
  COMPILED_ID=$(jq -r .bundle_id "$OUT/compile-$case.json")
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

# create_twin CASE ARGS...: twin create --branch $BRANCH ARGS, or --waypoint $CREATE_REF in
# place of the branch when CREATE_REF is set (case 7), ending with three
# ready nodes, the twin recorded, the bundle stored and staged as its id, and each node
# running its artifact; sets and exports BID and RUN_ID,
# and sets CREATE_TOOK.
CREATE_TIMES=()
create_twin() {
  local case=$1
  shift
  local start status=0 took ref=(--branch "$BRANCH")
  [ -z "${CREATE_REF:-}" ] || ref=(--waypoint "$CREATE_REF")
  start=$(now_ns)
  fylgja twin create "${ref[@]}" "$@" --json > "$OUT/create-$case.json" 2> "$OUT/create-$case.err" || status=$?
  took=$(since "$start")
  CREATE_TOOK=$took
  echo "e2e: case $case: create took ${took}s (exit $status)"
  expect "$OUT/create-$case.json" '.status=="ok" and (.twin.nodes|length)==3'
  jq -r '.twin.nodes[] | "e2e:   \(.name)  \(.mgmt_ipv4)  ready after \(.ready_after_s)s"' "$OUT/create-$case.json"

  BID=$(jq -r .bundle_id "$OUT/create-$case.json")
  RUN_ID=$(jq -r .subject.run_id "$OUT/create-$case.json")
  export BID RUN_ID
  echo "e2e: case $case: bundle_id $BID, run $RUN_ID"

  clab inspect --all --format json > "$OUT/inspect-create-$case.json"
  expect "$OUT/inspect-create-$case.json" '.fylgja | length == 3 and all(.state=="running")'

  expect "$TWIN/twin.json" '.bundle_id==env.BID and .source=="intent" and .observed_at != null
    and .run.workflow_id=="fylgja-provision" and .run.run_id==env.RUN_ID and (.nodes|length)==3'

  # Every node ready inside its own package's readiness budget, read from that package: a
  # mixed twin's nodes are held to different ones. For cases 1-5, all SR Linux,
  # this is the 60s a single bound asserted before M7.
  local name pspid ready budget
  while read -r name pspid ready; do
    budget=$(psp_scalar "psp/$pspid.yaml" timeout_s)
    [ -n "$budget" ] || fail "case $case: psp/$pspid.yaml states no readiness timeout_s"
    awk -v r="$ready" -v b="$budget" 'BEGIN { exit !(r < b) }' ||
      fail "case $case: node $name ($pspid) was ready after ${ready}s, its package's readiness budget is ${budget}s"
  done < <(jq -r '.nodes[] | "\(.name) \(.psp.id) \(.ready_after_s)"' "$TWIN/twin.json")

  { [ -d "$FYLGJA_STATE_ROOT/bundles/$BID" ] && [ -f "$FYLGJA_STATE_ROOT/bundles/$BID.ctm.json" ]; } ||
    fail "case $case: the store holds no entry or no CTM for $BID"
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
# 60s, leaving no lab, no twin directory and the bundle store as it was.
destroy_twin() {
  local case=$1 teardown=$2 unstage=$3
  local before start status=0 took
  before=$(store_digest)
  start=$(now_ns)
  fylgja twin destroy --json > "$OUT/destroy-$case.json" 2> "$OUT/destroy-$case.err" || status=$?
  took=$(since "$start")
  echo "e2e: case $case: destroy took ${took}s (exit $status)"
  expect "$OUT/destroy-$case.json" ".status==\"ok\" and .cleanup.teardown==\"$teardown\" and .cleanup.unstage==\"$unstage\" and (.cleanup.remaining|length)==0"
  [ "${took%.*}" -lt 60 ] || fail "case $case: destroy took ${took}s, over 60s"
  [ "$(clab inspect --all --format json)" = "{}" ] || fail "case $case: containerlab still reports a lab after destroy"
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
  # Destroy stops following first, so no check rebuilds what it removes. It is a request to
  # the script's server, which the success path has already stopped once nothing was left.
  if [ -n "${SERVER_PID:-}" ]; then
    fylgja twin destroy --json > "$OUT/trap-destroy.json" 2> "$OUT/trap-destroy.err" || true
  fi
  # The throwaway branches of cases 5, 6, 7 and 8, when they were made and not yet deleted;
  # -delete removes case 7's and case 8's series with their branches. A failure is
  # reported, not fatal. The destroy above cancels a step in flight and waits for its record.
  local branch
  for branch in "${FB:-}" "${FM:-}" "${FW:-}" "${FS:-}"; do
    [ -n "$branch" ] || continue
    if ! fixture -branch "$branch" -delete > "$OUT/trap-delete-$branch.out" 2>&1; then
      echo "e2e: branch $branch was not deleted; remove it with: go run -tags fixture ./cmd/fylgja-fixture -branch $branch -delete" >&2
    fi
  done
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
  if [ -e "$TWIN" ]; then
    echo "e2e: LEAK: $TWIN still present" >&2
    exit 99
  fi
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

# Every artifact carries this in its role comment (testsupport.MarkerPrefix); it may sit
# in the staged bundle, the store and a read's CTM, and nowhere else.
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
command -v gnmic > /dev/null || fail "gnmic is not on PATH: every create's read-back uses it"
command -v go > /dev/null || fail "go is not on PATH: case 5 seeds its branch with go run -tags fixture ./cmd/fylgja-fixture; install Go or add it to PATH"
# The Temporal CLI, from the PATH or else where its installer, run by scripts/bring-up.sh,
# puts it and leaves it off the PATH.
PATH="$PATH:$HOME/.temporalio/bin"
command -v temporal > /dev/null || fail "the Temporal CLI is neither on PATH nor in ~/.temporalio/bin, where scripts/bring-up.sh installs it"
if ! temporal operator cluster health --address "$TEMPORAL_ADDRESS" > "$OUT/health.out" 2>&1; then
  fail "the workflow service is not answering at $TEMPORAL_ADDRESS: start it with make temporal-dev"
fi

# The script's own server, from the tree and in the script's full environment:
# Infrahub's variables, both logins, the state root, and docker and containerlab on its PATH,
# which it reads at each request. Asked for port 0, it listens on one the system chose and
# names it in its listen line, so no port is taken from another process, nor one taken
# between a check and the listen. Started as a simple command so that $! is the server
# itself, as case 3's worker is. Its report and its request log go to server.log, which the
# greps below search.
FYLGJA_API_TOKEN="$API_TOKEN" "$FYLGJA" serve --listen 127.0.0.1:0 > "$OUT/server.log" 2>&1 &
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

# The dry run touches nothing but the bundle store. Refused means the host
# already holds a twin this script did not make: say so rather than destroy it.
dry_status=0
fylgja twin create --branch "$BRANCH" --dry-run --json > "$OUT/dry.json" 2> "$OUT/dry.err" || dry_status=$?
if jq -e '.dry_run.verdict=="refused"' "$OUT/dry.json" > /dev/null 2>&1; then
  fail "the host is not clear ($(jq -r '[.findings[] | select(.severity=="rejection") | .rule] | join(", ")' "$OUT/dry.json")): run fylgja twin destroy first"
fi
expect "$OUT/dry.json" '.status=="ok" and .dry_run.verdict=="clear" and (.dry_run.nodes|length)==3'
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

create_twin 1 --no-follow
BID1=$BID RUN1=$RUN_ID
export BID1 RUN1
expect "$TWIN/twin.json" '.provenance.branch==env.BRANCH and (.provenance | has("at") | not)'

compiled_id 1
[ "$BID1" = "$COMPILED_ID" ] || fail "case 1: the run deployed $BID1, but intent read | twin compile gives $COMPILED_ID"

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
fylgja twin create --branch "$BRANCH" --no-follow --json > "$OUT/refused-1.json" 2> "$OUT/refused-1.err" || refused_status=$?
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

create_twin 2 --at "$T"
BID2=$BID RUN2=$RUN_ID
export BID2 RUN2
[ "$BID2" != "$BID1" ] || fail "case 2: create --at $T gave case 1's bundle_id $BID1"
expect "$TWIN/twin.json" '.provenance.branch==env.BRANCH and .provenance.at==env.T and .bundle_id==env.BID2'
expect "$FYLGJA_STATE_ROOT/bundles/$BID2/manifest.json" '.provenance.at==env.T'
{ [ -d "$FYLGJA_STATE_ROOT/bundles/$BID1" ] && [ -d "$FYLGJA_STATE_ROOT/bundles/$BID2" ]; } ||
  fail "case 2: the store does not hold both bundles $BID1 and $BID2"

compiled_id 2 --at "$T"
[ "$BID2" = "$COMPILED_ID" ] || fail "case 2: the run deployed $BID2, but intent read --at $T | twin compile gives $COMPILED_ID"

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
fylgja twin create --branch "$BRANCH" --no-follow --dry-run --json > "$OUT/dry-orphan.json" 2> "$OUT/dry-orphan.err" || dry_orphan_status=$?
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

create_twin 4 --at "$T"
BID4=$BID RUN4=$RUN_ID
[ "$BID4" = "$BID2" ] || fail "case 4: create --at $T gave $BID4, but case 2 gave $BID2"
[ "$RUN4" != "$RUN2" ] || fail "case 4: create --at $T reports case 2's run $RUN2"
expect "$TWIN/twin.json" '.provenance.at==env.T and .bundle_id==env.BID2'

destroy_twin 4 "done" "done"
destroy_twin 4-again "nothing" "nothing"
else
  skip_case 4
fi

# --- case 5: an unpinned twin follows its branch (M4) --------------------------
if case_runs 5; then

# A throwaway branch: fylgja-fixture is never changed. Set before seeding, so the
# trap deletes a branch the seed left half made.
# The pid and a random number: the seed's marker role carries the branch name, so no two
# runs share one.
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
create_twin 5 --interval "${FOLLOW_INTERVAL_S}s"
BID5=$BID RUN5=$RUN_ID
export BID5 RUN5
expect "$OUT/create-5.json" '.following.branch==env.FB and .following.interval_s==(env.FOLLOW_INTERVAL_S|tonumber)
  and .following.schedule_id=="fylgja-follow" and .following.state=="started"'

fylgja twin show --json > "$OUT/show-5-created.json" 2> "$OUT/show-5-created.err" ||
  fail "case 5: twin show exited non-zero after the create; see $OUT/show-5-created.err"
expect "$OUT/show-5-created.json" '.show.kind=="following" and .show.record.bundle_id==env.BID5
  and .show.following.interval_s==(env.FOLLOW_INTERVAL_S|tonumber)'

# An unchanged check touches nothing: twin.json and the lab's containers are the
# same after a check has compared and found the branch unchanged. The containers are found
# by containerlab's own label, containerlab=fylgja.
twin_before=$(sha256sum < "$TWIN/twin.json")
containers_before=$(docker ps -q --no-trunc --filter label=containerlab=fylgja | LC_ALL=C sort)
[ "$(grep -c . <<< "$containers_before")" -eq 3 ] || fail "case 5: docker lists $(grep -c . <<< "$containers_before") containers of lab fylgja, not 3"
wait_s=$(( 3 * FOLLOW_INTERVAL_S ))
start=$(now_ns)
while :; do
  fylgja twin show --json > "$OUT/show-5-unchanged.json" 2> "$OUT/show-5-unchanged.err" || true
  jq -e '.show.following.last_check.outcome=="unchanged" and .show.following.last_check.twin_bundle_id==env.BID5' \
    "$OUT/show-5-unchanged.json" > /dev/null 2>&1 && break
  [ "$(( ($(now_ns) - start) / 1000000000 ))" -lt "$wait_s" ] ||
    fail "case 5: no check ended unchanged within ${wait_s}s of the create; see $OUT/show-5-unchanged.json"
  sleep 5
done
echo "e2e: case 5: a check ended unchanged $(since "$start")s after the first show"
[ "$twin_before" = "$(sha256sum < "$TWIN/twin.json")" ] || fail "case 5: an unchanged check changed twin.json"
[ "$containers_before" = "$(docker ps -q --no-trunc --filter label=containerlab=fylgja | LC_ALL=C sort)" ] ||
  fail "case 5: an unchanged check changed lab fylgja's containers"

# await_rebuild CASE PREV_RUN: the twin rebuilt with no command, to COMPILED_ID: twin.json
# records it under a run other than PREV_RUN, and three nodes run. Polled every second,
# not every five: the check that rebuilt stays twin show's last check only until the next
# check closes, which can be a few seconds after it at a 15s interval. Sets REBUILD_TOOK,
# from CHANGED.
await_rebuild() {
  local case=$1
  export PREV_RUN=$2
  # A rebuild is a destroy and a whole create, so this bound is the create's; M4 measured
  # 69.4s and M5 58.7-65.0s, and this host has taken 557s for one create.
  local rebuild_wait_s=$(( FOLLOW_INTERVAL_S + 600 ))
  until jq -e '.bundle_id==env.COMPILED_ID and .run.run_id!=env.PREV_RUN' "$TWIN/twin.json" > /dev/null 2>&1 &&
    clab inspect --all --format json 2> /dev/null | jq -e '(.fylgja // []) | length==3 and all(.state=="running")' > /dev/null; do
    [ "$(( ($(now_ns) - CHANGED) / 1000000000 ))" -lt "$rebuild_wait_s" ] ||
      fail "case $case: the twin was not rebuilt to $COMPILED_ID within ${rebuild_wait_s}s of the change"
    sleep 1
  done
  REBUILD_TOOK=$(since "$CHANGED")
  echo "e2e: case $case: rebuilt ${REBUILD_TOOK}s after the change"
  cp "$TWIN/twin.json" "$OUT/twin-$case.json"
}

# The artifact-only change: n1's ethernet-1/2 disabled, which the compiler
# does not see, then generated. Only the artifact moves, and bootstrap's enable is
# overridden by it on the node.
artifacts_of "$FB" "$OUT/artifacts-5a-before.json" 2> "$OUT/artifacts-5a-before.err" ||
  fail "case 5: reading $FB's artifacts failed; see $OUT/artifacts-5a-before.err"
fixture -branch "$FB" -disable-port n1:ethernet-1/2 -generate > "$OUT/disable-port-5.out" 2> "$OUT/disable-port-5.err" ||
  fail "case 5: -disable-port n1:ethernet-1/2 -generate on $FB failed; see $OUT/disable-port-5.err"
CHANGED=$(now_ns)
await_checksums_moved 5a "$FB" "$OUT/artifacts-5a-before.json" n1
compiled_id 5a
export COMPILED_ID
[ "$COMPILED_ID" != "$BID5" ] || fail "case 5: the artifact-only change left the compiled bundle_id at $BID5"
echo "e2e: case 5: n1:ethernet-1/2 disabled on $FB; it compiles to $COMPILED_ID"
await_rebuild 5a "$RUN5"
REBUILD_ARTIFACT_TOOK=$REBUILD_TOOK
BID5A=$COMPILED_ID RUN5A=$(jq -r .run.run_id "$TWIN/twin.json")
export BID5A
jq -e --slurpfile a "$OUT/artifacts-5a.json" '(.nodes[] | select(.name=="n1") | .artifact.checksum) == $a[0].n1.checksum' "$TWIN/twin.json" > /dev/null ||
  fail "case 5: twin.json does not carry n1's new checksum $(jq -r .n1.checksum "$OUT/artifacts-5a.json")"
readback 5a "$FB" disable

# twin verify on the rebuilt twin: intent disables n1:ethernet-1/2, so
# that port and its link's two ends are skipped, each named with its reason, and nothing is
# found. The bundle's mapping row carries enabled false; the node reads disable.
verify_twin 5a
VERIFY5_TOOK=$VERIFY_TOOK
expect "$OUT/verify-5a.json" '.verify.counts.port_enabled.skipped==1 and .verify.counts.neighbor.skipped==2
  and ([.verify.skipped[] | "\(.node):\(.port) \(.link)"] | sort)
    == ["n1:ethernet-1/2 n1:ethernet-1/2|n3:ethernet-1/2", "n1:ethernet-1/2 null", "n3:ethernet-1/2 n1:ethernet-1/2|n3:ethernet-1/2"]
  and .verify.twin.bundle_id==env.BID5A'

# The topology change: a third link, which moves n1's and n3's artifacts too; the
# fixture tool generates after it. The bundle it moves to is what the stage commands
# compile from the changed branch once both artifacts are rewritten, never a literal.
cp "$OUT/artifacts-5a.json" "$OUT/artifacts-5b-before.json"
fixture -branch "$FB" -add-link > "$OUT/add-link-5.out" 2> "$OUT/add-link-5.err" ||
  fail "case 5: -add-link on $FB failed; see $OUT/add-link-5.err"
CHANGED=$(now_ns)
await_checksums_moved 5b "$FB" "$OUT/artifacts-5b-before.json" n1 n3
compiled_id 5b
export COMPILED_ID
[ "$COMPILED_ID" != "$BID5A" ] || fail "case 5: the branch change left the compiled bundle_id at $BID5A"
echo "e2e: case 5: $FB changed; it compiles to $COMPILED_ID"
await_rebuild 5b "$RUN5A"
readback 5b "$FB" disable

# twin show names the new twin and the check that rebuilt it. A check that closes after the
# rebuild's, having compared the new twin, is shown instead once it closes; then the rebuild
# is confirmed from the service's own record of the checks on $FB.
start=$(now_ns)
while :; do
  fylgja twin show --json > "$OUT/show-5-rebuilt.json" 2> "$OUT/show-5-rebuilt.err" || true
  jq -e '.show.kind=="following" and .show.record.bundle_id==env.COMPILED_ID
    and .show.following.last_check.bundle_id==env.COMPILED_ID' "$OUT/show-5-rebuilt.json" > /dev/null 2>&1 && break
  # 90s, raised from 30s as a precaution rather than on a failure: the rebuild has already
  # happened by here, so what is waited on is the check closing and being reported, and a
  # loaded host has stretched every other such wait in this script.
  [ "$(( ($(now_ns) - start) / 1000000000 ))" -lt 90 ] ||
    fail "case 5: twin show did not name the rebuilt twin and its check within 90s; see $OUT/show-5-rebuilt.json"
  sleep 1
done
REBUILT_CHECK=""
if jq -e '.show.following.last_check.outcome=="rebuilt"' "$OUT/show-5-rebuilt.json" > /dev/null; then
  REBUILT_CHECK=$(jq -r '.show.following.last_check | "\(.workflow_id) \(.run_id)"' "$OUT/show-5-rebuilt.json")
  echo "e2e: case 5: twin show's last check rebuilt the twin"
else
  expect "$OUT/show-5-rebuilt.json" '.show.following.last_check.outcome=="unchanged" and .show.following.last_check.twin_bundle_id==env.COMPILED_ID'
  temporal workflow list --address "$TEMPORAL_ADDRESS" --query "WorkflowType='Reconcile' AND ExecutionStatus='Completed'" -o json \
    > "$OUT/checks-5.json" 2> "$OUT/checks-5.err" || fail "case 5: temporal workflow list failed; see $OUT/checks-5.err"
  n=0
  while read -r wid rid; do
    n=$(( n + 1 ))
    temporal workflow result --address "$TEMPORAL_ADDRESS" -w "$wid" -r "$rid" -o json > "$OUT/check-5-result-$n.json" 2> /dev/null || continue
    if jq -e '.result.branch==env.FB and .result.outcome=="rebuilt" and .result.bundle_id==env.COMPILED_ID' "$OUT/check-5-result-$n.json" > /dev/null; then
      REBUILT_CHECK="$wid $rid"
      break
    fi
  done < <(jq -r '.[].execution | "\(.workflowId) \(.runId)"' "$OUT/checks-5.json")
  [ -n "$REBUILT_CHECK" ] || fail "case 5: no check on $FB is recorded as rebuilt to $COMPILED_ID; see $OUT/checks-5.json"
  echo "e2e: case 5: a later check closed first; the service records ${REBUILT_CHECK% *} as the rebuild"
fi
# shellcheck disable=SC2086
history_of check-rebuilt $REBUILT_CHECK

# Destroy stops following: no Schedule is left to rebuild what it removed.
start=$(now_ns)
destroy_status=0
fylgja twin destroy --json > "$OUT/destroy-5.json" 2> "$OUT/destroy-5.err" || destroy_status=$?
DESTROY5_TOOK=$(since "$start")
echo "e2e: case 5: destroy took ${DESTROY5_TOOK}s (exit $destroy_status)"
# The bundle store is not compared across this destroy, as destroy_twin does: a check in
# flight reads into bundles/.reads/ until the destroy cancels it.
expect "$OUT/destroy-5.json" '.status=="ok" and .following.stopped==true and .following.branch==env.FB
  and .cleanup.teardown=="done" and .cleanup.unstage=="done" and (.cleanup.remaining|length)==0'
[ "${DESTROY5_TOOK%.*}" -lt 60 ] || fail "case 5: destroy took ${DESTROY5_TOOK}s, over 60s"
[ "$(clab inspect --all --format json)" = "{}" ] || fail "case 5: containerlab still reports a lab after destroy"
[ ! -e "$TWIN" ] || fail "case 5: $TWIN is still present after destroy"
[ "$(schedule_state)" = absent ] || fail "case 5: Schedule $FOLLOW_SCHEDULE is not reported absent after destroy; see $OUT/schedule-describe.err"

# The last check, whatever it was (the destroy may have cancelled it), for the greps below.
temporal workflow list --address "$TEMPORAL_ADDRESS" --query "WorkflowType='Reconcile'" -o json > "$OUT/checks-5-all.json" 2> "$OUT/checks-5-all.err" ||
  fail "case 5: temporal workflow list failed; see $OUT/checks-5-all.err"
# shellcheck disable=SC2046
history_of check-last $(jq -r 'sort_by(.startTime) | last | .execution | "\(.workflowId) \(.runId)"' "$OUT/checks-5-all.json")

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
create_twin 6 --no-follow
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

# --- case 7: a twin from a waypoint is the one the plan printed (M10) -----------
if case_runs 7; then

# A throwaway branch and a test series of the same name, set before seeding so the trap's
# -delete removes both: it deletes every test series naming the branch before the branch,
# since a waypoint outlives its branch. Made on the host case 6's destroy
# left clean.
FW="fylgja-test-e2e-wp-$$-$RANDOM"
export FW
start=$(now_ns)
seed_status=0
fixture -branch "$FW" > "$OUT/seed-7.out" 2> "$OUT/seed-7.err" || seed_status=$?
SEED7_TOOK=$(since "$start")
echo "e2e: case 7: seeding $FW took ${SEED7_TOOK}s (exit $seed_status)"
[ "$seed_status" -eq 0 ] || fail "case 7: seeding $FW exited $seed_status; see $OUT/seed-7.err"

# Each waypoint is written after the writes it seals and after their artifacts are rendered:
# the one rule (schema/README.md). The seed waits for its artifacts to be Ready. -add-link's
# generate returns before n1's and n3's are rewritten, so the second waypoint waits
# for their checksums to move, as tier 2's does. What Infrahub held when the
# first was written is kept: its twin is read back against it.
artifacts_of "$FW" "$OUT/artifacts-7-sealed-1.json" 2> "$OUT/artifacts-7-sealed-1.err" ||
  fail "case 7: reading $FW's artifacts failed; see $OUT/artifacts-7-sealed-1.err"
expect "$OUT/artifacts-7-sealed-1.json" 'length == 3 and all(.[]; .status == "Ready")'
fixture -branch "$FW" -waypoint "$FW/1" -description seeded > "$OUT/waypoint-7-1.out" 2> "$OUT/waypoint-7-1.err" ||
  fail "case 7: writing waypoint $FW/1 failed; see $OUT/waypoint-7-1.err"
fixture -branch "$FW" -add-link > "$OUT/add-link-7.out" 2> "$OUT/add-link-7.err" ||
  fail "case 7: -add-link on $FW failed; see $OUT/add-link-7.err"
await_checksums_moved 7 "$FW" "$OUT/artifacts-7-sealed-1.json" n1 n3
fixture -branch "$FW" -waypoint "$FW/2" -description "third link" > "$OUT/waypoint-7-2.out" 2> "$OUT/waypoint-7-2.err" ||
  fail "case 7: writing waypoint $FW/2 failed; see $OUT/waypoint-7-2.err"

# The plan: no lab, no worker, no workflow service. Two ids, and between them the
# third link, with n1 and n3 re-rendered and re-bootstrapped for it. mapping may stand beside
# bootstrap, since the link gives both ends the interface ethernet-1/3.
start=$(now_ns)
plan_status=0
fylgja waypoint plan --series "$FW" --json > "$OUT/plan-7.json" 2> "$OUT/plan-7.err" || plan_status=$?
PLAN7_TOOK=$(since "$start")
echo "e2e: case 7: plan took ${PLAN7_TOOK}s (exit $plan_status)"
[ "$plan_status" -eq 0 ] || fail "case 7: waypoint plan --series $FW exited $plan_status; see $OUT/plan-7.json and $OUT/plan-7.err"
expect "$OUT/plan-7.json" '.status=="ok" and .operation=="waypoint.plan" and .plan.series==env.FW
  and [.plan.waypoints[].sequence] == [1, 2]
  and all(.plan.waypoints[]; .branch==env.FW and .at_source=="written" and (.bundle_id | type)=="string"
    and (.findings | length)==0)
  and .plan.waypoints[0].bundle_id != .plan.waypoints[1].bundle_id
  and (.plan.steps | length) == 1'
PLAN1=$(jq -r '.plan.waypoints[0].bundle_id' "$OUT/plan-7.json")
PLAN2=$(jq -r '.plan.waypoints[1].bundle_id' "$OUT/plan-7.json")
PLAN_AT1=$(jq -r '.plan.waypoints[0].at' "$OUT/plan-7.json")
PLAN_AT2=$(jq -r '.plan.waypoints[1].at' "$OUT/plan-7.json")
export PLAN1 PLAN2 PLAN_AT1 PLAN_AT2
expect "$OUT/plan-7.json" '.plan.steps[0] | .computed and (.unchanged | not)
  and .from==(env.FW + "/1") and .to==(env.FW + "/2")
  and .from_bundle_id==env.PLAN1 and .to_bundle_id==env.PLAN2
  and .nodes.added == [] and .nodes.removed == []
  and [.nodes.changed[].node] == ["n1", "n3"]
  and all(.nodes.changed[]; any(.reasons[]; .=="bootstrap") and all(.reasons[]; .=="bootstrap" or .=="mapping"))
  and .links.removed == [] and (.links.added | length) == 1
  and ([.links.added[0].a.node, .links.added[0].b.node] | sort) == ["n1", "n3"]
  and [.artifacts.changed[].node] == ["n1", "n3"]'
echo "e2e: case 7: plan $FW/1 $PLAN1 at $PLAN_AT1, $FW/2 $PLAN2 at $PLAN_AT2; one link added, n1 and n3 changed"

# The list, before any twin: both waypoints, each resolving as the plan did, and no record.
fylgja waypoint list --json > "$OUT/list-7-before.json" 2> "$OUT/list-7-before.err" ||
  fail "case 7: waypoint list exited non-zero; see $OUT/list-7-before.json and $OUT/list-7-before.err"
expect "$OUT/list-7-before.json" '.status=="ok" and .waypoints.series==null and .waypoints.record==null
  and [.waypoints.waypoints[] | select(.series==env.FW) | {sequence, branch, at, at_source, twin}]
    == [{sequence: 1, branch: env.FW, at: env.PLAN_AT1, at_source: "written", twin: false},
        {sequence: 2, branch: env.FW, at: env.PLAN_AT2, at_source: "written", twin: false}]'

# The first waypoint's twin: the plan's first id, pinned at its at, never following, and the
# record naming the waypoint (twin.json 3). It is read back against what Infrahub held when
# the waypoint was written, since -add-link has moved n1's and n3's artifacts since.
BRANCH=$FW
READBACK=
CREATE_REF="$FW/1"
create_twin 7a
CREATE7A_TOOK=$CREATE_TOOK
[ "$BID" = "$PLAN1" ] || fail "case 7: create --waypoint $FW/1 deployed $BID, but the plan printed $PLAN1"
expect "$OUT/create-7a.json" '.subject.waypoint==(env.FW + "/1") and .subject.branch==env.FW and .subject.at==env.PLAN_AT1
  and .waypoint == {series: env.FW, sequence: 1, branch: env.FW, at: env.PLAN_AT1, at_source: "written", description: "seeded"}
  and (has("following") | not)'
expect "$TWIN/twin.json" '.twin_version=="5" and .provenance.branch==env.FW and .provenance.at==env.PLAN_AT1
  and .waypoint == {series: env.FW, sequence: 1, description: "seeded", at_source: "written"}'
[ "$(schedule_state)" = absent ] || fail "case 7: Schedule $FOLLOW_SCHEDULE is not reported absent beside a waypoint's twin; see $OUT/schedule-describe.err"
readback 7a "$FW" enable "$OUT/artifacts-7-sealed-1.json"

fylgja twin show --json > "$OUT/show-7a.json" 2> "$OUT/show-7a.err" ||
  fail "case 7: twin show exited non-zero; see $OUT/show-7a.err"
expect "$OUT/show-7a.json" '.show.kind=="pinned" and .show.record.bundle_id==env.PLAN1 and .show.record.at==env.PLAN_AT1
  and .show.record.waypoint == {series: env.FW, sequence: 1, description: "seeded", at_source: "written"}'

fylgja waypoint list --json > "$OUT/list-7a.json" 2> "$OUT/list-7a.err" ||
  fail "case 7: waypoint list exited non-zero beside the twin; see $OUT/list-7a.json and $OUT/list-7a.err"
expect "$OUT/list-7a.json" '.status=="ok"
  and .waypoints.record == {series: env.FW, sequence: 1, branch: env.FW, at: env.PLAN_AT1, at_source: "written", state: "ready", towards: null}
  and [.waypoints.waypoints[] | select(.twin) | "\(.series)/\(.sequence)"] == [env.FW + "/1"]
  and ([.findings[] | select(.rule=="waypoint.twin.moved")] | length) == 0'

destroy_twin 7a "done" "done"

# The second waypoint's twin: the plan's second id; the branch has not moved since it was
# written, so Infrahub's artifacts now are the ones it sealed.
CREATE_REF="$FW/2"
create_twin 7b
CREATE7B_TOOK=$CREATE_TOOK
[ "$BID" = "$PLAN2" ] || fail "case 7: create --waypoint $FW/2 deployed $BID, but the plan printed $PLAN2"
expect "$TWIN/twin.json" '.twin_version=="5" and .provenance.branch==env.FW and .provenance.at==env.PLAN_AT2
  and .waypoint == {series: env.FW, sequence: 2, description: "third link", at_source: "written"}'
readback 7b "$FW" enable

destroy_twin 7b "done" "done"
unset CREATE_REF
READBACK=readback

# The branch and its series go together; the product then lists none of the series.
if fixture -branch "$FW" -delete > "$OUT/delete-branch-7.out" 2>&1; then
  fylgja waypoint list --series "$FW" --json > "$OUT/list-7-deleted.json" 2> "$OUT/list-7-deleted.err" ||
    fail "case 7: waypoint list --series $FW exited non-zero after the delete; see $OUT/list-7-deleted.err"
  expect "$OUT/list-7-deleted.json" '.waypoints.waypoints == []'
  unset FW
else
  echo "e2e: case 7: branch $FW and its series were not deleted; remove them with: go run -tags fixture ./cmd/fylgja-fixture -branch $FW -delete" >&2
fi
else
  skip_case 7
fi

# --- case 8: a waypoint twin steps along its series (M11) -----------------------
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

# A throwaway branch seeded with the mixed fixture and a test series of the same name, set
# before seeding so the trap's -delete removes both. Made on the host case
# 7's destroy left clean.
FS="fylgja-test-e2e-step-$$-$RANDOM"
export FS
start=$(now_ns)
seed_status=0
fixture -branch "$FS" -mixed > "$OUT/seed-8.out" 2> "$OUT/seed-8.err" || seed_status=$?
SEED8_TOOK=$(since "$start")
echo "e2e: case 8: seeding $FS took ${SEED8_TOOK}s (exit $seed_status)"
[ "$seed_status" -eq 0 ] || fail "case 8: seeding $FS with -mixed exited $seed_status; see $OUT/seed-8.err"

# The series, as case 7 composes one: each waypoint after the writes it seals and after
# their artifacts are rendered. -add-mixed-link's generate returns before s1's and e1's are
# rewritten, so the second waypoint waits for their checksums to move. What
# Infrahub held when the first was written is kept: the twin at /1 is read back against it.
artifacts_of "$FS" "$OUT/artifacts-8-sealed-1.json" 2> "$OUT/artifacts-8-sealed-1.err" ||
  fail "case 8: reading $FS's artifacts failed; see $OUT/artifacts-8-sealed-1.err"
expect "$OUT/artifacts-8-sealed-1.json" 'length == 3 and all(.[]; .status == "Ready")'
fixture -branch "$FS" -waypoint "$FS/1" -description seeded > "$OUT/waypoint-8-1.out" 2> "$OUT/waypoint-8-1.err" ||
  fail "case 8: writing waypoint $FS/1 failed; see $OUT/waypoint-8-1.err"
fixture -branch "$FS" -add-mixed-link > "$OUT/add-mixed-link-8.out" 2> "$OUT/add-mixed-link-8.err" ||
  fail "case 8: -add-mixed-link on $FS failed; see $OUT/add-mixed-link-8.err"
await_checksums_moved 8 "$FS" "$OUT/artifacts-8-sealed-1.json" s1 e1
fixture -branch "$FS" -waypoint "$FS/2" -description "mixed link" > "$OUT/waypoint-8-2.out" 2> "$OUT/waypoint-8-2.err" ||
  fail "case 8: writing waypoint $FS/2 failed; see $OUT/waypoint-8-2.err"

# The plan (M10): two ids, and between them the link, with s1 re-bootstrapped for it and
# both ends' artifacts re-rendered. e1's bootstrap carries no per-port line, so e1
# changes in its mapping alone, if at all; e2 not at all. Each waypoint carries warnings and
# no rejection: the mixed fixture's EOS artifacts name Management1, which the node calls
# Management0 (artifact.interface.unrepresented, M7), as case 6's create does.
plan_status=0
fylgja waypoint plan --series "$FS" --json > "$OUT/plan-8.json" 2> "$OUT/plan-8.err" || plan_status=$?
[ "$plan_status" -eq 0 ] || fail "case 8: waypoint plan --series $FS exited $plan_status; see $OUT/plan-8.json and $OUT/plan-8.err"
expect "$OUT/plan-8.json" '.status=="ok" and [.plan.waypoints[].sequence] == [1, 2]
  and all(.plan.waypoints[]; .branch==env.FS and (.bundle_id | type)=="string"
    and all(.findings[]; .severity != "rejection"))
  and .plan.waypoints[0].bundle_id != .plan.waypoints[1].bundle_id
  and (.plan.steps | length) == 1'
P1=$(jq -r '.plan.waypoints[0].bundle_id' "$OUT/plan-8.json")
P2=$(jq -r '.plan.waypoints[1].bundle_id' "$OUT/plan-8.json")
export P1 P2
expect "$OUT/plan-8.json" '.plan.steps[0] | .computed and (.unchanged | not)
  and .from_bundle_id==env.P1 and .to_bundle_id==env.P2
  and .nodes.added == [] and .nodes.removed == []
  and any(.nodes.changed[]; .node=="s1" and any(.reasons[]; .=="bootstrap"))
  and all(.nodes.changed[]; (.node=="s1" or .node=="e1") and all(.reasons[]; .=="bootstrap" or .=="mapping"))
  and .links.removed == [] and (.links.added | length) == 1
  and ([.links.added[0].a.node, .links.added[0].b.node] | sort) == ["e1", "s1"]
  and [.artifacts.changed[].node] == ["e1", "s1"]'
echo "e2e: case 8: plan $FS/1 $P1, $FS/2 $P2; one link added between e1 and s1, both re-rendered"

# The twin at /1, pushed by replace: the plan's first id, a 5 record that has
# not stepped, every node holding /1's bundle.
BRANCH=$FS
READBACK=
CREATE_REF="$FS/1"
create_twin 8
CREATE8_TOOK=$CREATE_TOOK
[ "$BID" = "$P1" ] || fail "case 8: create --waypoint $FS/1 deployed $BID, but the plan printed $P1"
expect "$TWIN/twin.json" '.twin_version=="5" and .state=="ready" and .step==null
  and .waypoint.series==env.FS and .waypoint.sequence==1 and all(.nodes[]; .holds==env.P1)'
readback_mixed 8 "$FS" "$OUT/artifacts-8-sealed-1.json"
containers_of "$OUT/containers-8-created.txt"
[ "$(wc -l < "$OUT/containers-8-created.txt")" -eq 3 ] || fail "case 8: docker names $(wc -l < "$OUT/containers-8-created.txt") containers of the twin, not 3"

# The step to /2 restarts e1, so it is refused without --allow-restart: the dry run
# says so and touches nothing; the run is refused before it starts, and touches nothing.
twin_before=$(sha256sum < "$TWIN/twin.json")
dry8_status=0
fylgja twin step --dry-run --json > "$OUT/step-8-dry.json" 2> "$OUT/step-8-dry.err" || dry8_status=$?
[ "$dry8_status" -eq 1 ] || fail "case 8: twin step --dry-run exited $dry8_status, not 1; see $OUT/step-8-dry.json"
expect "$OUT/step-8-dry.json" '.status=="rejected" and .operation=="twin.step" and .dry_run.verdict=="refused"
  and [.findings[] | select(.severity=="rejection") | .rule] == ["step.restart.required"]
  and (.findings[] | select(.rule=="step.restart.required") | .object)=="e1"
  and .step.from.bundle_id==env.P1 and .step.to.bundle_id==env.P2
  and .step.reconcile.restarted == ["e1"]
  and [.step.push_plan[].node] == ["e1", "s1"]
  and (.step | has("run") | not)'
refused8_status=0
fylgja twin step --json > "$OUT/step-8-refused.json" 2> "$OUT/step-8-refused.err" || refused8_status=$?
[ "$refused8_status" -eq 1 ] || fail "case 8: twin step without --allow-restart exited $refused8_status, not 1; see $OUT/step-8-refused.json"
expect "$OUT/step-8-refused.json" '.status=="rejected"
  and [.findings[] | select(.severity=="rejection") | .rule] == ["step.restart.required"]
  and (.findings[] | select(.rule=="step.restart.required") | .object)=="e1"
  and (.step | has("run") | not)'
[ "$twin_before" = "$(sha256sum < "$TWIN/twin.json")" ] || fail "case 8: a refused step changed twin.json"
containers_of "$OUT/containers-8-refused.txt"
cmp -s "$OUT/containers-8-created.txt" "$OUT/containers-8-refused.txt" ||
  fail "case 8: a refused step changed the twin's containers; compare $OUT/containers-8-created.txt and $OUT/containers-8-refused.txt"
echo "e2e: case 8: the step to $FS/2 refused step.restart.required naming e1, dry run and run; nothing touched"

# The step to /2: e1 restarted in place, its id kept and its start time moved; s1
# re-cabled live and e2 untouched, their containers as they were; both pushed by replace.
start=$(now_ns)
step8a_status=0
fylgja twin step --allow-restart --json > "$OUT/step-8a.json" 2> "$OUT/step-8a.err" || step8a_status=$?
STEP8A_TOOK=$(since "$start")
echo "e2e: case 8: step to $FS/2 took ${STEP8A_TOOK}s (exit $step8a_status)"
[ "$step8a_status" -eq 0 ] || fail "case 8: twin step --allow-restart exited $step8a_status; see $OUT/step-8a.json and $OUT/step-8a.err"
expect "$OUT/step-8a.json" '.status=="ok" and .operation=="twin.step" and .bundle_id==env.P2
  and .step.outcome=="stepped" and .step.state=="ready" and .step.run.workflow_id=="fylgja-step"'
RUN8A=$(jq -r .subject.run_id "$OUT/step-8a.json")
export RUN8A
expect "$TWIN/twin.json" '.twin_version=="5" and .state=="ready" and .bundle_id==env.P2
  and .waypoint.series==env.FS and .waypoint.sequence==2 and .run.workflow_id=="fylgja-provision"
  and .step.outcome=="stepped" and .step.run.run_id==env.RUN8A and .step.phase==null
  and .step.from.waypoint.sequence==1 and .step.from.bundle_id==env.P1 and .step.to.bundle_id==env.P2
  and .step.reconcile.restarted == ["e1"] and .step.reconcile.recreated == [] and .step.reconcile.added == []
  and ([.step.pushed[] | {node, reasons, outcome}]
    == [{node: "e1", reasons: ["artifact", "restarted"], outcome: "landed"},
        {node: "s1", reasons: ["artifact", "bootstrap"], outcome: "landed"}])
  and all(.nodes[]; .holds==env.P2)'
cp "$TWIN/twin.json" "$OUT/twin-8a.json"
no_credential "the artifact marker" "$MARKER" "$TWIN/twin.json"
containers_of "$OUT/containers-8a.txt"
for node in s1 e2; do
  [ "$(container_line "$OUT/containers-8-created.txt" $node)" = "$(container_line "$OUT/containers-8a.txt" $node)" ] ||
    fail "case 8: the step to $FS/2 changed $node's container; compare $OUT/containers-8-created.txt and $OUT/containers-8a.txt"
done
read -r _ e1_id_before e1_started_before < <(container_line "$OUT/containers-8-created.txt" e1)
read -r _ e1_id_after e1_started_after < <(container_line "$OUT/containers-8a.txt" e1)
[ "$e1_id_before" = "$e1_id_after" ] || fail "case 8: the step to $FS/2 replaced e1's container, where containerlab restarts it in place"
[ "$(date -d "$e1_started_after" +%s%N)" -gt "$(date -d "$e1_started_before" +%s%N)" ] ||
  fail "case 8: e1's container started at $e1_started_after, not after the create's $e1_started_before: it was not restarted"
echo "e2e: case 8: e1 restarted in place; s1 and e2 untouched"
readback_mixed 8a "$FS"
# The replace's removal, first half: s1 is re-cabled live and never restarted, so
# only the push changes its configuration, and /2's artifact describes the new port.
S1_ADDR=$(jq -r '.nodes[] | select(.name=="s1") | .mgmt_ipv4' "$TWIN/twin.json")
want=$(s1_new_port_description)
[ -n "$want" ] || fail "case 8: s1's artifact at $FS/2 sets no description on ethernet-1/3, the port the step cabled"
got=$(gnmi_value 8a "$S1_ADDR" '/interface[name=ethernet-1/3]/description')
[ "$got" = "$want" ] || fail "case 8: s1's ethernet-1/3 description reads \"$got\", its artifact at $FS/2 sets \"$want\""
echo "e2e: case 8: s1 ethernet-1/3 carries the description its artifact at $FS/2 sets"
await_neighbour s1 ethernet-1/3 e1 Ethernet3
await_neighbour e1 Ethernet3 s1 ethernet-1/3
# The step's own wait after its record: the record and the step's
# document say it settled; await_neighbour above stays the independent read. after_s is
# recorded, not asserted.
step_wait_settled 8a
WAIT8A_AFTER=$WAIT_AFTER
history_of step-8a fylgja-step "$RUN8A"

fylgja twin show --json > "$OUT/show-8a.json" 2> "$OUT/show-8a.err" ||
  fail "case 8: twin show exited non-zero after the step; see $OUT/show-8a.err"
expect "$OUT/show-8a.json" '.show.kind=="pinned" and .show.record.bundle_id==env.P2
  and .show.record.state=="ready" and .show.record.step.outcome=="stepped"'
fylgja waypoint list --json > "$OUT/list-8a.json" 2> "$OUT/list-8a.err" ||
  fail "case 8: waypoint list exited non-zero beside the stepped twin; see $OUT/list-8a.json and $OUT/list-8a.err"
expect "$OUT/list-8a.json" '.status=="ok" and .waypoints.record.series==env.FS and .waypoints.record.sequence==2
  and .waypoints.record.state=="ready" and .waypoints.record.towards==null
  and [.waypoints.waypoints[] | select(.twin) | "\(.series)/\(.sequence)"] == [env.FS + "/2"]'

# The step back to /1: the link's endpoints deleted, e1 restarted again, s1 re-cabled
# live; the twin runs what Infrahub held when /1 was written, and e2 is still the create's.
start=$(now_ns)
step8b_status=0
fylgja twin step --waypoint "$FS/1" --allow-restart --json > "$OUT/step-8b.json" 2> "$OUT/step-8b.err" || step8b_status=$?
STEP8B_TOOK=$(since "$start")
echo "e2e: case 8: step back to $FS/1 took ${STEP8B_TOOK}s (exit $step8b_status)"
[ "$step8b_status" -eq 0 ] || fail "case 8: twin step --waypoint $FS/1 exited $step8b_status; see $OUT/step-8b.json and $OUT/step-8b.err"
expect "$OUT/step-8b.json" '.status=="ok" and .bundle_id==env.P1 and .step.outcome=="stepped"'
RUN8B=$(jq -r .subject.run_id "$OUT/step-8b.json")
export RUN8B
expect "$TWIN/twin.json" '.state=="ready" and .bundle_id==env.P1 and .waypoint.sequence==1
  and .step.outcome=="stepped" and .step.run.run_id==env.RUN8B
  and .step.from.waypoint.sequence==2 and .step.from.bundle_id==env.P2
  and .step.reconcile.restarted == ["e1"] and all(.nodes[]; .holds==env.P1)'
cp "$TWIN/twin.json" "$OUT/twin-8b.json"
no_credential "the artifact marker" "$MARKER" "$TWIN/twin.json"
containers_of "$OUT/containers-8b.txt"
[ "$(container_line "$OUT/containers-8-created.txt" e2)" = "$(container_line "$OUT/containers-8b.txt" e2)" ] ||
  fail "case 8: e2's container changed since the create; compare $OUT/containers-8-created.txt and $OUT/containers-8b.txt"
readback_mixed 8b "$FS" "$OUT/artifacts-8-sealed-1.json"
# The replace's removal, second half: /1's artifact never describes ethernet-1/3, and s1,
# never restarted, no longer carries the description /2's push set.
[ -z "$(s1_new_port_description)" ] || fail "case 8: s1's artifact at $FS/1 sets a description on ethernet-1/3, so its absence would show nothing"
gnmi_absent 8b "$S1_ADDR" '/interface[name=ethernet-1/3]/description'
echo "e2e: case 8: s1 ethernet-1/3 carries no description after the step back to $FS/1: the replace removed what /2 added"
step_wait_settled 8b
WAIT8B_AFTER=$WAIT_AFTER
echo "e2e: case 8: settled after ${WAIT8A_AFTER}s and ${WAIT8B_AFTER}s"
history_of step-8b fylgja-step "$RUN8B"

destroy_twin 8 "done" "done"
unset CREATE_REF
READBACK=readback

# The branch and its series go together; the product then lists none of the series.
if fixture -branch "$FS" -delete > "$OUT/delete-branch-8.out" 2>&1; then
  fylgja waypoint list --series "$FS" --json > "$OUT/list-8-deleted.json" 2> "$OUT/list-8-deleted.err" ||
    fail "case 8: waypoint list --series $FS exited non-zero after the delete; see $OUT/list-8-deleted.err"
  expect "$OUT/list-8-deleted.json" '.waypoints.waypoints == []'
  unset FS
else
  echo "e2e: case 8: branch $FS and its series were not deleted; remove them with: go run -tags fixture ./cmd/fylgja-fixture -branch $FS -delete" >&2
fi
else
  skip_case 8
fi

# --- credential hygiene over everything the run produced -----------------------

# The script's server is stopped first, so its log is whole when it is searched. Every twin
# is destroyed by now, so the trap has nothing to ask it.
stop_server
[ "$SERVER_STATUS" -eq 0 ] || fail "the API's server exited $SERVER_STATUS on SIGTERM, not 0; see $OUT/server.log"

# $OUT holds the short-lived worker's stdout and stderr, the orphan's deploy output, every
# twin show document, the checks' histories with their payloads decoded too, both boot
# halves' output (boot-half.out, boot-half-6.out), case 7's plan
# and list documents (plan-7.json, list-7-*.json), and case 8's step documents,
# record copies and step histories, decoded (step-8*.json, twin-8*.json, history-step-8*),
# every twin verify document (verify-*.json), and the API's
# server's report and request log (server.log). A step history's push results
# carry the device's diff by design, so they are searched for the marker and the
# credentials, not for configuration lines.
scan=("$OUT" "$FYLGJA_STATE_ROOT/bundles")
if [ -n "${WORKER_LOG:-}" ]; then
  [ -r "$WORKER_LOG" ] || fail "WORKER_LOG=$WORKER_LOG is not readable"
  scan+=("$WORKER_LOG")
fi
no_credential "the Infrahub token" "$INFRAHUB_API_TOKEN" "${scan[@]}"
no_credential "the API's token" "$API_TOKEN" "${scan[@]}"
# The operator's own token, when local/.env carries one: the run does not use it, but every
# process the script starts directly, the worker it greps included, has it in its environment.
# shellcheck disable=SC2031 # local/.env's token, not the one fylgja() sets in its subshell
if [ -n "${FYLGJA_API_TOKEN:-}" ]; then
  no_credential "local/.env's API token" "$FYLGJA_API_TOKEN" "${scan[@]}"
fi
no_credential "the probe password" "$FYLGJA_SRLINUX_PASSWORD" "${scan[@]}"
# The EOS password is the image's published default, `admin`: too common a word for the
# strong grep, so it is searched for in the shapes that would be a leak.
no_credential_contextual "the EOS password" "$FYLGJA_EOS_PASSWORD" "${scan[@]}"

# The marker: every output, record copy, twin show document, check result,
# history, the server's log and the worker log. A read's CTM (ctm-*.json) and a compiled bundle
# (compiled-*/) carry the artifact by design, as the bundle store does, so they are left
# out, and the store with them.
if grep -rqsF --exclude='ctm-*.json' --exclude-dir='compiled-*' -- "$MARKER" "$OUT" ${WORKER_LOG:+"$WORKER_LOG"}; then
  echo "e2e: LEAK: the artifact marker found in:" >&2
  grep -rlsF --exclude='ctm-*.json' --exclude-dir='compiled-*' -- "$MARKER" "$OUT" ${WORKER_LOG:+"$WORKER_LOG"} >&2 || true
  exit 1
fi

# The timings are recorded, not asserted: a slow host is the host's.
for t in "${CREATE_TIMES[@]}"; do
  echo "e2e: create $t"
done
# A case's line only when it ran: a skipped case set none of its variables, which set -u
# would refuse. Cases 1 and 5 need nokia_srlinux alone, which every list that selects a case
# names, so they run whenever any case does.
if ran 5; then
  echo "e2e: case 5: seed ${SEED_TOOK}s, artifact-only rebuild ${REBUILD_ARTIFACT_TOOK}s and topology rebuild ${REBUILD_TOOK}s from the change, destroy ${DESTROY5_TOOK}s"
fi
if ran 6; then
  echo "e2e: case 6: seed ${SEED6_TOOK}s, mixed twin $BID6 under run $RUN6"
fi
if ran 7; then
  echo "e2e: case 7: plan ${PLAN7_TOOK}s, creates ${CREATE7A_TOOK}s and ${CREATE7B_TOOK}s"
fi
if ran 8; then
  echo "e2e: case 8: steps ${STEP8A_TOOK}s and ${STEP8B_TOOK}s, create ${CREATE8_TOOK}s; runs $RUN8A and $RUN8B"
fi
line="e2e: verify ${VERIFY1_TOOK}s (case 1), ${VERIFY5_TOOK}s (case 5)"
if ran 6; then line+=", ${VERIFY6_TOOK}s (case 6)"; fi
if ran 8; then line+="; case 8 settled after ${WAIT8A_AFTER}s and ${WAIT8B_AFTER}s"; fi
echo "$line"
line="e2e: wall time $(since "$RUN_START")s, boot half ${BOOT_HALF_TOOK}s (case 1)"
if ran 6; then line+=" and ${BOOT_HALF6_TOOK}s (case 6)"; fi
echo "$line"
if [ "${#SKIPPED[@]}" -eq 0 ]; then
  echo E2E-OK
else
  echo "E2E-PARTIAL: platforms ${PLATFORM_LIST[*]}; ran ${RAN[*]}; skipped ${SKIPPED[*]}"
fi
