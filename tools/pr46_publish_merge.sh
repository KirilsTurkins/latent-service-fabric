#!/usr/bin/env bash
set -euo pipefail

EXPECTED_COMMIT="add7508ef04ce7305ac471d65e7d52215d472854"
EXPECTED_TREE="5d70424a650898a660c41308e07367fa9b2ddead"
EXPECTED_FEATURE_HEAD="e8cf01a4869b8f74a6231b68991a6ed8fd48b1f3"
EXPECTED_DEVELOPMENT_HEAD="7991defd7c3a8f05ac2720a9191072eb9ae35fd4"
TARGET_BRANCH="feat/issue-36-contract-hardening"

resolution_dir="$(mktemp -d)"
trap 'rm -rf "${resolution_dir}"' EXIT
cp tools/pr46-resolutions/api-proto-README.md "${resolution_dir}/api-proto-README.md"
cp tools/pr46-resolutions/docs-api-surface.md "${resolution_dir}/docs-api-surface.md"
cp tools/pr46-resolutions/validate_sdks.sh "${resolution_dir}/validate_sdks.sh"

git fetch --force --no-tags origin \
    "+refs/heads/${TARGET_BRANCH}:refs/remotes/origin/${TARGET_BRANCH}" \
    "+refs/heads/development:refs/remotes/origin/development"
test "$(git rev-parse "refs/remotes/origin/${TARGET_BRANCH}")" = "${EXPECTED_FEATURE_HEAD}"
test "$(git rev-parse refs/remotes/origin/development)" = "${EXPECTED_DEVELOPMENT_HEAD}"

git config user.name OpenAI
git config user.email noreply@openai.com
git switch --detach "${EXPECTED_FEATURE_HEAD}"
set +e
git merge --no-commit --no-ff "${EXPECTED_DEVELOPMENT_HEAD}"
merge_status=$?
set -e
test "${merge_status}" -eq 1

mapfile -t conflicts < <(git diff --name-only --diff-filter=U | sort)
expected_conflicts=(
    .github/workflows/issue-22-validation.yml
    .github/workflows/issue-23-validation.yml
    .github/workflows/issue-24-validation.yml
    .github/workflows/issue-25-validation.yml
    api/proto/README.md
    apps/latentd/src/bin/phase0_baseline/throughput.rs
    docs/api-surface.md
    tools/validate_sdks.sh
)
test "$(printf '%s\n' "${conflicts[@]}")" = "$(printf '%s\n' "${expected_conflicts[@]}")"

git checkout --theirs -- \
    .github/workflows/issue-22-validation.yml \
    .github/workflows/issue-23-validation.yml \
    .github/workflows/issue-24-validation.yml \
    .github/workflows/issue-25-validation.yml
cp "${resolution_dir}/api-proto-README.md" api/proto/README.md
cp "${resolution_dir}/docs-api-surface.md" docs/api-surface.md
cp "${resolution_dir}/validate_sdks.sh" tools/validate_sdks.sh
chmod +x tools/validate_sdks.sh

git checkout --theirs -- apps/latentd/src/bin/phase0_baseline/throughput.rs
python3 - <<'PY'
from pathlib import Path

path = Path("apps/latentd/src/bin/phase0_baseline/throughput.rs")
text = path.read_text()
old = "wall_deadline_unix_millis: Some(now_unix_millis().saturating_add(timeout_ms)),"
new = "wall_time_limit_millis: Some(timeout_ms),"
if text.count(old) != 1:
    raise SystemExit(f"expected exactly one legacy throughput budget field, found {text.count(old)}")
path.write_text(text.replace(old, new))
PY

git add \
    .github/workflows/issue-22-validation.yml \
    .github/workflows/issue-23-validation.yml \
    .github/workflows/issue-24-validation.yml \
    .github/workflows/issue-25-validation.yml \
    api/proto/README.md \
    apps/latentd/src/bin/phase0_baseline/throughput.rs \
    docs/api-surface.md \
    tools/validate_sdks.sh
test -z "$(git diff --name-only --diff-filter=U)"
git diff --check --cached

actual_tree="$(git write-tree)"
test "${actual_tree}" = "${EXPECTED_TREE}"
resolved_commit="$({
    printf '%s\n' 'merge: integrate build foundation into Phase 1 contract hardening'
} | GIT_AUTHOR_NAME=OpenAI \
    GIT_AUTHOR_EMAIL=noreply@openai.com \
    GIT_AUTHOR_DATE='@1788439766 +0000' \
    GIT_COMMITTER_NAME=OpenAI \
    GIT_COMMITTER_EMAIL=noreply@openai.com \
    GIT_COMMITTER_DATE='@1788439766 +0000' \
    git commit-tree "${actual_tree}" \
        -p "${EXPECTED_FEATURE_HEAD}" \
        -p "${EXPECTED_DEVELOPMENT_HEAD}")"
test "${resolved_commit}" = "${EXPECTED_COMMIT}"
git diff-tree --check "${resolved_commit}"

git push origin \
    "${resolved_commit}:refs/heads/${TARGET_BRANCH}" \
    "--force-with-lease=refs/heads/${TARGET_BRANCH}:${EXPECTED_FEATURE_HEAD}"
