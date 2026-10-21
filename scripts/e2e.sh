#!/bin/bash
# Tier 3: nine cases in one run, making nine twins, through the workflow service and the
# operator's worker, leaving the host as it found it. Run by `make test-e2e` from the
# repository root. Never runs in CI and never gates a PR. M3's four cases create with
# --no-follow, so nothing checks their twins.
#
# Every fylgja command but worker run goes through the API (M13): the script starts a server
# of its own from the tree, on a port of its own, with a token it makes for the run, and
# stops it in its trap. Each command runs with PATH, HOME and the API's address and token,
# and nothing else of the script's environment. The script's own reads (gnmic, Docker,
# containerlab, twin.json, the store), the boot half and the fixture tool stay direct, with
# the full environment, and so does case 3's short-lived worker. Case 9's two rehearsals are
# no command of the script's: the check fylgja-twin asks them from inside Infrahub's task
# workers, of the operator's server on the host's Docker bridge (015).
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
#   7. a throwaway branch seeded and a draft proposed change opened on it (014): stage
#      seeded marked, a third link added, stage third-link marked; stage plan names four
#      stages, the branch point refused (main holds no contract), three ids and three steps,
#      the last unchanged; stage list names them; create --stage seeded deploys the id the
#      plan printed and records the stage in twin.json 7, and twin show and stage list name
#      it; a step with no target to third-link, the link re-cabled live, and a second to the
#      head, unchanged, the record moving; destroy; the stages, the proposed change and the
#      branch deleted, after which stage list lists none and stage plan refuses the branch
#   8. a throwaway branch seeded with the mixed fixture and a draft proposed change opened on
#      it (M11, 014): stage seeded, a link s1:ethernet-1/3 <-> e1:Ethernet3 added, stage
#      mixed-link; create --stage seeded, pushed by replace; the step with no target to
#      mixed-link refused without --allow-restart, dry run and run, naming e1; taken with it:
#      e1 restarted in place, s1 re-cabled live and e2 untouched (their containers say so),
#      both pushed, the new link seen from both ends over gNMI, twin.json 7 naming the step
#      and its wait settled (M12); the step back with --stage seeded, settled too; destroy;
#      the stages, the proposed change and the branch deleted
#   9. a throwaway branch seeded and a draft proposed change opened on it (015): at the
#      draft's creation the check fylgja-twin skipped it and fylgja-step passed, and no
#      comment was posted; stage seeded, a third link, stage third-link; marked ready and the
#      user checks run again: fylgja-twin rehearsed it on a twin and passed, its message
#      saying rehearsal ok, one comment in a thread of the proposed change, which its overview
#      shows, holding the table, the drawing and the stages, and no twin left; an interface n1
#      does not have, generated, stage bad-port, the checks run again: fylgja-twin failed,
#      naming bad-port's push on n1, a second comment in a second thread holding the commands
#      that reproduce it and the head not reached; the branch deleted, and with its proposed
#      change the threads, their comments and the validators
#
# Needs, all running from this directory: `make temporal-dev`, `make worker` (restarted
# after every rebuild, since case 1's refusal is worded by the worker and case 5's checks
# run on it), Docker, containerlab, the SR Linux image, the imported cEOS image (never
# pulled; docs/development.md says how to import it), go (cases 1 and 6 run the boot half as
# go test; cases 5 to 9 seed their branches with cmd/fylgja-fixture), and Infrahub with
# fylgja-fixture seeded (local/.env). Every command goes to the script's own server, whose
# port is one the system chooses. Case 9 needs two things more, checked before anything
# starts: the operator's server from this tree, listening on the Docker bridge with
# local/.env's token as CLAUDE.md's start line has it (make serve listens on loopback alone),
# which Infrahub's task workers reach and the script never starts or stops; and the checks
# fylgja-step and fylgja-twin on main, pushed to origin's main and imported
# (specs/015-proposed-change-rehearsal/quickstart.md §6).
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
# after the trap's destroy, which cancels a rehearsal in flight and waits for its own destroy,
# and its deletion of the throwaway branches of cases 5 to 9 (7's, 8's and 9's with their
# stages and proposed changes, 9's threads and validators going with its proposed change); a
# lab, a twin directory or Schedule fylgja-follow left behind after that destroy exits 99.
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

