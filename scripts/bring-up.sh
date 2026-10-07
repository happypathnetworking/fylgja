#!/bin/bash
# The bring-up script: takes a fresh Ubuntu 26.04 host to tiers 1 and 2 passing and the
# dev server, the worker and the API's server running, with both platforms when the cEOS
# tar is at hand and SR Linux alone when it is not. CI's contract job runs its Infrahub
# part alone. Tooling beside scripts/e2e.sh; nothing Fylgja ships
# (specs/013-launch/contracts/bring-up-script.md).
#
#   scripts/bring-up.sh [--ceos-tar PATH] [--part NAME]... [--help]
#
# Run from a clone, by the user who will run Fylgja (not root). --part is repeatable and
# takes toolchain, lab, infrahub or fylgja; absent, all four run, in that order.
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
#   fylgja     the build, tiers 1 and 2, then the dev server, the worker and the API's
#              server started detached, each one's report read
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

PARTS_ALL=(toolchain lab infrahub fylgja)

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

# The re-executed run carries the counts, the start and the lab part's progress.
RUN_START=$SECONDS
LAB_HOST_DONE=0
if (( AFTER_GROUPS )); then
  for kv in ${BRING_UP_STATE:-}; do
    case $kv in
      elapsed=*) RUN_START=$(( SECONDS - ${kv#elapsed=} )) ;;
      lab_host=1) LAB_HOST_DONE=1 ;;
      *=*,*,*)
        p=${kv%%=*} c=${kv#*=}
        IFS=, read -r "N_PRESENT[$p]" "N_INSTALLED[$p]" "N_SKIPPED[$p]" <<< "$c"
        ;;
    esac
  done
fi

# (3) Privilege escalation: the one prompt. sudo's cached credential expires sooner than
# the toolchain and lab parts take, so a loop keeps it alive for the run and the trap ends
# it. The re-executed run, in a session of its own, keeps one alive when it can and prompts
# for nothing: nothing after the lab part's groups needs sudo.
if (( AFTER_GROUPS )); then
  if sudo -n -v 2> /dev/null; then
    ( while sudo -n -v 2> /dev/null; do sleep 60; done ) > /dev/null 2>&1 < /dev/null &
    SUDO_LOOP_PID=$!
  fi
else
  sudo -v || refuse "sudo did not grant privilege escalation; the toolchain and lab parts install with it"
  ( while sudo -n -v 2> /dev/null; do sleep 60; done ) > /dev/null 2>&1 < /dev/null &
  SUDO_LOOP_PID=$!
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

# (6) local/.env: scaffolded from .env.example's names when absent (data-model §2), every
# value made here and written there alone, mode 0600; kept byte for byte when present.
env_value() {
  case $1 in
    FYLGJA_API_ADDRESS) echo 127.0.0.1:7650 ;;
    FYLGJA_API_TOKEN) head -c 24 /dev/urandom | base64 ;;
    INFRAHUB_ADDRESS) echo http://localhost:8000 ;;
    INFRAHUB_API_TOKEN | INFRAHUB_INITIAL_ADMIN_TOKEN) echo "$ADMIN_TOKEN" ;;
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
  ADMIN_TOKEN=x
  for name in $ENV_NAMES; do
    env_value "$name" > /dev/null || refuse ".env.example names $name, which the script does not know how to fill"
  done
  mkdir -p local
  ADMIN_TOKEN=$(cat /proc/sys/kernel/random/uuid)
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
  unset ADMIN_TOKEN
  ENV_LINE="local/.env: scaffolded from .env.example (mode 0600)"
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
  # unless it is that release itself (26.04's is), when nothing is fetched, then or ever.
  want_go=go$(sed -n 's/^go \([0-9.]*\)$/\1/p' go.mod)
  local_go=$(cd / && GOTOOLCHAIN=local go version | awk '{print $3}')
  mod_cache=$(cd / && GOTOOLCHAIN=local go env GOMODCACHE)
  have_go=0
  ls -d "$mod_cache/golang.org/toolchain@v0.0.1-$want_go".* > /dev/null 2>&1 && have_go=1
  v=$(go version | awk '{print $3}')
  [ "$v" = "$want_go" ] || fail toolchain go "go version in the clone reports $v, not $want_go (go.mod)"
  if [ "$local_go" = "$want_go" ]; then
    item toolchain go present "$v (Ubuntu's go, go.mod's release)"
  elif (( have_go )); then
    item toolchain go present "$v (go.mod's, run by Ubuntu's go)"
  else
    item toolchain go installed "$v (fetched through go.mod)"
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
    curl -sSfL https://containerlab.dev/setup | sudo -E bash -s install-docker
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

# reexec_after_groups: the groups this part added are not in this session, and Docker
# needs them. One re-exec through a fresh login session, which carries them, with the
# remaining parts and this run's counts; the marker stops it looping.
reexec_after_groups() {
  local state p rest=()
  say "lab: groups: docker clab_admins added; continuing in a fresh login session"
  state="elapsed=$(( SECONDS - RUN_START )) lab_host=1"
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
  ready=$(gql fylgja-fixture '{ FylgjaDevice { edges { node { name { value }
    ... on CoreArtifactTarget { artifacts { edges { node { status { value }
      definition { node { ... on CoreArtifactDefinition { artifact_name { value } } } } } } } } } } } }' |
    jq '[.FylgjaDevice.edges[].node | [.artifacts.edges[].node
      | select(.definition.node.artifact_name.value=="device-config") | .status.value] | first
      | select(. == "Ready")] | length') || ready=0
  if [ "$ready" = 3 ]; then echo complete; else echo incomplete; fi
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

