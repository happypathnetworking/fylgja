#!/bin/bash
# The bring-up script: takes a fresh Ubuntu 26.04 host to tiers 1 and 2 passing and five
# processes running, the orchestrator's platform and runner and the dev server, the worker
# and the API's server, with both platforms when the cEOS tar is at hand and SR Linux alone
# when it is not. CI's contract job runs its Infrahub part alone. Tooling beside
# scripts/e2e.sh; nothing Fylgja ships (specs/013-launch/contracts/bring-up-script.md).
#
#   scripts/bring-up.sh [--ceos-tar PATH] [--part NAME]... [--help]
#
# Run from a clone, by the user who will run Fylgja (not root). --part is repeatable and
# takes toolchain, lab, infrahub, orchestrator or fylgja; absent, all five run, in that
# order.
#
# The preamble changes nothing until local/.env, and refuses with exit 2: a release other
# than Ubuntu 26.04, an unknown flag, a cEOS tar whose checksum is not the recorded one,
# port 8000 held by anything but the Compose project fylgja-infrahub. It asks for sudo
# once, the one prompt a run makes; looks for the cEOS tar at --ceos-tar, local/ and the
# clone's parent directory, never the clone's root; scaffolds local/.env when it is absent
# and keeps it byte for byte when it is present; and prints the first report.
#
#   toolchain  apt packages, the Go toolchain go.mod names, golangci-lint, the Temporal
#              CLI, gnmic, and .venv/ with infrahub-sdk[ctl]
#   lab        Docker, containerlab, the groups docker and clab_admins (then one re-exec
#              through a fresh login session, so the run sees them), the AppArmor lines
#              SR Linux's rsyslogd needs, the SR Linux image, the cEOS import
#   infrahub   Infrahub 1.11.2 by its published Compose file and this repository's
#              override, main prepared by the fixture tool, the fixture branch seeded
#   orchestrator  orchestrator/.venv by make orchestrator-venv; the Prefect server on the
#              Docker bridge, where Infrahub's task workers reach it (D-065), and the
#              runner, fylgja-orchestrator serve, started detached, each verified;
#              nothing of Infrahub's recreated
#              (specs/020-core-orchestrator-split/research.md, R-01 and R-17)
#   fylgja     the build; the dev server, the worker and the API's server started
#              detached, each one's report read, the server on loopback alone and with no
#              Infrahub variable, since the core reads no source of truth (020's FR-005);
#              then tiers 1 and 2
#
# Each item is verified, installed when missing and verified again, so a second run on a
# set-up host installs nothing and ends the same way. Exit 0: every part run completed and
# the last report printed. Exit 1: an item or a tier failed, named in the output. Exit 2:
# refused in the preamble, before any change.
#
# Hygiene: no value of local/.env is ever printed, logged or passed as an argument.
# Infrahub's token goes to curl as a header file, as e2e.sh's gql sends it; Compose reads
# the file through --env-file; everything else that needs a value loads the file in a
# subshell of its own. set -x is never used. Every file the script writes but local/.env
# carries no token and no password, and its output can be committed to a CI log.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")/.."
ROOT=$(pwd)

# The orchestrator's part comes before the core's: tier 1 runs the orchestrator's tests in
# its venv, and tier 2 its flows through its platform.
PARTS_ALL=(toolchain lab infrahub orchestrator fylgja)

# The cEOS tar the proven image was imported from (research R-12): the file Arista's portal
# gives, and the one layer `docker import` makes of it, which is the sha256 of the
# decompressed tar, so a present image can be told from the recorded tar without
# re-importing. The version is the package's, read from psp/arista_eos.yaml.
CEOS_TAR_SHA256=89a567d52f85e5f0e4650fe8e097e0226f78346d5a13d26bcab2a5623e888778
CEOS_LAYER=sha256:09ab96357c1d41f8bbaaead9ac10f61724f4890afcc09c75ad6b42519d73dd6c

INFRAHUB_VERSION=1.11.2
COMPOSE_URL="https://infrahub.opsmill.io/$INFRAHUB_VERSION"
COMPOSE_PROJECT=fylgja-infrahub
COMPOSE_DIR="$ROOT/local/infrahub"
# Infrahub's first start pulls about 2.1 GB of images and migrates an empty database.
INFRAHUB_WAIT_S=600

GOLANGCI_VERSION=2.14.0
TEMPORAL_VERSION=1.9.1
GNMIC_VERSION=0.49.0
CLAB_VERSION=0.79.0
SDK_VERSION=1.23.2
TEMPORAL_BIN="$HOME/.temporalio/bin/temporal"
TEMPORAL_WAIT_S=60
REPORT_WAIT_S=30

# The orchestrator (020's research R-01, R-02, R-17): its venv, the Prefect server's home and port,
# and the runner's six deployments, each a flow's `main`.
ORCH_VENV="$ROOT/orchestrator/.venv"
PREFECT_HOME_DIR="$ROOT/local/orchestrator/prefect"
PLATFORM_PORT=4200
PLATFORM_WAIT_S=120
DEPLOYMENTS=(intent-read twin-create twin-step stage-plan twin-rehearse schema-check)
# The names the orchestrator's part needs in local/.env; a file kept from before 020 lacks
# them.
ORCH_NAMES=(FYLGJA_ORCHESTRATOR_AUTH FYLGJA_ORCHESTRATOR_ROOT PREFECT_API_URL PREFECT_API_AUTH_STRING)
# The names the core's server must not carry: it reads no source of truth (D-065).
CORE_UNSET=(INFRAHUB_ADDRESS INFRAHUB_API_TOKEN FYLGJA_DEFAULT_SCOPE)

# The lines SR Linux's rsyslogd needs in the profile Ubuntu attaches to every rsyslogd
# (docs/verified-facts.md, The host).
APPARMOR_LOCAL=/etc/apparmor.d/local/usr.sbin.rsyslogd
APPARMOR_PROFILE=/etc/apparmor.d/usr.sbin.rsyslogd
APPARMOR_LINES=('/opt/srlinux/** mr,' '/run/srlinux/** rw,' '/run/syslogd.pid* rw,')

# --- helpers ------------------------------------------------------------------------------

say() { echo "bring-up: $*"; }

REFUSING=0
refuse() {
  REFUSING=1
  echo "bring-up: REFUSED: $*" >&2
  exit 2
}

# fail PART ITEM MESSAGE: an item that did not happen; the run ends with exit 1.
fail() {
  echo "bring-up: FAILED: $1: $2: $3" >&2
  exit 1
}

# Per-part counts of each outcome, for the last report; carried across the re-exec.
declare -A N_PRESENT=() N_INSTALLED=() N_SKIPPED=()
for p in "${PARTS_ALL[@]}"; do N_PRESENT[$p]=0 N_INSTALLED[$p]=0 N_SKIPPED[$p]=0; done

# item PART NAME present|installed|skipped DETAIL: one item's outcome, as one line.
item() {
  local part=$1 name=$2 outcome=$3 detail=$4
  case $outcome in
    present) N_PRESENT[$part]=$(( N_PRESENT[$part] + 1 )) ;;
    installed) N_INSTALLED[$part]=$(( N_INSTALLED[$part] + 1 )) ;;
    skipped) N_SKIPPED[$part]=$(( N_SKIPPED[$part] + 1 )) ;;
  esac
  say "$part: $name: $outcome $detail"
}

# wait_for PART ITEM WHAT SECONDS HINT COMMAND...: polls COMMAND each second until it
# succeeds; on expiry the run fails naming what did not happen.
wait_for() {
  local part=$1 it=$2 what=$3 seconds=$4 hint=$5 start
  shift 5
  say "$part: $it: waiting for $what (up to ${seconds}s)"
  start=$SECONDS
  until "$@" > /dev/null 2>&1; do
    if (( SECONDS - start >= seconds )); then
      fail "$part" "$it" "$what did not happen within ${seconds}s${hint:+: $hint}"
    fi
    sleep 1
  done
}

# psp_scalar FILE KEY: the value of the one `  key: value` line in a support package, less
# its trailing comment (as scripts/e2e.sh reads it).
psp_scalar() {
  sed -n "s/^  $2: *\([^ #]*\).*/\1/p" "$1" | head -1
}

# with_env COMMAND...: COMMAND with local/.env loaded into its own environment alone.
with_env() {
  (
    set -a
    # shellcheck disable=SC1091
    . "$ROOT/local/.env"
    set +a
    "$@"
  )
}

# infrahub_get PATH: Infrahub's answer at PATH, its token sent as a header file, so the
# token is in no process's arguments. Loads local/.env in a subshell of its own.
infrahub_get() {
  # shellcheck disable=SC2016
  with_env bash -c 'curl -sS --fail-with-body -H @<(printf "X-INFRAHUB-KEY: %s\n" "$INFRAHUB_API_TOKEN") "$INFRAHUB_ADDRESS$1"' get "$1"
}

# gql BRANCH QUERY: Infrahub's GraphQL answer's data on the branch (e2e.sh's gql).
gql() {
  local body
  body=$(jq -cn --arg q "$2" '{query: $q}')
  # shellcheck disable=SC2016
  with_env bash -c 'curl -sS --fail-with-body -H @<(printf "X-INFRAHUB-KEY: %s\n" "$INFRAHUB_API_TOKEN") \
    -H "Content-Type: application/json" -d "$1" "$INFRAHUB_ADDRESS/graphql/$2"' gql "$body" "$1" | jq -e '.data'
}

