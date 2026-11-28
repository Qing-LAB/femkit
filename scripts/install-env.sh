#!/usr/bin/env bash
# scripts/install-env.sh -- thin bootstrap shim for `femkit env ...`
# (docs/contracts/envs.md § 7).
#
# It does ONE thing: solve "you cannot run `femkit env ...` until the control
# environment exists". So it
#   1. finds every conda / mamba / micromamba in reach and proposes the first femkit
#      can drive; you choose (--yes takes the proposal);
#   2. makes sure the control environment, the manager's environment `femkit`, exists and
#      is current (`bootstrap` creates or rebuilds it; every other verb requires it), writes
#      into it the `femkit` command, which runs femkit from this checkout, and links that
#      command from ~/.local/bin/femkit, so `femkit` is on the path of every shell that has
#      ~/.local/bin on it;
#   3. forwards "$@" verbatim to its own `python -m femkit env ...`.
# Every command it starts -- the manager's, femkit's -- begins from the clean start
# femkit/data/process.toml declares (envs.md § 4.4), as femkit/envs/start.py writes it.
# Every flag after the verb is Python's: `bash scripts/install-env.sh <verb> --help`.
#
# Day to day you type `femkit ...` in any shell and any folder; `conda env list` lists
# every femkit environment, and `conda activate femkit` enters the control environment.

set -euo pipefail
# A replacement in ${text//pattern/value} is taken as it stands: bash 5.2 would otherwise put the
# pattern in place of each `&` of a path (bash before 5.2 has no such option, and does not).
shopt -u patsub_replacement 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SCHEDULERS="$REPO_ROOT/femkit/data/schedulers"   # the scheduler kinds: what a job of each adds to a clean start
CHANNELS_TXT="$REPO_ROOT/femkit/data/channels.txt"   # the channel order, one name a line
CONTROL_TXT="$REPO_ROOT/femkit/data/control.txt"     # the control environment's packages
LAUNCHER_TXT="$REPO_ROOT/femkit/data/launcher.sh"   # the `femkit` command's text, filled by write_launcher
PROCESS_TOML="$REPO_ROOT/femkit/data/process.toml"   # the clean start every manager command begins from

