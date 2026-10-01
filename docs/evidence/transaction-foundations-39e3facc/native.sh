#!/usr/bin/env bash
set -euo pipefail
umask 077
mkdir -p /work /fixtures/http409-r1
tar -xf /reports/source.tar -C /work
cd /work
export TMPDIR=/fixtures/http409-r1
printf 'source=%s\n' "$LSF_SOURCE"
rustc --version --verbose
cargo --version
cargo clippy --version
uname -srmo
printf 'fixtureFilesystem=%s\n' "$(stat -f -c %t /fixtures)"
test "$(rustc --version | cut -d' ' -f2)" = 1.97.1
test "$(stat -f -c %t /fixtures)" = ef53
run() {
    local name="$1"
    shift
    printf 'begin=%s\n' "$name"
    if "$@" >"/reports/$name.log" 2>&1; then
        printf 'pass=%s\n' "$name"
        tail -n 3 "/reports/$name.log"
    else
        local code=$?
        printf 'fail=%s exit=%s\n' "$name" "$code"
        tail -n 70 "/reports/$name.log"
        return "$code"
    fi
}
packages=(-p latent-state -p latent-protected-files -p latent-commit -p latent-effects -p latent-http -p latent-node -p latent-ingress -p latent-executor -p latent-wasmtime)
run build cargo test --config .cargo/managed-guest.toml --offline --locked "${packages[@]}" --all-features --lib --no-run --message-format json
for package in latent-state latent-protected-files latent-commit latent-effects latent-http latent-node latent-ingress latent-executor latent-wasmtime; do
    run "$package-list" cargo test --config .cargo/managed-guest.toml --offline --locked -p "$package" --all-features --lib -- --list --format terse
done
run ownership-tests cargo test --config .cargo/managed-guest.toml --offline --locked -p latent-state -p latent-protected-files -p latent-commit -p latent-effects -p latent-http -p latent-node -p latent-ingress -p latent-executor --all-features --lib -- --test-threads=2
run canonical-tests cargo test --config .cargo/managed-guest.toml --offline --locked -p latent-wasmtime --all-features --lib values::tests::canonical:: -- --test-threads=2
run clippy cargo clippy --config .cargo/managed-guest.toml --offline --locked "${packages[@]}" --all-targets --all-features --no-deps -- -D warnings
printf 'qualification=passed\n'