# orch_unnamed: the orchestrator's names local/.env does not name, read by name alone, never
# a value; empty when it names all four.
orch_unnamed() {
  local n lacks=""
  for n in "${ORCH_NAMES[@]}"; do
    grep -q "^$n=" "$ROOT/local/.env" 2> /dev/null || lacks+="${lacks:+, }$n"
  done
  echo "$lacks"
}

# orch_names_hint: what to add to a kept local/.env that lacks the orchestrator's names.
orch_names_hint() {
  echo "add FYLGJA_ORCHESTRATOR_AUTH and PREFECT_API_AUTH_STRING, one value 'fylgja:<password>' (for example \`head -c 24 /dev/urandom | base64 | tr '+/' '-_'\`), PREFECT_API_URL='http://<the Docker bridge address>:$PLATFORM_PORT/api' and FYLGJA_ORCHESTRATOR_ROOT='$ROOT/local/orchestrator' to it, as .env.example says"
}

compose() {
  docker compose -p "$COMPOSE_PROJECT" --env-file "$ROOT/local/.env" \
    -f "$COMPOSE_DIR/docker-compose.yml" -f "$COMPOSE_DIR/docker-compose.override.yml" "$@"
}

usage() {
  sed -n '2,/^set -euo/{/^set -euo/d;s/^# \{0,1\}//;p}' "$0"
}

# --- the trap -----------------------------------------------------------------------------

# The trap ends the sudo keep-alive loop and undoes nothing the run installed. It also holds
# the exit codes to the contract's three: a command that failed under set -e with a status
# of its own is a failed item of the part it ran in.
SUDO_LOOP_PID=""
CURRENT_PART=preamble
on_exit() {
  local status=$?
  if [ -n "$SUDO_LOOP_PID" ]; then
    kill "$SUDO_LOOP_PID" 2> /dev/null || true
  fi
  if (( status != 0 && status != 1 )) && (( REFUSING == 0 )); then
    echo "bring-up: FAILED: $CURRENT_PART: a command exited $status (the lines above name it)" >&2
    exit 1
  fi
}
trap on_exit EXIT

# --- the flags ----------------------------------------------------------------------------

# Parsed before the release is checked, so --help answers on any host; a flag refusal waits
# for its turn in the preamble's order.
CEOS_TAR_ARG=""
AFTER_GROUPS=0
FLAG_ERROR=""
declare -A WANT=()
while (( $# > 0 )); do
  case $1 in
    --help | -h)
      usage
      exit 0
      ;;
    --ceos-tar)
      if (( $# < 2 )); then FLAG_ERROR="--ceos-tar takes a path"; break; fi
      CEOS_TAR_ARG=$2
      shift
      ;;
    --part)
      if (( $# < 2 )); then FLAG_ERROR="--part takes one of: ${PARTS_ALL[*]}"; break; fi
      case " ${PARTS_ALL[*]} " in
        *" $2 "*) WANT[$2]=1 ;;
        *) FLAG_ERROR="--part $2 is not a part; the parts are: ${PARTS_ALL[*]}"; break ;;
      esac
      shift
      ;;
    --after-groups)
      if [ "${BRING_UP_REEXEC:-}" != 1 ]; then
        FLAG_ERROR="--after-groups is the script's own, set by its lab part; it is not given on the command line"
        break
      fi
      AFTER_GROUPS=1
      ;;
    *)
      FLAG_ERROR="unknown flag $1; scripts/bring-up.sh --help lists them"
      break
      ;;
  esac
  shift
