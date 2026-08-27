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
CANDIDATE_RUNS=3
PERF_FREQUENCY=999

usage() {
    printf '%s\n' "usage: $0 --published-source-commit SHA --published-source-tree TREE [--candidate-runs N] [--perf-frequency HZ] [output-directory]"
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
        --candidate-runs)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            CANDIDATE_RUNS="$2"
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

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="${ROOT}/target/phase0-hot-path/native-linux"
elif [[ "$OUTPUT_DIR" != /* ]]; then
    OUTPUT_DIR="${ROOT}/${OUTPUT_DIR}"
fi
if [[ -e "$OUTPUT_DIR" ]]; then
    printf '%s\n' "profile output directory must be new: $OUTPUT_DIR" >&2
    exit 2
fi
if ! [[ "$CANDIDATE_RUNS" =~ ^[0-9]+$ ]] || (( CANDIDATE_RUNS == 0 )); then
    printf '%s\n' "--candidate-runs must be a positive integer" >&2
    exit 2
fi
if ! [[ "$PERF_FREQUENCY" =~ ^[0-9]+$ ]] || (( PERF_FREQUENCY == 0 )); then
    printf '%s\n' "--perf-frequency must be a positive integer" >&2
    exit 2
fi
if ! [[ "$PUBLISHED_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || ! [[ "$PUBLISHED_SOURCE_TREE" =~ ^[0-9a-f]{40}$ ]]; then
    printf '%s\n' "a durable 40-character published source commit and tree are required" >&2
    exit 2
fi

for command in git "$PYTHON" cargo perf heaptrack heaptrack_print uname; do
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
if command -v systemd-detect-virt >/dev/null 2>&1; then
    CONTAINER_KIND="$(systemd-detect-virt --container 2>/dev/null || true)"
    if [[ -n "$CONTAINER_KIND" && "$CONTAINER_KIND" != "none" ]]; then
        printf '%s\n' "a container cannot produce the native-Linux profile reference: $CONTAINER_KIND" >&2
        exit 2
    fi
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

if [[ "$TARGET_ROOT" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi
mkdir -p "$OUTPUT_DIR" "$TARGET_ROOT"

printf '%s\n' "Profiling published source $PUBLISHED_SOURCE_COMMIT (tree $PUBLISHED_SOURCE_TREE)"
printf '%s\n' "Candidate repetitions: $CANDIDATE_RUNS; perf frequency: $PERF_FREQUENCY Hz"

"$PYTHON" tools/aggregate_phase0_hot_path_profiles.py capture-host \
    --output "$OUTPUT_DIR/host-before.json" \
    --source-commit "$PUBLISHED_SOURCE_COMMIT" \
    --source-tree "$PUBLISHED_SOURCE_TREE" \
    --repository-root "$ROOT"

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
    "$PYTHON" - "$destination" "$tool" "$PUBLISHED_SOURCE_COMMIT" "$PUBLISHED_SOURCE_TREE" "$EXECUTION_COMMIT" "$EXECUTION_TREE" "$@" <<'PY'
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
            "execution_commit": sys.argv[5],
            "execution_tree": sys.argv[6],
            "command": sys.argv[7:],
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY
}

profile_command() {
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
    local executable_probe="${11}"
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
        --coordination-timeout-ms 15000 \
        --wasmtime-allocator "$allocator" \
        --wasmtime-copy-on-write-images "$copy_on_write"
}

read_command() {
    local -n destination="$1"
    shift
    mapfile -d '' -t destination < <("$@")
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
    read_command perf_command profile_command \
        "$perf_root/raw-results.json" "$perf_root/BASELINE.md" \
        "$warm_samples" "$sequence_repetitions" "$throughput_batches" "$pool_iterations" \
        2 2 on-demand true "$EXECUTABLE_PROBE"
    write_command_json "$perf_root/command.json" "perf" \
        perf record --output "$perf_root/perf.data" --freq "$PERF_FREQUENCY" --call-graph dwarf -- "${perf_command[@]}"
    perf record --output "$perf_root/perf.data" --freq "$PERF_FREQUENCY" --call-graph dwarf -- "${perf_command[@]}" \
        >"$perf_root/stdout.log" 2>"$perf_root/stderr.log"
    perf report --stdio --no-children --percent-limit 0.1 --sort comm,dso,symbol \
        --input "$perf_root/perf.data" >"$perf_root/perf-report.txt" 2>"$perf_root/perf-report.stderr.log"

    local -a allocation_command
    read_command allocation_command profile_command \
        "$allocation_root/raw-results.json" "$allocation_root/BASELINE.md" \
        "$warm_samples" "$sequence_repetitions" "$throughput_batches" "$pool_iterations" \
        2 2 on-demand true "$EXECUTABLE_PROBE"
    write_command_json "$allocation_root/command.json" "heaptrack" \
        heaptrack --record-only --output "$allocation_root/heaptrack.gz" -- "${allocation_command[@]}"
    heaptrack --record-only --output "$allocation_root/heaptrack.gz" -- "${allocation_command[@]}" \
        >"$allocation_root/stdout.log" 2>"$allocation_root/stderr.log"
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
    read_command template profile_command \
        "RAW_RESULTS.json" "BASELINE.md" 40 10 24 2000 \
        "$runtime_workers" "$pool_capacity" "$allocator" "$copy_on_write" "$candidate_probe"
    write_command_json "$root/command-template.json" "phase0-baseline" "${template[@]}"
    for (( run = 1; run <= CANDIDATE_RUNS; run++ )); do
        printf -v run_name 'run-%02d' "$run"
        local run_root="$root/$run_name"
        mkdir -p "$run_root"
        local -a command
        read_command command profile_command \
            "$run_root/raw-results.json" "$run_root/BASELINE.md" 40 10 24 2000 \
            "$runtime_workers" "$pool_capacity" "$allocator" "$copy_on_write" "$candidate_probe"
        write_command_json "$run_root/command.json" "phase0-baseline" "${command[@]}"
        "${command[@]}" >"$run_root/stdout.log" 2>"$run_root/stderr.log"
    done
}

# Configurations bias each profile toward the named hot path without replacing
# its shared composition with a synthetic benchmark. Every process still runs
# all Phase 0 hard checks.
run_profile cold-preparation 1 1 1 1
run_profile first-activation 1 1 1 1
run_profile warm-execution 4000 1 1 1
run_profile failure-containment 1 10 1 1
run_profile cleanup 1 10 1 1
run_profile contention 1 1 96 1

# Each candidate is a separate process with the same fixture, toolchain,
# budgets, queue limit, and full Phase 0 checks. Three runs are evidence for a
# trade-off decision only; the aggregate will refuse to call them an adoption
# result until a seven-run matched set exists.
run_candidate worker-cell-1w-1c 1 1 on-demand true
run_candidate worker-cell-2w-2c 2 2 on-demand true
run_candidate worker-cell-2w-4c 2 4 on-demand true
run_candidate worker-cell-4w-2c 4 2 on-demand true
run_candidate on-demand-cow-disabled 2 2 on-demand false
run_candidate pooling-cow-disabled 2 2 pooling false
run_candidate pooling-cow-enabled 2 2 pooling true

"$PYTHON" tools/aggregate_phase0_hot_path_profiles.py aggregate \
    --profiles-directory "$OUTPUT_DIR/profiles" \
    --candidates-directory "$OUTPUT_DIR/candidates" \
    --host-observation "$OUTPUT_DIR/host-before.json" \
    --calibration-aggregate "$ROOT/benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/aggregate.json" \
    --source-commit "$PUBLISHED_SOURCE_COMMIT" \
    --source-tree "$PUBLISHED_SOURCE_TREE" \
    --output-json "$OUTPUT_DIR/aggregate.json" \
    --output-report "$OUTPUT_DIR/PROFILE.md"

printf '%s\n' "Phase 0 hot-path profile archive: $OUTPUT_DIR"
