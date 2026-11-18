#!/usr/bin/env bash
# What `make infrahub-demo` and `make netbox-demo` need of the host (docs/demonstrations.md, "What the host must
# have"), installed where it is missing and checked where only its owner can give it. Run by `make
# demo-dependencies`, which passes UV_VERSION, PYTHON_MIN, CONTAINERLAB_VERSION and LOCAL; DRY_RUN=1 prints each
# command that would change the host instead of running it.
#
# - git, ss (iproute2) and curl: by apt-get where the host has it, and said otherwise.
# - uv at UV_VERSION: Astral's standalone installer, into UV_INSTALL_DIR or ~/.local/bin, where `uv --version` names
#   another or none. No sudo.
# - python3 at PYTHON_MIN or later: checked, never installed, since uv is never let fetch one (D-115).
# - Docker with its Compose plugin, and containerlab at CONTAINERLAB_VERSION: containerlab's setup script
#   (https://containerlab.dev/setup), as root, where the command is missing; it pins Docker per distribution release
#   (design/verified-facts.md, containerlab, "Install"). One already installed is left alone, another version of it
#   said.
# - The user in the groups docker and clab_admins: added where the group exists and does not list the user; a group
#   added reaches no process begun before it, so the user logs in again.
# - On Ubuntu, the two lines SR Linux's rsyslogd needs in AppArmor's local profile, added and the profile reloaded.
# - The node login's two names in <local>/.env, and the memory: checked, never written.
#
# The twin's images are not pulled here: the demonstration pulls the ones Docker does not hold.
set -uo pipefail

: "${UV_VERSION:?}" "${PYTHON_MIN:?}" "${CONTAINERLAB_VERSION:?}" "${LOCAL:?}"
DRY_RUN="${DRY_RUN:-}"
SETUP_URL="https://containerlab.dev/setup"
APPARMOR_PROFILE="/etc/apparmor.d/usr.sbin.rsyslogd"
APPARMOR_LOCAL="${APPARMOR_LOCAL:-/etc/apparmor.d/local/usr.sbin.rsyslogd}"
# AppArmor's kernel interface, without which no profile is reloaded. This and APPARMOR_LOCAL are set only by a test.
APPARMOR_FS="${APPARMOR_FS:-/sys/kernel/security/apparmor}"
APPARMOR_LINES=("/opt/srlinux/** mr," "/run/srlinux/** rw,")
# scripts/demo.py's SOURCE_MB and TWIN_MB: the larger source's need, Infrahub's, with the twin's and the edge's.
NEED_MB=$((4608 + 7168))

USER_NAME="$(id -un)"
SUDO=()
[ "$(id -u)" -eq 0 ] || SUDO=(sudo)
BY_HAND=()   # what only the host's owner can give, said last; any makes the exit 1
NOTES=()     # what is done but asks something more of the user, said last
RELOGIN=""

say() { printf '%s\n' "$*"; }
# A command that changes the host: printed under DRY_RUN, run otherwise.
change() {
    if [ -n "$DRY_RUN" ]; then
        printf 'would run: %s\n' "$*"
    else
        "$@"
    fi
}
have() { command -v "$1" > /dev/null 2>&1; }

