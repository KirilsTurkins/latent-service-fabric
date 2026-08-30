#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=phase0_build_environment.sh
source "${ROOT}/tools/phase0_build_environment.sh"
PYTHON="${PYTHON:-python3}"
RUNS=7
OUTPUT_DIR=""
TARGET_ROOT="${LSF_CALIBRATION_TARGET_DIR:-}"
PUBLISHED_SOURCE_COMMIT=""
PUBLISHED_SOURCE_TREE=""
PUBLISHED_SOURCE_REF=""

phase0_reject_inherited_build_overrides

usage() {
    printf '%s\n' "usage: $0 --published-source-commit SHA --published-source-tree TREE --published-source-ref REF [--runs N] [output-directory]"
    printf '%s\n' "Runs at least seven independent native-Linux Phase 0 full profiles."
}

while (( $# > 0 )); do
    case "$1" in
        --runs)
            if (( $# < 2 )); then
                usage >&2
                exit 2
            fi
            RUNS="$2"
            shift 2
            ;;
        --published-source-commit)
            if (( $# < 2 )); then
                usage >&2
                exit 2
            fi
            PUBLISHED_SOURCE_COMMIT="$2"
            shift 2
            ;;
        --published-source-tree)
            if (( $# < 2 )); then
                usage >&2
                exit 2
            fi
            PUBLISHED_SOURCE_TREE="$2"
            shift 2
            ;;
        --published-source-ref)
            if (( $# < 2 )); then
                usage >&2
                exit 2
            fi
            PUBLISHED_SOURCE_REF="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        -*)
            usage >&2
            exit 2
            ;;
        *)
            if [[ -n "$OUTPUT_DIR" ]]; then
                usage >&2
                exit 2
            fi
            OUTPUT_DIR="$1"
            shift
            ;;
    esac
done

if ! [[ "$RUNS" =~ ^[0-9]+$ ]] || (( RUNS < 7 )); then
    printf '%s\n' "a calibration reference requires at least seven runs" >&2
    exit 2
fi
if [[ -z "$PUBLISHED_SOURCE_COMMIT" || -z "$PUBLISHED_SOURCE_TREE" || -z "$PUBLISHED_SOURCE_REF" ]]; then
    printf '%s\n' "a durable published source commit, tree, and branch or tag ref are required" >&2
    exit 2
fi

if [[ -z "$OUTPUT_DIR" ]]; then
    printf '%s\n' "calibration output directory must be supplied as a fresh absolute path outside the source tree" >&2
    exit 2
fi
if [[ "$OUTPUT_DIR" != /* ]]; then
    printf '%s\n' "calibration output directory must be an absolute path outside the source tree: $OUTPUT_DIR" >&2
    exit 2
fi
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    printf '%s\n' "required command is unavailable: $PYTHON" >&2
    exit 2
fi

# Resolve lexical paths before containment checks, including a non-existent
# final output component.  Evidence and build products must never land under
# the checkout being measured.
canonical_path() {
    "$PYTHON" - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).resolve(strict=False))
PY
}

OUTPUT_DIR="$(canonical_path "$OUTPUT_DIR")"
case "$OUTPUT_DIR" in
    "$ROOT"|"$ROOT"/*)
        printf '%s\n' "calibration output directory must be outside the source tree: $OUTPUT_DIR" >&2
        exit 2
        ;;
esac

if [[ -e "$OUTPUT_DIR" ]]; then
    printf '%s\n' "output directory must not already exist: $OUTPUT_DIR" >&2
    printf '%s\n' "choose a fresh archive path; calibration evidence is never overwritten" >&2
    exit 2
fi

if [[ -z "$TARGET_ROOT" ]]; then
    TARGET_ROOT="${OUTPUT_DIR}.build"
elif [[ "$TARGET_ROOT" != /* ]]; then
    printf '%s\n' "LSF_CALIBRATION_TARGET_DIR must be an absolute path outside the source tree: $TARGET_ROOT" >&2
    exit 2
fi
TARGET_ROOT="$(canonical_path "$TARGET_ROOT")"
case "$TARGET_ROOT" in
    "$ROOT"|"$ROOT"/*)
        printf '%s\n' "calibration build output must be outside the source tree: $TARGET_ROOT" >&2
        exit 2
        ;;
esac
if [[ -e "$TARGET_ROOT" ]]; then
    printf '%s\n' "calibration build output directory must not already exist: $TARGET_ROOT" >&2
    printf '%s\n' "choose a fresh external build path; collector build products are never reused or overwritten" >&2
    exit 2
fi
if ! "$PYTHON" - "$OUTPUT_DIR" "$TARGET_ROOT" <<'PY'
from pathlib import Path
import sys

output = Path(sys.argv[1]).resolve(strict=False)
target = Path(sys.argv[2]).resolve(strict=False)
for left, right in ((output, target), (target, output)):
    try:
        left.relative_to(right)
    except ValueError:
        continue
    raise SystemExit(1)
raise SystemExit(0)
PY
then
    printf '%s\n' "calibration output and build paths must not overlap: $OUTPUT_DIR and $TARGET_ROOT" >&2
    exit 2
fi

for command in git "$PYTHON" cargo uname systemd-detect-virt; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf '%s\n' "required command is unavailable: $command" >&2
        exit 2
    fi
done

if [[ "$(uname -s)" != "Linux" ]]; then
    printf '%s\n' "native-Linux calibration cannot run on a non-Linux host" >&2
    exit 2
fi
if {
    [[ -r /proc/sys/kernel/osrelease ]] && grep -qiE 'microsoft|wsl' /proc/sys/kernel/osrelease
} || {
    [[ -r /proc/version ]] && grep -qiE 'microsoft|wsl' /proc/version
}; then
    printf '%s\n' "WSL results are historical-only and cannot be the calibration reference" >&2
    exit 2
fi
CONTAINER_KIND="$(systemd-detect-virt --container 2>/dev/null || true)"
if [[ "$CONTAINER_KIND" != "none" ]]; then
    printf '%s\n' "native-Linux calibration requires systemd-detect-virt --container to report none: ${CONTAINER_KIND:-unavailable}" >&2
    exit 2
fi

cd "$ROOT"
if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
    printf '%s\n' "calibration requires a clean worktree so every run is from one source commit" >&2
    exit 2
fi
EXECUTION_COMMIT="$(git rev-parse HEAD)"
EXECUTION_TREE="$(git rev-parse HEAD^{tree})"
if ! [[ "$PUBLISHED_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
    printf '%s\n' "published source commit must be a 40-character lowercase Git SHA" >&2
    exit 2
fi
if ! [[ "$PUBLISHED_SOURCE_TREE" =~ ^[0-9a-f]{40}$ ]]; then
    printf '%s\n' "published source tree must be a 40-character lowercase Git tree SHA" >&2
    exit 2
fi
if [[ "$EXECUTION_COMMIT" != "$PUBLISHED_SOURCE_COMMIT" ]]; then
    printf '%s\n' "local execution HEAD does not equal the declared published source commit" >&2
    printf '%s\n' "execution commit: $EXECUTION_COMMIT" >&2
    printf '%s\n' "published commit: $PUBLISHED_SOURCE_COMMIT" >&2
    exit 2
fi
if [[ "$EXECUTION_TREE" != "$PUBLISHED_SOURCE_TREE" ]]; then
    printf '%s\n' "local execution tree does not match the declared published source tree" >&2
    printf '%s\n' "execution tree: $EXECUTION_TREE" >&2
    printf '%s\n' "published tree: $PUBLISHED_SOURCE_TREE" >&2
    exit 2
fi

# A tree hash alone is insufficient provenance.  Resolve the requested durable
# branch or tag, then retain the exact ref head that proved the local HEAD is
# published before any calibration process starts.  An already-present
# origin-tracking ref is accepted only if the fetch transport is unavailable;
# the recorded head makes that offline fallback auditable.
if [[ "$PUBLISHED_SOURCE_REF" == refs/* ]]; then
    SOURCE_REF_SPEC="$PUBLISHED_SOURCE_REF"
else
    SOURCE_REF_SPEC="refs/heads/$PUBLISHED_SOURCE_REF"
fi
case "$SOURCE_REF_SPEC" in
    refs/heads/*|refs/tags/*)
        ;;
    *)
        printf '%s\n' "published source ref must name a durable branch or tag: $PUBLISHED_SOURCE_REF" >&2
        exit 2
        ;;
esac
if ! git check-ref-format "$SOURCE_REF_SPEC"; then
    printf '%s\n' "published source ref is not a valid Git ref: $PUBLISHED_SOURCE_REF" >&2
    exit 2
fi
PUBLISHED_SOURCE_REF="$SOURCE_REF_SPEC"
if [[ "$SOURCE_REF_SPEC" == refs/heads/* ]]; then
    CACHED_SOURCE_REF="refs/remotes/origin/${SOURCE_REF_SPEC#refs/heads/}"
    if git fetch --quiet origin "$SOURCE_REF_SPEC"; then
        PUBLISHED_REF_HEAD="$(git rev-parse FETCH_HEAD^{commit})"
    elif git show-ref --verify --quiet "$CACHED_SOURCE_REF"; then
        PUBLISHED_REF_HEAD="$(git rev-parse "${CACHED_SOURCE_REF}^{commit}")"
        printf '%s\n' "unable to refresh origin; using cached origin ref $CACHED_SOURCE_REF" >&2
    else
        printf '%s\n' "cannot fetch durable published source branch and no cached origin ref exists: $PUBLISHED_SOURCE_REF" >&2
        exit 2
    fi
else
    if ! git fetch --quiet origin "$SOURCE_REF_SPEC"; then
        printf '%s\n' "cannot fetch durable published source tag from origin: $PUBLISHED_SOURCE_REF" >&2
        exit 2
    fi
    PUBLISHED_REF_HEAD="$(git rev-parse FETCH_HEAD^{commit})"
fi
if ! git cat-file -e "$PUBLISHED_SOURCE_COMMIT^{commit}"; then
    printf '%s\n' "declared published source commit does not exist after fetching $PUBLISHED_SOURCE_REF" >&2
    exit 2
fi
if [[ "$(git rev-parse "$PUBLISHED_SOURCE_COMMIT^{tree}")" != "$PUBLISHED_SOURCE_TREE" ]]; then
    printf '%s\n' "declared published source commit does not resolve to the declared tree" >&2
    exit 2
fi
if ! git merge-base --is-ancestor "$PUBLISHED_SOURCE_COMMIT" "$PUBLISHED_REF_HEAD"; then
    printf '%s\n' "declared published source commit is not reachable from $PUBLISHED_SOURCE_REF" >&2
    exit 2
fi
SOURCE_COMMIT="$PUBLISHED_SOURCE_COMMIT"
SOURCE_TREE="$PUBLISHED_SOURCE_TREE"

mkdir -p "$OUTPUT_DIR/runs"
printf '%s\n' "Calibrating $RUNS independent full-profile processes from published $SOURCE_COMMIT"
printf '%s\n' "Published/execution tree identity: $SOURCE_TREE"
printf '%s\n' "Local execution commit: $EXECUTION_COMMIT"
printf '%s\n' "Durable published ref: $PUBLISHED_SOURCE_REF ($PUBLISHED_REF_HEAD)"
printf '%s\n' "Raw archive: $OUTPUT_DIR"

failures=0
for (( index = 1; index <= RUNS; index++ )); do
    printf -v RUN_NAME 'run-%02d' "$index"
    RUN_DIR="$OUTPUT_DIR/runs/$RUN_NAME"
    mkdir -p "$RUN_DIR"
    "$PYTHON" tools/aggregate_phase0_calibration.py capture-host \
        --output "$RUN_DIR/host-before.json" \
        --phase before \
        --run-index "$index" \
        --source-commit "$SOURCE_COMMIT" \
        --source-tree "$SOURCE_TREE" \
        --published-source-ref "$PUBLISHED_SOURCE_REF" \
        --published-source-ref-head "$PUBLISHED_REF_HEAD" \
        --execution-commit "$EXECUTION_COMMIT" \
        --execution-tree "$EXECUTION_TREE" \
        --repository-root "$ROOT"

    printf 'Phase 0 native-Linux calibration full-profile output for %s.\n' "$RUN_NAME" \
        >"$RUN_DIR/run.log"
    set +e
    GITHUB_SHA="$SOURCE_COMMIT" CARGO_TARGET_DIR="$TARGET_ROOT" \
        LSF_PHASE0_RETAIN_COLLECTOR_PATH="$OUTPUT_DIR/collector/phase0-baseline" \
        tools/run_phase0_baselines.sh full "$RUN_DIR" >>"$RUN_DIR/run.log" 2>&1
    RUN_STATUS=$?
    set -e

    "$PYTHON" tools/aggregate_phase0_calibration.py capture-host \
        --output "$RUN_DIR/host-after.json" \
        --phase after \
        --run-index "$index" \
        --source-commit "$SOURCE_COMMIT" \
        --source-tree "$SOURCE_TREE" \
        --published-source-ref "$PUBLISHED_SOURCE_REF" \
        --published-source-ref-head "$PUBLISHED_REF_HEAD" \
        --execution-commit "$EXECUTION_COMMIT" \
        --execution-tree "$EXECUTION_TREE" \
        --repository-root "$ROOT"
    "$PYTHON" - "$RUN_DIR/execution-status.json" "$index" "$RUN_STATUS" "$SOURCE_COMMIT" "$SOURCE_TREE" "$PUBLISHED_SOURCE_REF" "$PUBLISHED_REF_HEAD" "$EXECUTION_COMMIT" "$EXECUTION_TREE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(
    json.dumps(
        {
            "schema_version": "latent.phase0.calibration.execution-status.v2",
            "run_index": int(sys.argv[2]),
            "exit_code": int(sys.argv[3]),
            "source_commit": sys.argv[4],
            "source_tree": sys.argv[5],
            "published_source_ref": sys.argv[6],
            "published_source_ref_head": sys.argv[7],
            "published_commit_reachable_from_ref": True,
            "execution_commit": sys.argv[8],
            "execution_tree": sys.argv[9],
            "execution_commit_matches_published": sys.argv[8] == sys.argv[4],
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY

    if (( RUN_STATUS == 0 )); then
        printf '%s\n' "$RUN_NAME: PASS"
    else
        printf '%s\n' "$RUN_NAME: FAIL (see $RUN_DIR/run.log)" >&2
        failures=$((failures + 1))
    fi
done

set +e
"$PYTHON" tools/aggregate_phase0_calibration.py aggregate \
    --runs-directory "$OUTPUT_DIR/runs" \
    --output-json "$OUTPUT_DIR/aggregate.json" \
    --output-report "$OUTPUT_DIR/CALIBRATION.md" \
    --source-commit "$SOURCE_COMMIT" \
    --source-tree "$SOURCE_TREE" \
    --minimum-runs "$RUNS"
AGGREGATE_STATUS=$?
set -e

if (( failures > 0 )); then
    printf '%s\n' "$failures full-profile run(s) failed; all run directories were retained" >&2
    exit 1
fi
exit "$AGGREGATE_STATUS"
