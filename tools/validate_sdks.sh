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
    cd sdk/go
    go test -timeout 30s ./...
)

npm --prefix sdk/typescript-client run build -- --noEmit
npm --prefix sdk/typescript-client run test:semantic

mapfile -t java_sources < <(find sdk/java-client/src/main/java sdk/java-client/src/test/java -type f -name '*.java' | sort)
if (( ${#java_sources[@]} == 0 )); then
    echo "no Java SDK sources found" >&2
    exit 1
fi
javac --release 21 -d "${OUTPUT}/java" "${java_sources[@]}"
java -cp "${OUTPUT}/java" dev.latent.sdk.InvocationIdentityTest

dotnet build sdk/dotnet/Latent.Sdk/Latent.Sdk.csproj \
    --configuration Release \
    --nologo \
    --output "${OUTPUT}/dotnet/bin" \
    -p:BaseIntermediateOutputPath="${OUTPUT}/dotnet/obj/" \
    -p:ContinuousIntegrationBuild=true

dotnet build sdk/dotnet/Latent.Sdk.SemanticTests/Latent.Sdk.SemanticTests.csproj \
    --configuration Release \
    --nologo \
    --artifacts-path "${OUTPUT}/dotnet-semantic" \
    -p:ContinuousIntegrationBuild=true
dotnet "${OUTPUT}/dotnet-semantic/bin/Latent.Sdk.SemanticTests/release/Latent.Sdk.SemanticTests.dll"

cat > "${OUTPUT}/c/header-smoke.c" <<'EOF_C'
#include <latent/latent.h>

int main(void) {
    latent_invocation_receipt receipt = {0};
    latent_declared_invocation_error declared = {
        .receipt = receipt,
    };
    latent_invocation_outcome outcome = {
        .kind = LATENT_INVOCATION_DECLARED_ERROR,
        .declared_error = &declared,
    };
    latent_activation_success_summary success = {0};
    latent_retained_invocation_outcome retained = {
        .kind = LATENT_RETAINED_INVOCATION_SUCCEEDED,
        .success = &success,
    };
    latent_activation_status status = {
        .has_terminal_outcome = true,
        .terminal_outcome = retained,
    };
    return outcome.declared_error == 0 || !status.has_terminal_outcome;
}
EOF_C
sed -i 's/^          //' "${OUTPUT}/c/header-smoke.c"
ZIG_LOCAL_CACHE_DIR="${ZIG_LOCAL_CACHE}" \
    zig cc -target "${C_TARGET}" -std=c11 -Wall -Wextra -Werror -pedantic \
    -I sdk/c/include "${OUTPUT}/c/header-smoke.c" -o "${OUTPUT}/c/header-smoke"
"${OUTPUT}/c/header-smoke"

ZIG_LOCAL_CACHE_DIR="${ZIG_LOCAL_CACHE}" \
    zig cc -target "${C_TARGET}" -std=c11 -Wall -Wextra -Werror -pedantic \
    -I sdk/c/include sdk/c/tests/invocation_identity.c -o "${OUTPUT}/c/invocation-identity"
"${OUTPUT}/c/invocation-identity"
