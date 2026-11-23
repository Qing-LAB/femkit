#!/usr/bin/env bash
# scripts/install-env.sh -- thin bootstrap shim for `python -m femkit env ...`
# (docs/contracts/envs.md § 7).
#
# It does ONE thing: solve "you cannot run `femkit env ...` until the control
# environment exists". So it
#   1. finds conda / mamba / micromamba and asks you to confirm it (--yes skips);
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
STAMP="$CONTROL/.femkit/control.sha256"

AUTO_YES=0
DRY_RUN=0
CLEAN=0
WANT_HELP=0
NO_ACTION=0   # --dry-run / --help: look, never create or remove

usage() {
    cat <<'EOF'
femkit environment installer -- thin shim over `python -m femkit env ...`.

Needs conda, mamba or micromamba on the system; finds it on PATH, through
MAMBA_EXE / CONDA_EXE, above an active CONDA_PREFIX, or in the usual install
folders, and asks you to confirm it unless you pass --yes.

COMMON TASKS:
    bash scripts/install-env.sh bootstrap           # control env, config (asked), both engines, record, doctor
    bash scripts/install-env.sh bootstrap --clean   # the same, every environment rebuilt
    bash scripts/install-env.sh install ngsolve --yes
    bash scripts/install-env.sh validate elmer
    bash scripts/install-env.sh list

With --yes nothing is asked: give --preamble LINE (once per line) or
--no-preamble, and --environments PATH, on the line instead.

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
has_kind() {  # femkit has a kind file for this manager (definitions.md § 6)
    [[ -f "$REPO_ROOT/femkit/data/managers/$(basename "$1").toml" ]]
}

detect_env_mgr() {
    # The first manager found that femkit has a kind file for (envs.md § 7.1); one found
    # without a kind file is passed over, and named if nothing else is found.
    local path name root passed_over=""
    if [[ -n "${FEMKIT_ENV_MANAGER:-}" ]]; then
        [[ -f "$FEMKIT_ENV_MANAGER" && -x "$FEMKIT_ENV_MANAGER" ]] \
            || refuse "FEMKIT_ENV_MANAGER is not an executable file: $FEMKIT_ENV_MANAGER"
        ENV_MGR="$FEMKIT_ENV_MANAGER"; FOUND_BY="FEMKIT_ENV_MANAGER"; return 0
    fi
    found() {  # found PATH HOW: take it if femkit can drive it, else remember it
        if has_kind "$1"; then ENV_MGR="$1"; FOUND_BY="$2"; return 0; fi
        passed_over="${passed_over:-$1}"; return 1
    }
    # PATH first: the manager loaded in this shell (a cluster's module) is the one meant;
    # MAMBA_EXE/CONDA_EXE may be left over from an old `conda init`.
    for name in mamba micromamba conda; do
        path="$(type -P "$name" 2>/dev/null || true)"
        [[ -n "$path" ]] && found "$path" "PATH" && return 0
    done
    for name in MAMBA_EXE CONDA_EXE; do
        path="${!name:-}"
        [[ -n "$path" && -f "$path" && -x "$path" ]] && found "$path" "$name" && return 0
    done
    if [[ -n "${CONDA_PREFIX:-}" ]]; then
        root="${CONDA_PREFIX%%/envs/*}"
        for name in conda mamba micromamba; do
            [[ -f "$root/bin/$name" && -x "$root/bin/$name" ]] \
                && found "$root/bin/$name" "the root above CONDA_PREFIX" && return 0
        done
    fi
    for root in "$HOME/miniforge3" "$HOME/miniforge" "$HOME/mambaforge" "$HOME/miniconda3" \
                "$HOME/anaconda3" "$HOME/conda" /opt/miniforge3 /opt/miniforge /opt/mambaforge \
                /opt/miniconda3 /opt/anaconda3 /opt/conda; do
        for name in conda mamba micromamba; do
            [[ -f "$root/bin/$name" && -x "$root/bin/$name" ]] && found "$root/bin/$name" "$root" && return 0
        done
    done
    if [[ -n "$passed_over" ]]; then
        refuse "found $passed_over, but femkit has no kind file for $(basename "$passed_over") (it has: $(kinds_list))" \
            "FEMKIT_ENV_MANAGER=/path/to/conda bash scripts/install-env.sh bootstrap"
    fi
    refuse "no conda, mamba or micromamba found (looked at FEMKIT_ENV_MANAGER, PATH, MAMBA_EXE, CONDA_EXE, the root above CONDA_PREFIX, ~/{miniforge3,miniforge,mambaforge,miniconda3,anaconda3,conda}, /opt/{miniforge3,miniforge,mambaforge,miniconda3,anaconda3,conda}); on a cluster, load the manager's module in this shell first" \
        "FEMKIT_ENV_MANAGER=/path/to/conda bash scripts/install-env.sh bootstrap"
}

kinds_list() {
    (cd "$REPO_ROOT/femkit/data/managers" && ls -- *.toml | sed 's/\.toml$//' | tr '\n' ' ' | sed 's/ $//')
}

verb_changes_envs() {  # the verbs whose run creates or removes an environment
    case "${1:-}" in
        bootstrap|install|clean) return 0 ;;
        *)                       return 1 ;;
    esac
}