done
PARTS=()
for p in "${PARTS_ALL[@]}"; do
  if (( ${#WANT[@]} == 0 )) || [ -n "${WANT[$p]:-}" ]; then PARTS+=("$p"); fi
done
runs() { case " ${PARTS[*]} " in *" $1 "*) return 0 ;; esac; return 1; }

# --- the preamble -------------------------------------------------------------------------

# (1) The release.
# shellcheck disable=SC1091
OS_ID=$(. /etc/os-release && echo "${ID:-}")
# shellcheck disable=SC1091
OS_VERSION=$(. /etc/os-release && echo "${VERSION_ID:-}")
# shellcheck disable=SC1091
OS_NAME=$(. /etc/os-release && echo "${PRETTY_NAME:-unknown}")
if [ "$OS_ID" != ubuntu ] || [ "$OS_VERSION" != 26.04 ]; then
  refuse "this host is $OS_NAME; the script supports Ubuntu 26.04 alone"
fi

# (2) The flags.
[ -z "$FLAG_ERROR" ] || refuse "$FLAG_ERROR"
[ "$(id -u)" -ne 0 ] || refuse "run as the user who will run Fylgja, not root; the script asks for sudo itself"

# The re-executed run carries the counts, the start, the lab part's progress and the parts
# the whole run runs, which the last report names although the re-execution runs fewer.
RUN_START=$SECONDS
LAB_HOST_DONE=0
REPORT_PARTS=("${PARTS[@]}")
if (( AFTER_GROUPS )); then
  for kv in ${BRING_UP_STATE:-}; do
    case $kv in
      elapsed=*) RUN_START=$(( SECONDS - ${kv#elapsed=} )) ;;
      lab_host=1) LAB_HOST_DONE=1 ;;
      parts=*) IFS=, read -ra REPORT_PARTS <<< "${kv#parts=}" ;;
      *=*,*,*)
        p=${kv%%=*} c=${kv#*=}
        IFS=, read -r "N_PRESENT[$p]" "N_INSTALLED[$p]" "N_SKIPPED[$p]" <<< "$c"
        ;;
    esac
  done
fi

# (3) Privilege escalation: at most one prompt. sudo's cached credential expires sooner
# than the toolchain and lab parts take, so a loop keeps it alive for the run and the trap
# ends it. No prompt when none is needed: a credential already cached is kept alive, and a
# user whose commands need no password has nothing to keep alive, although sudo -v may
# still ask (sudo's verifypw=all asks unless every rule naming the user says NOPASSWD). The
# re-executed run, in a session of its own, keeps one alive when it can and prompts for
# nothing: nothing after the lab part's groups needs sudo.
keep_sudo_alive() {
  ( while sudo -n -v 2> /dev/null; do sleep 60; done ) > /dev/null 2>&1 < /dev/null &
  SUDO_LOOP_PID=$!
}
if sudo -n -v 2> /dev/null; then
  keep_sudo_alive
elif (( AFTER_GROUPS )) || sudo -n true 2> /dev/null; then
  :
else
  sudo -v || refuse "sudo did not grant privilege escalation; the toolchain and lab parts install with it"
  keep_sudo_alive
fi

# (4) The cEOS tar (research R-12). The package's image reference names the version, and
# with it the file Arista's portal gives.
SRL_REF=$(psp_scalar psp/nokia_srlinux.yaml ref)
CEOS_REF=$(psp_scalar psp/arista_eos.yaml ref)
{ [ -n "$SRL_REF" ] && [ -n "$CEOS_REF" ]; } || refuse "psp/nokia_srlinux.yaml or psp/arista_eos.yaml states no image ref"
CEOS_VERSION=${CEOS_REF#*:}
CEOS_NAMES=("cEOS-lab-$CEOS_VERSION.tar" "cEOS-lab-$CEOS_VERSION.tar.xz")
PARENT=$(dirname "$ROOT")

ceos_present() { docker image inspect "$CEOS_REF" > /dev/null 2>&1 || sudo -n docker image inspect "$CEOS_REF" > /dev/null 2>&1; }

CEOS_TAR=""
CEOS_STATE=absent
if ceos_present; then
  CEOS_STATE=image
  CEOS_LINE="cEOS tar: not needed; $CEOS_REF is present"
else
  candidates=()
  [ -z "$CEOS_TAR_ARG" ] || candidates+=("$CEOS_TAR_ARG")
  for n in "${CEOS_NAMES[@]}"; do candidates+=("$ROOT/local/$n"); done
  for n in "${CEOS_NAMES[@]}"; do candidates+=("$PARENT/$n"); done
  for c in "${candidates[@]}"; do
    if [ -f "$c" ]; then CEOS_TAR=$(readlink -f "$c"); break; fi
  done
  if [ -n "$CEOS_TAR" ]; then
    found=$(sha256sum "$CEOS_TAR" | cut -d' ' -f1)
    [ "$found" = "$CEOS_TAR_SHA256" ] ||
      refuse "$CEOS_TAR: sha256 $found does not match the recorded $CEOS_TAR_SHA256; nothing was imported"
    CEOS_STATE=tar
    CEOS_LINE="cEOS tar: found $CEOS_TAR (sha256 matches ${CEOS_TAR_SHA256:0:8}…)"
  else
    CEOS_LINE="cEOS tar: not found; looked at --ceos-tar (${CEOS_TAR_ARG:-none given}), local/, $PARENT/; the repository root is never searched"
  fi
fi
if [ "$CEOS_STATE" = absent ]; then
  PLATFORMS=(nokia_srlinux)
  PLATFORMS_LINE="platforms: nokia_srlinux (arista_eos needs the cEOS tar: docs/development.md says where to get it)"
else
  PLATFORMS=(nokia_srlinux arista_eos)
  PLATFORMS_LINE="platforms: ${PLATFORMS[*]}"
fi

# (5) Port 8000, Infrahub's: free, or Compose project fylgja-infrahub's.
port_holder() {
  local name
  local format='{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Ports}}'
  name=$( { docker ps --format "$format" 2> /dev/null || sudo -n docker ps --format "$format" 2> /dev/null; } |
    awk -F'|' '$3 ~ /:8000->/ {print $1 "|" $2; exit}')
  if [ -n "$name" ]; then echo "container ${name%%|*} (project ${name#*|})"; return; fi
  name=$(ss -ltnpH 'sport = :8000' 2> /dev/null | sed -n 's/.*users:(("\([^"]*\)".*/\1/p' | head -1)
  echo "${name:+process $name}${name:-a process this user cannot name}"
}
if [ -n "$(ss -ltnH 'sport = :8000' 2> /dev/null)" ]; then
  holder=$(port_holder)
  case $holder in
    *"(project $COMPOSE_PROJECT)") ;;
    *) refuse "port 8000 is held by $holder; stop it, or point INFRAHUB_ADDRESS at it and run with --part fylgja" ;;
  esac
fi

# docker_bridge: the host's Docker bridge address, where host-gateway resolves inside
# Infrahub's task workers (D-050), or nothing when Docker does not answer this user.
docker_bridge() {
  local format='{{(index .IPAM.Config 0).Gateway}}'
  docker network inspect bridge -f "$format" 2> /dev/null || sudo -n docker network inspect bridge -f "$format" 2> /dev/null || true
}

# (6) local/.env: scaffolded from .env.example's names when absent (data-model §2), every
# value made here and written there alone, mode 0600; kept byte for byte when present.
env_value() {
  case $1 in
    FYLGJA_API_ADDRESS) echo 127.0.0.1:7650 ;;
    FYLGJA_API_TOKEN) head -c 24 /dev/urandom | base64 ;;
    INFRAHUB_ADDRESS) echo http://localhost:8000 ;;
    INFRAHUB_API_TOKEN | INFRAHUB_INITIAL_ADMIN_TOKEN) echo "$ADMIN_TOKEN" ;;
    # The fixture's tag (017): the scope a read that names none is read under.
    FYLGJA_DEFAULT_SCOPE) echo tag:fylgja ;;
    FYLGJA_ORCHESTRATOR_ROOT) echo "$ROOT/local/orchestrator" ;;
    # The platform listens on the bridge (020's research R-01). On a host whose Docker the lab part
    # has yet to install, Docker's default bridge address; the orchestrator's part holds the
    # file to the bridge it finds.
    PREFECT_API_URL) echo "http://${PLATFORM_BRIDGE:-172.17.0.1}:$PLATFORM_PORT/api" ;;
    # One <user>:<password> for the platform's clients on the host and the checks in the
    # task workers.
    FYLGJA_ORCHESTRATOR_AUTH | PREFECT_API_AUTH_STRING) echo "$ORCH_AUTH" ;;
    # Empty on purpose: the embedded packages. A directory that does not exist would refuse
    # the roles' start.
    FYLGJA_PSP_DIR) echo "" ;;
    FYLGJA_TEMPORAL_ADDRESS) echo localhost:7233 ;;
    FYLGJA_TEMPORAL_NAMESPACE) echo default ;;
    FYLGJA_STATE_ROOT) echo "$ROOT/local" ;;
    # Infrahub idles at about 5 GiB of the host's memory.
    FYLGJA_HOST_MEMORY_MB) echo $(( $(awk '/^MemTotal:/ {print int($2 / 1024)}' /proc/meminfo) - 8192 )) ;;
    # Each image's published default login, as scripts/e2e.sh exports it. The two platforms
    # name different variables, so one environment carries both.
    FYLGJA_SRLINUX_USERNAME) echo admin ;;
    FYLGJA_SRLINUX_PASSWORD) echo 'NokiaSrl1!' ;;
    FYLGJA_EOS_USERNAME) echo admin ;;
    FYLGJA_EOS_PASSWORD) echo admin ;;
    COMPOSE_PROJECT_NAME) echo "$COMPOSE_PROJECT" ;;
    INFRAHUB_INITIAL_ADMIN_PASSWORD) head -c 18 /dev/urandom | base64 | tr '+/' '-_' ;;
    INFRAHUB_INITIAL_AGENT_TOKEN) cat /proc/sys/kernel/random/uuid ;;
    INFRAHUB_SECURITY_SECRET_KEY) head -c 32 /dev/urandom | base64 | tr '+/' '-_' ;;
    *) return 1 ;;
  esac
}
ENV_LINE="local/.env: kept"
if [ ! -e local/.env ]; then
  ENV_NAMES=$(sed -n 's/^\([A-Z][A-Z0-9_]*\)=.*/\1/p' .env.example)
  ADMIN_TOKEN=x ORCH_AUTH=x
  for name in $ENV_NAMES; do
    env_value "$name" > /dev/null || refuse ".env.example names $name, which the script does not know how to fill"
  done
  mkdir -p local
  ADMIN_TOKEN=$(cat /proc/sys/kernel/random/uuid)
  # base64's alphabet less + and /, so the value needs no quoting in a URL, a header or
  # Compose's interpolation, and no colon past the user's.
  ORCH_AUTH="fylgja:$(head -c 24 /dev/urandom | base64 | tr '+/' '-_')"
  PLATFORM_BRIDGE=$(docker_bridge)
  (
    umask 077
    tmp=$(mktemp local/.env.XXXXXX)
    {
      echo "# Scaffolded by scripts/bring-up.sh from .env.example's names; .env.example says"
      echo "# what each one is. The one file that holds a value: never print, log or copy it."
      for name in $ENV_NAMES; do
        value=$(env_value "$name")
        if [ -n "$value" ]; then printf "%s='%s'\n" "$name" "$value"; else printf '%s=\n' "$name"; fi
      done
    } > "$tmp"
    chmod 0600 "$tmp"
    mv "$tmp" local/.env
  )
  unset ADMIN_TOKEN ORCH_AUTH
  ENV_LINE="local/.env: scaffolded from .env.example (mode 0600)"
else
  # A file kept from before 017 names no default scope, and one from before 020 none of the
  # orchestrator's names. Each is a note and not a refusal: the file is the operator's, kept
  # byte for byte, and read here by name alone, never a value. The orchestrator's part
  # fails on the names it lacks.
  ENV_NOTES=()
  grep -q '^FYLGJA_DEFAULT_SCOPE=' local/.env ||
    ENV_NOTES+=("it names no FYLGJA_DEFAULT_SCOPE, so the orchestrator reads with no default scope and refuses a read that names none, the checks' among them: add FYLGJA_DEFAULT_SCOPE='tag:fylgja' to it")
  ORCH_LACKS=$(orch_unnamed)
  [ -z "$ORCH_LACKS" ] ||
    ENV_NOTES+=("it names no $ORCH_LACKS, so the orchestrator's part cannot start its platform: $(orch_names_hint)")
  for note in "${ENV_NOTES[@]}"; do ENV_LINE+="; $note"; done
fi

# (7) The first report.
MEM_MIB=$(awk '/^MemTotal:/ {print int($2 / 1024)}' /proc/meminfo)
SWAP_MIB=$(awk '/^SwapTotal:/ {print int($2 / 1024)}' /proc/meminfo)
if (( ! AFTER_GROUPS )); then
  say "host: $OS_NAME, kernel $(uname -r), $(nproc) CPUs, $MEM_MIB MiB, swap $SWAP_MIB MiB"
  say "parts: ${PARTS[*]}"
  say "$CEOS_LINE"
  say "$PLATFORMS_LINE"
  say "memory: $MEM_MIB MiB; tier 3 was proved with 32768 MiB"
  if (( MEM_MIB < 24576 )); then
    say "memory: WARNING: under 24576 MiB, a twin may starve beside Infrahub; the script goes on"
  fi
  say "$ENV_LINE"
fi

# --- toolchain ----------------------------------------------------------------------------

APT_UPDATED=0
apt_install() {
  if (( ! APT_UPDATED )); then sudo apt-get update -q; APT_UPDATED=1; fi
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q "$@"
}

gnmic_is() { grep -qx "version : $1" <<< "$(gnmic version 2> /dev/null)"; }

