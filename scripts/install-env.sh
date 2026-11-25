#!/usr/bin/env bash
# scripts/install-env.sh -- thin bootstrap shim for `python -m femkit env ...`
# (docs/contracts/envs.md § 7).
#
# It does ONE thing: solve "you cannot run `femkit env ...` until the control
# environment exists". So it
#   1. finds every conda / mamba / micromamba in reach and proposes the first femkit
#      can drive; you choose (--yes takes the proposal);
#   2. makes sure the control environment exists and is current
#      (`bootstrap` creates or rebuilds it; every other verb requires it);
#   3. forwards "$@" verbatim to its own `python -m femkit env ...`.
# Every flag after the verb is Python's: `bash scripts/install-env.sh <verb> --help`.
#
# Day to day femkit runs in the activated control environment, from this checkout;
# `bootstrap` ends by printing the lines that enter it on this machine.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
CHANNELS_TXT="$REPO_ROOT/femkit/data/channels.txt"   # the channel order, one name a line
CONTROL_TXT="$REPO_ROOT/femkit/data/control.txt"     # the control environment's packages

# The control environment's place: <data>/environments/control (envs.md § 1),
# the rule of femkit/core/dirs.py; tests/basic/test_entry.py holds the two together.
DATA_DIR="${FEMKIT_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/femkit}"
[[ "$DATA_DIR" == "~" || "$DATA_DIR" == "~/"* ]] && DATA_DIR="$HOME${DATA_DIR#\~}"
if [[ "$DATA_DIR" != /* ]]; then
    echo "[femkit] refused: the data directory must be an absolute path, not $DATA_DIR" >&2
    exit 2
fi
CONTROL="$DATA_DIR/environments/control"
CACHE_DIR="${FEMKIT_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/femkit}"
[[ "$CACHE_DIR" == "~" || "$CACHE_DIR" == "~/"* ]] && CACHE_DIR="$HOME${CACHE_DIR#\~}"
if [[ "$CACHE_DIR" != /* ]]; then
    echo "[femkit] refused: the cache directory must be an absolute path, not $CACHE_DIR" >&2
    exit 2
fi
# Every manager command runs in femkit's own places, never the person's home (envs.md § 4.4):
# its HOME, its package cache, its list of environments and its temporary files; none of the
# person's own configuration or caches named apart from HOME, and none of their CONDA_* or
# MAMBA_* variables, which a manager reads as its settings -- as femkit/envs/manager.py does.
MANAGER_ENV=(env -u XDG_CONFIG_HOME -u XDG_CACHE_HOME -u XDG_DATA_HOME -u XDG_STATE_HOME -u CONDARC -u MAMBARC)
for variable in $(compgen -e); do
    case "$variable" in CONDA_*|MAMBA_*) MANAGER_ENV+=(-u "$variable") ;; esac
done
MANAGER_ENV+=("HOME=$CACHE_DIR/manager-home" "CONDA_PKGS_DIRS=$CACHE_DIR/pkgs" "CONDA_REGISTER_ENVS=false"
              "TMPDIR=$CACHE_DIR/tmp")
STAMP="$CONTROL/.femkit/control.sha256"

AUTO_YES=0
DRY_RUN=0
CLEAN=0
WANT_HELP=0
NO_ACTION=0   # --dry-run / --help: look, never create or remove

usage() {
    cat <<'EOF'
femkit environment installer -- thin shim over `python -m femkit env ...`.

Needs conda or mamba on the system (micromamba is found, and listed, but
femkit cannot drive it yet). Looks on PATH, at MAMBA_EXE / CONDA_EXE, above an
active CONDA_PREFIX and in the usual install folders, lists every manager found,
and proposes the first femkit can drive; you choose, or --yes takes the proposal.
FEMKIT_ENV_MANAGER=conda (a name on PATH, or a path) makes the choice up front.

COMMON TASKS:
    bash scripts/install-env.sh bootstrap           # control env, config (asked), both engines, record, doctor
    bash scripts/install-env.sh bootstrap --clean   # the same, every environment rebuilt
    bash scripts/install-env.sh install ngsolve --yes
    bash scripts/install-env.sh validate elmer
    bash scripts/install-env.sh list

With --yes nothing is asked: give --preamble LINE (once per line) or
--no-preamble, --activation COMMAND, and --environments PATH, on the line instead.

Every verb after `bootstrap` is forwarded verbatim to `python -m femkit env`;
its flags are Python's:  bash scripts/install-env.sh <verb> --help

Day to day, activate the control environment and run femkit from this checkout;
`bootstrap` ends by printing the lines that do it on this machine.
EOF
}

say()     { echo "[femkit] $*" >&2; }
refuse()  {  # refuse REASON NEXT...: exit 2 with the commands to run instead
    local reason="$1"; shift
    say "refused: $reason"
    if (($#)); then echo "next -- instead:" >&2; printf '    %s\n' "$@" >&2; fi
    exit 2
}

# ------------------------------------------------------------------ the manager (§ 7.1)

ENV_MGR=""
FOUND_BY=""
FOUND=()      # every manager found, once each: "path|how"
LOOKED=""     # where the search looked, for a refusal

has_kind() {  # femkit has a kind file for this manager (definitions.md § 6)
    [[ -f "$REPO_ROOT/femkit/data/managers/$(basename "$1").toml" ]]
}

kinds_list() {
    (cd "$REPO_ROOT/femkit/data/managers" && ls -- *.toml | sed 's/\.toml$//' | tr '\n' ' ' | sed 's/ $//')
}

same_file() {  # the file a path reaches, so a manager reached two ways is listed once
    readlink -f -- "$1" 2>/dev/null || printf '%s\n' "$1"
}

add_found() {  # add_found PATH HOW
    local real entry
    real="$(same_file "$1")"
    for entry in "${FOUND[@]+"${FOUND[@]}"}"; do
        [[ "$(same_file "${entry%%|*}")" == "$real" ]] && return 0
    done
    FOUND+=("$1|$2")
}

find_env_mgrs() {
    # Every manager in reach, in the order of envs.md § 7.1: PATH first -- the manager
    # loaded in this shell (a cluster's module) is the one meant; MAMBA_EXE/CONDA_EXE may
    # be left over from an old `conda init`. `type -P` finds files, never shell functions.
    local path name root
    for name in conda mamba micromamba; do
        path="$(type -P "$name" 2>/dev/null || true)"
        [[ -n "$path" ]] && add_found "$path" "PATH"
    done
    for name in MAMBA_EXE CONDA_EXE; do
        path="${!name:-}"
        [[ -n "$path" && -f "$path" && -x "$path" ]] && add_found "$path" "$name"
    done
    if [[ -n "${CONDA_PREFIX:-}" ]]; then
        root="${CONDA_PREFIX%%/envs/*}"
        for name in conda mamba micromamba; do
            [[ -f "$root/bin/$name" && -x "$root/bin/$name" ]] && add_found "$root/bin/$name" "the root above CONDA_PREFIX"
        done
    fi
    for root in "$HOME/miniforge3" "$HOME/miniforge" "$HOME/mambaforge" "$HOME/miniconda3" \
                "$HOME/anaconda3" "$HOME/conda" /opt/miniforge3 /opt/miniforge /opt/mambaforge \
                /opt/miniconda3 /opt/anaconda3 /opt/conda; do
        for name in conda mamba micromamba; do
            [[ -f "$root/bin/$name" && -x "$root/bin/$name" ]] && add_found "$root/bin/$name" "$root"
        done
    done
    LOOKED="PATH, MAMBA_EXE, CONDA_EXE, the root above CONDA_PREFIX, ~/{miniforge3,miniforge,mambaforge,miniconda3,anaconda3,conda}, /opt/{miniforge3,miniforge,mambaforge,miniconda3,anaconda3,conda}"
}

show_found() {  # each manager found: a number when femkit can drive it, else why not
    local i=0 entry path
    say "package managers found:"
    for entry in "${FOUND[@]}"; do
        path="${entry%%|*}"
        if has_kind "$path"; then
            i=$((i + 1))
            printf '    %s  %-10s %s   # %s\n' "$i" "$(basename "$path")" "$path" "${entry#*|}" >&2
        else
            printf '    -  %-10s %s   # %s; femkit has no kind file for %s yet (it has: %s)\n' \
                "$(basename "$path")" "$path" "${entry#*|}" "$(basename "$path")" "$(kinds_list)" >&2
        fi
    done
}

named_env_mgr() {  # FEMKIT_ENV_MANAGER: a path, or a name looked up on PATH
    local named="$FEMKIT_ENV_MANAGER" path
    if [[ "$named" == */* ]]; then path="$named"; else path="$(type -P "$named" 2>/dev/null || true)"; fi
    [[ -n "$path" && -f "$path" && -x "$path" ]] \
        || refuse "FEMKIT_ENV_MANAGER=$named is not an executable file${path:+: $path}, nor a name on PATH"
    [[ "$path" == /* ]] || path="$(cd "$(dirname "$path")" && pwd -P)/$(basename "$path")"
    printf '%s\n' "$path"
}

verb_changes_envs() {  # the verbs whose run creates or removes an environment
    case "${1:-}" in
        bootstrap|install|clean) return 0 ;;
        *)                       return 1 ;;
    esac
}

require_conda() {
    # One manager for everything after (envs.md § 7.1). Every manager found is listed, the one
    # FEMKIT_ENV_MANAGER names first, and the first femkit can drive is proposed: a verb that
    # creates or removes an environment asks on a terminal, --yes takes the proposal. One named
    # that femkit cannot drive is never replaced silently.
    local named="" blocked="" drivable=() entry answer=""
    if [[ -n "${FEMKIT_ENV_MANAGER:-}" ]]; then
        named="$(named_env_mgr)"
        add_found "$named" "FEMKIT_ENV_MANAGER"
        has_kind "$named" || blocked="$named"
    fi
    find_env_mgrs
    for entry in "${FOUND[@]+"${FOUND[@]}"}"; do
        has_kind "${entry%%|*}" && drivable+=("$entry")
    done
    if ((${#drivable[@]} == 0)); then
        if ((${#FOUND[@]})); then
            show_found
            refuse "femkit can drive none of these (it has kind files for: $(kinds_list)); looked at $LOOKED" \
                "FEMKIT_ENV_MANAGER=/path/to/conda bash scripts/install-env.sh $*"
        fi
        refuse "no conda, mamba or micromamba found (looked at $LOOKED); on a cluster, load the manager's module in this shell first" \
            "FEMKIT_ENV_MANAGER=/path/to/conda bash scripts/install-env.sh $*"
    fi
    entry="${drivable[0]}"   # the proposal
    local ask=0
    if ! ((AUTO_YES)) && { verb_changes_envs "${1:-}" || [[ -n "$blocked" ]]; }; then ask=1; fi
    # The list is shown with every question, and whenever a verb that creates or removes an
    # environment had more than one to choose from; a verb that only looks says its one line.
    if ((ask)) || [[ -n "$blocked" ]] || { verb_changes_envs "${1:-}" && ((${#FOUND[@]} > 1)); }; then
        show_found
    fi
    if [[ -n "$blocked" ]] && ((AUTO_YES)); then
        refuse "FEMKIT_ENV_MANAGER names $(basename "$blocked"), which femkit cannot drive yet; with --yes nothing is chosen in its place" \
            "FEMKIT_ENV_MANAGER=${entry%%|*} bash scripts/install-env.sh $*" \
            "unset FEMKIT_ENV_MANAGER   # then run it again, and choose"
    fi
    if ((ask)); then
        [[ -t 0 ]] || refuse "no terminal to choose the env manager on" "bash scripts/install-env.sh $* --yes"
        read -r -p "[femkit] use which env manager? [1] " answer || refuse "no answer"
        answer="${answer:-1}"
        [[ "$answer" =~ ^[0-9]+$ ]] && ((answer >= 1 && answer <= ${#drivable[@]})) \
            || refuse "no manager numbered $answer; nothing was changed"
        entry="${drivable[$((answer - 1))]}"
    fi
    ENV_MGR="${entry%%|*}"; FOUND_BY="${entry#*|}"
    say "env manager: $ENV_MGR   # found by $FOUND_BY"
}

# ------------------------------------------------------------------ the control environment (§ 7.2)

control_digest() {  # the SHA-256 of channels.txt then control.txt, as femkit's catalogue.control_digest
    if command -v sha256sum >/dev/null 2>&1; then cat "$CHANNELS_TXT" "$CONTROL_TXT" | sha256sum | cut -d' ' -f1
    else cat "$CHANNELS_TXT" "$CONTROL_TXT" | shasum -a 256 | cut -d' ' -f1; fi
}

# The rules femkit/data/states/control.toml declares, in its order, written here in bash since
# the script runs before femkit can; tests/basic/test_entry.py holds the two equal on every way
# the prefix can stand, and the next step a refusal below names to the one that table gives.
control_state() {
    if [[ ! -e "$CONTROL" ]]; then echo absent
    elif [[ ! -d "$CONTROL/conda-meta" || ! -x "$CONTROL/bin/python" || ! -f "$STAMP" ]]; then echo broken
    elif [[ "$(cat "$STAMP")" != "$(control_digest)" ]]; then echo outdated
    else echo current; fi
}

ARGV=()
kind_argv() {  # kind_argv KEY: the chosen manager's kind-file command KEY, its {exe} and {prefix} filled
    # The kind file is the one home of the manager's commands (definitions.md § 6); each is a
    # one-line list of plain strings, read here without a TOML parser.
    local file line rest arg
    file="$REPO_ROOT/femkit/data/managers/$(basename "$ENV_MGR").toml"
    line="$(grep -E "^$1 = \[" "$file")" || { say "$file has no one-line $1"; exit 1; }
    rest="${line#*[}"; rest="${rest%%]*}"; ARGV=()
    while [[ "$rest" =~ ^[^\"]*\"([^\"]*)\"(.*)$ ]]; do
        arg="${BASH_REMATCH[1]}"; rest="${BASH_REMATCH[2]}"
        arg="${arg//\{exe\}/$ENV_MGR}"; ARGV+=("${arg//\{prefix\}/$CONTROL}")
    done
}

create_control() {
    say "creating the control environment at $CONTROL from femkit/data/control.txt"
    # The kind's `create`: the declared channels only (envs.md § 4.4), then control.txt.
    # channels.txt holds one bare name a line, so each line is a channel as it stands.
    local channels=() cmd=() channel arg
    mapfile -t channels < "$CHANNELS_TXT"
    kind_argv create; cmd=("${ARGV[@]}")
    for channel in "${channels[@]}"; do
        kind_argv channel
        for arg in "${ARGV[@]}"; do cmd+=("${arg//\{channel\}/$channel}"); done
    done
    mkdir -p "$CACHE_DIR/manager-home" "$CACHE_DIR/pkgs" "$CACHE_DIR/tmp"
    "${MANAGER_ENV[@]}" "${cmd[@]}" --file "$CONTROL_TXT" || { say "creating the control environment failed"; exit 1; }
    mkdir -p "$CONTROL/.femkit"
    local digest
    digest="$(control_digest)" || { say "could not hash channels.txt and control.txt; no stamp written"; exit 1; }
    printf '%s\n' "$digest" > "$STAMP.tmp"
    mv "$STAMP.tmp" "$STAMP"   # the stamp is written last
}

CONTROL_REMOVED=0
AGAIN=""  # what recreates the control environment: the person's own bootstrap, never with --yes
rebuild_failed() {  # on exit after the remove and before the create finished
    ((CONTROL_REMOVED)) || return 0
    say "THE CONTROL ENVIRONMENT WAS REMOVED AND THE REBUILD FAILED; there is none at $CONTROL now."
    echo "next -- recreate it:" >&2
    echo "    $AGAIN" >&2
}

recreate_control() {
    AGAIN="bash scripts/install-env.sh bootstrap"
    if ((CLEAN)); then AGAIN+=" --clean"; fi
    say "rebuilding the control environment at $CONTROL; if the create after the removal fails, run:"
    echo "    $AGAIN" >&2
    if ((! AUTO_YES)); then
        [[ -t 0 ]] || refuse "no terminal to confirm the rebuild on" "bash scripts/install-env.sh bootstrap $([[ $CLEAN == 1 ]] && echo '--clean ')--yes"
        local answer=""
        read -r -p "[femkit] remove and rebuild the control environment at $CONTROL? [y/N] " answer || refuse "no answer"
        case "$answer" in y|Y|yes) ;; *) refuse "declined; nothing was changed" ;; esac
    fi
    trap rebuild_failed EXIT
    kind_argv remove; local rm=("${ARGV[@]}") channel arg channels=()
    # Where the kind's removal names the declared channels, as its create does (envs.md § 4.4).
    if grep -qE '^channels_named = \[.*"remove"' "$REPO_ROOT/femkit/data/managers/$(basename "$ENV_MGR").toml"; then
        mapfile -t channels < "$CHANNELS_TXT"
        for channel in "${channels[@]}"; do
            kind_argv channel
            for arg in "${ARGV[@]}"; do rm+=("${arg//\{channel\}/$channel}"); done
        done
    fi
    mkdir -p "$CACHE_DIR/manager-home" "$CACHE_DIR/pkgs" "$CACHE_DIR/tmp"
    "${MANAGER_ENV[@]}" "${rm[@]}" || { say "removing the control environment failed"; exit 1; }
    CONTROL_REMOVED=1
    create_control
    CONTROL_REMOVED=0
    trap - EXIT
}

# ------------------------------------------------------------------ forwarding

# The control environment's own python, never `<manager> run`: `run` would stand between
# Python and the terminal it asks on, and femkit needs no activation to run -- it is pure
# Python, from this checkout (envs.md § 7.3). The checkout alone is its PYTHONPATH, and no
# user site-packages load: none of the person's own Python packages reaches femkit.
dispatch() {
    FEMKIT_ENV_MANAGER="$ENV_MGR" PYTHONPATH="$REPO_ROOT" PYTHONNOUSERSITE=1 \
        "$CONTROL/bin/python" -m femkit env "$@"
}

# ------------------------------------------------------------------ main (§ 7.3)

if [[ $# -eq 0 ]]; then
    printf 'No verb given. First-time install on a fresh machine?\n    bash scripts/install-env.sh bootstrap\n\n' >&2
    usage >&2
    exit 2
fi

for arg in "$@"; do
    case "$arg" in
        --yes|-y)  AUTO_YES=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --clean)   CLEAN=1 ;;
        --help|-h) WANT_HELP=1 ;;
    esac
done
# Only looking needs no consent, and changes nothing.
if ((DRY_RUN || WANT_HELP)); then NO_ACTION=1; AUTO_YES=1; fi

case "$1" in
    -h|--help|help)
        usage
        exit 0
        ;;
    bootstrap)
        require_conda "$@"
        state="$(control_state)"
        say "control environment: $state   # $CONTROL"
        if ((WANT_HELP)) && [[ "$state" != current ]]; then
            usage; exit 0   # femkit's own help needs the control environment; this one does not
        fi
        if ((NO_ACTION)) && [[ "$state" != current ]]; then
            refuse "--dry-run needs the control environment, which is $state; making it is the install you did not ask for" \
                "bash scripts/install-env.sh bootstrap"
        fi
        ((NO_ACTION)) && CLEAN=0   # look at a rebuild, never do one
        # A broken control environment is rebuilt like an outdated one, never by --clean,
        # which also rebuilds every engine environment.
        case "$state:$CLEAN" in
            absent:*)                         create_control ;;
            outdated:*|broken:*|current:1)    recreate_control ;;
            current:0)                        ;;
        esac
        dispatch "$@"
        ;;
    *)
        require_conda "$@"
        state="$(control_state)"
        case "$state" in
            current) dispatch "$@" ;;
            *)       refuse "the control environment is $state: $CONTROL" "bash scripts/install-env.sh bootstrap" ;;
        esac
        ;;
esac