part_infrahub() {
  local c outcome running wanted state

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
    item infrahub override installed "(from scripts/infrahub/)"
  fi

  wanted=$(compose config --services | sort)
  running=$(compose ps --services --status running | sort)
  if [ -n "$running" ] && [ "$running" = "$wanted" ]; then
    item infrahub compose present "(project $COMPOSE_PROJECT, $(wc -l <<< "$running") services running)"
  else
    compose up -d --quiet-pull
    item infrahub compose installed "(project $COMPOSE_PROJECT, $(wc -l <<< "$wanted") services started)"
  fi
  wait_for infrahub server "infrahub-server healthy and /api/info answering $INFRAHUB_VERSION" "$INFRAHUB_WAIT_S" \
    "docker compose -p $COMPOSE_PROJECT logs infrahub-server" infrahub_answers
  item infrahub server present "$INFRAHUB_VERSION (http://localhost:8000)"

  # main: the schema, the group and this repository's registration (D-028, D-044), by the
  # fixture tool, the one writer, which skips what exists.
  local out="$ROOT/local/bring-up-main.log"
  with_env go run -tags fixture ./cmd/fylgja-fixture -prepare-main > "$out" 2>&1 ||
    { sed 's/^/bring-up: infrahub: main: /' "$out" >&2; fail infrahub main "the fixture tool's -prepare-main failed (local/bring-up-main.log)"; }
  sed 's/^/bring-up: infrahub: main: /' "$out"
  if grep -q ' created' "$out"; then
    item infrahub main installed "(schema, group, repository registered and imported)"
  else
    item infrahub main present "(schema, group, repository imported)"
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

# --- fylgja -------------------------------------------------------------------------------

TIER1_S="" TIER2_S=""
declare -A ROLE_PID=()

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
# package the host can run with its login set, and the server's names its listen address.
report_ok() {
  local role=$1 log=$2 from=$3 text pkg
  text=$(tail -c "+$(( from + 1 ))" "$log" 2> /dev/null) || return 1
  if [ "$role" = serve ]; then
    grep -q "^fylgja serve: listening on 127.0.0.1:7650 (API version 1, build " <<< "$text" || return 1
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
# start of the running process's report.
last_report_offset() {
  local line
  line=$(grep -n "$2" "$1" 2> /dev/null | tail -1 | cut -d: -f1)
  [ -n "$line" ] || { echo 0; return; }
  head -n $(( line - 1 )) "$1" | wc -c
}

# start_role ROLE LOG: started detached, as CLAUDE.md starts it, from a shell that loaded
# local/.env; the dev server's CLI on the PATH it hands on.
start_role() {
  local role=$1 log=$2
  local -a cmd=(bin/fylgja serve)
  [ "$role" = worker ] && cmd=(bin/fylgja worker run)
  # shellcheck disable=SC2016
  with_env bash -c 'PATH="$(dirname "$1"):$PATH" setsid nohup env FYLGJA_STATE_ROOT="$2" "${@:4}" >> "$3" 2>&1 < /dev/null &' \
    start "$TEMPORAL_BIN" "$ROOT/local" "$log" "${cmd[@]}"
}

ensure_role() {
  local role=$1 log="$ROOT/local/$2.log" name=$2 pid exe from pattern
  pattern="^fylgja $role: listening on "
  [ "$role" = worker ] && pattern="^fylgja worker: serving task queue "
  if pid=$(fylgja_pid "$role"); then
    exe=$(readlink "/proc/$pid/exe" 2> /dev/null || true)
    case $exe in
      "$ROOT/bin/fylgja")
        from=$(last_report_offset "$log" "$pattern")
        if report_ok "$role" "$log" "$from"; then
          ROLE_PID[$role]=$pid
          item fylgja "$name" present "(pid $pid, this tree's bin/fylgja)"
          return
        fi
        say "fylgja: $name: pid $pid's report does not name ${PLATFORMS[*]} with their logins set; restarting it"
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
  wait_for fylgja "$name" "its start-up report naming ${PLATFORMS[*]} with their logins set" "$REPORT_WAIT_S" \
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

  timed_tier TIER1_S "tier 1" "$ROOT/local/bring-up-tier1.log" make test
  timed_tier TIER2_S "tier 2" "$ROOT/local/bring-up-tier2.log" with_env make test-contract

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
}

# --- the run ------------------------------------------------------------------------------

for part in "${PARTS[@]}"; do
  CURRENT_PART=$part
  "part_$part"
done
CURRENT_PART=report

# The last report.
for part in "${PARTS_ALL[@]}"; do
  runs "$part" || continue
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
    say "tier 3: not run; make test-e2e runs it (about 17–19 minutes; needs both images, or PLATFORMS=nokia_srlinux)"
  fi
  say "running: temporal (pid $TEMPORAL_PID, local/temporal.log)"
  say "running: worker (pid ${ROLE_PID[worker]}, local/worker.log; packages ${PLATFORMS[*]})"
  say "running: server (pid ${ROLE_PID[serve]}, local/server.log, 127.0.0.1:7650; packages ${PLATFORMS[*]})"
  say "to stop them: pkill -x fylgja; pkill -f 'temporal server start-dev'"
fi
say "DONE in $(( SECONDS - RUN_START ))s"
