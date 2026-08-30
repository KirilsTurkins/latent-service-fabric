#!/usr/bin/env bash
# Shared native-collector build policy for Phase 0 evidence. This file is
# sourced by the runners; it is not a standalone command.

PHASE0_BUILD_REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PHASE0_CANONICAL_SOURCE_ROOT="/phase0/source"
PHASE0_CANONICAL_TARGET_ROOT="/phase0/target"
PHASE0_CANONICAL_CARGO_HOME="/phase0/cargo-home"
PHASE0_NATIVE_RELEASE_PATH_REMAP="source-target-cargo-home-v1"
PHASE0_NATIVE_RELEASE_LINKER_BUILD_ID="sha1"
PHASE0_NATIVE_RELEASE_PROMOTED_LOCALS="source-filename"

phase0_reject_inherited_build_overrides() {
    local name
    local -a rejected=()
    while IFS='=' read -r name _; do
        case "$name" in
            RUSTFLAGS|RUSTDOCFLAGS|RUSTC|RUSTC_BOOTSTRAP|RUSTC_WRAPPER|RUSTC_WORKSPACE_WRAPPER|RUSTUP_TOOLCHAIN|\
            CARGO_ENCODED_RUSTFLAGS|CARGO_ENCODED_RUSTDOCFLAGS|CARGO_INCREMENTAL|\
            CARGO_BUILD_*|CARGO_PROFILE_*|CARGO_TARGET_*_RUSTFLAGS|\
            CARGO_TARGET_*_LINKER|CARGO_TARGET_*_RUNNER|\
            PHASE0_NATIVE_RELEASE_PATH_REMAP|PHASE0_NATIVE_RELEASE_LINKER_BUILD_ID|\
            PHASE0_NATIVE_RELEASE_PROMOTED_LOCALS|\
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

phase0_release_rustflags() {
    local cargo_home target_root
    local index insert_index
    local -a physical_roots canonical_roots
    target_root="${CARGO_TARGET_DIR:-$PHASE0_BUILD_REPOSITORY_ROOT/target}"
    if ! command -v realpath >/dev/null 2>&1; then
        printf '%s\n' \
            "Phase 0 native collector builds require realpath to canonicalize the target root" >&2
        return 2
    fi
    if ! target_root="$(realpath -m -- "$target_root")"; then
        printf '%s\n' \
            "Phase 0 native collector build target cannot be canonicalized: $target_root" >&2
        return 2
    fi
    if [[ -n "${CARGO_HOME:-}" ]]; then
        cargo_home="$CARGO_HOME"
    elif [[ -n "${HOME:-}" ]]; then
        cargo_home="$HOME/.cargo"
    else
        printf '%s\n' "Phase 0 native collector builds cannot resolve CARGO_HOME" >&2
        return 2
    fi
    if ! cargo_home="$(realpath -m -- "$cargo_home")"; then
        printf '%s\n' \
            "Phase 0 native collector Cargo home cannot be canonicalized: $cargo_home" >&2
        return 2
    fi

    # Cargo build scripts generate Rust sources under OUT_DIR, and dependency
    # debug information retains registry source paths under CARGO_HOME. With
    # release debug information retained, those absolute paths otherwise make
    # two clean builds of the same tree produce different ELF bytes. Map every
    # root to a stable virtual path in every rustc path scope.
    case "$target_root$cargo_home$PHASE0_BUILD_REPOSITORY_ROOT" in
        *$'\n'*|*$'\r'*|*$'\x1f'*|*'='*)
            printf '%s\n' \
                "Phase 0 native collector paths cannot be encoded safely for rustc path remapping" >&2
            return 2
            ;;
    esac
    if [[ "$target_root" == "$cargo_home" \
        || "$target_root" == "$PHASE0_BUILD_REPOSITORY_ROOT" \
        || "$cargo_home" == "$PHASE0_BUILD_REPOSITORY_ROOT" ]]; then
        printf '%s\n' \
            "Phase 0 native collector source, target, and Cargo roots must be distinct" >&2
        return 2
    fi

    physical_roots=("$PHASE0_BUILD_REPOSITORY_ROOT" "$cargo_home" "$target_root")
    canonical_roots=("$PHASE0_CANONICAL_SOURCE_ROOT" "$PHASE0_CANONICAL_CARGO_HOME" "$PHASE0_CANONICAL_TARGET_ROOT")

    # rustc applies the last matching prefix. Sort broad/short prefixes before
    # narrow/long ones so a repository-owned target or Cargo home retains its
    # more-specific canonical identity.
    for (( index = 1; index < ${#physical_roots[@]}; index++ )); do
        insert_index="$index"
        while (( insert_index > 0 \
            && ${#physical_roots[insert_index - 1]} > ${#physical_roots[insert_index]} )); do
            local physical_swap="${physical_roots[insert_index - 1]}"
            local canonical_swap="${canonical_roots[insert_index - 1]}"
            physical_roots[insert_index - 1]="${physical_roots[insert_index]}"
            canonical_roots[insert_index - 1]="${canonical_roots[insert_index]}"
            physical_roots[insert_index]="$physical_swap"
            canonical_roots[insert_index]="$canonical_swap"
            insert_index=$((insert_index - 1))
        done
    done

    for index in "${!physical_roots[@]}"; do
        (( index > 0 )) && printf '\x1f'
        printf '%s\x1f%s' \
            "--remap-path-prefix" \
            "${physical_roots[index]}=${canonical_roots[index]}"
    done
    printf '\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s' \
        "--remap-path-scope" "all" \
        "-C" "llvm-args=--use-source-filename-for-promoted-locals" \
        "-C" "link-arg=-Wl,--build-id=sha1"
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
    local encoded_rustflags
    phase0_reject_inherited_build_overrides || return
    phase0_reject_hidden_cargo_configuration "$@" || return
    encoded_rustflags="$(phase0_release_rustflags)" || return
    env \
        CARGO_ENCODED_RUSTFLAGS="$encoded_rustflags" \
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
        PHASE0_NATIVE_RELEASE_PATH_REMAP="$PHASE0_NATIVE_RELEASE_PATH_REMAP" \
        PHASE0_NATIVE_RELEASE_LINKER_BUILD_ID="$PHASE0_NATIVE_RELEASE_LINKER_BUILD_ID" \
        PHASE0_NATIVE_RELEASE_PROMOTED_LOCALS="$PHASE0_NATIVE_RELEASE_PROMOTED_LOCALS" \
        cargo "$@"
}