# version_at_least A B: A is B or a later release (go1.26.10 is later than go1.26.9).
version_at_least() { [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n 1)" = "$2" ]; }

pkg_version() { dpkg-query -W -f='${Status} ${Version}' "$1" 2> /dev/null | sed -n 's/^install ok installed //p'; }

part_toolchain() {
  local p missing=() v want_go local_go have_go mod_cache

  for p in make git curl jq xz-utils file golang-go python3-venv shellcheck; do
    [ -n "$(pkg_version "$p")" ] || missing+=("$p")
  done
  (( ${#missing[@]} == 0 )) || apt_install "${missing[@]}"
  for p in make git curl jq xz-utils file golang-go python3-venv shellcheck; do
    v=$(pkg_version "$p")
    [ -n "$v" ] || fail toolchain "$p" "apt-get did not install it"
    case " ${missing[*]} " in
      *" $p "*) item toolchain "$p" installed "$v" ;;
      *) item toolchain "$p" present "$v" ;;
    esac
  done

  # Ubuntu's go is the bootstrap: in the clone it fetches and runs the release go.mod names,
  # unless it is that release (26.04's is) or a later one, which Go runs as it is, so
  # nothing is fetched, then or ever.
  want_go=go$(sed -n 's/^go \([0-9.]*\)$/\1/p' go.mod)
  local_go=$(cd / && GOTOOLCHAIN=local go version | awk '{print $3}')
  mod_cache=$(cd / && GOTOOLCHAIN=local go env GOMODCACHE)
  have_go=0
  ls -d "$mod_cache/golang.org/toolchain@v0.0.1-$want_go".* > /dev/null 2>&1 && have_go=1
  v=$(go version | awk '{print $3}')
  if [ "$v" = "$local_go" ] && version_at_least "$local_go" "$want_go"; then
    if [ "$local_go" = "$want_go" ]; then
      item toolchain go present "$v (Ubuntu's go, go.mod's release)"
    else
      item toolchain go present "$v (Ubuntu's go, newer than go.mod's $want_go)"
    fi
  elif [ "$v" = "$want_go" ]; then
    if (( have_go )); then
      item toolchain go present "$v (go.mod's, run by Ubuntu's go)"
    else
      item toolchain go installed "$v (fetched through go.mod)"
    fi
  else
    fail toolchain go "go version in the clone reports $v, neither go.mod's $want_go nor Ubuntu's $local_go"
  fi

  if [[ $(golangci-lint version 2> /dev/null) == *"version $GOLANGCI_VERSION "* ]]; then
    item toolchain golangci-lint present "$GOLANGCI_VERSION"
  else
    curl -sSfL "https://raw.githubusercontent.com/golangci/golangci-lint/v$GOLANGCI_VERSION/install.sh" |
      sudo sh -s -- -b /usr/local/bin "v$GOLANGCI_VERSION"
    [[ $(golangci-lint version) == *"version $GOLANGCI_VERSION "* ]] || fail toolchain golangci-lint "not $GOLANGCI_VERSION after the install"
    item toolchain golangci-lint installed "$GOLANGCI_VERSION"
  fi

  if [[ $("$TEMPORAL_BIN" --version 2> /dev/null) == *"version $TEMPORAL_VERSION "* ]]; then
    item toolchain temporal present "$TEMPORAL_VERSION ($TEMPORAL_BIN)"
  else
    curl -sSf https://temporal.download/cli.sh | sh -s -- --version "$TEMPORAL_VERSION"
    [[ $("$TEMPORAL_BIN" --version) == *"version $TEMPORAL_VERSION "* ]] || fail toolchain temporal "not $TEMPORAL_VERSION at $TEMPORAL_BIN after the install"
    item toolchain temporal installed "$TEMPORAL_VERSION ($TEMPORAL_BIN)"
  fi

  if gnmic_is "$GNMIC_VERSION"; then
    item toolchain gnmic present "$GNMIC_VERSION"
  else
    bash -c "$(curl -sSfL https://get-gnmic.openconfig.net)" -- --version "$GNMIC_VERSION"
    gnmic_is "$GNMIC_VERSION" || fail toolchain gnmic "not $GNMIC_VERSION after the install"
    item toolchain gnmic installed "$GNMIC_VERSION"
  fi

  # The venv is not ignored by the repository: a .gitignore of * inside it keeps the tree
  # clean.
  [ -d .venv ] || python3 -m venv .venv
  [ -f .venv/.gitignore ] || echo '*' > .venv/.gitignore
  if [ -x .venv/bin/infrahubctl ] && [ "$(.venv/bin/pip show infrahub-sdk 2> /dev/null | sed -n 's/^Version: //p')" = "$SDK_VERSION" ]; then
    item toolchain infrahub-sdk present "$SDK_VERSION (.venv, $(.venv/bin/python --version))"
  else
    .venv/bin/pip install -q "infrahub-sdk[ctl]==$SDK_VERSION"
    [ -x .venv/bin/infrahubctl ] || fail toolchain infrahub-sdk ".venv/bin/infrahubctl is absent after the install"
    item toolchain infrahub-sdk installed "$SDK_VERSION (.venv, $(.venv/bin/python --version))"
  fi
}

# --- lab ----------------------------------------------------------------------------------

in_group() { [[ " $(id -nG "$(id -un)") " == *" $1 "* ]]; }
session_has_group() { [[ " $(id -nG) " == *" $1 "* ]]; }

part_lab_host() {
  local v added=() line appended=0

  if v=$(sudo docker version --format '{{.Server.Version}}' 2> /dev/null); then
    item lab docker present "$v (compose $(docker compose version --short 2> /dev/null || echo absent))"
  else
    # containerlab's setup script pins the Docker release it supports on each Ubuntu
    # release; the copy at containerlab's v0.79.0 tag predates 26.04, so the current one.
    curl -sSfL https://containerlab.dev/setup | sudo bash -s install-docker
    v=$(sudo docker version --format '{{.Server.Version}}') || fail lab docker "the engine does not answer after the install"
    item lab docker installed "$v (compose $(docker compose version --short))"
  fi

  if v=$(containerlab version 2> /dev/null | sed -n 's/^ *version: *//p') && [ "$v" = "$CLAB_VERSION" ]; then
    item lab containerlab present "$v"
  else
    bash -c "$(curl -sSfL https://get.containerlab.dev)" -- --version "$CLAB_VERSION"
    v=$(containerlab version | sed -n 's/^ *version: *//p')
    [ "$v" = "$CLAB_VERSION" ] || fail lab containerlab "containerlab reports ${v:-nothing} after the install, not $CLAB_VERSION"
    item lab containerlab installed "$v"
  fi

  for g in docker clab_admins; do
    getent group "$g" > /dev/null || sudo groupadd -r "$g"
    if in_group "$g"; then continue; fi
    sudo usermod -aG "$g" "$(id -un)"
    added+=("$g")
  done
  if (( ${#added[@]} )); then
    item lab groups installed "(${added[*]} added)"
  else
    item lab groups present "(docker clab_admins)"
  fi

  if [ -f "$APPARMOR_PROFILE" ]; then
    sudo touch "$APPARMOR_LOCAL"
    for line in "${APPARMOR_LINES[@]}"; do
      if ! sudo grep -qxF -- "$line" "$APPARMOR_LOCAL"; then
        echo "$line" | sudo tee -a "$APPARMOR_LOCAL" > /dev/null
        appended=$(( appended + 1 ))
      fi
    done
    if (( appended )); then
      sudo apparmor_parser -r "$APPARMOR_PROFILE"
      item lab apparmor installed "($appended lines added to $APPARMOR_LOCAL; profile reloaded)"
    else
      item lab apparmor present "(${#APPARMOR_LINES[@]} lines in $APPARMOR_LOCAL)"
    fi
  else
    item lab apparmor skipped "(no $APPARMOR_PROFILE on this host: no profile attaches to SR Linux's rsyslogd)"
  fi
}

# reexec_after_groups: the user's groups are not all in this session, whether this run or
# an earlier one added them, and Docker needs them. One re-exec through a fresh login
# session, which carries them, with the remaining parts and this run's counts; the marker
# stops it looping.
reexec_after_groups() {
  local state p g rest=() lacking=()
  for g in docker clab_admins; do session_has_group "$g" || lacking+=("$g"); done
  say "lab: groups: ${lacking[*]} not in this session; continuing in a fresh login session"
  state="elapsed=$(( SECONDS - RUN_START )) lab_host=1 parts=$(IFS=,; echo "${REPORT_PARTS[*]}")"
  for p in "${PARTS_ALL[@]}"; do state+=" $p=${N_PRESENT[$p]},${N_INSTALLED[$p]},${N_SKIPPED[$p]}"; done
  for p in "${PARTS[@]}"; do
    [ "$p" = toolchain ] || rest+=(--part "$p")
  done
  [ -z "$CEOS_TAR_ARG" ] || rest+=(--ceos-tar "$(readlink -f "$CEOS_TAR_ARG")")
  if [ -n "$SUDO_LOOP_PID" ]; then kill "$SUDO_LOOP_PID" 2> /dev/null || true; SUDO_LOOP_PID=""; fi
  trap - EXIT
  exec sudo -u "$(id -un)" -i -- env BRING_UP_REEXEC=1 BRING_UP_STATE="$state" \
    "$ROOT/scripts/bring-up.sh" --after-groups "${rest[@]}"
}

part_lab_images() {
  local layer
  if docker image inspect "$SRL_REF" > /dev/null 2>&1; then
    item lab "$SRL_REF" present "(pulled)"
  else
    docker pull -q "$SRL_REF" > /dev/null || fail lab "$SRL_REF" "docker pull failed"
    item lab "$SRL_REF" installed "(pulled)"
  fi

  # The cEOS image is never pulled: its package says account_gated. The host check reads
  # the reference alone; the layer is said as information.
  if docker image inspect "$CEOS_REF" > /dev/null 2>&1; then
    layer=$(docker image inspect --format '{{index .RootFS.Layers 0}}' "$CEOS_REF")
    if [ "$layer" = "$CEOS_LAYER" ]; then
      item lab "$CEOS_REF" skipped "($CEOS_REF present; its layer is the recorded tar's)"
    else
      item lab "$CEOS_REF" skipped "($CEOS_REF present; its layer is not the recorded tar's)"
    fi
  elif [ -n "$CEOS_TAR" ]; then
    docker import "$CEOS_TAR" "$CEOS_REF" > /dev/null || fail lab "$CEOS_REF" "docker import of $CEOS_TAR failed"
    item lab "$CEOS_REF" installed "$CEOS_REF (from $CEOS_TAR)"
  else
    item lab "$CEOS_REF" skipped "(no cEOS tar: SR Linux alone)"
  fi
}

part_lab() {
  if (( ! LAB_HOST_DONE )); then
    part_lab_host
    LAB_HOST_DONE=1
  fi
  if ! session_has_group docker || ! session_has_group clab_admins; then
    (( ! AFTER_GROUPS )) || fail lab groups "the fresh login session still lacks docker or clab_admins"
    reexec_after_groups
  fi
  part_lab_images
}

# --- infrahub -----------------------------------------------------------------------------

infrahub_answers() {
  local id
  id=$(compose ps -q infrahub-server 2> /dev/null) && [ -n "$id" ] &&
    [ "$(docker inspect --format '{{.State.Health.Status}}' "$id")" = healthy ] &&
    [ "$(infrahub_get /api/info | jq -r .version)" = "$INFRAHUB_VERSION" ]
}

# fixture_state: complete (three device-config artifacts Ready), absent or incomplete.
fixture_state() {
  local ready
  if ! gql main '{ Branch { name } }' | jq -e '.Branch | any(.name == "fylgja-fixture")' > /dev/null; then
    echo absent
    return
  fi
  ready=$(gql fylgja-fixture '{ DcimDevice { edges { node { name { value }
    ... on CoreArtifactTarget { artifacts { edges { node { status { value }
      definition { node { ... on CoreArtifactDefinition { artifact_name { value } } } } } } } } } } } }' |
    jq '[.DcimDevice.edges[].node | [.artifacts.edges[].node
      | select(.definition.node.artifact_name.value=="device-config") | .status.value] | first
      | select(. == "Ready")] | length') || ready=0
  if [ "$ready" = 3 ]; then echo complete; else echo incomplete; fi
}