normal_path() {  # a path written as Python's pathlib writes it: no empty or `.` step, no `/` at its end
    # (`..` is kept, as pathlib keeps it), so the places the script forms are the text femkit forms
    local steps=() step out="" lead=/
    [[ "$1" == //* && "$1" != ///* ]] && lead=//   # POSIX leaves a leading `//` to the system; pathlib keeps it
    IFS=/ read -r -a steps <<< "$1"
    for step in "${steps[@]+"${steps[@]}"}"; do
        [[ -z "$step" || "$step" == . ]] || out+="/$step"
    done
    printf '%s\n' "${lead}${out#/}"
}

folder_from() {  # folder_from VALUE WHAT: a folder a variable names, by femkit/core/dirs.py's rule
    local path="$1"
    [[ "$path" == "~" || "$path" == "~/"* ]] && path="$HOME${path#\~}"
    if [[ "$path" != /* ]]; then
        echo "[femkit] refused: the $2 directory must be an absolute path, not $path" >&2
        exit 2
    fi
    normal_path "$path"
}

# femkit's folders, by the rules of femkit/core/dirs.py; tests/basic/test_entry.py holds the two
# together. The control environment's place is the manager's: asked of it by its name (envs.md § 1).
DATA_DIR="$(folder_from "${FEMKIT_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/femkit}" data)"
BIN_DIR="$(folder_from "${FEMKIT_BIN_DIR:-$HOME/.local/bin}" bin)"
LINK="$BIN_DIR/femkit"    # the link that puts the `femkit` command on a shell's path (envs.md § 7)
NAMING_TOML="$REPO_ROOT/femkit/data/naming.toml"   # every environment's name with the manager (envs.md § 1)
CONTROL_NAME=""   # the control environment's name with the manager, read from NAMING_TOML (main)
CONTROL=""        # its prefix, as the manager lists it (locate_control); none while it lists none
STAMP=""
LAUNCHER=""       # the `femkit` command in it, which LINK names
# The control environment's lock, the file femkit/core/locks.py takes for the subject `control`
# (core.md § 5): held alone to create or remove the environment, shared while femkit runs from it.
CONTROL_LOCK="$DATA_DIR/locks/control.lock"

AUTO_YES=0
DRY_RUN=0
CLEAN=0
WANT_HELP=0
NO_ACTION=0   # --dry-run / --help: look, never create or remove

usage() {
    cat <<'EOF'
femkit environment installer -- thin shim over `femkit env ...`.

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
--no-preamble, --activation COMMAND, and --projects PATH, on the line instead.

Every verb after `bootstrap` is forwarded verbatim to `femkit env`;
its flags are Python's:  bash scripts/install-env.sh <verb> --help

Each run but a --dry-run or --help writes the `femkit` command into the control
environment, naming this checkout, and links it from ~/.local/bin/femkit. Day to
day, type `femkit ...` in any shell and any folder; `conda activate femkit`
enters the control environment the way you enter any of conda's.
EOF
}

quoted() {  # $1 as one shell word, as Python's shlex.quote writes it: as it stands where it is safe
    if [[ -n "$1" && "$1" =~ ^[A-Za-z0-9@%+=:,./_-]+$ ]]; then printf '%s' "$1"
    else local q="'\"'\"'"; printf "'%s'" "${1//\'/$q}"; fi
}
# This script, by its absolute path in the checkout, as every line it prints names it, so the line
# pastes from any folder (envs.md § 7) -- as femkit's own steps name it (femkit/core/dirs.py).
SELF="bash $(quoted "$SCRIPT_DIR/install-env.sh")"

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
            refuse "femkit can drive none of these (it has kind files for: $(kinds_list)); looked at $LOOKED; on a cluster, load the manager's module in this shell first" \
                "FEMKIT_ENV_MANAGER=/path/to/conda $SELF $*"
        fi
        refuse "no conda, mamba or micromamba found (looked at $LOOKED); on a cluster, load the manager's module in this shell first" \
            "FEMKIT_ENV_MANAGER=/path/to/conda $SELF $*"
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
            "FEMKIT_ENV_MANAGER=${entry%%|*} $SELF $*" \
            "unset FEMKIT_ENV_MANAGER   # then run it again, and choose"
    fi
    if ((ask)); then
        [[ -t 0 ]] || refuse "no terminal to choose the env manager on" "$SELF $* --yes"
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

# The clean start every command this script starts begins from (envs.md § 4.4), read from
# process.toml and the scheduler kinds as femkit/envs/start.py reads them: of this shell's
# variables, only those its `passes` -- with each kind's `passes` -- name and none its `removes`
# name; of its exported functions, only those a kind names in its `functions` stay exported;
# `PATH` its `path`, then its `sets`. Each list is one line there, read without a TOML parser, as the
# kind files' commands are. START holds it as the very lines femkit's `start.lines` writes -- the
# `femkit` command's own start (write_launcher); `clean` runs a command from it.
toml_strings() {  # toml_strings FILE KEY: each quoted word of the one-line list or table KEY holds
    local line rest
    line="$(grep -E "^$2 = " "$1")" || { say "$1 has no one-line $2"; exit 1; }
    rest="${line#*= }"
    while [[ "$rest" =~ ^[^\"]*\"([^\"]*)\"(.*)$ ]]; do
        printf '%s\n' "${BASH_REMATCH[1]}"; rest="${BASH_REMATCH[2]}"
    done
}

toml_strings_or_none() {  # the same, nothing where FILE has no KEY
    if grep -qE "^$2 = " "$1"; then toml_strings "$1" "$2"; fi
}

joined() {  # joined WORD...: the words, ` | ` between each two
    local out="" word
    for word in "$@"; do out+="${out:+ | }$word"; done
    printf '%s' "$out"
}

START=""
start_lines() {
    local passes=() removes=() functions=() kind word sets line
    local -A seen=() said=()
    mapfile -t passes < <(toml_strings "$PROCESS_TOML" passes)
    mapfile -t removes < <(toml_strings "$PROCESS_TOML" removes)
    local jobs=()
    while IFS= read -r kind; do   # every kind, in the order femkit loads them: by file name
        while IFS= read -r word; do
            [[ -n "${seen[$word]+x}" ]] || { seen[$word]=1; jobs+=("$word"); }
        done < <(toml_strings_or_none "$kind" passes)
        while IFS= read -r word; do
            [[ -n "${said[$word]+x}" ]] || { said[$word]=1; functions+=("$word"); }
        done < <(toml_strings_or_none "$kind" functions)
    done < <(printf '%s\n' "$SCHEDULERS"/*.toml | LC_ALL=C sort)
    START='for exported in $(compgen -e); do'$'\n'
    START+='  case "$exported" in'$'\n'
    START+="    $(joined "${removes[@]}")) unset \"\$exported\" 2>/dev/null || true ;;"$'\n'
    START+="    $(joined "${passes[@]}" "${jobs[@]+"${jobs[@]}"}")) ;;"$'\n'
    START+='    *) unset "$exported" 2>/dev/null || true ;;'$'\n'
    START+='  esac'$'\n'
    START+='done'$'\n'
    START+='while read -r _ _ exported; do'$'\n'
    START+='  case "$exported" in'$'\n'
    if ((${#functions[@]})); then START+="    $(joined "${functions[@]}")) ;;"$'\n'; fi
    START+='    *) export -fn "$exported" ;;'$'\n'
    START+='  esac'$'\n'
    START+='done < <(declare -Fx)'$'\n'
    START+="export PATH=$(quoted "$(toml_strings "$PROCESS_TOML" path)")"
    # `sets` is a one-line table: each `NAME = "value"` in it, in its order
    while IFS= read -r line; do
        [[ -n "$line" ]] && START+=$'\n'"export ${line%%=*}=$(quoted "${line#*=}")"
    done < <(grep -E '^sets = ' "$PROCESS_TOML" | grep -oE '[A-Za-z_][A-Za-z0-9_]* = "[^"]*"' | sed 's/ = "/=/; s/"$//')
}

own_lines() {  # what the `femkit` command sheds of the shell (process.toml's femkit_sheds), as femkit's own_lines
    local name first=1
    while IFS= read -r name; do
        ((first)) || printf '\n'; first=0
        printf 'unset %s 2>/dev/null || true' "$name"
    done < <(toml_strings_or_none "$PROCESS_TOML" femkit_sheds)
}

clean() {  # clean COMMAND...: COMMAND run from the clean start, in a shell of its own
    ( eval "$START"; exec "$@" )
}

# The chosen manager's kind file, the one home of its commands and queries (definitions.md § 6).
kind_file() { printf '%s\n' "$REPO_ROOT/femkit/data/managers/$(basename "$ENV_MGR").toml"; }

kind_query() {  # kind_query KEY: the command of the kind's one-line query KEY, its {exe} filled, into ARGV
    local line rest arg
    ARGV=()
    line="$(grep -E "^$1 = " "$(kind_file)")" || return 1
    rest="${line#*argv = [}"; rest="${rest%%]*}"
    while [[ "$rest" =~ ^[^\"]*\"([^\"]*)\"(.*)$ ]]; do
        arg="${BASH_REMATCH[1]}"; rest="${BASH_REMATCH[2]}"; ARGV+=("${arg//\{exe\}/$ENV_MGR}")
    done
}

kind_keys() {  # kind_keys KEY FIELD: each word of the field FIELD -- a text, or a list of them -- of the one-line query KEY
    local line value
    line="$(grep -E "^$1 = " "$(kind_file)")" || return 0
    if [[ "$line" =~ [{,][[:space:]]*$2\ =\ \[([^]]*)\] ]]; then value="${BASH_REMATCH[1]}"
    elif [[ "$line" =~ [{,][[:space:]]*$2\ =\ (\"[^\"]*\") ]]; then value="${BASH_REMATCH[1]}"
    else return 0; fi
    grep -oE '"[^"]*"' <<< "$value" | tr -d '"'
}

json_strings() {  # json_strings JSON KEY: each text of the list the object's KEY holds, as the manager wrote it
    local one="${1//$'\n'/ }"
    [[ "$one" =~ \"$2\":[[:space:]]*\[([^]]*)\] ]] || return 0
    grep -oE '"[^"]*"' <<< "${BASH_REMATCH[1]}" | tr -d '"'
}

# Where the manager keeps the control environment, by the manager's own name for it (envs.md § 1),
# asked as femkit/envs/manager.py asks it: of the prefixes its `environments` query lists, the one it
# names `femkit` in its `names` answer -- or, where it says no name, a listed one in one of the
# folders where it keeps environments (its `envs_dirs`), under that name there -- never any listed
# path whose last step happens to be the name; none while it names none so. Two are refused, naming
# both.
locate_control() {
    local listed one found=() path key name details="" dirs=() d
    kind_query environments || { say "$(kind_file) has no one-line environments"; exit 1; }
    listed="$(clean "${ARGV[@]}")" || refuse "the manager does not say where its environments are: \`${ARGV[*]}\` failed"
    one="${listed//$'\n'/ }"
    key="$(kind_keys names key | head -n 1)"; name="$(kind_keys names name | head -n 1)"
    if [[ -n "$key" && "$one" =~ \"$key\":[[:space:]]*\{ ]]; then details="yes"; fi
    if [[ -n "$details" ]]; then
        while IFS= read -r path; do
            [[ -n "$path" ]] && found+=("$(normal_path "$path")")
        done < <(grep -oE "\"/[^\"]*\":[[:space:]]*\{[^{}]*\"$name\":[[:space:]]*\"$CONTROL_NAME\"[^{}]*\}" <<< "$one" \
                 | sed -E 's/^"([^"]*)".*/\1/')
    else
        local folders
        kind_query envs_dirs || { say "$(kind_file) has no one-line envs_dirs"; exit 1; }
        folders="$(clean "${ARGV[@]}")" || refuse "the manager does not say where it keeps environments: \`${ARGV[*]}\` failed"
        while IFS= read -r key; do
            while IFS= read -r d; do [[ -n "$d" ]] && dirs+=("$(normal_path "$d")"); done < <(json_strings "$folders" "$key")
        done < <(kind_keys envs_dirs key)
        while IFS= read -r path; do
            [[ -n "$path" ]] || continue
            path="$(normal_path "$path")"
            [[ "${path##*/}" == "$CONTROL_NAME" ]] || continue
            for d in "${dirs[@]+"${dirs[@]}"}"; do
                [[ "${path%/*}" == "$d" ]] && { found+=("$path"); break; }
            done
        done < <(json_strings "$listed" "$(kind_keys environments key | head -n 1)")
    fi
    local unique=() p q
    for p in "${found[@]+"${found[@]}"}"; do
        for q in "${unique[@]+"${unique[@]}"}"; do [[ "$q" == "$p" ]] && continue 2; done
        unique+=("$p")
    done
    if ((${#unique[@]} > 1)); then
        refuse "the manager lists two environments named $CONTROL_NAME: ${unique[*]}; remove one with the manager"
    fi
    CONTROL="${unique[0]-}"
    STAMP="${CONTROL:+$CONTROL/.femkit/control.sha256}"
    LAUNCHER="${CONTROL:+$CONTROL/bin/femkit}"
    launcher_text
}

# The person's own settings that nothing a create carries sets aside, refused before the control
# environment is created (envs.md § 4.4): each the kind's `[settings.refused]` names, set -- to the
# value it refuses, where it names one -- in a place the manager says it read it, `[settings]`'s
# query. A kind that declares no way to read them refuses nothing.
settings_refused() {
    local file argv=() line arg rest sources key when change hit
    file="$(kind_file)"
    line="$(awk '/^\[settings\]$/{s=1;next} /^\[/{s=0} s && /^argv = \[/' "$file")"
    [[ -n "$line" ]] || return 0
    rest="${line#*[}"; rest="${rest%%]*}"
    while [[ "$rest" =~ ^[^\"]*\"([^\"]*)\"(.*)$ ]]; do
        arg="${BASH_REMATCH[1]}"; rest="${BASH_REMATCH[2]}"; argv+=("${arg//\{exe\}/$ENV_MGR}")
    done
    sources="$(clean "${argv[@]}")" || refuse "the manager does not say which of your settings it read: \`${argv[*]}\` failed"
    sources="${sources//$'\n'/ }"
    while IFS= read -r line; do
        [[ "$line" =~ ^([A-Za-z0-9_]+)\ =\ \{\ (when\ =\ ([^,]*),\ )?change\ =\ \"(.*)\"\ \}$ ]] || continue
        key="${BASH_REMATCH[1]}"; when="${BASH_REMATCH[3]}"; change="${BASH_REMATCH[4]}"
        hit="$(setting_source "$sources" "$key" "$when")"
        [[ -n "$hit" ]] && refuse "your setting $key, in $hit: $change"
    done < <(awk '/^\[settings\.refused\]$/{s=1;next} /^\[/{s=0} s' "$file")
    return 0
}

setting_source() {  # setting_source JSON KEY WHEN: the first place whose settings hold KEY -- set to WHEN, where given
    # The manager's answer is one object: each place it read settings from, an object of the settings it
    # read there. Walked a character at a time, strings and nesting kept, since a setting's value may be
    # an object or a list.
    local json="$1" key="$2" when="$3" i c depth=0 in_string=0 escaped=0 text="" last="" source="" at_key=""
    local value_start=-1
    for ((i = 0; i < ${#json}; i++)); do
        c="${json:i:1}"
        if ((in_string)); then
            if ((escaped)); then escaped=0; text+="$c"
            elif [[ "$c" == "\\" ]]; then escaped=1; text+="$c"
            elif [[ "$c" == '"' ]]; then in_string=0; last="$text"
            else text+="$c"; fi
            continue
        fi
        case "$c" in
            '"') in_string=1; text="" ;;
            ':') if ((depth == 1)); then source="$last"; elif ((depth == 2)) && [[ "$last" == "$key" ]]; then
                     at_key=1; value_start=$((i + 1)); fi ;;
            '{'|'[') depth=$((depth + 1)) ;;
            '}'|']'|',')
                if [[ -n "$at_key" ]] && ((depth == 2)); then
                    local value="${json:value_start:i - value_start}"
                    value="${value#"${value%%[![:space:]]*}"}"; value="${value%"${value##*[![:space:]]}"}"
                    if [[ -z "$when" || "$value" == "$when" ]]; then printf '%s\n' "$source"; return 0; fi
                    at_key=""
                fi
                [[ "$c" == ',' ]] || depth=$((depth - 1)) ;;
        esac
    done
}

# The rules femkit/data/states/control.toml declares, in its order, written here in bash since
# the script runs before femkit can; tests/basic/test_entry.py holds the two equal on every way
# the prefix can stand, and the next step a refusal below names to the one that table gives.
# `conda-meta` is the script's own copy of the manager kinds' `environment` (envs.md § 7): it runs
# before Python, and reads no kind file but its one-line command lists.
control_state() {
    if [[ -z "$CONTROL" || ! -e "$CONTROL" ]]; then echo absent
    elif [[ ! -d "$CONTROL/conda-meta" || ! -x "$CONTROL/bin/python" || ! -f "$STAMP" ]]; then echo broken
    elif [[ "$(cat "$STAMP")" != "$(control_digest)" ]]; then echo outdated
    elif ! [[ -f "$LAUNCHER" && "$(cat "$LAUNCHER"; printf x)" == "${LAUNCHER_TEXT}x" ]]; then echo unlinked
    elif ! [[ -L "$LINK" && "$(readlink "$LINK")" == "$LAUNCHER" ]]; then echo unlinked
    else echo current; fi
}

# ------------------------------------------------------------------ the control environment's lock (§ 7.3)

identity() {  # identity PID: "PID START BOOT", the process as femkit/core/process.py identifies one
    # (core.md § 8) -- its start in clock ticks since boot, the boot's ID; nothing when no process
    # of this account runs with that ID
    local stat fields
    [[ -O "/proc/$1" ]] && stat="$(cat "/proc/$1/stat" 2>/dev/null)" || return 0
    read -r -a fields <<< "${stat##*)}"
    [[ "${fields[0]}" == [ZX] ]] || printf '%s %s %s\n' "$1" "${fields[19]}" "$(cat /proc/sys/kernel/random/boot_id)"
}

json_text() {  # $1 as the inside of a JSON string
    local s="${1//\\/\\\\}"
    printf '%s' "${s//\"/\\\"}"
}

HOLDERS=()   # each live holder the lock's file names: "BY (pid N)"
STEPS=()     # the commands that end their holds, as their lines name them
holders() {
    # The lock's file holds one JSON line per holder, as core/locks.py writes it: only so the
    # refusal names the live ones, and what ends their holds; nothing is decided from it. A
    # holder that named its hold anew wrote a line after its first: its last line is what it is.
    local line rest pid start boot by label call steps order=()
    local -A said=() ends=()
    local named='"process": \{"pid": ([0-9]+), "start": ([0-9]+), "boot": "([^"]*)"\}, "by": "((\\.|[^"\\])*)"'
    local step='\{"label": "((\\.|[^"\\])*)", "note": (null|"(\\.|[^"\\])*"), "call": (null|\{)(.*)$'
    HOLDERS=(); STEPS=()
    while IFS= read -r line; do
        if [[ "$line" =~ $named ]]; then
            pid="${BASH_REMATCH[1]}"; start="${BASH_REMATCH[2]}"; boot="${BASH_REMATCH[3]}"; by="${BASH_REMATCH[4]}"
            [[ "$pid" != "$$" && "$(identity "$pid")" == "$pid $start $boot" ]] || continue
            [[ -n "${said[$pid]+x}" ]] || order+=("$pid")
            said[$pid]="${by//\\\"/\"} (pid $pid)"
            rest="${line#*\"next\": \[}"; steps=""
            while [[ "$rest" =~ $step ]]; do   # an action: the shell line it is, or femkit's command
                label="${BASH_REMATCH[1]//\\\"/\"}"; call="${BASH_REMATCH[5]}"; rest="${BASH_REMATCH[6]}"
                if [[ "$call" == null ]]; then steps+="$label"$'\n'; else steps+="femkit $label"$'\n'; fi
            done
            ends[$pid]="$steps"
        elif [[ -n "${line// /}" ]]; then
            HOLDERS+=("$line")   # a line it cannot read: named as it is
        fi
    done < "$CONTROL_LOCK"
    for pid in "${order[@]+"${order[@]}"}"; do
        HOLDERS+=("${said[$pid]}")
        while IFS= read -r label; do
            if [[ -n "$label" ]]; then STEPS+=("$label"); fi
        done <<< "${ends[$pid]}"
    done
}

LOCKED=""   # how this script holds the control environment's lock: alone, shared, or not yet
hold_control() {  # hold_control alone|shared: the lock, on fd 9; refused, never waited for, while
    # another process holds it so. Python, which the script runs, inherits the hold.
    local how=-s
    [[ "$1" == alone ]] && how=-x
    if [[ -z "$LOCKED" ]]; then
        mkdir -p "$(dirname "$CONTROL_LOCK")"
        exec 9>>"$CONTROL_LOCK"   # opened to add a line, as a shared holder's is
    fi
    if ! flock "$how" -n 9; then
        holders
        local who="" holder
        for holder in "${HOLDERS[@]+"${HOLDERS[@]}"}"; do who+="${who:+; }$holder"; done
        refuse "the control environment is in use by ${who:-another process}; nothing was changed" \
            "${STEPS[@]+"${STEPS[@]}"}" "$SELF $ARGS   # once that has ended"
    fi
    if [[ "$1" == alone ]]; then : > "$CONTROL_LOCK"; fi   # a holder alone rewrites the file
    if [[ "$1" == alone || -z "$LOCKED" ]]; then           # a shared one adds its line
        printf '{"process": {"pid": %s, "start": %s, "boot": "%s"}, "by": "%s", "next": []}\n' \
            $(identity $$) "$(json_text "$SELF $ARGS")" >&9
    fi
    LOCKED="$1"
}

ARGV=()
kind_argv() {  # kind_argv KEY: the chosen manager's kind-file command KEY, its {exe} and {name} filled
    # The kind file is the one home of the manager's commands (definitions.md § 6); each is a
    # one-line list of plain strings, read here without a TOML parser.
    local file line rest arg
    file="$(kind_file)"
    line="$(grep -E "^$1 = \[" "$file")" || { say "$file has no one-line $1"; exit 1; }
    rest="${line#*[}"; rest="${rest%%]*}"; ARGV=()
    while [[ "$rest" =~ ^[^\"]*\"([^\"]*)\"(.*)$ ]]; do
        arg="${BASH_REMATCH[1]}"; rest="${BASH_REMATCH[2]}"
        arg="${arg//\{exe\}/$ENV_MGR}"; ARGV+=("${arg//\{name\}/$CONTROL_NAME}")
    done
}

create_control() {
    settings_refused   # before any create: what nothing it carries sets aside (envs.md § 4.4)
    say "creating the control environment $CONTROL_NAME, where $(basename "$ENV_MGR") keeps environments, from femkit/data/control.txt"
    # The kind's `create`: the declared channels only (envs.md § 4.4), then control.txt.
    # channels.txt holds one bare name a line, so each line is a channel as it stands.
    local channels=() cmd=() channel arg
    mapfile -t channels < "$CHANNELS_TXT"
    kind_argv create; cmd=("${ARGV[@]}")
    for channel in "${channels[@]}"; do
        kind_argv channel
        for arg in "${ARGV[@]}"; do cmd+=("${arg//\{channel\}/$channel}"); done
    done
    clean "${cmd[@]}" --file "$CONTROL_TXT" || { say "creating the control environment failed"; exit 1; }
    locate_control
    [[ -n "$CONTROL" ]] || { say "the manager made $CONTROL_NAME and does not list it"; exit 1; }
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
    say "THE CONTROL ENVIRONMENT WAS REMOVED AND THE REBUILD FAILED; there is no $CONTROL_NAME now."
    echo "next -- recreate it:" >&2
    echo "    $AGAIN" >&2
}

recreate_control() {
    settings_refused   # before the removal: what nothing the create carries sets aside (envs.md § 4.4)
    AGAIN="$SELF bootstrap"
    if ((CLEAN)); then AGAIN+=" --clean"; fi
    say "rebuilding the control environment at $CONTROL; if the create after the removal fails, run:"
    echo "    $AGAIN" >&2
    if ((! AUTO_YES)); then
        [[ -t 0 ]] || refuse "no terminal to confirm the rebuild on" "$SELF bootstrap $([[ $CLEAN == 1 ]] && echo '--clean ')--yes"
        local answer=""
        read -r -p "[femkit] remove and rebuild the control environment at $CONTROL? [y/N] " answer || refuse "no answer"
        case "$answer" in y|Y|yes) ;; *) refuse "declined; nothing was changed" ;; esac
    fi
    trap rebuild_failed EXIT
    kind_argv remove; local rm=("${ARGV[@]}") channel arg channels=()
    # Where the kind's removal names the declared channels, as its create does (envs.md § 4.4).
    if grep -qE '^channels_named = \[.*"remove"' "$(kind_file)"; then
        mapfile -t channels < "$CHANNELS_TXT"
        for channel in "${channels[@]}"; do
            kind_argv channel
            for arg in "${ARGV[@]}"; do rm+=("${arg//\{channel\}/$channel}"); done
        done
    fi
    clean "${rm[@]}" || { say "removing the control environment failed"; exit 1; }
    CONTROL_REMOVED=1
    create_control
    CONTROL_REMOVED=0
    trap - EXIT
}

# ------------------------------------------------------------------ the `femkit` command (§ 7)

shell_word() {  # $1 as one single-quoted shell word, each ' in it written '\'' -- as femkit/envs/control.py quotes it
    local closed="'\\''"
    printf "'%s'" "${1//\'/$closed}"
}

# The `femkit` command: femkit/data/launcher.sh, its one source, with {checkout} and then {python}
# each replaced by a shell word, and {start} by the clean start's lines (START) -- as doctor fills it
# to see whether the command there names this checkout (femkit/envs/control.py). Held whole, its last
# newline kept, so control_state compares the file with it as doctor does; made once the control
# environment's prefix is known.
LAUNCHER_TEXT=""
launcher_text() {
    LAUNCHER_TEXT=""
    [[ -n "$CONTROL" && -s "$LAUNCHER_TXT" ]] || return 0
    IFS= read -r -d '' LAUNCHER_TEXT < "$LAUNCHER_TXT" || true
    LAUNCHER_TEXT="${LAUNCHER_TEXT//\{checkout\}/$(shell_word "$REPO_ROOT")}"
    LAUNCHER_TEXT="${LAUNCHER_TEXT//\{python\}/$(shell_word "$CONTROL/bin/python")}"
    LAUNCHER_TEXT="${LAUNCHER_TEXT//\{start\}/$(own_lines)}"
}

# Written whole, then moved into place, in the control prefix and nowhere else, and linked from
# <bin>/femkit -- a link of this script's alone: a file of the person's there is refused, never
# overwritten; each said when it changed (envs.md § 7.3).
write_launcher() {
    [[ -n "$LAUNCHER_TEXT" ]] || { say "$LAUNCHER_TXT is not there; the femkit command is not written"; exit 1; }
    if ! [[ -f "$LAUNCHER" && "$(cat "$LAUNCHER"; printf x)" == "${LAUNCHER_TEXT}x" ]]; then
        printf '%s' "$LAUNCHER_TEXT" > "$LAUNCHER.tmp"
        chmod 755 "$LAUNCHER.tmp"
        mv -f "$LAUNCHER.tmp" "$LAUNCHER"
        say "femkit command: $LAUNCHER   # runs femkit from $REPO_ROOT"
    fi
    [[ -L "$LINK" && "$(readlink "$LINK")" == "$LAUNCHER" ]] && return 0
    if [[ -e "$LINK" && ! -L "$LINK" ]]; then
        refuse "$LINK is a file of yours, not the link this script makes; nothing was changed there" \
            "mv $(shell_word "$LINK") $(shell_word "$LINK.yours")   # then run this again"
    fi
    mkdir -p "$BIN_DIR"
    ln -s "$LAUNCHER" "$LINK.tmp.$$"
    mv -fT "$LINK.tmp.$$" "$LINK"
    say "femkit is on the path of every shell that has $BIN_DIR on it: $LINK -> $LAUNCHER"
}

on_path() {  # whether a new shell finds `femkit`: <bin> on this shell's PATH; else the one line that puts it there
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) say "$BIN_DIR is not on this shell's PATH, so a new shell does not find femkit; add this line to your ~/.bashrc:"
           printf '    export PATH=%s:"$PATH"\n' "$(quoted "$BIN_DIR")" >&2
           say "or enter the control environment the way you enter any of $(basename "$ENV_MGR")'s: $(basename "$ENV_MGR") activate $CONTROL_NAME" ;;
    esac
}

# ------------------------------------------------------------------ forwarding

# The control environment's own python, never `<manager> run`: `run` would stand between
# Python and the terminal it asks on, and femkit needs no activation to run -- it is pure
# Python, from this checkout (envs.md § 7.3). Run as the `femkit` command runs it: isolated, the
# shell kept but what process.toml's `femkit_sheds` names, so femkit sees the machine it probes as
# you do and every process it starts begins clean; the manager this script found handed to it by
# its full path.
dispatch() {
    ( eval "$(own_lines)"; export FEMKIT_ENV_MANAGER="$ENV_MGR"
      exec "$CONTROL/bin/python" -I "$REPO_ROOT/femkit/__main__.py" env "$@" )
}

# ------------------------------------------------------------------ main (§ 7.3)

if [[ $# -eq 0 ]]; then
    printf 'No verb given. First-time install on a fresh machine?\n    %s bootstrap\n\n' "$SELF" >&2
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
ARGS="$*"   # the command as typed, which the lock's file names as its holder

usable() {  # femkit can run from the control environment: only its `femkit` command or its link may be missing
    [[ "$1" == current || "$1" == unlinked ]]
}

case "$1" in
    -h|--help|help)
        usage
        exit 0
        ;;
    bootstrap)
        require_conda "$@"
        CONTROL_NAME="$(toml_strings "$NAMING_TOML" control)"
        start_lines
        hold_control shared   # what the state is observed from stays as it is while this runs
        locate_control
        state="$(control_state)"
        say "control environment $CONTROL_NAME: $state   # ${CONTROL:-the manager lists none}"
        if ((WANT_HELP)) && ! usable "$state"; then
            usage; exit 0   # femkit's own help needs the control environment; this one does not
        fi
        if ((NO_ACTION)) && ! usable "$state"; then
            refuse "--dry-run needs the control environment, which is $state; making it is the install you did not ask for" \
                "$SELF bootstrap"
        fi
        ((NO_ACTION)) && CLEAN=0   # look at a rebuild, never do one
        # A broken control environment is rebuilt like an outdated one, never by --clean,
        # which also rebuilds every engine environment. Either holds the lock alone: refused
        # while femkit runs from the environment -- a web server's supervisor, another script.
        case "$state:$CLEAN" in
            absent:*)                                   hold_control alone; create_control ;;
            outdated:*|broken:*|current:1|unlinked:1)   hold_control alone; recreate_control ;;
            current:0|unlinked:0)                       ;;
        esac
        ((NO_ACTION)) || { write_launcher; on_path; }   # a look writes nothing
        hold_control shared   # femkit runs from it now: used, never changed
        dispatch "$@"
        ;;
    *)
        require_conda "$@"
        CONTROL_NAME="$(toml_strings "$NAMING_TOML" control)"
        start_lines
        hold_control shared
        locate_control
        state="$(control_state)"
        if usable "$state"; then
            ((NO_ACTION)) || write_launcher
            dispatch "$@"
        else
            refuse "the control environment $CONTROL_NAME is $state${CONTROL:+: $CONTROL}" "$SELF bootstrap"
        fi
        ;;
esac
