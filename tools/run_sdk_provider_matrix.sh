#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
TARGET_ROOT="$(realpath -m "${TARGET_ROOT}")"
NATIVE="${TARGET_ROOT}/sdk-native"
OUTPUT="${TARGET_ROOT}/phase3-sdk"
cd "${ROOT}"

case "${1:-}" in
    build)
        test "$#" -eq 1
        mkdir -p "${NATIVE}/go" "${NATIVE}/dotnet"
        cargo build -p latent-sdk --example provider_workflow --locked
        npm ci --prefix sdk/typescript-client --ignore-scripts
        npm --prefix sdk/typescript-client run build
        python3 tools/check_tool_versions.py
        (
            export GOTOOLCHAIN=local GOWORK=off GOENV=off GOFLAGS=-mod=readonly
            export GOPROXY=https://proxy.golang.org GOSUMDB=sum.golang.org
            export GOPRIVATE= GONOPROXY= GONOSUMDB=
            python3 sdk/go/dependencies.py --check
            python3 sdk/go/generate.py
            python3 sdk/go/generate.py --check
            cd sdk/go
            go build -trimpath -o "${NATIVE}/go/provider-workflow" ./cmd/provider-workflow
        )
        python3 sdk/c/tools/validate.py --build-dir "${NATIVE}/c"
        python3 sdk/java-client/tools/build.py build
        (
            cd sdk/dotnet
            dotnet restore Latent.Sdk.ProviderWorkflow/Latent.Sdk.ProviderWorkflow.csproj \
                --locked-mode --configfile nuget.transport.config \
                -p:ArtifactsPath="${NATIVE}/dotnet" \
                -p:ImportDirectoryBuildProps=false -p:ImportDirectoryBuildTargets=false \
                -p:ImportDirectoryPackagesProps=false -p:UseSharedCompilation=false -nodeReuse:false
            dotnet build Latent.Sdk.ProviderWorkflow/Latent.Sdk.ProviderWorkflow.csproj \
                --no-restore --disable-build-servers --artifacts-path "${NATIVE}/dotnet" \
                -p:ImportDirectoryBuildProps=false -p:ImportDirectoryBuildTargets=false \
                -p:ImportDirectoryPackagesProps=false -p:UseSharedCompilation=false -nodeReuse:false
        )
        ;;
    run)
        test "$#" -eq 4
        CLI="$(realpath -e "$2")"
        NODE="$(realpath -e "$3")"
        FIXTURE="$(realpath -e "$4")"
        mkdir -p "${OUTPUT}"
        rm -f -- "${OUTPUT}/matrix.json"
        for language in rust typescript go c java dotnet; do
            case "${language}" in
                rust) participant=("${TARGET_ROOT}/debug/examples/provider_workflow") ;;
                typescript) participant=("$(command -v node)" "${ROOT}/sdk/typescript-client/tests/provider-workflow.mjs") ;;
                go) participant=("${NATIVE}/go/provider-workflow") ;;
                c) participant=("${NATIVE}/c/provider-workflow") ;;
                # This controlled Java 25 process uses only the locked classpath.
                # Explicitly acknowledge protobuf Unsafe and Netty native access;
                # do not discard stderr or weaken the shared result contract.
                java) participant=("$(command -v java)" --sun-misc-unsafe-memory-access=allow --enable-native-access=ALL-UNNAMED -jar "${ROOT}/sdk/java-client/build/latent-java-client.jar") ;;
                dotnet) participant=("$(command -v dotnet)" "${NATIVE}/dotnet/bin/Latent.Sdk.ProviderWorkflow/debug/Latent.Sdk.ProviderWorkflow.dll") ;;
            esac
            timeout 300 python3 tools/run_sdk_provider_workflow.py \
                --cli "${CLI}" --node "${NODE}" --fixture-root "${FIXTURE}" \
                --language "${language}" -- "${participant[@]}" > "${OUTPUT}/${language}.json"
            printf 'PASS native provider workflow: %s\n' "${language}"
        done
        python3 tools/verify_sdk_provider_matrix.py "${OUTPUT}" > "${OUTPUT}/matrix.json"
        cat "${OUTPUT}/matrix.json"
        ;;
    *)
        printf 'usage: %s build | run CLI NODE FIXTURE\n' "$0" >&2
        exit 2
        ;;
esac
