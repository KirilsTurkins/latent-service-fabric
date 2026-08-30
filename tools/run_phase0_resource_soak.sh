#!/usr/bin/env bash
set -euo pipefail

# Explicit native-Linux long-running resource evidence for issue #39. This is
# intentionally separate from PR smoke CI: each retained process performs
# 1,000 warm-up and 100,000 normal measured fresh-store activations.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=phase0_build_environment.sh
source "${ROOT}/tools/phase0_build_environment.sh"
PYTHON="${PYTHON:-python3}"
RUNS=3
OUTPUT_DIR=""
TARGET_ROOT="${LSF_RESOURCE_SOAK_TARGET_DIR:-}"
PUBLISHED_SOURCE_COMMIT=""
PUBLISHED_SOURCE_TREE=""
PUBLISHED_SOURCE_REF=""
PUBLISHED_REF_HEAD=""
FINAL_CONFIGURATION_COMMIT=""
CALIBRATION=""
RETAINING_SUBSYSTEM=""
FOLLOWUP_ISSUE=""

phase0_reject_inherited_build_overrides

usage() {
    printf '%s\n' "usage: $0 --final-configuration-commit SHA --published-source-commit SHA --published-source-tree TREE --published-source-ref REF --calibration PATH [--runs N] [--retaining-subsystem NAME] [--followup-issue URL_OR_NUMBER] output-directory"
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
        --published-source-ref)
            if (( $# < 2 )); then
                usage >&2
                exit 2
            fi
            PUBLISHED_SOURCE_REF="$2"
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
if [[ -z "$PUBLISHED_SOURCE_COMMIT" || -z "$PUBLISHED_SOURCE_TREE" || -z "$PUBLISHED_SOURCE_REF" ]]; then
    printf '%s\n' "a durable published source commit, tree, and branch or tag ref are required" >&2
    exit 2
fi
if [[ -z "$CALIBRATION" ]]; then
    printf '%s\n' "--calibration is required and must name a fresh passing calibration aggregate" >&2
    exit 2
fi
if [[ "$OUTPUT_DIR" != /* ]]; then
    printf '%s\n' "resource-soak output directory must be an absolute path outside the source tree: $OUTPUT_DIR" >&2
    exit 2
fi
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    printf '%s\n' "required command is unavailable: $PYTHON" >&2
    exit 2
fi

canonical_path() {
    "$PYTHON" - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).resolve(strict=False))
PY
}

if [[ -e "$OUTPUT_DIR" || -L "$OUTPUT_DIR" ]]; then
    printf '%s\n' "output directory must not already exist: $OUTPUT_DIR" >&2
    printf '%s\n' "choose a fresh archive path; raw soak evidence is never overwritten" >&2
    exit 2
fi
OUTPUT_DIR="$(canonical_path "$OUTPUT_DIR")"
case "$OUTPUT_DIR" in
    "$ROOT"|"$ROOT"/*)
        printf '%s\n' "resource-soak output directory must be outside the source tree: $OUTPUT_DIR" >&2
        exit 2
        ;;
esac

if [[ -z "$TARGET_ROOT" ]]; then
    TARGET_ROOT="${OUTPUT_DIR}.build"
elif [[ "$TARGET_ROOT" != /* ]]; then
    printf '%s\n' "LSF_RESOURCE_SOAK_TARGET_DIR must be an absolute path outside the source tree: $TARGET_ROOT" >&2
    exit 2
fi
if [[ -e "$TARGET_ROOT" || -L "$TARGET_ROOT" ]]; then
    printf '%s\n' "resource-soak build output must not already exist: $TARGET_ROOT" >&2
    printf '%s\n' "choose a fresh build path; the collector never reuses prior build state" >&2
    exit 2
fi
TARGET_ROOT="$(canonical_path "$TARGET_ROOT")"
case "$TARGET_ROOT" in
    "$ROOT"|"$ROOT"/*)
        printf '%s\n' "resource-soak build output must be outside the source tree: $TARGET_ROOT" >&2
        exit 2
        ;;
esac
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
    printf '%s\n' "resource-soak output and build paths must not overlap: $OUTPUT_DIR and $TARGET_ROOT" >&2
    exit 2
fi

if [[ "$CALIBRATION" != /* ]]; then
    CALIBRATION="${ROOT}/${CALIBRATION}"
fi
if [[ ! -f "$CALIBRATION" || -L "$CALIBRATION" ]]; then
    printf '%s\n' "--calibration must be an existing regular fresh calibration aggregate: $CALIBRATION" >&2
    exit 2
fi

for command in git "$PYTHON" cargo cp uname systemd-detect-virt; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf '%s\n' "required command is unavailable: $command" >&2
        exit 2
    fi
done

cd "$ROOT"
if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
    printf '%s\n' "resource soak requires a clean worktree so every retained process measures one source tree" >&2
    exit 2
fi
EXECUTION_COMMIT="$(git rev-parse HEAD)"
EXECUTION_TREE="$(git rev-parse HEAD^{tree})"
for object in "$PUBLISHED_SOURCE_COMMIT" "$PUBLISHED_SOURCE_TREE" "$FINAL_CONFIGURATION_COMMIT"; do
    if ! [[ "$object" =~ ^[0-9a-f]{40}$ ]]; then
        printf '%s\n' "source/final-configuration identifiers must be 40-character lowercase Git object IDs" >&2
        exit 2
    fi
done

# Resolve an advertised origin ref before any fixture build or measured
# process. A local branch or local tag alone is not proof that this source was
# pushed and can be retrieved independently.
if [[ "$PUBLISHED_SOURCE_REF" == refs/heads/* || "$PUBLISHED_SOURCE_REF" == refs/tags/* ]]; then
    SOURCE_REF_SPEC="$PUBLISHED_SOURCE_REF"
elif [[ "$PUBLISHED_SOURCE_REF" == refs/* ]]; then
    printf '%s\n' "--published-source-ref must name an origin branch or tag, not $PUBLISHED_SOURCE_REF" >&2
    exit 2
else
    SOURCE_REF_SPEC="refs/heads/$PUBLISHED_SOURCE_REF"
fi
if ! git check-ref-format "$SOURCE_REF_SPEC"; then
    printf '%s\n' "--published-source-ref is not a valid durable Git ref: $PUBLISHED_SOURCE_REF" >&2
    exit 2
fi
if [[ "$SOURCE_REF_SPEC" == refs/heads/* ]]; then
    CACHED_SOURCE_REF="refs/remotes/origin/${SOURCE_REF_SPEC#refs/heads/}"
    if git fetch --quiet origin "$SOURCE_REF_SPEC"; then
        PUBLISHED_REF_HEAD="$(git rev-parse FETCH_HEAD^{commit})"
    elif git show-ref --verify --quiet "$CACHED_SOURCE_REF"; then
        PUBLISHED_REF_HEAD="$(git rev-parse "${CACHED_SOURCE_REF}^{commit}")"
        printf '%s\n' "unable to refresh origin; using cached origin ref $CACHED_SOURCE_REF" >&2
    else
        printf '%s\n' "cannot fetch durable published source ref and no cached origin ref exists: $PUBLISHED_SOURCE_REF" >&2
        exit 2
    fi
else
    if ! git fetch --quiet origin "$SOURCE_REF_SPEC"; then
        printf '%s\n' "cannot fetch durable published source tag from origin: $PUBLISHED_SOURCE_REF" >&2
        exit 2
    fi
    PUBLISHED_REF_HEAD="$(git rev-parse FETCH_HEAD^{commit})"
fi
if ! git cat-file -e "${PUBLISHED_SOURCE_COMMIT}^{commit}" 2>/dev/null; then
    printf '%s\n' "declared published source commit does not exist after fetching $PUBLISHED_SOURCE_REF" >&2
    exit 2
fi
if [[ "$(git rev-parse "${PUBLISHED_SOURCE_COMMIT}^{tree}")" != "$PUBLISHED_SOURCE_TREE" ]]; then
    printf '%s\n' "declared published source commit does not resolve to the declared tree" >&2
    exit 2
fi
if ! git merge-base --is-ancestor "$PUBLISHED_SOURCE_COMMIT" "$PUBLISHED_REF_HEAD"; then
    printf '%s\n' "declared published source commit is not reachable from $PUBLISHED_SOURCE_REF" >&2
    exit 2
fi
if [[ "$EXECUTION_TREE" != "$PUBLISHED_SOURCE_TREE" ]]; then
    printf '%s\n' "local execution tree does not match the declared published source tree" >&2
    printf '%s\n' "execution tree: $EXECUTION_TREE" >&2
    printf '%s\n' "published tree: $PUBLISHED_SOURCE_TREE" >&2
    exit 2
fi
if [[ "$EXECUTION_COMMIT" != "$PUBLISHED_SOURCE_COMMIT" ]]; then
    printf '%s\n' "local execution commit does not match the declared published source commit" >&2
    printf '%s\n' "execution commit: $EXECUTION_COMMIT" >&2
    printf '%s\n' "published commit: $PUBLISHED_SOURCE_COMMIT" >&2
    exit 2
fi
if [[ "$FINAL_CONFIGURATION_COMMIT" != "$PUBLISHED_SOURCE_COMMIT" ]]; then
    printf '%s\n' "the final post-issue-40 configuration commit must equal the published source commit measured by this archive" >&2
    exit 2
fi

# Do not create a target directory, build a fixture, or begin any measured
# process unless the host is a native Linux host or VM.  Source provenance is
# resolved first so a local-only commit/ref is rejected deterministically even
# when this wrapper is being exercised from a non-evidence test environment.
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

# Rebuild the explicit fresh calibration from its retained raw evidence before
# the long-running processes start. A merely present JSON file is not enough.
"$PYTHON" tools/aggregate_phase0_calibration.py verify \
    --aggregate "$CALIBRATION" \
    --source-commit "$PUBLISHED_SOURCE_COMMIT" \
    --source-tree "$PUBLISHED_SOURCE_TREE"

mkdir -p "$OUTPUT_DIR/runs" "$TARGET_ROOT/phase0-resource-soak"
printf '%s\n' "Running $RUNS independent native-Linux resource-soak processes from final configuration $PUBLISHED_SOURCE_COMMIT (ref $SOURCE_REF_SPEC at $PUBLISHED_REF_HEAD)"
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

CARGO_TARGET_DIR="$TARGET_ROOT" phase0_release_cargo \
    build -p latentd --bin phase0-soak --release --locked
BUILT_COLLECTOR="$TARGET_ROOT/release/phase0-soak"
COLLECTOR_BINARY="$OUTPUT_DIR/collector/phase0-soak"
mkdir -p "$(dirname "$COLLECTOR_BINARY")"
cp -- "$BUILT_COLLECTOR" "$COLLECTOR_BINARY"

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
        --published-source-ref "$SOURCE_REF_SPEC" \
        --published-source-ref-head "$PUBLISHED_REF_HEAD" \
        --execution-commit "$EXECUTION_COMMIT" \
        --execution-tree "$EXECUTION_TREE"
    printf 'Phase 0 native-Linux resource-soak output for %s.\n' "$RUN_NAME" >"$RUN_DIR/run.log"
    set +e
    GITHUB_SHA="$PUBLISHED_SOURCE_COMMIT" "$COLLECTOR_BINARY" \
        --capsule "$STAGED_DIR/capsule.json" \
        --output-json "$RUN_DIR/raw.json" \
        --run-index "$index" \
        --source-commit "$PUBLISHED_SOURCE_COMMIT" \
        --source-tree "$PUBLISHED_SOURCE_TREE" \
        --published-source-ref "$SOURCE_REF_SPEC" \
        --published-source-ref-head "$PUBLISHED_REF_HEAD" \
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
        --published-source-ref "$SOURCE_REF_SPEC" \
        --published-source-ref-head "$PUBLISHED_REF_HEAD" \
        --execution-commit "$EXECUTION_COMMIT" \
        --execution-tree "$EXECUTION_TREE"
    "$PYTHON" - "$RUN_DIR/execution-status.json" "$index" "$RUN_STATUS" "$PUBLISHED_SOURCE_COMMIT" "$PUBLISHED_SOURCE_TREE" "$SOURCE_REF_SPEC" "$PUBLISHED_REF_HEAD" "$EXECUTION_COMMIT" "$EXECUTION_TREE" <<'PY'
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