# git, ss and curl.
missing_pkgs=()
have git || missing_pkgs+=(git)
have ss || missing_pkgs+=(iproute2)
have curl || missing_pkgs+=(curl)
if [ ${#missing_pkgs[@]} -eq 0 ]; then
    say "git, ss, curl: present"
elif have apt-get; then
    say "${missing_pkgs[*]}: installing"
    change "${SUDO[@]}" apt-get update -y && change "${SUDO[@]}" apt-get install -y "${missing_pkgs[@]}" \
        || BY_HAND+=("apt-get could not install ${missing_pkgs[*]}")
else
    BY_HAND+=("install ${missing_pkgs[*]} (the packages giving git, ss and curl): this host has no apt-get")
fi

# uv.
if [ "$(uv --version 2> /dev/null | cut -d' ' -f2)" = "$UV_VERSION" ]; then
    say "uv $UV_VERSION: present"
elif have curl; then
    say "uv $UV_VERSION: installing"
    if [ -n "$DRY_RUN" ]; then
        say "would run: curl -LsSf https://astral.sh/uv/$UV_VERSION/install.sh | UV_NO_MODIFY_PATH=1 sh"
    elif curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | UV_NO_MODIFY_PATH=1 sh; then
        NOTES+=("uv $UV_VERSION was installed into ${UV_INSTALL_DIR:-$HOME/.local/bin}: put it on PATH ahead of any other uv")
    else
        BY_HAND+=("uv $UV_VERSION was not installed: Astral's installer failed")
    fi
else
    BY_HAND+=("uv $UV_VERSION is needed, and curl to install it")
fi

# python3.
if python3 -c "import sys; sys.exit(sys.version_info[:2] < tuple(map(int, '$PYTHON_MIN'.split('.'))))" 2> /dev/null; then
    say "python3 $(python3 -c 'import platform; print(platform.python_version())'): present"
else
    BY_HAND+=("python3 $PYTHON_MIN or later is needed on PATH, from the system: uv will not fetch one")
fi

# Docker and containerlab, by containerlab's setup script as root. It reads SUDO_USER for the user it adds to the
# groups, so it is run under sudo even where this script is root, and is given its two names through env: Ubuntu
# 26.04's sudo, sudo-rs, ignores -E and says so.
setup_script=""
run_setup() {
    if [ -z "$setup_script" ]; then
        setup_script="$(mktemp)"
        trap 'rm -f "$setup_script"' EXIT
        curl -fsSL "$SETUP_URL" -o "$setup_script" || { setup_script=""; return 1; }
    fi
    change sudo env SUDO_USER="$USER_NAME" CLAB_VERSION="$CONTAINERLAB_VERSION" bash "$setup_script" "$@"
}

if have docker; then
    say "docker $(docker --version 2> /dev/null | sed -n 's/^Docker version \([^,]*\).*/\1/p'): present"
    docker compose version > /dev/null 2>&1 \
        || BY_HAND+=("docker is installed without its Compose plugin: install docker-compose-plugin")
elif have curl; then
    say "docker: installing, by containerlab's setup script"
    if run_setup install-docker && run_setup post-install-docker; then
        RELOGIN=1
    else
        BY_HAND+=("Docker was not installed: containerlab's setup script failed; read its lines above")
    fi
else
    BY_HAND+=("Docker is needed, and curl to install it")
fi

if have containerlab; then
    clab="$(containerlab version --short 2> /dev/null)"
    say "containerlab $clab: present"
    [ "$clab" = "$CONTAINERLAB_VERSION" ] \
        || NOTES+=("containerlab is $clab, and the demonstrations were verified on $CONTAINERLAB_VERSION: left as it is")
elif have curl; then
    say "containerlab $CONTAINERLAB_VERSION: installing, by containerlab's setup script"
    if run_setup install-containerlab && run_setup post-install-clab; then
        RELOGIN=1
    else
        BY_HAND+=("containerlab was not installed: containerlab's setup script failed; read its lines above")
    fi
else
    BY_HAND+=("containerlab is needed, and curl to install it")
fi

# The groups, but for root.
if [ "$(id -u)" -ne 0 ]; then
    for group in docker clab_admins; do
        entry="$(getent group "$group")"
        if [ -z "$entry" ] && [ -z "$DRY_RUN" ]; then
            BY_HAND+=("the host has no group $group")
        elif [ -n "$entry" ] && ! printf '%s\n' "${entry##*:}" | tr ',' '\n' | grep -qx "$USER_NAME"; then
            say "group $group: adding $USER_NAME"
            change sudo usermod -aG "$group" "$USER_NAME" && RELOGIN=1
        elif [ -n "$entry" ] && ! id -nG | tr ' ' '\n' | grep -qx "$group"; then
            say "group $group: $USER_NAME is listed, not yet in this login"
            RELOGIN=1
        else
            say "group $group: present"
        fi
    done
fi

# The AppArmor widening, where Ubuntu's profile of rsyslogd is.
# Its lines are read as scripts/demo.py's `apparmor` reads them: comments and spacing aside.
if [ -f "$APPARMOR_PROFILE" ]; then
    lacking=()
    held=""
    if [ -e "$APPARMOR_LOCAL" ] && [ ! -r "$APPARMOR_LOCAL" ]; then
        held="unread"
    elif [ -e "$APPARMOR_LOCAL" ]; then
        held="$(sed -e 's/#.*//' -e 's/[[:space:]]\+/ /g' -e 's/^ //' -e 's/ $//' "$APPARMOR_LOCAL")"
    fi
    if [ "$held" != "unread" ]; then
        for line in "${APPARMOR_LINES[@]}"; do
            printf '%s\n' "$held" | grep -qxF -- "$line" || lacking+=("$line")
        done
    fi
    if [ "$held" = "unread" ]; then
        NOTES+=("$APPARMOR_LOCAL is not yours to read: check that it holds ${APPARMOR_LINES[*]}")
    elif [ ${#lacking[@]} -eq 0 ]; then
        say "AppArmor widening for SR Linux's rsyslogd: present"
    else
        say "AppArmor widening for SR Linux's rsyslogd: adding ${lacking[*]} to $APPARMOR_LOCAL"
        if [ -n "$DRY_RUN" ]; then
            say "would run: printf '%s\\n' ${lacking[*]} | sudo tee -a $APPARMOR_LOCAL"
        else
            printf '%s\n' "${lacking[@]}" | "${SUDO[@]}" tee -a "$APPARMOR_LOCAL" > /dev/null \
                || BY_HAND+=("$APPARMOR_LOCAL could not be written")
        fi
        # A reload needs AppArmor's kernel interface, which a host without AppArmor enabled, or a container not
        # given securityfs, lacks; there the lines are added and no reload asked.
        if [ -d "$APPARMOR_FS" ]; then
            change "${SUDO[@]}" apparmor_parser -r "$APPARMOR_PROFILE" \
                || BY_HAND+=("apparmor_parser -r $APPARMOR_PROFILE failed")
        else
            NOTES+=("AppArmor's kernel interface, $APPARMOR_FS, is not here: the lines were added and the profile not reloaded")
        fi
    fi
fi

# The node login in <local>/.env: its names alone are read, never a value.
env_file="$LOCAL/.env"
unset_names=()
for name in FYLGJA_CREDENTIAL_SRLINUX_USERNAME FYLGJA_CREDENTIAL_SRLINUX_PASSWORD; do
    grep -qE "^(export +)?$name=.+" "$env_file" 2> /dev/null || unset_names+=("$name")
done
if [ ${#unset_names[@]} -eq 0 ]; then
    say "node login in $env_file: present"
elif [ -f "$env_file" ]; then
    BY_HAND+=("$env_file gives ${unset_names[*]} no value: add NAME=value lines for them; the SR Linux image's published default login is enough")
else
    BY_HAND+=("$env_file is not there: make it with \`install -m 0600 /dev/null $env_file\`, then add NAME=value lines for ${unset_names[*]}; the SR Linux image's published default login is enough")
fi

# The memory: the host's whole, since what is free depends on what runs at the demonstration's start.
total_mb=$(($(sed -n 's/^MemTotal: *\([0-9]*\) kB$/\1/p' /proc/meminfo) / 1024))
if [ "$total_mb" -ge "$NEED_MB" ]; then
    say "memory: $total_mb MiB in all, of the $NEED_MB MiB available Infrahub's demonstration needs"
else
    NOTES+=("the host has $total_mb MiB of memory in all, and Infrahub's demonstration needs $NEED_MB MiB available, NetBox's 8704")
fi

[ -n "$RELOGIN" ] && NOTES+=("log in again: a group added reaches no process begun before it")
for note in "${NOTES[@]}"; do say "note: $note"; done
for item in "${BY_HAND[@]}"; do printf 'demo-dependencies: %s\n' "$item" >&2; done
[ ${#BY_HAND[@]} -eq 0 ]
