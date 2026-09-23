#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
OUTPUT="${TARGET_ROOT}/contracts/sdk"
ZIG_LOCAL_CACHE="${TARGET_ROOT}/zig-local-cache"
C_TARGET="x86_64-linux-gnu"

cd "${ROOT}"
rm -rf "${OUTPUT}"
rm -rf "${ROOT}/sdk/typescript-client/dist/semantic-tests"
mkdir -p "${OUTPUT}/c" "${OUTPUT}/dotnet" "${OUTPUT}/java" "${ZIG_LOCAL_CACHE}"

npm ci --prefix sdk/typescript-client --ignore-scripts
python3 tools/check_tool_versions.py

(
    export GOTOOLCHAIN=local GOWORK=off GOENV=off GOFLAGS=-mod=readonly
    export GOPROXY=https://proxy.golang.org GOSUMDB=sum.golang.org
    export GOPRIVATE= GONOPROXY= GONOSUMDB=
    python3 -m unittest discover -s sdk/go -p 'test_*.py'
    python3 sdk/go/dependencies.py --check
    python3 sdk/go/generate.py
    python3 sdk/go/generate.py --check
    cd sdk/go
    go test -timeout 30s ./...
    go test -race -timeout 60s ./transport -run 'TestCancellationQueueAndReservedRecovery|TestConcurrentCloseReapsPendingAndQueuedCalls|TestFailedStartupAndAdoptedConnectionOwnership'
)

npm --prefix sdk/typescript-client run build -- --noEmit
npm --prefix sdk/typescript-client run test:semantic
npm --prefix sdk/typescript-client run test:transport

mapfile -t java_sources < <(find sdk/java-client/src/main/java sdk/java-client/src/test/java -type f -name '*.java' | sort)
if (( ${#java_sources[@]} == 0 )); then
    echo "no Java SDK sources found" >&2
    exit 1
fi
javac --release 25 -d "${OUTPUT}/java" "${java_sources[@]}"
python3 sdk/java-client/tools/java_toolchain.py classes "${OUTPUT}/java"
java -cp "${OUTPUT}/java" dev.latent.sdk.InvocationIdentityTest
python3 sdk/java-client/tools/build.py test
python3 sdk/java-client/tools/build.py build

python3 -m unittest discover -s sdk/dotnet -p 'test_validate.py'
python3 sdk/dotnet/validate.py --check

cat > "${OUTPUT}/c/header-smoke.c" <<'EOF_C'
#include <latent/profile.h>

int main(void) {
    latent_profile_invoke_response outcome = {
        .has_declared_error = true,
        .declared_error = {.code = {"example", 7}},
    };
    latent_profile_activation_status status = {.has_succeeded = true};
    return !outcome.has_declared_error || !status.has_succeeded;
}
EOF_C
sed -i 's/^          //' "${OUTPUT}/c/header-smoke.c"
ZIG_LOCAL_CACHE_DIR="${ZIG_LOCAL_CACHE}" \
    zig cc -target "${C_TARGET}" -std=c11 -Wall -Wextra -Werror -pedantic \
    -I sdk/c/include "${OUTPUT}/c/header-smoke.c" -o "${OUTPUT}/c/header-smoke"
"${OUTPUT}/c/header-smoke"

ZIG_LOCAL_CACHE_DIR="${ZIG_LOCAL_CACHE}" \
    zig cc -target "${C_TARGET}" -std=c11 -Wall -Wextra -Werror -pedantic \
    -I sdk/c/include sdk/c/tests/profile_semantics.c -o "${OUTPUT}/c/profile-semantics"
"${OUTPUT}/c/profile-semantics"

python3 sdk/c/tools/validate.py --build-dir "${TARGET_ROOT}/c-sdk"
python3 sdk/c/tools/validate.py --build-dir "${TARGET_ROOT}/c-sdk-asan" --sanitize
