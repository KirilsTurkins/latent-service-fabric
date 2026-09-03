#!/usr/bin/env bash
set -euo pipefail

EXPECTED_FEATURE_HEAD="5736f296d9334c27a77e30ba08c48322d7f4eed6"
EXPECTED_PATCH_SHA256="f6d3652e812551b3fe9f0d54d782322b5ad3cbefb4cb8ced953e5ba22365deb9"
TARGET_BRANCH="feat/issue-36-contract-hardening"

work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT
cat tools/pr46-qa.patch.part*.b64 | base64 --decode > "${work_dir}/pr46-qa.patch"
echo "${EXPECTED_PATCH_SHA256}  ${work_dir}/pr46-qa.patch" | sha256sum --check --status

git fetch --force --no-tags origin \
    "+refs/heads/${TARGET_BRANCH}:refs/remotes/origin/${TARGET_BRANCH}"
test "$(git rev-parse "refs/remotes/origin/${TARGET_BRANCH}")" = "${EXPECTED_FEATURE_HEAD}"

git config user.name OpenAI
git config user.email noreply@openai.com
git switch --detach "${EXPECTED_FEATURE_HEAD}"
git apply --check "${work_dir}/pr46-qa.patch"
git apply --index "${work_dir}/pr46-qa.patch"
git diff --check --cached

git commit -m "fix: add structured platform-error round trip"
result_commit="$(git rev-parse HEAD)"
git push origin \
    "${result_commit}:refs/heads/${TARGET_BRANCH}" \
    "--force-with-lease=refs/heads/${TARGET_BRANCH}:${EXPECTED_FEATURE_HEAD}"