# library_held LOG: whether the fixture tool's -prepare-main refused a main already holding
# the schema library's kinds, by its own sentence (R-13).
library_held() {
  grep -q "^fylgja-fixture: main holds [0-9]* of the schema library's kinds (.*): -prepare-main is the development host's and CI's tool, which loads the library on an empty main alone" "$1"
}

# main_lacks: what -prepare-main puts on main beside the library that main does not hold,
# read by name and written nothing: the stage and probe kinds, the group and the
# registration. Empty when main holds all four.
main_lacks() {
  local lacks="" schema
  schema=$(infrahub_get '/api/schema?branch=main')
  jq -e '.nodes | any(.kind == "FylgjaStage")' <<< "$schema" > /dev/null ||
    lacks+="${lacks:+, }the stage kind FylgjaStage"
  jq -e '.nodes | any(.kind == "FylgjaProbe")' <<< "$schema" > /dev/null ||
    lacks+="${lacks:+, }the probe kind FylgjaProbe"
  gql main '{ CoreStandardGroup(name__value: "fylgja-devices") { count } }' |
    jq -e '.CoreStandardGroup.count == 1' > /dev/null || lacks+="${lacks:+, }the group fylgja-devices"
  gql main '{ CoreReadOnlyRepository(name__value: "fylgja") { count } }' |
    jq -e '.CoreReadOnlyRepository.count == 1' > /dev/null || lacks+="${lacks:+, }the registration fylgja"
  echo "$lacks"
}

# seed: make infrahub-seed, run once more on graphql: None (a BranchCreate straight after a
# BranchDelete of the same name; docs/verified-facts.md).
seed() {
  local log="$ROOT/local/bring-up-seed.log"
  if with_env make infrahub-seed > "$log" 2>&1; then return 0; fi
  if grep -q 'graphql: None' "$log"; then
    say "infrahub: fixture: the seed met graphql: None; running it once more"
    with_env make infrahub-seed > "$log" 2>&1 && return 0
  fi
  tail -20 "$log" >&2
  fail infrahub fixture "make infrahub-seed failed (local/bring-up-seed.log)"
}

# workers_carry_override: whether every running task worker carries the override's two
# variables, the orchestrator's address and auth string (D-065), read by name alone through docker inspect's template, never a value (T111). The
# file in local/infrahub/ equal to the tree's says nothing of the running containers: a run
# whose up -d failed or was interrupted, or an Infrahub recreated without the override, leaves
# the task workers without them, and both checks failing for want of them.
workers_carry_override() {
  local ids id names
  ids=$(compose ps -q task-worker) || return 1
  [ -n "$ids" ] || return 1
  for id in $ids; do
    names=$(docker inspect -f '{{range .Config.Env}}{{index (split . "=") 0}}{{println}}{{end}}' "$id") || return 1
    grep -qx FYLGJA_ORCHESTRATOR_ADDRESS <<< "$names" || return 1
    grep -qx FYLGJA_ORCHESTRATOR_AUTH <<< "$names" || return 1
  done
}

part_infrahub() {
  local c outcome running wanted state override=present

  for c in docker go curl jq; do
    if ! command -v "$c" > /dev/null; then
      case $c in
        go) fail infrahub go "go is not on the PATH: run the toolchain part, or set up Go" ;;
        *) fail infrahub "$c" "$c is not on the PATH: run the toolchain and lab parts" ;;
      esac
    fi
  done

  mkdir -p "$COMPOSE_DIR"
  if [ -f "$COMPOSE_DIR/docker-compose.yml" ]; then
    outcome=present
  else
    curl -sSfL "$COMPOSE_URL" -o "$COMPOSE_DIR/docker-compose.yml.part" ||
      fail infrahub compose-file "fetching $COMPOSE_URL failed"
    mv "$COMPOSE_DIR/docker-compose.yml.part" "$COMPOSE_DIR/docker-compose.yml"
    outcome=installed
  fi
  grep -q "VERSION:-$INFRAHUB_VERSION}" "$COMPOSE_DIR/docker-compose.yml" ||
    fail infrahub compose-file "local/infrahub/docker-compose.yml is not Infrahub $INFRAHUB_VERSION's; remove it and run again"
  item infrahub compose-file "$outcome" "$INFRAHUB_VERSION (local/infrahub/docker-compose.yml from $COMPOSE_URL)"

  if cmp -s scripts/infrahub/docker-compose.override.yml "$COMPOSE_DIR/docker-compose.override.yml"; then
    item infrahub override present "(local/infrahub/docker-compose.override.yml)"
  else
    cp scripts/infrahub/docker-compose.override.yml "$COMPOSE_DIR/docker-compose.override.yml"
    override=installed
    item infrahub override installed "(from scripts/infrahub/)"
  fi

  # A copied or replaced override reaches a running container only when it is recreated:
  # up -d runs then even with every service up, and recreates those whose configuration
  # moved, the task workers among them, and leaves the rest and the volumes as they are. It
  # runs too when the override is in place but a running task worker lacks its variables.
  wanted=$(compose config --services | sort)
  running=$(compose ps --services --status running | sort)
  if [ "$override" = present ] && [ -n "$running" ] && [ "$running" = "$wanted" ] && workers_carry_override; then
    item infrahub compose present "(project $COMPOSE_PROJECT, $(wc -l <<< "$running") services running)"
  elif [ "$override" = present ] && [ -n "$running" ] && [ "$running" = "$wanted" ]; then
    compose up -d --quiet-pull
    item infrahub compose installed "(project $COMPOSE_PROJECT, $(wc -l <<< "$wanted") services up; the task workers lacked FYLGJA_ORCHESTRATOR_ADDRESS or FYLGJA_ORCHESTRATOR_AUTH and were recreated)"
  elif [ -n "$running" ] && [ "$running" = "$wanted" ]; then
    compose up -d --quiet-pull
    item infrahub compose installed "(project $COMPOSE_PROJECT, $(wc -l <<< "$wanted") services up; those the override moved recreated)"
  else
    compose up -d --quiet-pull
    item infrahub compose installed "(project $COMPOSE_PROJECT, $(wc -l <<< "$wanted") services started)"
  fi
  wait_for infrahub server "infrahub-server healthy and /api/info answering $INFRAHUB_VERSION" "$INFRAHUB_WAIT_S" \
    "docker compose -p $COMPOSE_PROJECT logs infrahub-server" infrahub_answers
  item infrahub server present "$INFRAHUB_VERSION (http://localhost:8000)"

  # main: the stage and probe kinds, the schema library, the group and this repository's
  # registration (D-028, D-044), by the fixture tool, the one writer. It loads the two kinds
  # where either is absent, then the library only on a main that holds none of its kinds,
  # then skips what exists. On a main holding any of them it refuses, exit 1, writing
  # nothing after the two kinds (R-13): a second run's answer, read as present once main is
  # read to hold the two kinds, the group and the registration the refusal never reached.
  # Any other failure is a refusal.
  local out="$ROOT/local/bring-up-main.log" rc=0 missing
  with_env go run -tags fixture ./cmd/fylgja-fixture -prepare-main > "$out" 2>&1 || rc=$?
  if (( rc != 0 )) && ! library_held "$out"; then
    sed 's/^/bring-up: infrahub: main: /' "$out" >&2
    fail infrahub main "the fixture tool's -prepare-main failed (local/bring-up-main.log)"
  fi
  # go run's module downloads and its exit status stay in the log; the report relays the
  # tool's own lines.
  sed -e '/^go: downloading /d' -e '/^exit status /d' -e 's/^/bring-up: infrahub: main: /' "$out"
  # A run that succeeds has loaded the library, since a main holding it is refused.
  if (( rc == 0 )); then
    item infrahub main installed "(the library loaded; the stage and probe kinds, the group and the repository registered and imported)"
  else
    missing=$(main_lacks)
    [ -z "$missing" ] ||
      fail infrahub main "main holds the schema library but not $missing: -prepare-main loads only the stage and probe kinds on a main holding any of the library's kinds, so a group or a registration missing is added by hand (local/bring-up-main.log)"
    item infrahub main present "(the library, the stage and probe kinds, the group, the repository)"
  fi

  state=$(fixture_state)
  case $state in
    complete)
      item infrahub fixture present "(fylgja-fixture, 3 artifacts Ready)"
      ;;
    absent)
      seed
      ;;
    incomplete)
      say "infrahub: fixture: fylgja-fixture is incomplete; cleaning it before the seed"
      with_env make infrahub-clean > "$ROOT/local/bring-up-clean.log" 2>&1 ||
        fail infrahub fixture "make infrahub-clean failed (local/bring-up-clean.log)"
      seed
      ;;
  esac
  if [ "$state" != complete ]; then
    [ "$(fixture_state)" = complete ] || fail infrahub fixture "fylgja-fixture's three device-config artifacts are not Ready after the seed"
    item infrahub fixture installed "(fylgja-fixture, 3 artifacts Ready)"
  fi
}

