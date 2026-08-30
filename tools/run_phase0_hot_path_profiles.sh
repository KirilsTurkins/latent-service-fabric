#!/usr/bin/env bash
# Run the native-Linux Phase 0 CPU/allocation profile set and bounded experiment
# matrix. This is a manual evidence command, never shared pull-request CI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
OUTPUT_DIR=""
TARGET_ROOT="${LSF_HOT_PATH_TARGET_DIR:-${ROOT}/target/phase0-hot-path-work}"
PUBLISHED_SOURCE_COMMIT=""
PUBLISHED_SOURCE_TREE=""
PUBLISHED_SOURCE_REF=""
CALIBRATION_AGGREGATE=""
CANDIDATE_RUNS=3
REFERENCE_CANDIDATE_RUNS=7
PERF_FREQUENCY=999
MINIMUM_EXPERIMENT_RUNS=3
MINIMUM_REFERENCE_RUNS=7

usage() {
    printf '%s\n' "usage: $0 --published-source-commit SHA --published-source-tree TREE --published-source-ref REF --calibration-aggregate PATH [--candidate-runs N] [--reference-candidate-runs N] [--perf-frequency HZ] [output-directory]"
    printf '%s\n' "Records native-Linux perf + heaptrack evidence and a bounded Phase 0 experiment matrix."
}

while (( $# > 0 )); do
    case "$1" in
        --published-source-commit)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            PUBLISHED_SOURCE_COMMIT="$2"
            shift 2
            ;;
        --published-source-tree)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            PUBLISHED_SOURCE_TREE="$2"
            shift 2
            ;;
        --published-source-ref)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            PUBLISHED_SOURCE_REF="$2"
            shift 2
            ;;
        --calibration-aggregate)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            CALIBRATION_AGGREGATE="$2"
            shift 2
            ;;
        --candidate-runs)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            CANDIDATE_RUNS="$2"
            shift 2
            ;;
        --reference-candidate-runs)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            REFERENCE_CANDIDATE_RUNS="$2"
            shift 2
            ;;
        --perf-frequency)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            PERF_FREQUENCY="$2"
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
            [[ -z "$OUTPUT_DIR" ]] || { usage >&2; exit 2; }
            OUTPUT_DIR="$1"
            shift
            ;;
    esac
done

if [[ -z "$CALIBRATION_AGGREGATE" ]]; then
    printf '%s\n' "--calibration-aggregate is required and must name a fresh calibration aggregate" >&2
    exit 2
