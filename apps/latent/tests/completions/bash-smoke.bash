set -eu
# Only Bash builtins are available after launch. No startup files, external
# completion helpers or callbacks into the product participate in this proof.
PATH=''
latent() { printf 'unexpected latent callback\n' >&2; exit 99; }
source "$1"
complete -p latent >/dev/null

assert_completion() {
    local expected="$1" candidate
    shift
    COMP_WORDS=("$@")
    COMP_CWORD=$((${#COMP_WORDS[@]} - 1))
    # compopt can only change Readline options inside an interactive completion.
    # The generated function still computes its real candidates in this shell.
    if ! _latent latent "${COMP_WORDS[COMP_CWORD]}" "${COMP_WORDS[COMP_CWORD-1]}" 2>/dev/null; then
        printf 'completion function failed\n' >&2
        exit 1
    fi
    for candidate in "${COMPREPLY[@]}"; do
        if [[ "$candidate" == "$expected" ]]; then return 0; fi
    done
    printf 'missing completion %s for:' "$expected" >&2
    printf ' [%s]' "${COMP_WORDS[@]}" >&2
    printf '\n' >&2
    exit 1
}

assert_completion completions latent comp
assert_completion build latent package bu
assert_completion build latent --quiet package bu
assert_completion --connect-timeout-ms latent package build --connect
assert_completion phase1 latent invoke --budget-profile ph
assert_completion phase3 latent invoke --budget-profile ph
assert_completion provider-binding latent policy get --kind provider
assert_completion rolled-back latent rollout list --state rolled
assert_completion powershell latent completions pow
assert_completion json latent package build --output j
printf '{}\n' >'sample capsule.json'
assert_completion 'sample capsule.json' latent --config sample
printf 'bash completion smoke passed\n'