require_conda() {
    detect_env_mgr
    say "env manager: $ENV_MGR   # found by $FOUND_BY"
    # The script and Python drive the same manager the same way: one named with no kind file is refused.
    if ! has_kind "$ENV_MGR"; then
        refuse "femkit has no kind file for $(basename "$ENV_MGR") (it has: $(kinds_list))" \
            "FEMKIT_ENV_MANAGER=/path/to/conda bash scripts/install-env.sh $*"
    fi
    ((AUTO_YES)) && return 0
    verb_changes_envs "${1:-}" || return 0
    [[ -t 0 ]] || refuse "no terminal to confirm the env manager on" "bash scripts/install-env.sh $* --yes"
    local answer=""
    read -r -p "[femkit] use this env manager? [Y/n] " answer || refuse "no answer"
    case "$answer" in ""|y|Y|yes) ;; *) refuse "declined" ;; esac
}

# ------------------------------------------------------------------ the control environment (§ 7.2)

control_digest() {  # the SHA-256 of channels.txt then control.txt, as femkit's catalogue.control_digest
    if command -v sha256sum >/dev/null 2>&1; then cat "$CHANNELS_TXT" "$CONTROL_TXT" | sha256sum | cut -d' ' -f1
    else cat "$CHANNELS_TXT" "$CONTROL_TXT" | shasum -a 256 | cut -d' ' -f1; fi
}

control_state() {
    if [[ ! -e "$CONTROL" ]]; then echo absent
    elif [[ ! -d "$CONTROL/conda-meta" || ! -x "$CONTROL/bin/python" || ! -f "$STAMP" ]]; then echo broken
    elif [[ "$(cat "$STAMP")" != "$(control_digest)" ]]; then echo outdated
    else echo current; fi
}

create_control() {
    say "creating the control environment at $CONTROL from femkit/data/control.txt"
    # The conda kind's `create`: the declared channels only, none of the person's own settings
    # (envs.md § 4.4). channels.txt holds one bare name a line, so each line is a channel as it stands.
    local channels=() channel_args=() channel
    mapfile -t channels < "$CHANNELS_TXT"
    for channel in "${channels[@]}"; do channel_args+=(-c "$channel"); done
    "$ENV_MGR" create -y -p "$CONTROL" --override-channels --no-default-packages "${channel_args[@]}" \
        --file "$CONTROL_TXT" || { say "creating the control environment failed"; exit 1; }
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
    "$ENV_MGR" env remove -y -p "$CONTROL" || { say "removing the control environment failed"; exit 1; }
    CONTROL_REMOVED=1
    create_control
    CONTROL_REMOVED=0
    trap - EXIT
}

# ------------------------------------------------------------------ forwarding

# The control environment's own python, never `<manager> run`:
# some managers' `run` (a cluster's mamba module among them) writes a stub that dies on
# `exec: --: invalid option`, and `run` stands between Python and the terminal it asks
# on. femkit needs no activation to run: it is pure Python, from this checkout
# (envs.md § 7.3).
dispatch() {
    FEMKIT_ENV_MANAGER="$ENV_MGR" PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
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
