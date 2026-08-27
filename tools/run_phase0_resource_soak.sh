#!/usr/bin/env bash
set -euo pipefail

# Explicit native-Linux long-running resource evidence for issue #39. This is
# intentionally separate from PR smoke CI: each retained process performs
# 1,000 warm-up and 100,000 normal measured fresh-store activations.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
RUNS=3
OUTPUT_DIR=""
TARGET_ROOT="${LSF_RESOURCE_SOAK_TARGET_DIR:-${ROOT}/target/phase0-resource-soak-work}"
PUBLISHED_SOURCE_COMMIT=""
PUBLISHED_SOURCE_TREE=""
FINAL_CONFIGURATION_COMMIT=""
CALIBRATION="${ROOT}/benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/aggregate.json"
RETAINING_SUBSYSTEM=""
FOLLOWUP_ISSUE=""

usage() {
    printf '%s\n' "usage: $0 --final-configuration-commit SHA [--runs N] [--published-source-commit SHA --published-source-tree TREE] [--calibration PATH] [--retaining-subsystem NAME] [--followup-issue URL_OR_NUMBER] output-directory"
    printf '%s\n' "Runs at least three independent 100,000-activation native-Linux Phase 0 resource soaks."
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
        --final-configuration-commit)
            if (( $# < 2 )); then
                usage >&2
                exit 2
            fi
            FINAL_CONFIGURATION_COMMIT="$2"
            shift 2
            ;;
        --calibration)
            if (( $# < 2 )); then
                usage >&2
                exit 2
            fi
            CALIBRATION="$2"
            shift 2
            ;;
        --retaining-subsystem)
            if (( $# < 2 )); then
                usage >&2
                exit 2
            fi
            RETAINING_SUBSYSTEM="$2"
            shift 2
            ;;
        --followup-issue)
            if (( $# < 2 )); then
                usage >&2
                exit 2
            fi
            FOLLOWUP_ISSUE="$2"
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

if ! [[ "$RUNS" =~ ^[0-9]+$ ]] || (( RUNS < 3 )); then
    printf '%s\n' "a resource plateau reference requires at least three independent runs" >&2
    exit 2
fi
if [[ -z "$OUTPUT_DIR" || -z "$FINAL_CONFIGURATION_COMMIT" ]]; then
    usage >&2
    exit 2
fi
if [[ "$OUTPUT_DIR" != /* ]]; then
    OUTPUT_DIR="${ROOT}/${OUTPUT_DIR}"
fi
if [[ "$TARGET_ROOT" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi
if [[ "$CALIBRATION" != /* ]]; then
    CALIBRATION="${ROOT}/${CALIBRATION}"
fi
if [[ -e "$OUTPUT_DIR" ]]; then
    printf '%s\n' "output directory must not already exist: $OUTPUT_DIR" >&2
    printf '%s\n' "choose a fresh archive path; raw soak evidence is never overwritten" >&2
    exit 2
fi
if [[ ! -f "$CALIBRATION" ]]; then
    printf '%s\n' "required Phase 0 calibration aggregate is unavailable: $CALIBRATION" >&2
    exit 2
fi

for command in git "$PYTHON" cargo uname systemd-detect-virt; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf '%s\n' "required command is unavailable: $command" >&2
        exit 2
    fi
done

if [[ "$(uname -s)" != "Linux" ]]; then
    printf '%s\n' "resource soak requires a native Linux host or VM" >&2
    exit 2
fi
if {
    [[ -r /proc/sys/kernel/osrelease ]] && grep -qiE 'microsoft|wsl' /proc/sys/kernel/osrelease
} || {
    [[ -r /proc/version ]] && grep -qiE 'microsoft|wsl' /proc/version
}; then
    printf '%s\n' "WSL cannot produce native-Linux resource-soak evidence" >&2
    exit 2
fi
CONTAINER_KIND="$(systemd-detect-virt --container 2>/dev/null || true)"
if [[ "$CONTAINER_KIND" != "none" ]]; then
    printf '%s\n' "a container cannot produce native-Linux resource-soak evidence: ${CONTAINER_KIND:-unavailable}" >&2
    exit 2
fi

cd "$ROOT"
if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
    printf '%s\n' "resource soak requires a clean worktree so every retained process measures one source tree" >&2
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
for object in "$PUBLISHED_SOURCE_COMMIT" "$PUBLISHED_SOURCE_TREE" "$FINAL_CONFIGURATION_COMMIT"; do
    if ! [[ "$object" =~ ^[0-9a-f]{40}$ ]]; then
        printf '%s\n' "source/final-configuration identifiers must be 40-character lowercase Git object IDs" >&2
        exit 2
    fi
done
if ! git cat-file -e "${PUBLISHED_SOURCE_COMMIT}^{commit}" 2>/dev/null; then
    printf '%s\n' "published source commit is not available in this repository: $PUBLISHED_SOURCE_COMMIT" >&2
    exit 2
fi
PUBLISHED_COMMIT_TREE="$(git rev-parse "${PUBLISHED_SOURCE_COMMIT}^{tree}")"
if [[ "$PUBLISHED_COMMIT_TREE" != "$PUBLISHED_SOURCE_TREE" ]]; then
    printf '%s\n' "declared published source tree does not belong to the published source commit" >&2
    printf '%s\n' "commit tree: $PUBLISHED_COMMIT_TREE" >&2
    printf '%s\n' "declared tree: $PUBLISHED_SOURCE_TREE" >&2
    exit 2
fi
if [[ -z "$(git for-each-ref --format='%(refname)' --contains "$PUBLISHED_SOURCE_COMMIT" refs/heads refs/remotes refs/tags)" ]]; then
    printf '%s\n' "published source commit must be retained by a local branch, remote-tracking branch, or tag before measuring" >&2
    exit 2
fi
if [[ "$EXECUTION_TREE" != "$PUBLISHED_SOURCE_TREE" ]]; then
    printf '%s\n' "local execution tree does not match the declared published source tree" >&2
    printf '%s\n' "execution tree: $EXECUTION_TREE" >&2
    printf '%s\n' "published tree: $PUBLISHED_SOURCE_TREE" >&2
    exit 2
fi
if [[ "$FINAL_CONFIGURATION_COMMIT" != "$PUBLISHED_SOURCE_COMMIT" ]]; then
    printf '%s\n' "the final post-issue-40 configuration commit must equal the published source commit measured by this archive" >&2
    exit 2
fi

mkdir -p "$OUTPUT_DIR/runs" "$TARGET_ROOT/phase0-resource-soak"
printf '%s\n' "Running $RUNS independent native-Linux resource-soak processes from final configuration $PUBLISHED_SOURCE_COMMIT"
printf '%s\n' "Published/execution tree identity: $PUBLISHED_SOURCE_TREE"
printf '%s\n' "Raw archive: $OUTPUT_DIR"

# This is mandatory fixture/toolchain validation. It is deliberately outside
# normal PR smoke execution; missing targets or tools abort the soak rather
# than letting it silently produce an incomplete archive.
# Keep the mandatory fixture validation and the measured executable in one
# isolated target root.  The staged capsule below must be the exact fixture
# that this validation produced, never a similarly named default-target file.
CARGO_TARGET_DIR="$TARGET_ROOT" tools/validate_contracts.sh

ECHO_CAPSULE="${TARGET_ROOT}/capsules/echo/capsule.json"
CONTAINMENT_COMPONENT="${TARGET_ROOT}/capsules/containment/containment-capsule.wasm"
STAGED_DIR="${TARGET_ROOT}/phase0-resource-soak/staged-containment"

"$PYTHON" - "$ECHO_CAPSULE" "$CONTAINMENT_COMPONENT" "$STAGED_DIR" <<'PY'
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

source_capsule = Path(sys.argv[1])
source_component = Path(sys.argv[2])
staged_dir = Path(sys.argv[3])

if not source_capsule.is_file():
    raise SystemExit(f"echo capsule fixture is missing: {source_capsule}")
if not source_component.is_file():
    raise SystemExit(f"containment component fixture is missing: {source_component}")

staged_dir.mkdir(parents=True, exist_ok=True)
component_destination = staged_dir / source_component.name
shutil.copy2(source_component, component_destination)
component_bytes = component_destination.read_bytes()
component_digest = "sha256:" + hashlib.sha256(component_bytes).hexdigest()

document = json.loads(source_capsule.read_text(encoding="utf-8"))
document["component"]["digest"] = component_digest
document["execution"]["limits"]["cpuFuel"] = 1_000_000_000_000
document["execution"]["limits"]["memoryBytes"] = 32 * 1024 * 1024
document["metadata"].setdefault("annotations", {})["latent.dev/artifact"] = source_component.name
(staged_dir / "capsule.json").write_text(
    json.dumps(document, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

CARGO_TARGET_DIR="$TARGET_ROOT" cargo build -p latentd --bin phase0-soak --release --locked

failures=0
for (( index = 1; index <= RUNS; index++ )); do
    printf -v RUN_NAME 'run-%02d' "$index"
    RUN_DIR="$OUTPUT_DIR/runs/$RUN_NAME"
    mkdir -p "$RUN_DIR"
    "$PYTHON" tools/aggregate_phase0_resource_soak.py capture-host \
        --output "$RUN_DIR/host-before.json" \
        --phase before \
        --run-index "$index" \
        --source-commit "$PUBLISHED_SOURCE_COMMIT" \
        --source-tree "$PUBLISHED_SOURCE_TREE" \
        --execution-commit "$EXECUTION_COMMIT" \
        --execution-tree "$EXECUTION_TREE"
    printf 'Phase 0 native-Linux resource-soak output for %s.\n' "$RUN_NAME" >"$RUN_DIR/run.log"
    set +e
    GITHUB_SHA="$PUBLISHED_SOURCE_COMMIT" "$TARGET_ROOT/release/phase0-soak" \
        --capsule "$STAGED_DIR/capsule.json" \
        --output-json "$RUN_DIR/raw.json" \
        --run-index "$index" \
        --source-commit "$PUBLISHED_SOURCE_COMMIT" \
        --source-tree "$PUBLISHED_SOURCE_TREE" \
        --execution-commit "$EXECUTION_COMMIT" \
        --execution-tree "$EXECUTION_TREE" \
        --final-configuration-commit "$FINAL_CONFIGURATION_COMMIT" >>"$RUN_DIR/run.log" 2>&1
    RUN_STATUS=$?
    set -e
    "$PYTHON" tools/aggregate_phase0_resource_soak.py capture-host \
        --output "$RUN_DIR/host-after.json" \
        --phase after \
        --run-index "$index" \
        --source-commit "$PUBLISHED_SOURCE_COMMIT" \
        --source-tree "$PUBLISHED_SOURCE_TREE" \
        --execution-commit "$EXECUTION_COMMIT" \
        --execution-tree "$EXECUTION_TREE"
    "$PYTHON" - "$RUN_DIR/execution-status.json" "$index" "$RUN_STATUS" "$PUBLISHED_SOURCE_COMMIT" "$PUBLISHED_SOURCE_TREE" "$EXECUTION_COMMIT" "$EXECUTION_TREE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(
    json.dumps(
        {
            "schema_version": "latent.phase0.resource-soak.execution-status.v1",
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

aggregate_arguments=(
    aggregate
    --runs-directory "$OUTPUT_DIR/runs"
    --output-json "$OUTPUT_DIR/aggregate.json"
    --output-report "$OUTPUT_DIR/SOAK.md"
    --source-commit "$PUBLISHED_SOURCE_COMMIT"
    --source-tree "$PUBLISHED_SOURCE_TREE"
    --calibration "$CALIBRATION"
    --minimum-runs "$RUNS"
)
if [[ -n "$RETAINING_SUBSYSTEM" ]]; then
    aggregate_arguments+=(--retaining-subsystem "$RETAINING_SUBSYSTEM")
fi
if [[ -n "$FOLLOWUP_ISSUE" ]]; then
    aggregate_arguments+=(--followup-issue "$FOLLOWUP_ISSUE")
fi
set +e
"$PYTHON" tools/aggregate_phase0_resource_soak.py "${aggregate_arguments[@]}"
AGGREGATE_STATUS=$?
set -e
if (( failures > 0 )); then
    printf '%s\n' "$failures resource-soak process(es) failed; every run directory was retained" >&2
    exit 1
fi
exit "$AGGREGATE_STATUS"
