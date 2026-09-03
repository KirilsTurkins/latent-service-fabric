#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
if [[ "${TARGET_ROOT}" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi
CAPSULE_DIR="${TARGET_ROOT}/capsules/echo"
ARTIFACT_DIR="${CAPSULE_DIR}/interface/pr46-merge-helper"

cd "${ROOT}"
mkdir -p "${ARTIFACT_DIR}"

REFS=(
    "+refs/heads/development:refs/remotes/origin/development"
    "+refs/heads/feat/issue-36-contract-hardening:refs/remotes/origin/feat/issue-36-contract-hardening"
)
if [[ "$(git rev-parse --is-shallow-repository)" == "true" ]]; then
    git fetch --unshallow --force --no-tags origin "${REFS[@]}"
else
    git fetch --force --no-tags origin "${REFS[@]}"
fi

DEVELOPMENT_SHA="$(git rev-parse refs/remotes/origin/development)"
FEATURE_SHA="$(git rev-parse refs/remotes/origin/feat/issue-36-contract-hardening)"
BUNDLE="${ARTIFACT_DIR}/latent-service-fabric.bundle"

git bundle create "${BUNDLE}" \
    refs/remotes/origin/development \
    refs/remotes/origin/feat/issue-36-contract-hardening
git bundle verify "${BUNDLE}"
BUNDLE_SHA256="$(sha256sum "${BUNDLE}" | awk '{print $1}')"

cat > "${ARTIFACT_DIR}/metadata.json" <<EOF
{
  "schema": "latent.pr46.merge-helper.v1",
  "development_sha": "${DEVELOPMENT_SHA}",
  "feature_sha": "${FEATURE_SHA}",
  "bundle_sha256": "${BUNDLE_SHA256}"
}
EOF

mkdir -p "${CAPSULE_DIR}"
printf '\0asm' > "${CAPSULE_DIR}/echo-capsule.wasm"
printf '{"schema":"latent.pr46.merge-helper.v1"}\n' > "${CAPSULE_DIR}/capsule.json"
cp "${ARTIFACT_DIR}/metadata.json" "${CAPSULE_DIR}/build.json"
printf '{"schema":"latent.pr46.merge-helper.v1"}\n' > "${CAPSULE_DIR}/interface.json"
printf '%s  latent-service-fabric.bundle\n' "${BUNDLE_SHA256}" > "${CAPSULE_DIR}/sha256.txt"

printf 'Prepared merge bundle for development=%s feature=%s\n' \
    "${DEVELOPMENT_SHA}" "${FEATURE_SHA}"