# gql BRANCH QUERY: Infrahub's GraphQL answer's data on the branch, or on the default branch
# through the unnamed endpoint when BRANCH is "", as the stage reader asks it. The token goes
# to curl as a header file, so it is in no process's arguments.
gql() {
  local body
  body=$(jq -cn --arg q "$2" '{query: $q}')
  curl -sS --fail-with-body -H @<(printf 'X-INFRAHUB-KEY: %s\n' "$INFRAHUB_API_TOKEN") \
    -H 'Content-Type: application/json' -d "$body" "$INFRAHUB_ADDRESS/graphql${1:+/$1}" | jq -e '.data'
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
# twin's pinned reference was marked. Case 7's first stage needs it: the branch has moved on
# since, and the twin runs what Infrahub held then.
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
# twin at its first stage runs what Infrahub held when that stage was marked (M11, 014).
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

# create_twin CASE ARGS...: twin create --branch $BRANCH ARGS, or --stage $CREATE_REF in
# place of the branch when CREATE_REF is set (cases 7 and 8), ending with three
# ready nodes, the twin recorded, the bundle stored and staged as its id, and each node
# running its artifact; sets and exports BID and RUN_ID,
# and sets CREATE_TOOK.
CREATE_TIMES=()
create_twin() {
  local case=$1
  shift
  local start status=0 took ref=(--branch "$BRANCH")
  [ -z "${CREATE_REF:-}" ] || ref=(--stage "$CREATE_REF")
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
  # The throwaway branches of cases 5 to 9, when they were made and not yet deleted; -delete
  # removes the stages and proposed changes of cases 7, 8 and 9 before their branches, case
  # 9's comments and validators with its proposed change. A failure is reported, not fatal.
  # The destroy above cancels a step in flight and waits for its record, and a rehearsal in
  # flight, case 9's check's, and waits for that run's own destroy; the comment the check
  # posts on the cancelled run goes with its proposed change, or finds none to go on.
  local branch
  for branch in "${FB:-}" "${FM:-}" "${FP:-}" "${FS:-}" "${FR:-}"; do
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

# Case 9's rehearsals are asked from inside Infrahub (R-19), so two things outside the script
# are required first. Case 9 needs nokia_srlinux alone, which every list that selects a case
# names, so it runs whenever any case does.
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
# the Python the task workers run, which must be this tree's, as the server's binary must be
# below: the registration fylgja's imported commit, read on main, is one this clone knows,
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

# The server the task workers reach: the operator's, on the Docker bridge's gateway at 7650,
# where the Compose override points them (host.docker.internal:7650), with local/.env's
# token, which curl reads from a header file so that it is in no process's arguments. It
# must be this tree's build, as the script's own server is, since the rehearsals it serves
# are what case 9 asserts. The script's own server stays on loopback.
BRIDGE=$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}' 2> "$OUT/bridge.err") && [ -n "$BRIDGE" ] ||
  fail "Docker reports no bridge network, the address Infrahub's task workers reach the server on; see $OUT/bridge.err"
BUILD=$("$FYLGJA" --version | sed -n 's/^fylgja version //p')
SERVE_REMEDY="start it from this tree with CLAUDE.md's start line, fylgja serve --listen 127.0.0.1:7650 --listen $BRIDGE:7650, from a shell that has loaded local/.env"
# shellcheck disable=SC2031 # local/.env's token, not the one fylgja() sets in its subshell
[ -n "${FYLGJA_API_TOKEN:-}" ] ||
  fail "case 9 needs local/.env's FYLGJA_API_TOKEN, the token of the server Infrahub's task workers reach; set it and $SERVE_REMEDY"
# shellcheck disable=SC2031
bridge_status=$(curl -sS -o "$OUT/bridge-show.ndjson" -D "$OUT/bridge-show.headers" -w '%{http_code}' \
  -H @<(printf 'Authorization: Bearer %s\n' "$FYLGJA_API_TOKEN") -H 'Content-Type: application/json' \
  -d '{}' "http://$BRIDGE:7650/v1/twin/show" 2> "$OUT/bridge-show.err") || bridge_status="nothing"
bridge_build=$(sed -n 's/^Fylgja-Build: *\([^[:space:]]*\).*/\1/Ip' "$OUT/bridge-show.headers" 2> /dev/null | tail -1)
{ [ "$bridge_status" = 200 ] && [ "$bridge_build" = "$BUILD" ]; } ||
  fail "case 9 needs the server Infrahub's task workers reach, at http://$BRIDGE:7650, from this tree (build $BUILD) and with local/.env's token: it answered $bridge_status${bridge_build:+, build $bridge_build}; $SERVE_REMEDY"
# Every unstamped build is the same version, so the build header alone proves no tree: the
# server's process, the fylgja serve whose arguments listen on $BRIDGE:7650, must run this
# tree's binary itself, neither replaced, (deleted), nor another file. A /proc entry this
# shell cannot read, as for a server started under sg docker, is said and not compared.
bridge_pid=""
for pid in $(pgrep -x fylgja || true); do
  mapfile -d '' -t args < "/proc/$pid/cmdline" 2> /dev/null || continue
  [ "${args[1]:-}" = serve ] || continue
  for (( i = 2; i < ${#args[@]}; i++ )); do
    if [ "${args[i]}" = "--listen=$BRIDGE:7650" ] || { [ "${args[i]}" = --listen ] && [ "${args[i + 1]:-}" = "$BRIDGE:7650" ]; }; then
      bridge_pid=$pid
    fi
  done
  if [ -n "$bridge_pid" ]; then break; fi
done
[ -n "$bridge_pid" ] ||
  fail "case 9 needs the server on $BRIDGE:7650 to run this tree's $FYLGJA, and no fylgja serve process listens there by its arguments; $SERVE_REMEDY"
bridge_binary="its binary not compared"
if bridge_exe=$(readlink "/proc/$bridge_pid/exe" 2> /dev/null); then
  case $bridge_exe in
    *" (deleted)") fail "case 9 needs the server on $BRIDGE:7650 to run this tree's $FYLGJA, and pid $bridge_pid runs a replaced binary ($bridge_exe): restart it; $SERVE_REMEDY" ;;
  esac
  [ "/proc/$bridge_pid/exe" -ef "$FYLGJA" ] ||
    fail "case 9 needs the server on $BRIDGE:7650 to run this tree's $FYLGJA, and pid $bridge_pid runs $bridge_exe; $SERVE_REMEDY"
  bridge_binary="this tree's $FYLGJA (pid $bridge_pid)"
else
  echo "e2e: note: the server on $BRIDGE:7650 is pid $bridge_pid, whose /proc/$bridge_pid/exe this shell cannot read, as for a server started under sg docker: its binary is not compared with $FYLGJA, only its build"
fi
echo "e2e: case 9's checks are on main, imported at this tree's ${IMPORTED:0:12}, and the server on $BRIDGE:7650 answers, build $BUILD, $bridge_binary"

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

# The plan: no lab, no worker, no workflow service. Four stages in order. The branch point
# is main at the branch's creation, which holds no contract on this install, so it is
# refused at its read (research R-04) and the plan exits 1. The two marks and the head
# compile to three ids, the head's at being its own. Three steps: the first not computed;
# the second the third link, with n1 and n3 re-rendered and re-bootstrapped for it (mapping
# may stand beside bootstrap, since the link gives both ends the interface ethernet-1/3);
# the third unchanged, since nothing was written after the second mark but the mark.
start=$(now_ns)
plan_status=0
fylgja stage plan --branch "$FP" --json > "$OUT/plan-7.json" 2> "$OUT/plan-7.err" || plan_status=$?
PLAN7_TOOK=$(since "$start")
echo "e2e: case 7: plan took ${PLAN7_TOOK}s (exit $plan_status)"
[ "$plan_status" -eq 1 ] ||
  fail "case 7: stage plan --branch $FP exited $plan_status, not 1 for its refused branch point; see $OUT/plan-7.json and $OUT/plan-7.err"
expect "$OUT/plan-7.json" '.status=="rejected" and .operation=="stage.plan" and .plan.branch==env.FP
  and .plan.proposed_change.name==env.FP and .plan.proposed_change.branch==env.FP and .plan.proposed_change.draft
  and [.plan.stages[] | {ref, at_source}]
    == [{ref: (env.FP + "/branch-point"), at_source: "branch_point"}, {ref: (env.FP + "/seeded"), at_source: "written"},
        {ref: (env.FP + "/third-link"), at_source: "written"}, {ref: (env.FP + "/head"), at_source: "head"}]
  and [.findings[] | select(.severity=="rejection") | .rule] == ["contract.node.missing"]
  and (.plan.stages[0] | .branch=="main" and .bundle_id==null
    and [.findings[] | select(.severity=="rejection") | .rule] == ["contract.node.missing"])
  and all(.plan.stages[1:][]; .branch==env.FP and (.bundle_id | type)=="string" and (.findings | length)==0)
  and [.plan.stages[1:][].description] == ["seeded", "third link", ""]
  and ([.plan.stages[1:][].bundle_id] | unique | length) == 3
  and (.plan.steps | length) == 3'
PC7=$(jq -r '.plan.proposed_change.id' "$OUT/plan-7.json")
AT7B=$(jq -r '.plan.stages[0].at' "$OUT/plan-7.json")
PLAN7S=$(jq -r '.plan.stages[1].bundle_id' "$OUT/plan-7.json")
PLAN7T=$(jq -r '.plan.stages[2].bundle_id' "$OUT/plan-7.json")
PLAN7H=$(jq -r '.plan.stages[3].bundle_id' "$OUT/plan-7.json")
AT7S=$(jq -r '.plan.stages[1].at' "$OUT/plan-7.json")
AT7T=$(jq -r '.plan.stages[2].at' "$OUT/plan-7.json")
AT7H=$(jq -r '.plan.stages[3].at' "$OUT/plan-7.json")
export PC7 AT7B PLAN7S PLAN7T PLAN7H AT7S AT7T AT7H
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

# The list, before any twin: the four stages, each resolving as the plan did, and no record.
fylgja stage list --branch "$FP" --json > "$OUT/list-7-before.json" 2> "$OUT/list-7-before.err" ||
  fail "case 7: stage list --branch $FP exited non-zero; see $OUT/list-7-before.json and $OUT/list-7-before.err"
expect "$OUT/list-7-before.json" '.status=="ok" and .stages.branch==env.FP and .stages.record==null
  and [.stages.rows[] | {ref, branch, at, at_source, twin}]
    == [{ref: (env.FP + "/branch-point"), branch: "main", at: env.AT7B, at_source: "branch_point", twin: false},
        {ref: (env.FP + "/seeded"), branch: env.FP, at: env.AT7S, at_source: "written", twin: false},
        {ref: (env.FP + "/third-link"), branch: env.FP, at: env.AT7T, at_source: "written", twin: false},
        {ref: (env.FP + "/head"), branch: env.FP, at: env.AT7H, at_source: "head", twin: false}]
  and all(.stages.rows[]; .proposed_change.id==env.PC7)'

# The twin from the first mark: the plan's id, pinned at its at, never following, and the
# record naming the stage and its proposed change, and no rehearsal (twin.json 7). It is
# read back against what Infrahub held when the mark was made, since -add-link has moved
# n1's and n3's artifacts since.
BRANCH=$FP
READBACK=
CREATE_REF="$FP/seeded"
create_twin 7
CREATE7_TOOK=$CREATE_TOOK
[ "$BID" = "$PLAN7S" ] || fail "case 7: create --stage $FP/seeded deployed $BID, but the plan printed $PLAN7S"
expect "$OUT/create-7.json" '.subject.stage==(env.FP + "/seeded") and .subject.branch==env.FP and .subject.at==env.AT7S
  and .stage == {ref: (env.FP + "/seeded"), branch: env.FP, label: "seeded",
    proposed_change: {id: env.PC7, name: env.FP, branch: env.FP, draft: true},
    at: env.AT7S, at_source: "written", description: "seeded"}
  and (has("following") | not)'
expect "$TWIN/twin.json" '.twin_version=="7" and .rehearsal==null and .provenance.branch==env.FP and .provenance.at==env.AT7S and .step==null
  and .stage == {proposed_change: {id: env.PC7, branch: env.FP}, label: "seeded", description: "seeded", at_source: "written"}'
[ "$(schedule_state)" = absent ] || fail "case 7: Schedule $FOLLOW_SCHEDULE is not reported absent beside a stage's twin; see $OUT/schedule-describe.err"
readback 7 "$FP" enable "$OUT/artifacts-7-sealed-1.json"

fylgja twin show --json > "$OUT/show-7.json" 2> "$OUT/show-7.err" ||
  fail "case 7: twin show exited non-zero; see $OUT/show-7.err"
expect "$OUT/show-7.json" '.show.kind=="pinned" and .show.record.bundle_id==env.PLAN7S and .show.record.at==env.AT7S
  and .show.record.stage == {proposed_change: {id: env.PC7, branch: env.FP}, label: "seeded", description: "seeded", at_source: "written"}'

fylgja stage list --branch "$FP" --json > "$OUT/list-7.json" 2> "$OUT/list-7.err" ||
  fail "case 7: stage list exited non-zero beside the twin; see $OUT/list-7.json and $OUT/list-7.err"
expect "$OUT/list-7.json" '.status=="ok"
  and .stages.record == {ref: (env.FP + "/seeded"), proposed_change: {id: env.PC7, branch: env.FP}, label: "seeded",
    branch: env.FP, at: env.AT7S, at_source: "written", state: "ready", towards: null}
  and [.stages.rows[] | select(.twin) | .ref] == [env.FP + "/seeded"]
  and ([.findings[] | select(.rule=="stage.twin.moved")] | length) == 0'

# A step with no target goes to the next stage, the second mark: the third link re-cabled
# live on n1 and n3, which SR Linux's package allows with no restart, and both pushed by
# replace; n2 untouched. The branch has not moved since the mark, so Infrahub's artifacts
# now are the ones it sealed.
start=$(now_ns)
step7a_status=0
fylgja twin step --json > "$OUT/step-7a.json" 2> "$OUT/step-7a.err" || step7a_status=$?
STEP7A_TOOK=$(since "$start")
echo "e2e: case 7: step to $FP/third-link took ${STEP7A_TOOK}s (exit $step7a_status)"
[ "$step7a_status" -eq 0 ] || fail "case 7: twin step exited $step7a_status; see $OUT/step-7a.json and $OUT/step-7a.err"
expect "$OUT/step-7a.json" '.status=="ok" and .operation=="twin.step" and .bundle_id==env.PLAN7T
  and .subject.stage==(env.FP + "/third-link") and .stage.at==env.AT7T and .stage.at_source=="written"
  and .step.outcome=="stepped" and .step.state=="ready" and .step.run.workflow_id=="fylgja-step"'
RUN7A=$(jq -r .subject.run_id "$OUT/step-7a.json")
export RUN7A
expect "$TWIN/twin.json" '.twin_version=="7" and .rehearsal==null and .state=="ready" and .bundle_id==env.PLAN7T
  and .provenance.branch==env.FP and .provenance.at==env.AT7T
  and .stage == {proposed_change: {id: env.PC7, branch: env.FP}, label: "third-link", description: "third link", at_source: "written"}
  and .step.outcome=="stepped" and .step.run.run_id==env.RUN7A and .step.phase==null
  and .step.from.stage.label=="seeded" and .step.from.bundle_id==env.PLAN7S
  and .step.to.stage.label=="third-link" and .step.to.bundle_id==env.PLAN7T
  and .step.reconcile.restarted == [] and .step.reconcile.recreated == [] and .step.reconcile.added == []
  and (.step.reconcile.links_added | length) == 1
  and [.step.pushed[] | {node, outcome}] == [{node: "n1", outcome: "landed"}, {node: "n3", outcome: "landed"}]
  and all(.nodes[]; .holds==env.PLAN7T)'
cp "$TWIN/twin.json" "$OUT/twin-7a.json"
no_credential "the artifact marker" "$MARKER" "$TWIN/twin.json"
readback 7a "$FP" enable
history_of step-7a fylgja-step "$RUN7A"

# A second step with no target goes to the head, the stage after the second mark. Nothing
# was written after the mark but the mark, so the two bundles differ in provenance alone:
# the step is unchanged, nothing is reconciled or pushed, and the record moves to the head
# (US2's second scenario). The list then marks the head, which has not moved.
start=$(now_ns)
step7b_status=0
fylgja twin step --json > "$OUT/step-7b.json" 2> "$OUT/step-7b.err" || step7b_status=$?
STEP7B_TOOK=$(since "$start")
echo "e2e: case 7: step to $FP/head took ${STEP7B_TOOK}s (exit $step7b_status)"
[ "$step7b_status" -eq 0 ] || fail "case 7: the second twin step exited $step7b_status; see $OUT/step-7b.json and $OUT/step-7b.err"
expect "$OUT/step-7b.json" '.status=="ok" and .operation=="twin.step" and .bundle_id==env.PLAN7H
  and .subject.stage==(env.FP + "/head") and .stage.at==env.AT7H and .stage.at_source=="head"
  and .step.outcome=="unchanged"'
RUN7B=$(jq -r .subject.run_id "$OUT/step-7b.json")
export RUN7B
expect "$TWIN/twin.json" '.state=="ready" and .bundle_id==env.PLAN7H and .provenance.at==env.AT7H
  and .stage == {proposed_change: {id: env.PC7, branch: env.FP}, label: "head", description: "", at_source: "head"}
  and .step.outcome=="unchanged" and .step.run.run_id==env.RUN7B
  and .step.from.stage.label=="third-link" and .step.from.bundle_id==env.PLAN7T and .step.to.bundle_id==env.PLAN7H
  and .step.reconcile.skipped and (.step.pushed | length) == 0
  and all(.nodes[]; .holds==env.PLAN7H)'
cp "$TWIN/twin.json" "$OUT/twin-7b.json"
no_credential "the artifact marker" "$MARKER" "$TWIN/twin.json"
history_of step-7b fylgja-step "$RUN7B"
fylgja stage list --branch "$FP" --json > "$OUT/list-7b.json" 2> "$OUT/list-7b.err" ||
  fail "case 7: stage list exited non-zero beside the twin at the head; see $OUT/list-7b.json and $OUT/list-7b.err"
expect "$OUT/list-7b.json" '.status=="ok" and .stages.record.label=="head" and .stages.record.at==env.AT7H
  and .stages.record.state=="ready" and [.stages.rows[] | select(.twin) | .ref] == [env.FP + "/head"]
  and ([.findings[] | select(.rule=="stage.twin.moved")] | length) == 0'

destroy_twin 7 "done" "done"
unset CREATE_REF
READBACK=readback

# The branch goes with its stages and its proposed change, in that order, and -delete says
# so; Infrahub then holds none of them. The product then lists no stage of the branch, and
# plans none: no open proposed change has it as its source. A failed delete fails the case,
# and the trap tries it again.
if fixture -branch "$FP" -delete > "$OUT/delete-branch-7.out" 2>&1; then
  grep -qxF "deleted 2 stages, 1 proposed change, branch $FP" "$OUT/delete-branch-7.out" ||
    fail "case 7: -delete on $FP did not report its two stages and its proposed change; see $OUT/delete-branch-7.out"
  infrahub_holds_none 7 "$FP"
  fylgja stage list --branch "$FP" --json > "$OUT/list-7-deleted.json" 2> "$OUT/list-7-deleted.err" ||
    fail "case 7: stage list --branch $FP exited non-zero after the delete; see $OUT/list-7-deleted.err"
  expect "$OUT/list-7-deleted.json" '.status=="ok" and .stages.branch==env.FP and .stages.rows == []'
  plan_status=0
  fylgja stage plan --branch "$FP" --json > "$OUT/plan-7-deleted.json" 2> "$OUT/plan-7-deleted.err" || plan_status=$?
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

# The plan (M10, 014): four stages, the branch point refused as case 7's is, so the plan
# exits 1; the marks and the head compiled to three ids, and between the marks the link,
# with s1 re-bootstrapped for it and both ends' artifacts re-rendered. e1's bootstrap
# carries no per-port line, so e1 changes in its mapping alone, if at all; e2 not at all.
# The step to the head is unchanged. Each compiled stage carries warnings and no rejection:
# the mixed fixture's EOS artifacts name Management1, which the node calls Management0
# (artifact.interface.unrepresented, M7), as case 6's create does.
plan_status=0
fylgja stage plan --branch "$FS" --json > "$OUT/plan-8.json" 2> "$OUT/plan-8.err" || plan_status=$?
[ "$plan_status" -eq 1 ] ||
  fail "case 8: stage plan --branch $FS exited $plan_status, not 1 for its refused branch point; see $OUT/plan-8.json and $OUT/plan-8.err"
expect "$OUT/plan-8.json" '.status=="rejected" and .operation=="stage.plan" and .plan.branch==env.FS
  and [.plan.stages[].ref]
    == [env.FS + "/branch-point", env.FS + "/seeded", env.FS + "/mixed-link", env.FS + "/head"]
  and [.findings[] | select(.severity=="rejection") | .rule] == ["contract.node.missing"]
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

# The twin at seeded, pushed by replace: the plan's id, a 7 record of no rehearsal that has
# not stepped, every node holding seeded's bundle.
BRANCH=$FS
READBACK=
CREATE_REF="$FS/seeded"
create_twin 8
CREATE8_TOOK=$CREATE_TOOK
[ "$BID" = "$P1" ] || fail "case 8: create --stage $FS/seeded deployed $BID, but the plan printed $P1"
expect "$TWIN/twin.json" '.twin_version=="7" and .rehearsal==null and .state=="ready" and .step==null
  and .stage.proposed_change.branch==env.FS and .stage.label=="seeded" and all(.nodes[]; .holds==env.P1)'
readback_mixed 8 "$FS" "$OUT/artifacts-8-sealed-1.json"
containers_of "$OUT/containers-8-created.txt"
[ "$(wc -l < "$OUT/containers-8-created.txt")" -eq 3 ] || fail "case 8: docker names $(wc -l < "$OUT/containers-8-created.txt") containers of the twin, not 3"

# The step with no target goes to the next stage, mixed-link. It restarts e1, so it is
# refused without --allow-restart: the dry run says so and touches nothing; the run is
# refused before it starts, and touches nothing.
twin_before=$(sha256sum < "$TWIN/twin.json")
dry8_status=0
fylgja twin step --dry-run --json > "$OUT/step-8-dry.json" 2> "$OUT/step-8-dry.err" || dry8_status=$?
[ "$dry8_status" -eq 1 ] || fail "case 8: twin step --dry-run exited $dry8_status, not 1; see $OUT/step-8-dry.json"
expect "$OUT/step-8-dry.json" '.status=="rejected" and .operation=="twin.step" and .dry_run.verdict=="refused"
  and .subject.stage==(env.FS + "/mixed-link")
  and [.findings[] | select(.severity=="rejection") | .rule] == ["step.restart.required"]
  and (.findings[] | select(.rule=="step.restart.required") | .object)=="e1"
  and .step.from.stage.label=="seeded" and .step.from.bundle_id==env.P1
  and .step.to.stage.label=="mixed-link" and .step.to.bundle_id==env.P2
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
echo "e2e: case 8: the step to $FS/mixed-link refused step.restart.required naming e1, dry run and run; nothing touched"

# The step to mixed-link: e1 restarted in place, its id kept and its start time moved; s1
# re-cabled live and e2 untouched, their containers as they were; both pushed by replace.
start=$(now_ns)
step8a_status=0
fylgja twin step --allow-restart --json > "$OUT/step-8a.json" 2> "$OUT/step-8a.err" || step8a_status=$?
STEP8A_TOOK=$(since "$start")
echo "e2e: case 8: step to $FS/mixed-link took ${STEP8A_TOOK}s (exit $step8a_status)"
[ "$step8a_status" -eq 0 ] || fail "case 8: twin step --allow-restart exited $step8a_status; see $OUT/step-8a.json and $OUT/step-8a.err"
expect "$OUT/step-8a.json" '.status=="ok" and .operation=="twin.step" and .bundle_id==env.P2
  and .step.outcome=="stepped" and .step.state=="ready" and .step.run.workflow_id=="fylgja-step"'
RUN8A=$(jq -r .subject.run_id "$OUT/step-8a.json")
export RUN8A
expect "$TWIN/twin.json" '.twin_version=="7" and .rehearsal==null and .state=="ready" and .bundle_id==env.P2
  and .stage.proposed_change.branch==env.FS and .stage.label=="mixed-link" and .run.workflow_id=="fylgja-provision"
  and .step.outcome=="stepped" and .step.run.run_id==env.RUN8A and .step.phase==null
  and .step.from.stage.label=="seeded" and .step.from.bundle_id==env.P1 and .step.to.bundle_id==env.P2
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
# recorded, not asserted.
step_wait_settled 8a
WAIT8A_AFTER=$WAIT_AFTER
history_of step-8a fylgja-step "$RUN8A"

fylgja twin show --json > "$OUT/show-8a.json" 2> "$OUT/show-8a.err" ||
  fail "case 8: twin show exited non-zero after the step; see $OUT/show-8a.err"
expect "$OUT/show-8a.json" '.show.kind=="pinned" and .show.record.bundle_id==env.P2
  and .show.record.state=="ready" and .show.record.step.outcome=="stepped"'
fylgja stage list --branch "$FS" --json > "$OUT/list-8a.json" 2> "$OUT/list-8a.err" ||
  fail "case 8: stage list exited non-zero beside the stepped twin; see $OUT/list-8a.json and $OUT/list-8a.err"
expect "$OUT/list-8a.json" '.status=="ok" and .stages.record.proposed_change.branch==env.FS
  and .stages.record.label=="mixed-link" and .stages.record.state=="ready" and .stages.record.towards==null
  and [.stages.rows[] | select(.twin) | .ref] == [env.FS + "/mixed-link"]'

# The step back to seeded, named: the link's endpoints deleted, e1 restarted again, s1
# re-cabled live; the twin runs what Infrahub held when seeded was marked, and e2 is still
# the create's.
start=$(now_ns)
step8b_status=0
fylgja twin step --stage "$FS/seeded" --allow-restart --json > "$OUT/step-8b.json" 2> "$OUT/step-8b.err" || step8b_status=$?
STEP8B_TOOK=$(since "$start")
echo "e2e: case 8: step back to $FS/seeded took ${STEP8B_TOOK}s (exit $step8b_status)"
[ "$step8b_status" -eq 0 ] || fail "case 8: twin step --stage $FS/seeded exited $step8b_status; see $OUT/step-8b.json and $OUT/step-8b.err"
expect "$OUT/step-8b.json" '.status=="ok" and .bundle_id==env.P1 and .step.outcome=="stepped"'
RUN8B=$(jq -r .subject.run_id "$OUT/step-8b.json")
export RUN8B
expect "$TWIN/twin.json" '.state=="ready" and .bundle_id==env.P1 and .stage.label=="seeded"
  and .step.outcome=="stepped" and .step.run.run_id==env.RUN8B
  and .step.from.stage.label=="mixed-link" and .step.from.bundle_id==env.P2
  and .step.reconcile.restarted == ["e1"] and all(.nodes[]; .holds==env.P1)'
cp "$TWIN/twin.json" "$OUT/twin-8b.json"
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
echo "e2e: case 8: settled after ${WAIT8A_AFTER}s and ${WAIT8B_AFTER}s"
history_of step-8b fylgja-step "$RUN8B"

destroy_twin 8 "done" "done"
unset CREATE_REF
READBACK=readback

# The branch goes with its stages and its proposed change, as case 7's, and Infrahub then
# holds none of them; the product then lists no stage of it, and plans none.
if fixture -branch "$FS" -delete > "$OUT/delete-branch-8.out" 2>&1; then
  grep -qxF "deleted 2 stages, 1 proposed change, branch $FS" "$OUT/delete-branch-8.out" ||
    fail "case 8: -delete on $FS did not report its two stages and its proposed change; see $OUT/delete-branch-8.out"
  infrahub_holds_none 8 "$FS"
  fylgja stage list --branch "$FS" --json > "$OUT/list-8-deleted.json" 2> "$OUT/list-8-deleted.err" ||
    fail "case 8: stage list --branch $FS exited non-zero after the delete; see $OUT/list-8-deleted.err"
  expect "$OUT/list-8-deleted.json" '.status=="ok" and .stages.branch==env.FS and .stages.rows == []'
  plan_status=0
  fylgja stage plan --branch "$FS" --json > "$OUT/plan-8-deleted.json" 2> "$OUT/plan-8-deleted.err" || plan_status=$?
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
# `fylgja-rehearse <id>`; sets REHEARSAL_RUN and REHEARSAL_USED, the time it used against
# its deadline, and fetches the run's history, whose payloads the greps read decoded.
rehearsal_run() {
  # shellcheck disable=SC2016 # the backticks are the markdown's code span, read literally
  REHEARSAL_RUN=$(sed -n 's/^Run `fylgja-rehearse \([^`]*\)`.*/\1/p' "$2")
  # shellcheck disable=SC2016
  REHEARSAL_USED=$(sed -n 's/^Run `fylgja-rehearse [^`]*`, .* \([0-9.]*s of the [0-9]*s deadline\).*/\1/p' "$2")
  [ -n "$REHEARSAL_RUN" ] || fail "case $1: the comment names no fylgja-rehearse run; see $2"
  history_of "rehearse-$1" fylgja-rehearse "$REHEARSAL_RUN"
  jq -e '.events[-1].eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED"' "$OUT/history-rehearse-$1.json" > /dev/null ||
    fail "case $1: rehearsal run $REHEARSAL_RUN did not complete; see $OUT/history-rehearse-$1.json"
  # Each child the run started, as its history names them: its provision, its steps and its
  # destroy, whose histories the greps read too (SC-008), a step's push results carrying the
  # device's diff by design, as cases 7 and 8's do.
  jq -r '.events[] | select(.eventType == "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED")
    | .childWorkflowExecutionStartedEventAttributes.workflowExecution | "\(.workflowId) \(.runId)"' \
    "$OUT/history-rehearse-$1.json" > "$OUT/children-rehearse-$1.txt"
  if ! grep -q '^fylgja-provision ' "$OUT/children-rehearse-$1.txt" || ! grep -q '^fylgja-destroy ' "$OUT/children-rehearse-$1.txt"; then
    fail "case $1: rehearsal run $REHEARSAL_RUN started no provision or no destroy; see $OUT/children-rehearse-$1.txt"
  fi
  local n=0 workflow run
  while read -r workflow run; do
    n=$((n + 1))
    history_of "rehearse-$1-$n-$workflow" "$workflow" "$run"
  done < "$OUT/children-rehearse-$1.txt"
}

# no_twin CASE: the rehearsal's own destroy left the host clear, as twin show reports it and as
# containerlab and the state root say.
no_twin() {
  fylgja twin show --json > "$OUT/show-$1.json" 2> "$OUT/show-$1.err" ||
    fail "case $1: twin show exited non-zero after the rehearsal; see $OUT/show-$1.err"
  expect "$OUT/show-$1.json" '.show.kind == "none" and (.show.host.lab_present | not)
    and (.show.host.twin_dir_present | not) and .show.in_flight == []'
  [ "$(clab inspect --all --format json)" = "{}" ] || fail "case $1: containerlab reports a lab after the rehearsal"
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
CAVEAT="*Fidelity is asserted, not measured: the twin's containers forward in software and keep their own timing.*"
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

# The draft. Its creation runs both checks after the rest of the pipeline, which -propose
# waits for, so they are awaited here, bounded as tier 2's test bounds them: fylgja-twin
# skips a draft, asking nothing of Fylgja, and fylgja-step plans the branch point and the
# head, the branch point's refusal for want of a contract on main excepted. No comment is
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
stage_lines 9a "^stage $FR/branch-point: refused \\(contract\\.node\\.missing\\)\$" "^stage $FR/seeded: created; .*; baseline\$" \
  "^stage $FR/third-link: .*; passed\$" "^stage $FR/head: .*; passed\$"
comments_of 9a "$PC9" 2> "$OUT/comments-9a.err" || fail "case 9: reading $PC9's comments failed; see $OUT/comments-9a.err"
expect "$OUT/comments-9a.json" 'length == 1 and (.[0].text | contains("Status **ok**")
  and contains("| stage | at | bundle | step | wait | verify | new findings | verdict |")
  and contains("```mermaid") and contains("**Stages**") and endswith("\n\n" + env.CAVEAT + "\n"))'
jq -r '.[0].text' "$OUT/comments-9a.json" > "$OUT/comment-9a.md"
comment_stages 9a "branch-point=refused (contract.node.missing)" seeded=baseline third-link=passed head=passed
COMMENT9A=$(jq -r '.[0].id' "$OUT/comments-9a.json")
export COMMENT9A
rehearsal_run 9a "$OUT/comment-9a.md"
RUN9A=$REHEARSAL_RUN USED9A=$REHEARSAL_USED
echo "e2e: case 9: rehearsal run $RUN9A passed, $USED9A; one comment, holding the table, the drawing and the stages"
no_twin 9a

# A stage made to fail: a port n1 does not have, rendered into n1's artifact alone, which the
# compile omits and the node refuses at the push (research R-14). The rehearsal builds the
# baseline, steps to third-link, and fails at bad-port's push on n1; the head is not reached.
artifacts_of "$FR" "$OUT/artifacts-9b-before.json" 2> "$OUT/artifacts-9b-before.err" ||
  fail "case 9: reading $FR's artifacts failed; see $OUT/artifacts-9b-before.err"
fixture -branch "$FR" -add-interface n1:ethernet-1/99 -generate > "$OUT/add-interface-9.out" 2> "$OUT/add-interface-9.err" ||
  fail "case 9: -add-interface n1:ethernet-1/99 -generate on $FR failed; see $OUT/add-interface-9.err"
await_checksums_moved 9b "$FR" "$OUT/artifacts-9b-before.json" n1
fixture -branch "$FR" -stage bad-port -description "a port n1 does not have" > "$OUT/stage-9-bad-port.out" 2> "$OUT/stage-9-bad-port.err" ||
  fail "case 9: marking stage $FR/bad-port failed; see $OUT/stage-9-bad-port.err"
start=$(now_ns)
fixture -branch "$FR" -run-checks user > "$OUT/run-checks-9b.out" 2> "$OUT/run-checks-9b.err" ||
  fail "case 9: -run-checks user on $FR failed; see $OUT/run-checks-9b.err"
REHEARSE9B_TOOK=$(since "$start")
echo "e2e: case 9: the checks concluded again in ${REHEARSE9B_TOOK}s"
run_checks_named 9b failure
user_checks 9b "$PC9" 2> "$OUT/checks-9b.err" || fail "case 9: reading $PC9's checks failed; see $OUT/checks-9b.err"
expect "$OUT/checks-9b.json" '(map(select(.name == "fylgja-twin")) | length == 1 and (.[0] | .conclusion == "failure"
    and .validator_state == "completed" and ((.message // "")
      | contains("stage " + env.FR + "/bad-port failed at phase push") and contains("not landed n1 (push.refused)"))))
  and (map(select(.name == "fylgja-step")) | length == 1 and .[0].conclusion == "success")'
stage_lines 9b "^stage $FR/branch-point: refused \\(contract\\.node\\.missing\\)\$" "^stage $FR/seeded: created; .*; baseline\$" \
  "^stage $FR/third-link: .*; passed\$" "^stage $FR/bad-port: diverged at phase push: .*; failed\$" "^stage $FR/head: not reached\$"
comments_of 9b "$PC9" 2> "$OUT/comments-9b.err" || fail "case 9: reading $PC9's comments failed; see $OUT/comments-9b.err"
# The failure's comment: its table, its drawing, the five commands that reproduce it in order
# (FR-015), and the caveat last.
# shellcheck disable=SC2016 # the backticks are the markdown's fences, read literally by jq
expect "$OUT/comments-9b.json" 'length == 2 and any(.[]; .id == env.COMMENT9A) and (map(.thread) | unique | length == 2)
  and (map(select(.id != env.COMMENT9A)) | length == 1 and (.[0].text | contains("Status **nonconforming**")
    and contains("```mermaid") and contains("**Reproduce by hand**:\n\n```\n"
      + "fylgja twin create --stage " + env.FR + "/seeded\n"
      + "fylgja twin step --stage " + env.FR + "/third-link --allow-restart\n"
      + "fylgja twin step --stage " + env.FR + "/bad-port --allow-restart\n"
      + "fylgja twin verify\nfylgja twin destroy\n```\n")
    and endswith("\n\n" + env.CAVEAT + "\n")))'
jq -r '.[] | select(.id != env.COMMENT9A) | .text' "$OUT/comments-9b.json" > "$OUT/comment-9b.md"
COMMENT9B=$(jq -r '.[] | select(.id != env.COMMENT9A) | .id' "$OUT/comments-9b.json")
THREADS9=$(jq -c 'map(.thread)' "$OUT/comments-9b.json")
comment_stages 9b "branch-point=refused (contract.node.missing)" seeded=baseline third-link=passed bad-port=failed \
  "head=not reached"
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
echo "e2e: case 9: rehearsal run $RUN9B failed at $FR/bad-port's push on n1, $USED9B; a second comment, with the commands that reproduce it"
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
else
  skip_case 9
fi

# --- credential hygiene over everything the run produced -----------------------

# The script's server is stopped first, so its log is whole when it is searched. Every twin
# is destroyed by now, so the trap has nothing to ask it.
stop_server
[ "$SERVER_STATUS" -eq 0 ] || fail "the API's server exited $SERVER_STATUS on SIGTERM, not 0; see $OUT/server.log"

# $OUT holds the short-lived worker's stdout and stderr, the orphan's deploy output, every
# twin show document, the checks' histories with their payloads decoded too, both boot
# halves' output (boot-half.out, boot-half-6.out), the plan and list documents of cases 7
# and 8 (plan-*.json, list-*.json), and their step documents, record copies and step
# histories, decoded (step-7*.json, step-8*.json, twin-7*.json, twin-8*.json, history-step-*),
# every twin verify document (verify-*.json), case 9's checks with their messages
# (checks-9*.json), its proposed change's comments (comments-9*.json, comment-9*.md) and its
# two rehearsals' histories and each of their children's, its provision, its steps and its
# destroy, decoded (history-rehearse-*), the overview's threads (overview-9.json), the answer
# of the server on the bridge (bridge-show.*), and the API's
# server's report and request log (server.log). A step history's push results
# carry the device's diff by design, so they are searched for the marker and the
# credentials, not for configuration lines; so do a rehearsal's step children's.
# Case 9's stage.plan and twin.rehearse went to the operator's server on the bridge, not to
# the script's: its log, local/server.log by CLAUDE.md's start line, is searched too (SC-008).
# The worker's log is searched when WORKER_LOG names it, and the line after the greps says
# whether it was.
scan=("$OUT" "$FYLGJA_STATE_ROOT/bundles")
searched="the run's outputs and the bundle store"
BRIDGE_LOG=""
if ran 9; then
  BRIDGE_LOG="$FYLGJA_STATE_ROOT/server.log"
  [ -r "$BRIDGE_LOG" ] ||
    fail "case 9 went through the server on $BRIDGE:7650, whose log $BRIDGE_LOG, as CLAUDE.md's start line writes it, is not readable"
  scan+=("$BRIDGE_LOG")
  searched+=", the log of the server on the bridge ($BRIDGE_LOG)"
fi
if [ -n "${WORKER_LOG:-}" ]; then
  [ -r "$WORKER_LOG" ] || fail "WORKER_LOG=$WORKER_LOG is not readable"
  scan+=("$WORKER_LOG")
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
# history, the servers' logs and the worker log. A read's CTM (ctm-*.json) and a compiled bundle
# (compiled-*/) carry the artifact by design, as the bundle store does, so they are left
# out, and the store with them.
if grep -rqsF --exclude='ctm-*.json' --exclude-dir='compiled-*' -- "$MARKER" "$OUT" ${BRIDGE_LOG:+"$BRIDGE_LOG"} ${WORKER_LOG:+"$WORKER_LOG"}; then
  echo "e2e: LEAK: the artifact marker found in:" >&2
  grep -rlsF --exclude='ctm-*.json' --exclude-dir='compiled-*' -- "$MARKER" "$OUT" ${BRIDGE_LOG:+"$BRIDGE_LOG"} ${WORKER_LOG:+"$WORKER_LOG"} >&2 || true
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
  echo "e2e: case 5: seed ${SEED_TOOK}s, artifact-only rebuild ${REBUILD_ARTIFACT_TOOK}s and topology rebuild ${REBUILD_TOOK}s from the change, destroy ${DESTROY5_TOOK}s"
fi
if ran 6; then
  echo "e2e: case 6: seed ${SEED6_TOOK}s, mixed twin $BID6 under run $RUN6"
fi
if ran 7; then
  echo "e2e: case 7: proposed change ${PROPOSE7_TOOK}s, plan ${PLAN7_TOOK}s, create ${CREATE7_TOOK}s, steps ${STEP7A_TOOK}s and ${STEP7B_TOOK}s; runs $RUN7A and $RUN7B"
fi
if ran 8; then
  echo "e2e: case 8: proposed change ${PROPOSE8_TOOK}s, steps ${STEP8A_TOOK}s and ${STEP8B_TOOK}s, create ${CREATE8_TOOK}s; runs $RUN8A and $RUN8B"
fi
if ran 9; then
  echo "e2e: case 9: seed ${SEED9_TOOK}s, proposed change ${PROPOSE9_TOOK}s and its checks ${DRAFT9_TOOK}s; checks with the rehearsals ${REHEARSE9A_TOOK}s ($USED9A) and ${REHEARSE9B_TOOK}s ($USED9B); runs $RUN9A and $RUN9B"
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