fi
if [[ "$CALIBRATION_AGGREGATE" != /* ]]; then
    CALIBRATION_AGGREGATE="$ROOT/$CALIBRATION_AGGREGATE"
fi
if [[ ! -f "$CALIBRATION_AGGREGATE" || -L "$CALIBRATION_AGGREGATE" ]]; then
    printf '%s\n' "--calibration-aggregate must be an existing regular file: $CALIBRATION_AGGREGATE" >&2
    exit 2
fi

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="${ROOT}/target/phase0-hot-path/native-linux"
elif [[ "$OUTPUT_DIR" != /* ]]; then
    OUTPUT_DIR="${ROOT}/${OUTPUT_DIR}"
fi
if [[ -e "$OUTPUT_DIR" ]]; then
    printf '%s\n' "profile output directory must be new: $OUTPUT_DIR" >&2
    exit 2
fi
if ! [[ "$CANDIDATE_RUNS" =~ ^[0-9]+$ ]] || (( CANDIDATE_RUNS < MINIMUM_EXPERIMENT_RUNS )); then
    printf '%s\n' "--candidate-runs must be at least $MINIMUM_EXPERIMENT_RUNS" >&2
    exit 2
fi
if ! [[ "$REFERENCE_CANDIDATE_RUNS" =~ ^[0-9]+$ ]] || (( REFERENCE_CANDIDATE_RUNS < MINIMUM_REFERENCE_RUNS )); then
    printf '%s\n' "--reference-candidate-runs must be at least $MINIMUM_REFERENCE_RUNS" >&2
    exit 2
fi
if ! [[ "$PERF_FREQUENCY" =~ ^[0-9]+$ ]] || (( PERF_FREQUENCY == 0 )); then
    printf '%s\n' "--perf-frequency must be a positive integer" >&2
    exit 2
fi
if ! [[ "$PUBLISHED_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || ! [[ "$PUBLISHED_SOURCE_TREE" =~ ^[0-9a-f]{40}$ ]] || [[ -z "$PUBLISHED_SOURCE_REF" ]]; then
    printf '%s\n' "a durable source commit, tree, and branch or tag ref are required" >&2
    exit 2
fi

for command in git "$PYTHON" cargo perf heaptrack heaptrack_print uname systemd-detect-virt; do
    command -v "$command" >/dev/null 2>&1 || {
        printf '%s\n' "required command is unavailable: $command" >&2
        exit 2
    }
done
if [[ "$(uname -s)" != "Linux" ]]; then
    printf '%s\n' "Phase 0 hot-path profiles require native Linux" >&2
    exit 2
fi
if {
    [[ -r /proc/sys/kernel/osrelease ]] && grep -qiE 'microsoft|wsl' /proc/sys/kernel/osrelease
} || {
    [[ -r /proc/version ]] && grep -qiE 'microsoft|wsl' /proc/version
}; then
    printf '%s\n' "WSL is historical-only and cannot produce Phase 0 profile evidence" >&2
    exit 2
fi
CONTAINER_KIND="$(systemd-detect-virt --container 2>/dev/null || true)"
if [[ "$CONTAINER_KIND" != "none" ]]; then
    printf '%s\n' "native-Linux profiles require systemd-detect-virt --container to report none: ${CONTAINER_KIND:-unavailable}" >&2
    exit 2
fi

cd "$ROOT"
if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
    printf '%s\n' "hot-path profiles require a clean worktree so source identity remains auditable" >&2
    exit 2
fi
EXECUTION_COMMIT="$(git rev-parse HEAD)"
EXECUTION_TREE="$(git rev-parse HEAD^{tree})"
if [[ "$EXECUTION_TREE" != "$PUBLISHED_SOURCE_TREE" ]]; then
    printf '%s\n' "local execution tree does not match the declared published source tree" >&2
    printf '%s\n' "execution tree: $EXECUTION_TREE" >&2
    printf '%s\n' "published tree: $PUBLISHED_SOURCE_TREE" >&2
    exit 2
fi

# Resolve the durable ref before collecting evidence.  A tree hash alone is
# insufficient: the exact supplied commit must exist, resolve to that tree,
# and be reachable from an advertised branch or tag.  Ordinarily this refreshes
# `origin`; an already-present origin-tracking ref is accepted only when the
# fetch transport is unavailable (for example an offline rerun of an already
# fetched source).  The recorded ref head makes that fallback auditable.
if [[ "$PUBLISHED_SOURCE_REF" == refs/* ]]; then
    SOURCE_REF_SPEC="$PUBLISHED_SOURCE_REF"
else
    SOURCE_REF_SPEC="refs/heads/$PUBLISHED_SOURCE_REF"
fi
if [[ "$SOURCE_REF_SPEC" == refs/heads/* ]]; then
    CACHED_SOURCE_REF="refs/remotes/origin/${SOURCE_REF_SPEC#refs/heads/}"
else
    CACHED_SOURCE_REF="$SOURCE_REF_SPEC"
fi
if git fetch --quiet origin "$SOURCE_REF_SPEC"; then
    PUBLISHED_REF_HEAD="$(git rev-parse FETCH_HEAD)"
elif [[ "$PUBLISHED_SOURCE_REF" == refs/tags/* ]] \
    && git fetch --quiet origin "$PUBLISHED_SOURCE_REF"; then
    PUBLISHED_REF_HEAD="$(git rev-parse FETCH_HEAD)"
elif git show-ref --verify --quiet "$CACHED_SOURCE_REF"; then
    PUBLISHED_REF_HEAD="$(git rev-parse "$CACHED_SOURCE_REF")"
    printf '%s\n' "unable to refresh origin; using cached origin ref $CACHED_SOURCE_REF" >&2
else
    printf '%s\n' "cannot fetch durable published source ref and no cached origin ref exists: $PUBLISHED_SOURCE_REF" >&2
    exit 2
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

# The profile aggregate is only as applicable as the calibration it consumes.
# Rebuild the supplied fresh aggregate from its retained raw runs before any
# output directory or profiler work is created. This rejects stale, relabelled,
# incomplete, or manually altered calibration evidence instead of falling back
# to the historical checked-in aggregate.
"$PYTHON" tools/aggregate_phase0_calibration.py verify \
    --aggregate "$CALIBRATION_AGGREGATE" \
    --source-commit "$PUBLISHED_SOURCE_COMMIT" \
    --source-tree "$PUBLISHED_SOURCE_TREE"

if [[ "$TARGET_ROOT" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi
mkdir -p "$OUTPUT_DIR" "$TARGET_ROOT"

printf '%s\n' "Profiling published source $PUBLISHED_SOURCE_COMMIT (tree $PUBLISHED_SOURCE_TREE, ref $PUBLISHED_SOURCE_REF)"
printf '%s\n' "Experiment repetitions: $CANDIDATE_RUNS; reference repetitions: $REFERENCE_CANDIDATE_RUNS; perf frequency: $PERF_FREQUENCY Hz"

capture_measurement_host() {
    local output="$1"
    "$PYTHON" tools/aggregate_phase0_hot_path_profiles.py capture-host \
        --output "$output" \
        --source-commit "$PUBLISHED_SOURCE_COMMIT" \
        --source-tree "$PUBLISHED_SOURCE_TREE" \
        --published-source-ref "$PUBLISHED_SOURCE_REF" \
        --published-source-ref-head "$PUBLISHED_REF_HEAD" \
        --repository-root "$ROOT"
}

# Keep a wrapper-level observation for a concise archive overview, then bind
# every measured process to its own before/after observations below.
capture_measurement_host "$OUTPUT_DIR/host-before.json"

# A smoke run builds verified real fixtures and the parity probe through the
# exact executable path. It is intentionally outside perf/heaptrack samples:
# tool startup, contract validation, and fixture generation must not be
# misattributed to one hot-path workload.
BOOTSTRAP_DIR="$OUTPUT_DIR/bootstrap"
printf '%s\n' "Building verified profiling fixture and executable parity probe"
GITHUB_SHA="$PUBLISHED_SOURCE_COMMIT" \
    CARGO_TARGET_DIR="$TARGET_ROOT" \
    CARGO_PROFILE_RELEASE_DEBUG=1 \
    CARGO_PROFILE_RELEASE_STRIP=none \
    tools/run_phase0_baselines.sh smoke "$BOOTSTRAP_DIR" >"$OUTPUT_DIR/bootstrap.log" 2>&1

BASELINE="$TARGET_ROOT/release/phase0-baseline"
CAPSULE="$TARGET_ROOT/phase0-baseline/staged-containment/capsule.json"
EXECUTABLE_PROBE="$TARGET_ROOT/phase0-baseline/smoke/executable-harness-probe.json"
for required in "$BASELINE" "$CAPSULE" "$EXECUTABLE_PROBE"; do
    [[ -f "$required" ]] || {
        printf '%s\n' "bootstrap did not create required profile input: $required" >&2
        exit 1
    }
done

write_command_json() {
    local destination="$1"
    local tool="$2"
    shift 2
    "$PYTHON" - "$destination" "$tool" "$PUBLISHED_SOURCE_COMMIT" "$PUBLISHED_SOURCE_TREE" "$PUBLISHED_SOURCE_REF" "$PUBLISHED_REF_HEAD" "$EXECUTION_COMMIT" "$EXECUTION_TREE" "$@" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(
    json.dumps(
        {
            "schema_version": "latent.phase0.hot-path.command.v1",
            "tool": sys.argv[2],
            "source_commit": sys.argv[3],
            "source_tree": sys.argv[4],
            "published_source_ref": sys.argv[5],
            "published_source_ref_head": sys.argv[6],
            "execution_commit": sys.argv[7],
            "execution_tree": sys.argv[8],
            "command": sys.argv[9:],
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY
}

phase0_command() {
    local output_json="$1"
    local output_report="$2"
    local warm_samples="$3"
    local sequence_repetitions="$4"
    local throughput_batches="$5"
    local pool_iterations="$6"
    local runtime_workers="$7"
    local pool_capacity="$8"
    local allocator="$9"
    local copy_on_write="${10}"
    local cache_enabled="${11}"
    local executable_probe="${12}"
    local coordination_poll_interval_ms="${13}"
    local profile_workload="${14}"
    local parent_launch
    parent_launch="$($PYTHON - <<'PY'
from time import time_ns
print(time_ns() // 1_000)
PY
)"
    printf '%s\0' \
        "$BASELINE" \
        --capsule "$CAPSULE" \
        --executable-harness-probe "$executable_probe" \
        --parent-launch-unix-micros "$parent_launch" \
        --output-json "$output_json" \
        --output-report "$output_report" \
        --mode full \
        --warm-samples "$warm_samples" \
        --sequence-repetitions "$sequence_repetitions" \
        --throughput-batches "$throughput_batches" \
        --pool-iterations "$pool_iterations" \
        --runtime-workers "$runtime_workers" \
        --pool-capacity "$pool_capacity" \
        --pool-queue-capacity 4 \
        --coordination-timeout-ms 2000 \
        --coordination-poll-interval-ms "$coordination_poll_interval_ms" \
        --wasmtime-allocator "$allocator" \
        --wasmtime-copy-on-write-images "$copy_on_write" \
        --prepared-cache-enabled "$cache_enabled"
    if [[ -n "$profile_workload" ]]; then
        printf '%s\0' --profile-workload "$profile_workload"
    fi
}

read_command() {
    local -n destination="$1"
    shift
    mapfile -d '' -t destination < <("$@")
}

run_full_invariant_proof() {
    local root="$OUTPUT_DIR/full-invariant-proof"
    mkdir -p "$root"
    local -a command
    read_command command phase0_command \
        "$root/raw-results.json" "$root/BASELINE.md" \
        40 10 24 2000 2 2 on-demand true true "$EXECUTABLE_PROBE" 0 ""
    write_command_json "$root/command.json" "phase0-baseline-full-invariant-proof" "${command[@]}"
    capture_measurement_host "$root/host-before.json"
    "${command[@]}" >"$root/stdout.log" 2>"$root/stderr.log"
    capture_measurement_host "$root/host-after.json"
}

run_profile() {
    local workload="$1"
    local warm_samples="$2"
    local sequence_repetitions="$3"
    local throughput_batches="$4"
    local pool_iterations="$5"
    local root="$OUTPUT_DIR/profiles/$workload"
    local perf_root="$root/perf"
    local allocation_root="$root/allocation"
    mkdir -p "$perf_root" "$allocation_root"

    local -a perf_command
    read_command perf_command phase0_command \
        "$perf_root/raw-results.json" "$perf_root/BASELINE.md" \
        "$warm_samples" "$sequence_repetitions" "$throughput_batches" "$pool_iterations" \
        2 2 on-demand true true "$EXECUTABLE_PROBE" 1 "$workload"
    write_command_json "$perf_root/command.json" "perf" \
        perf record --output "$perf_root/perf.data" --freq "$PERF_FREQUENCY" --call-graph dwarf -- "${perf_command[@]}"
    capture_measurement_host "$perf_root/host-before.json"
    perf record --output "$perf_root/perf.data" --freq "$PERF_FREQUENCY" --call-graph dwarf -- "${perf_command[@]}" \
        >"$perf_root/stdout.log" 2>"$perf_root/stderr.log"
    capture_measurement_host "$perf_root/host-after.json"
    perf report --stdio --no-children --percent-limit 0.1 --sort comm,dso,symbol \
        --input "$perf_root/perf.data" >"$perf_root/perf-report.txt" 2>"$perf_root/perf-report.stderr.log"
    perf report --stdio --percent-limit 0.1 --sort comm,dso,symbol \
        --input "$perf_root/perf.data" >"$perf_root/perf-inclusive-report.txt" \
        2>"$perf_root/perf-inclusive-report.stderr.log"

    local -a allocation_command
    read_command allocation_command phase0_command \
        "$allocation_root/raw-results.json" "$allocation_root/BASELINE.md" \
        "$warm_samples" "$sequence_repetitions" "$throughput_batches" "$pool_iterations" \
        2 2 on-demand true true "$EXECUTABLE_PROBE" 1 "$workload"
    write_command_json "$allocation_root/command.json" "heaptrack" \
        heaptrack --record-only --output "$allocation_root/heaptrack.gz" -- "${allocation_command[@]}"
    capture_measurement_host "$allocation_root/host-before.json"
    heaptrack --record-only --output "$allocation_root/heaptrack.gz" -- "${allocation_command[@]}" \
        >"$allocation_root/stdout.log" 2>"$allocation_root/stderr.log"
    capture_measurement_host "$allocation_root/host-after.json"
    local allocation_data="$allocation_root/heaptrack.gz.zst"
    if [[ ! -f "$allocation_data" ]]; then
        mapfile -t heaptrack_outputs < <(find "$allocation_root" -maxdepth 1 -type f -name 'heaptrack*.gz*' -print)
        if (( ${#heaptrack_outputs[@]} != 1 )); then
            printf '%s\n' "heaptrack did not create exactly one raw profile for $workload" >&2
            exit 1
        fi
        allocation_data="${heaptrack_outputs[0]}"
    fi
    heaptrack_print "$allocation_data" >"$allocation_root/heaptrack-report.txt" \
        2>"$allocation_root/heaptrack-print.stderr.log"
    # Heaptrack's folded output repeats deep demangled stacks and is far larger
    # than the compressed raw trace from which it can be regenerated. Keep it
    # outside the checked-in output, compact it into category totals bound to
    # the raw-trace checksum, and retain the raw trace plus normal reports.
    local folded_root
    folded_root="$(mktemp -d "$TARGET_ROOT/heaptrack-folded.${workload}.XXXXXX")"
    local allocation_folded="$folded_root/allocations.folded"
    local peak_folded="$folded_root/peak-bytes.folded"
    heaptrack_print --file "$allocation_data" --flamegraph-cost-type allocations \
        --print-flamegraph "$allocation_folded" \
        >/dev/null \
        2>"$allocation_root/heaptrack-allocations.stderr.log"
    heaptrack_print --file "$allocation_data" --flamegraph-cost-type peak \
        --print-flamegraph "$peak_folded" \
        >/dev/null \
        2>"$allocation_root/heaptrack-peak-bytes.stderr.log"
    "$PYTHON" tools/aggregate_phase0_hot_path_profiles.py summarize-heaptrack \
        --allocation-folded "$allocation_folded" \
        --peak-folded "$peak_folded" \
        --raw-heaptrack-data "$allocation_data" \
        --output "$allocation_root/heaptrack-contributors.json"
    heaptrack_print --file "$allocation_data" --print-allocators=0 --print-peaks=0 \
        --print-temporary=0 --print-leaks=1 --peak-limit 20 --sub-peak-limit 5 \
        >"$allocation_root/heaptrack-leaks.txt" 2>"$allocation_root/heaptrack-leaks.stderr.log"
}

run_candidate() {
    local candidate="$1"
    local runtime_workers="$2"
    local pool_capacity="$3"
    local allocator="$4"
    local copy_on_write="$5"
    local cache_enabled="$6"
    local run_count="$7"
    local root="$OUTPUT_DIR/candidates/$candidate"
    mkdir -p "$root"
    local candidate_probe="$root/executable-harness-probe.json"
    local shared_probe="$TARGET_ROOT/phase0-baseline/smoke/executable-harness-probe.json"
    # The exact issue-23 executable probe includes worker and cell capacity in
    # its parity contract. Regenerate it for each topology instead of weakening
    # that contract or comparing a candidate against an incompatible probe.
    GITHUB_SHA="$PUBLISHED_SOURCE_COMMIT" \
        LSF_BASELINE_POOL_CAPACITY="$pool_capacity" \
        LSF_BASELINE_RUNTIME_WORKERS="$runtime_workers" \
        CARGO_TARGET_DIR="$TARGET_ROOT" \
        CARGO_PROFILE_RELEASE_DEBUG=1 \
        CARGO_PROFILE_RELEASE_STRIP=none \
        tools/run_phase0_baselines.sh smoke "$root/parity-bootstrap" >"$root/parity-bootstrap.log" 2>&1
    [[ -f "$shared_probe" ]] || {
        printf '%s\n' "candidate parity bootstrap did not produce its executable probe: $shared_probe" >&2
        exit 1
    }
    cp "$shared_probe" "$candidate_probe"
    local -a template
    read_command template phase0_command \
        "RAW_RESULTS.json" "BASELINE.md" 40 10 24 2000 \
        "$runtime_workers" "$pool_capacity" "$allocator" "$copy_on_write" "$cache_enabled" "$candidate_probe" 0 ""
    write_command_json "$root/command-template.json" "phase0-baseline" "${template[@]}"
    for (( run = 1; run <= run_count; run++ )); do
        printf -v run_name 'run-%02d' "$run"
        local run_root="$root/$run_name"
        mkdir -p "$run_root"
        local -a command
        read_command command phase0_command \
            "$run_root/raw-results.json" "$run_root/BASELINE.md" 40 10 24 2000 \
            "$runtime_workers" "$pool_capacity" "$allocator" "$copy_on_write" "$cache_enabled" "$candidate_probe" 0 ""
        write_command_json "$run_root/command.json" "phase0-baseline" "${command[@]}"
        capture_measurement_host "$run_root/host-before.json"
        "${command[@]}" >"$run_root/stdout.log" 2>"$run_root/stderr.log"
        capture_measurement_host "$run_root/host-after.json"
    done
}

# One complete full-profile proof establishes all canonical invariants. The
# eight tool runs below are deliberately scenario-selective and each declares a
# different `--profile-workload` boundary in its retained command document.
run_full_invariant_proof

# These are distinct real-composition paths, not differently named copies of
# the full process. Profiler-only polling is explicit and does not affect any
# unprofiled candidate throughput interval.
run_profile cold-preparation 1 1 1 1
run_profile prepared-cache-reuse 1 1 1 1
run_profile first-activation 1 1 1 1
run_profile warm-execution 1000 1 1 1
run_profile failure-containment 1 4 1 1
run_profile cleanup 128 1 1 1
run_profile at-capacity-contention 1 1 48 1
run_profile queued-contention 1 1 48 1

# The fixed default is the only calibration-reference candidate: it retains a
# complete seven-run matched set. The deliberately different configurations
# remain bounded Phase 1 experiments with three retained observations each;
# they are never presented as comparisons against the default calibration.
run_candidate worker-cell-1w-1c 1 1 on-demand true true "$CANDIDATE_RUNS"
run_candidate worker-cell-2w-2c 2 2 on-demand true true "$REFERENCE_CANDIDATE_RUNS"
run_candidate worker-cell-2w-4c 2 4 on-demand true true "$CANDIDATE_RUNS"
run_candidate worker-cell-4w-2c 4 2 on-demand true true "$CANDIDATE_RUNS"
run_candidate on-demand-cow-disabled 2 2 on-demand false true "$CANDIDATE_RUNS"
run_candidate pooling-cow-disabled 2 2 pooling false true "$CANDIDATE_RUNS"
run_candidate pooling-cow-enabled 2 2 pooling true true "$CANDIDATE_RUNS"
run_candidate prepared-cache-disabled 2 2 on-demand true false "$CANDIDATE_RUNS"

"$PYTHON" tools/aggregate_phase0_hot_path_profiles.py aggregate \
    --profiles-directory "$OUTPUT_DIR/profiles" \
    --full-invariant-proof "$OUTPUT_DIR/full-invariant-proof/raw-results.json" \
    --candidates-directory "$OUTPUT_DIR/candidates" \
    --host-observation "$OUTPUT_DIR/host-before.json" \
    --calibration-aggregate "$CALIBRATION_AGGREGATE" \
    --source-commit "$PUBLISHED_SOURCE_COMMIT" \
    --source-tree "$PUBLISHED_SOURCE_TREE" \
    --published-source-ref "$PUBLISHED_SOURCE_REF" \
    --required-candidate-runs "$CANDIDATE_RUNS" \
    --required-reference-candidate-runs "$REFERENCE_CANDIDATE_RUNS" \
    --output-json "$OUTPUT_DIR/aggregate.json" \
    --output-report "$OUTPUT_DIR/PROFILE.md"

printf '%s\n' "Phase 0 hot-path profile archive: $OUTPUT_DIR"
