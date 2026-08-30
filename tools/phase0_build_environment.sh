#!/usr/bin/env bash
# Shared native-collector build policy for Phase 0 evidence. This file is
# sourced by the runners; it is not a standalone command.

PHASE0_BUILD_REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

phase0_reject_inherited_build_overrides() {
    local name
    local -a rejected=()
    while IFS='=' read -r name _; do
        case "$name" in
            RUSTFLAGS|RUSTDOCFLAGS|RUSTC|RUSTC_BOOTSTRAP|RUSTC_WRAPPER|RUSTC_WORKSPACE_WRAPPER|RUSTUP_TOOLCHAIN|\
            CARGO_ENCODED_RUSTFLAGS|CARGO_ENCODED_RUSTDOCFLAGS|CARGO_INCREMENTAL|\
            CARGO_BUILD_*|CARGO_PROFILE_*|CARGO_TARGET_*_RUSTFLAGS|\
            CARGO_TARGET_*_LINKER|CARGO_TARGET_*_RUNNER|\
            CC|CXX|AR|CPPFLAGS|CFLAGS|CXXFLAGS|ARFLAGS|LDFLAGS|\
            CC_*|CXX_*|AR_*|CPPFLAGS_*|CFLAGS_*|CXXFLAGS_*|ARFLAGS_*|LDFLAGS_*|\
            *_CC|*_CXX|*_AR|*_CPPFLAGS|*_CFLAGS|*_CXXFLAGS|*_ARFLAGS|*_LDFLAGS)
                rejected+=("$name")
                ;;
        esac
    done < <(env)
    if (( ${#rejected[@]} > 0 )); then
        printf '%s\n' \
            "Phase 0 evidence runners reject inherited Rust/Cargo build overrides: ${rejected[*]}" >&2
        printf '%s\n' \
            "use the pinned toolchain and the committed Phase 0 native release recipe" >&2
        return 2
    fi
}

phase0_reject_hidden_cargo_configuration() {
    local argument directory parent cargo_home candidate
    for argument in "$@"; do
        if [[ "$argument" == "--config" || "$argument" == --config=* ]]; then
            printf '%s\n' \
                "Phase 0 native collector builds reject Cargo --config overrides" >&2
            return 2
        fi
    done

    # Cargo merges configuration from the invocation directory and every
    # ancestor. Only the repository-owned, execution-identity-bound config is
    # admitted; a user/CI/ancestor config could otherwise inject rustflags,
    # wrappers, linkers, targets, or profile settings behind the recorded
    # release recipe.
    directory="$(pwd -P)"
    while true; do
        for candidate in "$directory/.cargo/config" "$directory/.cargo/config.toml"; do
            if [[ -e "$candidate" || -L "$candidate" ]]; then
                if [[ "$candidate" != "$PHASE0_BUILD_REPOSITORY_ROOT/.cargo/config.toml" ]]; then
                    printf '%s\n' \
                        "Phase 0 native collector builds reject hidden Cargo configuration: $candidate" >&2
                    return 2
                fi
            fi
        done
        [[ "$directory" == "/" ]] && break
        parent="${directory%/*}"
        directory="${parent:-/}"
    done

    if [[ -n "${CARGO_HOME:-}" ]]; then
        cargo_home="$CARGO_HOME"
    elif [[ -n "${HOME:-}" ]]; then
        cargo_home="$HOME/.cargo"
    else
        printf '%s\n' "Phase 0 native collector builds cannot resolve CARGO_HOME" >&2
        return 2
    fi
    if [[ "$cargo_home" != /* ]]; then
        cargo_home="$(pwd -P)/$cargo_home"
    fi
    for candidate in "$cargo_home/config" "$cargo_home/config.toml"; do
        if [[ -e "$candidate" || -L "$candidate" ]]; then
            if [[ "$candidate" != "$PHASE0_BUILD_REPOSITORY_ROOT/.cargo/config.toml" ]]; then
                printf '%s\n' \
                    "Phase 0 native collector builds reject hidden Cargo configuration: $candidate" >&2
                return 2
            fi
        fi
    done
}

phase0_release_cargo() {
    phase0_reject_hidden_cargo_configuration "$@" || return
    env \
        CARGO_INCREMENTAL=0 \
        CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16 \
        CARGO_PROFILE_RELEASE_DEBUG=1 \
        CARGO_PROFILE_RELEASE_DEBUG_ASSERTIONS=false \
        CARGO_PROFILE_RELEASE_INCREMENTAL=false \
        CARGO_PROFILE_RELEASE_LTO=false \
        CARGO_PROFILE_RELEASE_OPT_LEVEL=3 \
        CARGO_PROFILE_RELEASE_OVERFLOW_CHECKS=false \
        CARGO_PROFILE_RELEASE_PANIC=unwind \
        CARGO_PROFILE_RELEASE_STRIP=none \
        cargo "$@"
}