# --- orchestrator -------------------------------------------------------------------------

BRIDGE_ADDR="" PLATFORM_URL="" PREFECT_VERSION="" PLATFORM_STARTED=0
RUNNER_LOG="$ROOT/local/orchestrator.log"
declare -A ROLE_PID=()

# bridge_address: BRIDGE_ADDR is the host's Docker bridge address, where host-gateway
# resolves inside Infrahub's task workers and the orchestrator's platform listens (D-050,
# 020's research R-01). A host with no bridge network fails the platform's item, naming it.
bridge_address() {
  BRIDGE_ADDR=$(docker_bridge)
  [ -n "$BRIDGE_ADDR" ] ||
    fail orchestrator platform "this host has no Docker network bridge with a gateway address (docker network inspect bridge): Infrahub's task workers reach the orchestrator's platform there"
}

# platform_get PATH: the platform's answer at PATH under PREFECT_API_URL, its basic-auth
# string sent as a header file, so it is in no process's arguments. Loads local/.env in a
# subshell of its own.
platform_get() {
  # shellcheck disable=SC2016
  with_env bash -c 'curl -sS --fail-with-body --max-time 10 \
    -H @<(printf "Authorization: Basic %s\n" "$(printf %s "$PREFECT_API_AUTH_STRING" | base64 -w0)") \
    "${PREFECT_API_URL%/}$1"' get "$1"
}

# platform_serving: the platform answers its health, which Prefect serves to anyone, and
# its release to local/.env's auth string, as the venv's Prefect: a server started with
# another auth string, or from another venv, does not pass.
platform_serving() {
  curl -sS --fail --max-time 10 "$PLATFORM_URL/health" > /dev/null 2>&1 &&
    [ "$(platform_get /admin/version 2> /dev/null | jq -r . 2> /dev/null)" = "$PREFECT_VERSION" ]
}

# deployments_named: the runner's start-up line's list, each flow's deployment main.
deployments_named() {
  local d named=""
  for d in "${DEPLOYMENTS[@]}"; do named+="${named:+, }$d/main"; done
  echo "$named"
}

# deployments_read: the platform answers each of the six deployments to local/.env's auth
# string, as a check reads one before it starts a run.
deployments_read() {
  local d
  for d in "${DEPLOYMENTS[@]}"; do
    platform_get "/deployments/name/$d/main" > /dev/null 2>&1 || return 1
  done
}

# runner_ready FROM: the runner's start-up line in its log, from byte FROM, names the six
# deployments on the platform at PLATFORM_URL, and the platform answers each.
runner_ready() {
  local text
  text=$(tail -c "+$(( $1 + 1 ))" "$RUNNER_LOG" 2> /dev/null | tr -d '\0') || return 1
  grep -qxF "fylgja-orchestrator: serving $(deployments_named) on the platform at $PLATFORM_URL" <<< "$text" &&
    deployments_read
}

# venv_pid SCRIPT WORD...: the pid of this tree's orchestrator/.venv/bin/SCRIPT run with the
# words WORD... first and PREFECT_HOME at PREFECT_HOME_DIR, as this script and make
# prefect-server and make orchestrator-serve start it, if one runs. The script runs under the
# venv's interpreter, so its path is the process's first argument; pgrep -f alone would also
# match a shell that runs it. A Prefect server or a runner a test started, under a home of
# its own, is not this host's and is left alone.
venv_pid() {
  local script="$ORCH_VENV/bin/$1" pid home
  local -a args
  shift
  for pid in $(pgrep -f -- "$script" || true); do
    mapfile -d '' -t args < "/proc/$pid/cmdline" 2> /dev/null || continue
    if [ "${args[1]:-}" != "$script" ] || [ "${args[*]:2:$#}" != "$*" ]; then continue; fi
    home=$(tr '\0' '\n' < "/proc/$pid/environ" 2> /dev/null | sed -n 's/^PREFECT_HOME=//p')
    [ "$home" = "$PREFECT_HOME_DIR" ] || continue
    echo "$pid"
    return 0
  done
  return 1
}

