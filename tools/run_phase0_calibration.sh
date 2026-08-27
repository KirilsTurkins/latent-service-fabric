#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
RUNS=7
OUTPUT_DIR=""
TARGET_ROOT="${LSF_CALIBRATION_TARGET_DIR:-${ROOT}/target/phase0-calibration-work}"
PUBLISHED_SOURCE_COMMIT=""
PUBLISHED_SOURCE_TREE=""

usage() {
    printf '%s\n' "usage: $0 [--runs N] [--published-source-commit SHA --published-source-tree TREE] [output-directory]"
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

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="${ROOT}/target/phase0-calibration/native-linux"
elif [[ "$OUTPUT_DIR" != /* ]]; then
    OUTPUT_DIR="${ROOT}/${OUTPUT_DIR}"
fi

if [[ -e "$OUTPUT_DIR" ]]; then
    printf '%s\n' "output directory must not already exist: $OUTPUT_DIR" >&2
    printf '%s\n' "choose a fresh archive path; calibration evidence is never overwritten" >&2
    exit 2
fi

if [[ "$TARGET_ROOT" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi

for command in git "$PYTHON" cargo uname; do
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
if command -v systemd-detect-virt >/dev/null 2>&1; then
    CONTAINER_KIND="$(systemd-detect-virt --container 2>/dev/null || true)"
    if [[ -n "$CONTAINER_KIND" && "$CONTAINER_KIND" != "none" ]]; then
        printf '%s\n' "a container environment cannot be the native-Linux reference: $CONTAINER_KIND" >&2
        exit 2
    fi
fi

cd "$ROOT"
dirty_entries=()
while IFS= read -r status_line; do
    [[ -z "$status_line" ]] && continue
    if [[ "${status_line:0:3}" == "?? " \
        && "${status_line:3}" == benchmarks/phase0/calibration/* ]]; then
        continue
    fi
    dirty_entries+=("$status_line")
done < <(git status --porcelain --untracked-files=all)
if (( ${#dirty_entries[@]} > 0 )); then
    printf '%s\n' "calibration requires a clean worktree so every run is from one source commit" >&2
    exit 2
fi
EXECUTION_COMMIT="$(git rev-parse HEAD)"
EXECUTION_TREE="$(git rev-parse HEAD^{tree})"
if [[ -z "$PUBLISHED_SOURCE_COMMIT" && -z "$PUBLISHED_SOURCE_TREE" ]]; then
    PUBLISHED_SOURCE_COMMIT="$EXECUTION_COMMIT"
    PUBLISHED_SOURCE_TREE="$EXECUTION_TREE"
elif [[ -z "$PUBLISHED_SOURCE_COMMIT" || -z "$PUBLISHED_SOURCE_TREE" ]]; then
    printf '%s\n' "published source commit and tree must be supplied together" >&2
    exit 2
fi
if ! [[ "$PUBLISHED_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
    printf '%s\n' "published source commit must be a 40-character lowercase Git SHA" >&2
    exit 2
fi
if ! [[ "$PUBLISHED_SOURCE_TREE" =~ ^[0-9a-f]{40}$ ]]; then
    printf '%s\n' "published source tree must be a 40-character lowercase Git tree SHA" >&2
    exit 2
fi
if [[ "$EXECUTION_TREE" != "$PUBLISHED_SOURCE_TREE" ]]; then
    printf '%s\n' "local execution tree does not match the declared published source tree" >&2
    printf '%s\n' "execution tree: $EXECUTION_TREE" >&2
    printf '%s\n' "published tree: $PUBLISHED_SOURCE_TREE" >&2
    exit 2
fi
SOURCE_COMMIT="$PUBLISHED_SOURCE_COMMIT"
SOURCE_TREE="$PUBLISHED_SOURCE_TREE"

mkdir -p "$OUTPUT_DIR/runs"
printf '%s\n' "Calibrating $RUNS independent full-profile processes from published $SOURCE_COMMIT"
printf '%s\n' "Published/execution tree identity: $SOURCE_TREE"
printf '%s\n' "Local execution commit: $EXECUTION_COMMIT"
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
        --execution-commit "$EXECUTION_COMMIT" \
        --execution-tree "$EXECUTION_TREE" \
        --repository-root "$ROOT"

    printf 'Phase 0 native-Linux calibration full-profile output for %s.\n' "$RUN_NAME" \
        >"$RUN_DIR/run.log"
    set +e
    GITHUB_SHA="$SOURCE_COMMIT" CARGO_TARGET_DIR="$TARGET_ROOT" \
        tools/run_phase0_baselines.sh full "$RUN_DIR" >>"$RUN_DIR/run.log" 2>&1
    RUN_STATUS=$?
    set -e

    "$PYTHON" tools/aggregate_phase0_calibration.py capture-host \
        --output "$RUN_DIR/host-after.json" \
        --phase after \
        --run-index "$index" \
        --source-commit "$SOURCE_COMMIT" \
        --source-tree "$SOURCE_TREE" \
        --execution-commit "$EXECUTION_COMMIT" \
        --execution-tree "$EXECUTION_TREE" \
        --repository-root "$ROOT"
    "$PYTHON" - "$RUN_DIR/execution-status.json" "$index" "$RUN_STATUS" "$SOURCE_COMMIT" "$SOURCE_TREE" "$EXECUTION_COMMIT" "$EXECUTION_TREE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(
    json.dumps(
        {
            "schema_version": "latent.phase0.calibration.execution-status.v1",
            "run_index": int(sys.argv[2]),
            "exit_code": int(sys.argv[3]),
            "source_commit": sys.argv[4],
            "source_tree": sys.argv[5],
            "execution_commit": sys.argv[6],
            "execution_tree": sys.argv[7],
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
