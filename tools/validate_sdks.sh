#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
OUTPUT="${TARGET_ROOT}/contracts/sdk"
ZIG_LOCAL_CACHE="${TARGET_ROOT}/zig-local-cache"
C_TARGET="x86_64-linux-gnu"

cd "${ROOT}"
rm -rf "${OUTPUT}"
mkdir -p "${OUTPUT}/c" "${OUTPUT}/dotnet" "${OUTPUT}/java" "${ZIG_LOCAL_CACHE}"

npm ci --prefix sdk/typescript-client --ignore-scripts
python3 tools/check_tool_versions.py

(
    cd sdk/go
    go test ./...
)

npm --prefix sdk/typescript-client run build -- --noEmit

mapfile -t java_sources < <(find sdk/java-client/src/main/java -type f -name '*.java' | sort)
if (( ${#java_sources[@]} == 0 )); then
    echo "no Java SDK sources found" >&2
    exit 1
fi
javac --release 21 -d "${OUTPUT}/java" "${java_sources[@]}"

dotnet build sdk/dotnet/Latent.Sdk/Latent.Sdk.csproj \
    --configuration Release \
    --nologo \
    --output "${OUTPUT}/dotnet/bin" \
    -p:BaseIntermediateOutputPath="${OUTPUT}/dotnet/obj/" \
    -p:ContinuousIntegrationBuild=true

cat > "${OUTPUT}/c/header-smoke.c" <<'EOF_C'
#include <latent/latent.h>

int main(void) {
    return 0;
}
EOF_C
ZIG_LOCAL_CACHE_DIR="${ZIG_LOCAL_CACHE}" \
    zig cc -target "${C_TARGET}" -std=c11 -Wall -Wextra -Werror -pedantic \
    -I sdk/c/include "${OUTPUT}/c/header-smoke.c" -o "${OUTPUT}/c/header-smoke"