# arg_values PID FLAG: each value the process's arguments give FLAG, as FLAG VALUE or
# FLAG=VALUE, one a line, read as tier 3's case 9 reads them.
arg_values() {
  local -a args
  local i
  mapfile -d '' -t args < "/proc/$1/cmdline" 2> /dev/null || return 1
  for (( i = 1; i < ${#args[@]}; i++ )); do
    case ${args[i]} in
      "$2="*) echo "${args[i]#"$2"=}" ;;
      "$2") echo "${args[i + 1]:-}" ;;
    esac
  done
}

# stop_pid PART ITEM PID: PID ended, the run failing if it outlives 30 s.
stop_pid() {
  kill "$3"
  wait_for "$1" "$2" "pid $3 to exit" 30 "" bash -c "! kill -0 $3"
}

# ensure_platform: the Prefect server, started detached with its home under local/ and the
# auth string local/.env carries, on the bridge alone (020's research R-01): uvicorn takes one
# host, and the host's processes reach the bridge as the task workers do. One that runs from
# this venv is kept when it listens there, writes to local/prefect.log and answers as this
# venv's release to the file's auth string; else it is restarted.
ensure_platform() {
  local log="$ROOT/local/prefect.log" pid why
  if pid=$(venv_pid prefect server start); then
    if [ "$(arg_values "$pid" --host)" != "$BRIDGE_ADDR" ] || [ "$(arg_values "$pid" --port)" != "$PLATFORM_PORT" ]; then
      why="does not listen on $BRIDGE_ADDR:$PLATFORM_PORT (its --host and --port)"
    elif [ "$(readlink "/proc/$pid/fd/1" 2> /dev/null)" != "$log" ]; then
      why="writes its output elsewhere than local/prefect.log"
    elif ! platform_serving; then
      why="does not answer at $PLATFORM_URL as Prefect $PREFECT_VERSION to local/.env's auth string"
    else
      ROLE_PID[platform]=$pid
      item orchestrator platform present "(pid $pid, Prefect $PREFECT_VERSION at $PLATFORM_URL)"
      return
    fi
    say "orchestrator: platform: pid $pid $why; restarting it"
    stop_pid orchestrator platform "$pid"
  fi
  [ -z "$(ss -ltnH "sport = :$PLATFORM_PORT" 2> /dev/null)" ] ||
    fail orchestrator platform "port $PLATFORM_PORT is held by a process that is not this tree's Prefect server under local/orchestrator/prefect; stop it and run again"
  mkdir -p "$PREFECT_HOME_DIR"
  touch "$log"
  # shellcheck disable=SC2016
  with_env bash -c 'PREFECT_HOME="$1" PREFECT_SERVER_API_AUTH_STRING="$PREFECT_API_AUTH_STRING" \
    setsid nohup "$2" server start --host "$3" --port "$4" --no-ui >> "$5" 2>&1 < /dev/null &' \
    start "$PREFECT_HOME_DIR" "$ORCH_VENV/bin/prefect" "$BRIDGE_ADDR" "$PLATFORM_PORT" "$log"
  PLATFORM_STARTED=1
  wait_for orchestrator platform "Prefect $PREFECT_VERSION answering at $PLATFORM_URL" "$PLATFORM_WAIT_S" \
    "local/prefect.log" platform_serving
  pid=$(venv_pid prefect server start) || fail orchestrator platform "it answered, then exited (local/prefect.log)"
  ROLE_PID[platform]=$pid
  item orchestrator platform installed "(pid $pid, Prefect $PREFECT_VERSION at $PLATFORM_URL, local/prefect.log)"
}

# ensure_runner: fylgja-orchestrator serve, started detached as make orchestrator-serve
# starts it, from a shell that loaded local/.env. One that runs from this venv is kept when
# the platform was not started by this run, it writes to local/orchestrator.log, no file of
# the orchestrator's source is newer than it (the package is installed editable, so a
# running runner holds the code it started with), and its start-up line and the six
# deployments read; else it is restarted.
ensure_runner() {
  local pid why from started
  if pid=$(venv_pid fylgja-orchestrator serve); then
    started=$(ps -o etimes= -p "$pid" | tr -d ' ')
    started=$(( $(date +%s) - ${started:-0} ))
    if (( PLATFORM_STARTED )); then
      why="served the platform before this run started it"
    elif [ "$(readlink "/proc/$pid/fd/1" 2> /dev/null)" != "$RUNNER_LOG" ]; then
      why="writes its output elsewhere than local/orchestrator.log, so that log's start-up line is not its own"
    elif [ -n "$(find "$ROOT/orchestrator/src" -name '*.py' -newermt "@$started" -print -quit 2> /dev/null)" ]; then
      why="started before the orchestrator's source last changed"
    elif ! runner_ready "$(last_report_offset "$RUNNER_LOG" '^fylgja-orchestrator: serving ')"; then
      why="has not reported serving the six deployments at $PLATFORM_URL, or the platform does not answer them"
    else
      ROLE_PID[runner]=$pid
      item orchestrator runner present "(pid $pid, ${#DEPLOYMENTS[@]} deployments)"
      return
    fi
    say "orchestrator: runner: pid $pid $why; restarting it"
    stop_pid orchestrator runner "$pid"
  fi
  touch "$RUNNER_LOG"
  from=$(wc -c < "$RUNNER_LOG")
  # shellcheck disable=SC2016
  with_env bash -c 'PREFECT_HOME="$1" setsid nohup "$2" serve >> "$3" 2>&1 < /dev/null &' \
    start "$PREFECT_HOME_DIR" "$ORCH_VENV/bin/fylgja-orchestrator" "$RUNNER_LOG"
  wait_for orchestrator runner "its start-up line naming the six deployments at $PLATFORM_URL, and each read" \
    "$PLATFORM_WAIT_S" "local/orchestrator.log" runner_ready "$from"
  pid=$(venv_pid fylgja-orchestrator serve) || fail orchestrator runner "it reported, then exited (local/orchestrator.log)"
  ROLE_PID[runner]=$pid
  item orchestrator runner installed "(pid $pid, ${#DEPLOYMENTS[@]} deployments, local/orchestrator.log)"
}

part_orchestrator() {
  local c before after lacks
  for c in docker make python3 curl jq; do
    command -v "$c" > /dev/null || fail orchestrator "$c" "$c is not on the PATH: run the toolchain and lab parts"
  done

  # make orchestrator-venv reinstalls nothing current; the venv's packages before and after
  # tell present from installed.
  before=$("$ORCH_VENV/bin/pip" freeze 2> /dev/null | sha256sum) || before=""
  make orchestrator-venv > "$ROOT/local/bring-up-orchestrator-venv.log" 2>&1 ||
    { tail -20 "$ROOT/local/bring-up-orchestrator-venv.log" >&2; fail orchestrator venv "make orchestrator-venv failed (local/bring-up-orchestrator-venv.log)"; }
  for c in prefect fylgja-orchestrator fylgja-cli pytest ruff; do
    [ -x "$ORCH_VENV/bin/$c" ] || fail orchestrator venv "orchestrator/.venv/bin/$c is absent after make orchestrator-venv"
  done
  PREFECT_VERSION=$("$ORCH_VENV/bin/python" -I -c 'import importlib.metadata as m; print(m.version("prefect"))') ||
    fail orchestrator venv "orchestrator/.venv holds no prefect after make orchestrator-venv"
  after=$("$ORCH_VENV/bin/pip" freeze 2> /dev/null | sha256sum)
  if [ "$before" = "$after" ]; then
    item orchestrator venv present "(orchestrator/.venv, Prefect $PREFECT_VERSION, $("$ORCH_VENV/bin/python" --version))"
  else
    item orchestrator venv installed "(orchestrator/.venv, Prefect $PREFECT_VERSION, $("$ORCH_VENV/bin/python" --version))"
  fi

  # local/.env's names, read by name, and its values compared in a subshell of their own,
  # never printed.
  lacks=$(orch_unnamed)
  [ -z "$lacks" ] || fail orchestrator env "local/.env names no $lacks: $(orch_names_hint)"
  # shellcheck disable=SC2016
  with_env bash -c '[ "$FYLGJA_ORCHESTRATOR_AUTH" = "$PREFECT_API_AUTH_STRING" ] && [[ $PREFECT_API_AUTH_STRING == ?*:?* ]]' ||
    fail orchestrator env "local/.env's FYLGJA_ORCHESTRATOR_AUTH and PREFECT_API_AUTH_STRING are not one value <user>:<password>: the checks in Infrahub's task workers send the first, and the platform compares the second"
  bridge_address
  PLATFORM_URL="http://$BRIDGE_ADDR:$PLATFORM_PORT/api"
  # shellcheck disable=SC2016
  with_env bash -c '[ "${PREFECT_API_URL%/}" = "$1" ]' check "$PLATFORM_URL" ||
    fail orchestrator env "local/.env's PREFECT_API_URL is not $PLATFORM_URL, where the platform listens on this host's Docker bridge (020's research R-01): edit it"
  item orchestrator env present "(local/.env names ${ORCH_NAMES[*]})"

  ensure_platform
  ensure_runner
}

# --- fylgja -------------------------------------------------------------------------------

TIER1_S="" TIER2_S=""

# report_wants ROLE: what the role's start-up report must name, for the run's lines.
report_wants() {
  if [ "$1" = serve ]; then
    echo "127.0.0.1:7650 and ${PLATFORMS[*]} with their logins set"
  else
    echo "${PLATFORMS[*]} with their logins set"
  fi
}

# fylgja_pid ROLE: the pid of this tree's fylgja ROLE (worker or serve), if one runs.
# pgrep -x, since -f also matches the shell that runs it; the role is in its cmdline.
fylgja_pid() {
  local pid cmd
  for pid in $(pgrep -x fylgja || true); do
    cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2> /dev/null) || continue
    case $1 in
      worker) [[ $cmd == *" worker run"* ]] || continue ;;
      serve) [[ $cmd == *" serve"* ]] || continue ;;
    esac
    echo "$pid"
    return 0
  done
  return 1
}

# report_ok ROLE LOG FROM: the role's start-up report in LOG, from byte FROM, names every
# package the host can run with its login set, and the server's names its loopback address.
# A log can hold NUL bytes (local/worker.log has a run of them), which bash cannot keep in a
# variable: they are dropped before it reads the text.
report_ok() {
  local role=$1 log=$2 from=$3 text pkg
  text=$(tail -c "+$(( from + 1 ))" "$log" 2> /dev/null | tr -d '\0') || return 1
  if [ "$role" = serve ]; then
    grep -q "^fylgja serve: listening on 127\.0\.0\.1:7650 (API version 1, build " <<< "$text" || return 1
  else
    grep -q "^fylgja worker: serving task queue " <<< "$text" || return 1
  fi
  for pkg in "${PLATFORMS[@]}"; do
    grep -qE "^fylgja $role: probe login $pkg: [A-Z_]+ set, [A-Z_]+ set$" <<< "$text" || return 1
    grep -qE "^fylgja $role: $pkg \([a-z]+\): image " <<< "$text" || return 1
  done
  if [ "$CEOS_STATE" != absent ]; then
    grep -qE "^fylgja $role: arista_eos \([a-z]+\): image [^ ]+ \([a-z_]+, present on this host\)" <<< "$text" || return 1
  fi
}

# last_report_offset LOG PATTERN: the byte offset of the last line matching PATTERN, the
# start of the running process's report. The log is read as text (-a): past a NUL byte, grep
# would list no match and say only "binary file matches".
last_report_offset() {
  local line
  line=$(grep -an "$2" "$1" 2> /dev/null | tail -1 | cut -d: -f1)
  [ -n "$line" ] || { echo 0; return; }
  head -n $(( line - 1 )) "$1" | wc -c
}

# as_started ROLE PID LOG OUT: the process runs as start_role starts it, or it prints how it
# does not. OUT, its standard output, must be LOG, so that LOG's last start-up report is its
# own: make serve and make worker print theirs to their own terminal, and an earlier
# process's report in LOG would pass for it. A server's arguments must listen on loopback
# alone (020's FR-005 and R-18), so one an earlier run started on the bridge as well is restarted, and
# its environment must carry none of CORE_UNSET's names, read by name alone, so one started
# with Infrahub's variables is restarted with none (D-065).
as_started() {
  local role=$1 pid=$2 log=$3 out=$4 listens name
  if [ "$out" != "$log" ]; then
    echo "writes its output to $out, not local/$(basename "$log"), so that log's report is not its own"
    return 1
  fi
  [ "$role" = serve ] || return 0
  listens=$(arg_values "$pid" --listen | paste -sd' ')
  if [ "$listens" != 127.0.0.1:7650 ]; then
    echo "listens on ${listens:-its default}, not on --listen 127.0.0.1:7650 alone"
    return 1
  fi
  for name in "${CORE_UNSET[@]}"; do
    if tr '\0' '\n' < "/proc/$pid/environ" 2> /dev/null | cut -d= -f1 | grep -qx "$name"; then
      echo "carries $name in its environment, which the core never reads"
      return 1
    fi
  done
}

# start_role ROLE LOG: started detached, as CLAUDE.md starts it, from a shell that loaded
# local/.env; the dev server's CLI on the PATH it hands on. The server listens on loopback
# alone, and starts with CORE_UNSET's names taken from the environment the file gave it;
# the worker's environment is the file's whole, as before.
start_role() {
  local role=$1 log=$2 name
  local -a cmd=(bin/fylgja serve --listen 127.0.0.1:7650) unset=()
  if [ "$role" = worker ]; then
    cmd=(bin/fylgja worker run)
  else
    for name in "${CORE_UNSET[@]}"; do unset+=(-u "$name"); done
  fi
  # shellcheck disable=SC2016
  with_env bash -c 'PATH="$(dirname "$1"):$PATH" setsid nohup env "${@:4}" >> "$3" 2>&1 < /dev/null &' \
    start "$TEMPORAL_BIN" "$ROOT/local" "$log" "${unset[@]}" "FYLGJA_STATE_ROOT=$ROOT/local" "${cmd[@]}"
}

ensure_role() {
  local role=$1 log="$ROOT/local/$2.log" name=$2 pid exe out why from pattern
  # The report's first line: the server's names loopback.
  pattern="^fylgja serve: listening on 127\.0\.0\.1:7650 (API version "
  [ "$role" = worker ] && pattern="^fylgja worker: serving task queue "
  if pid=$(fylgja_pid "$role"); then
    exe=$(readlink "/proc/$pid/exe" 2> /dev/null || true)
    case $exe in
      "$ROOT/bin/fylgja")
        # The log's last report is judged only once the process is known to have written it.
        out=$(readlink "/proc/$pid/fd/1" 2> /dev/null || true)
        [ -n "$out" ] ||
          fail fylgja "$name" "a fylgja $name runs whose output this shell cannot read (pid $pid, /proc/$pid/fd/1 unreadable); stop it and run again"
        if ! why=$(as_started "$role" "$pid" "$log" "$out"); then
          say "fylgja: $name: pid $pid $why; restarting it"
        else
          from=$(last_report_offset "$log" "$pattern")
          if report_ok "$role" "$log" "$from"; then
            ROLE_PID[$role]=$pid
            item fylgja "$name" present "(pid $pid, this tree's bin/fylgja)"
            return
          fi
          say "fylgja: $name: pid $pid's report does not name $(report_wants "$role"); restarting it"
        fi
        kill "$pid"
        wait_for fylgja "$name" "pid $pid to exit" 30 "" bash -c "! kill -0 $pid"
        ;;
      "$ROOT/bin/fylgja (deleted)")
        say "fylgja: $name: pid $pid runs a replaced binary; restarting it"
        kill "$pid"
        wait_for fylgja "$name" "pid $pid to exit" 30 "" bash -c "! kill -0 $pid"
        ;;
      *)
        fail fylgja "$name" "a fylgja $name from elsewhere runs (pid $pid, ${exe:-unreadable}); stop it and run again"
        ;;
    esac
  fi
  touch "$log"
  from=$(wc -c < "$log")
  start_role "$role" "$log"
  wait_for fylgja "$name" "its start-up report naming $(report_wants "$role")" "$REPORT_WAIT_S" \
    "local/$name.log" report_ok "$role" "$log" "$from"
  pid=$(fylgja_pid "$role") || fail fylgja "$name" "it reported, then exited (local/$name.log)"
  ROLE_PID[$role]=$pid
  item fylgja "$name" installed "(pid $pid, local/$name.log)"
}

temporal_serving() { [ "$("$TEMPORAL_BIN" operator cluster health 2> /dev/null)" = SERVING ]; }

# timed_tier VAR NAME LOG COMMAND...: VAR is set to the tier's wall time in seconds, or the
# run fails with its log's tail.
timed_tier() {
  local var=$1 name=$2 log=$3 start
  shift 3
  start=$SECONDS
  say "fylgja: $name: running (local/$(basename "$log"))"
  if ! "$@" > "$log" 2>&1; then
    tail -40 "$log" >&2
    fail fylgja "$name" "failed (local/$(basename "$log"))"
  fi
  printf -v "$var" '%d' $(( SECONDS - start ))
}

part_fylgja() {
  local before after
  before=$(sha256sum bin/fylgja 2> /dev/null | cut -d' ' -f1 || true)
  make build > "$ROOT/local/bring-up-build.log" 2>&1 || { tail -20 "$ROOT/local/bring-up-build.log" >&2; fail fylgja build "make build failed"; }
  [[ $(file bin/fylgja) == *"statically linked"* ]] || fail fylgja build "bin/fylgja is not statically linked"
  after=$(sha256sum bin/fylgja | cut -d' ' -f1)
  if [ "$before" = "$after" ]; then
    item fylgja build present "(bin/fylgja $(bin/fylgja --version), static)"
  else
    item fylgja build installed "(bin/fylgja $(bin/fylgja --version), static)"
  fi

  # The three processes come before the tiers, so that tier 2's flows reach this build's
  # server, never a replaced binary or none at all; the orchestrator's part, run before this
  # one, has the platform and the runner up for them and for TestChecksInsideInfrahub.
  if temporal_serving; then
    item fylgja temporal present "(SERVING at localhost:7233)"
  else
    setsid nohup "$TEMPORAL_BIN" server start-dev --db-filename local/temporal.db >> local/temporal.log 2>&1 < /dev/null &
    wait_for fylgja temporal "the dev server SERVING at localhost:7233" "$TEMPORAL_WAIT_S" "local/temporal.log" temporal_serving
    item fylgja temporal installed "(SERVING at localhost:7233, local/temporal.log)"
  fi
  TEMPORAL_PID=$(pgrep -f -o 'temporal server start-dev' || echo unknown)

  ensure_role worker worker
  ensure_role serve server

  timed_tier TIER1_S "tier 1" "$ROOT/local/bring-up-tier1.log" make test
  timed_tier TIER2_S "tier 2" "$ROOT/local/bring-up-tier2.log" with_env make test-contract
}

# --- the run ------------------------------------------------------------------------------

for part in "${PARTS[@]}"; do
  CURRENT_PART=$part
  "part_$part"
done
CURRENT_PART=report

# The last report.
for part in "${PARTS_ALL[@]}"; do
  [[ " ${REPORT_PARTS[*]} " == *" $part "* ]] || continue
  say "did: $part: ${N_PRESENT[$part]} present, ${N_INSTALLED[$part]} installed, ${N_SKIPPED[$part]} skipped"
done
say "$CEOS_LINE"
say "$PLATFORMS_LINE"
if runs fylgja; then
  say "tier 1: passed (${TIER1_S}s)"
  say "tier 2: passed (${TIER2_S}s)"
  if [ "$CEOS_STATE" = absent ]; then
    say "tier 3: not run; PLATFORMS=nokia_srlinux make test-e2e runs it on SR Linux alone (needs the dev server and a worker)"
  else
    say "tier 3: not run; make test-e2e runs it (about 26 minutes, needs both images; about 17 with PLATFORMS=nokia_srlinux)"
  fi
fi
# The five processes: the orchestrator's two, then the core's three.
STOPS=()
if runs orchestrator; then
  say "running: platform (pid ${ROLE_PID[platform]}, local/prefect.log, Prefect $PREFECT_VERSION at $PLATFORM_URL, its auth string crossing the bridge in the clear)"
  say "running: runner (pid ${ROLE_PID[runner]}, local/orchestrator.log; deployments $(deployments_named))"
  STOPS+=("pkill -f '$ORCH_VENV/bin/fylgja-orchestrator serve'" "pkill -f '$ORCH_VENV/bin/prefect server start'")
fi
if runs fylgja; then
  say "running: temporal (pid $TEMPORAL_PID, local/temporal.log)"
  say "running: worker (pid ${ROLE_PID[worker]}, local/worker.log; packages ${PLATFORMS[*]})"
  say "running: server (pid ${ROLE_PID[serve]}, local/server.log, 127.0.0.1:7650 alone, with no Infrahub variable; packages ${PLATFORMS[*]})"
  STOPS+=("pkill -x fylgja" "pkill -f 'temporal server start-dev'")
fi
if (( ${#STOPS[@]} )); then
  say "to stop them: $(printf '%s; ' "${STOPS[@]}" | sed 's/; $//')"
fi
say "DONE in $(( SECONDS - RUN_START ))s"
