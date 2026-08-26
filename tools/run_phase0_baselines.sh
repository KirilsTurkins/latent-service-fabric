#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
if [[ "${TARGET_ROOT}" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi
MODE="${1:-full}"
OUTPUT_DIR="${2:-${TARGET_ROOT}/phase0-baseline/${MODE}}"

case "${MODE}" in
    smoke|full) ;;
    *)
        echo "usage: $0 [smoke|full] [output-directory]" >&2
        exit 2
        ;;
esac

for command in cargo python3; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        echo "required command is unavailable: ${command}" >&2
        exit 2
    fi
done

cd "${ROOT}"

# This gate is mandatory. It verifies every checked-in contract, builds both
# real Wasm components, and exercises the lower-level containment suite. Missing
# targets or external tools therefore fail rather than silently skipping data.
tools/validate_contracts.sh

ECHO_CAPSULE="${TARGET_ROOT}/capsules/echo/capsule.json"
CONTAINMENT_COMPONENT="${TARGET_ROOT}/capsules/containment/containment-capsule.wasm"
STAGED_DIR="${TARGET_ROOT}/phase0-baseline/staged-containment"
POOL_CAPACITY="${LSF_BASELINE_POOL_CAPACITY:-2}"
QUEUE_CAPACITY="${LSF_BASELINE_QUEUE_CAPACITY:-4}"
RUNTIME_WORKERS="${LSF_BASELINE_RUNTIME_WORKERS:-2}"
RSS_ALLOWANCE="${LSF_BASELINE_RSS_ALLOWANCE_BYTES:-67108864}"
FD_ALLOWANCE="${LSF_BASELINE_FD_ALLOWANCE:-2}"

python3 - "${ECHO_CAPSULE}" "${CONTAINMENT_COMPONENT}" "${STAGED_DIR}" <<'PY'
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
component_name = source_component.name
component_destination = staged_dir / component_name
shutil.copy2(source_component, component_destination)
component_bytes = component_destination.read_bytes()
component_digest = "sha256:" + hashlib.sha256(component_bytes).hexdigest()

document = json.loads(source_capsule.read_text(encoding="utf-8"))
document["component"]["digest"] = component_digest
document["execution"]["limits"]["cpuFuel"] = 1_000_000_000_000
document["execution"]["limits"]["memoryBytes"] = 32 * 1024 * 1024
document["metadata"].setdefault("annotations", {})["latent.dev/artifact"] = component_name
(staged_dir / "capsule.json").write_text(
    json.dumps(document, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

mkdir -p "${OUTPUT_DIR}"
cargo build -p latentd --bin latentd --bin phase0-baseline --release --locked

# Produce independent cold samples through the exact issue-23 executable
# composition. The retained benchmark refuses to run when this parity probe is
# absent, malformed, unhealthy, or topologically inconsistent.
python3 - \
    "${TARGET_ROOT}/release/latentd" \
    "${STAGED_DIR}/capsule.json" \
    "${OUTPUT_DIR}/executable-harness-probe.json" \
    "${MODE}" \
    "${POOL_CAPACITY}" \
    "${QUEUE_CAPACITY}" \
    "${RUNTIME_WORKERS}" <<'PY'
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

binary = Path(sys.argv[1])
capsule = Path(sys.argv[2])
output = Path(sys.argv[3])
mode = sys.argv[4]
pool_capacity = int(sys.argv[5])
queue_capacity = int(sys.argv[6])
runtime_workers = int(sys.argv[7])
sample_count = 3 if mode == "smoke" else 12

base_command = [
    str(binary),
    "phase0-spike",
    "invoke-once",
    "--capsule",
    str(capsule),
    "--input",
    "phase0 executable cold echo",
    "--pool-capacity",
    str(pool_capacity),
    "--pool-queue-capacity",
    str(queue_capacity),
    "--runtime-workers",
    str(runtime_workers),
    "--memory-bytes",
    str(16 * 1024 * 1024),
    "--fuel",
    "1000000000000",
    "--timeout-ms",
    "1000",
]

samples: list[dict[str, object]] = []
for iteration in range(sample_count):
    command = base_command + [
        "--activation-id",
        f"baseline-executable-cold-{iteration:08d}",
    ]
    started = time.perf_counter_ns()
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    elapsed_micros = (time.perf_counter_ns() - started) // 1_000
    if completed.returncode != 0:
        raise SystemExit(
            f"issue-23 executable cold sample {iteration} failed with {completed.returncode}: "
            f"{completed.stderr}"
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SystemExit(
            f"issue-23 executable cold sample {iteration} emitted {len(lines)} JSON lines"
        )
    result = json.loads(lines[0])
    if result.get("schema_version") != "latent.phase0.spike.result.v1":
        raise SystemExit("unexpected issue-23 executable result schema")
    if result.get("outcome") != "success":
        raise SystemExit(f"issue-23 executable sample did not succeed: {result.get('outcome')}")
    if result.get("output", {}).get("utf8") != "phase0 executable cold echo":
        raise SystemExit("issue-23 executable sample returned the wrong output")
    if not result.get("shutdown", {}).get("clean"):
        raise SystemExit("issue-23 executable sample did not shut down cleanly")
    topology = result.get("topology", {})
    if not topology.get("unchanged"):
        raise SystemExit("issue-23 executable sample changed topology")
    before = topology.get("before_component_load") or {}
    samples.append(
        {
            "iteration": iteration,
            "launch_to_completion_micros": elapsed_micros,
            "activation_elapsed_micros": int(result.get("elapsed_time_micros", 0)),
            "runtime_workers": int(before.get("runtime_workers", -1)),
            "pool_capacity": int(before.get("pool_capacity", -1)),
            "listener_socket_count": int(before.get("listener_socket_count", -1)),
            "shutdown_clean": True,
            "topology_unchanged": True,
            "output_utf8": result["output"]["utf8"],
            "raw_result": result,
        }
    )

output.write_text(
    json.dumps(
        {
            "schema_version": "latent.phase0.executable-probe.v1",
            "command": base_command,
            "samples": samples,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY

# Capture the launch timestamp in the parent immediately before spawning the
# benchmark process. The child records readiness only after its configured Tokio
# worker lifecycle hooks and fixed pool report the expected topology.
python3 - \
    "${TARGET_ROOT}/release/phase0-baseline" \
    "${STAGED_DIR}/capsule.json" \
    "${OUTPUT_DIR}/executable-harness-probe.json" \
    "${OUTPUT_DIR}/raw-results.json" \
    "${OUTPUT_DIR}/BASELINE.md" \
    "${MODE}" \
    "${POOL_CAPACITY}" \
    "${QUEUE_CAPACITY}" \
    "${RUNTIME_WORKERS}" \
    "${RSS_ALLOWANCE}" \
    "${FD_ALLOWANCE}" <<'PY'
from __future__ import annotations

import subprocess
import sys
import time

(
    binary,
    capsule,
    executable_probe,
    raw_results,
    report,
    mode,
    pool_capacity,
    queue_capacity,
    runtime_workers,
    rss_allowance,
    fd_allowance,
) = sys.argv[1:]

parent_launch_unix_micros = time.time_ns() // 1_000
command = [
    binary,
    "--capsule",
    capsule,
    "--executable-harness-probe",
    executable_probe,
    "--parent-launch-unix-micros",
    str(parent_launch_unix_micros),
    "--output-json",
    raw_results,
    "--output-report",
    report,
    "--mode",
    mode,
    "--pool-capacity",
    pool_capacity,
    "--pool-queue-capacity",
    queue_capacity,
    "--runtime-workers",
    runtime_workers,
    "--rss-growth-allowance-bytes",
    rss_allowance,
    "--fd-growth-allowance",
    fd_allowance,
]
completed = subprocess.run(command, check=False)
raise SystemExit(completed.returncode)
PY

python3 - "${OUTPUT_DIR}/raw-results.json" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
document = json.loads(path.read_text(encoding="utf-8"))
if document.get("schema_version") != "latent.phase0.baseline.v2":
    raise SystemExit("unexpected Phase 0 baseline schema")
if document.get("status") != "pass":
    failures = [
        check.get("name", "unknown")
        for check in document.get("checks", [])
        if not check.get("passed", False)
    ]
    raise SystemExit(f"Phase 0 baseline invariants failed: {failures}")
if len(document.get("executable_harness", {}).get("samples", [])) < 3:
    raise SystemExit("independent issue-23 cold-start evidence is missing")
if document.get("timings", {}).get("distributions", {}).get(
    "cold_echo_elapsed_micros", {}
).get("samples", 0) < 3:
    raise SystemExit("cold activation distribution is anecdotal")
phase_fields = {
    "acquire_or_queue_wait_micros",
    "contained_execution_micros",
    "backend_resource_cleanup_micros",
    "cell_disposition_micros",
    "post_invocation_cleanup_micros",
    "total_invocation_micros",
}
first_sample = document.get("activation_samples", [{}])[0]
if not phase_fields.issubset(first_sample.get("phase_timings", {})):
    raise SystemExit("structured activation phase timings are incomplete")
saturated = document.get("activation_throughput", {}).get(
    "bounded_queue_saturation", {}
)
config = document.get("config", {})
if saturated.get("maximum_observed_active_leases") != config.get("pool_capacity"):
    raise SystemExit("real activation saturation did not reach pool capacity")
if saturated.get("maximum_observed_queue_depth") != config.get("pool_queue_capacity"):
    raise SystemExit("real activation saturation did not reach queue capacity")
if not saturated.get("queued_acquire_wait_micros"):
    raise SystemExit("queued activation wait distribution is missing")
if not any(
    snapshot.get("process", {}).get("probe_supported")
    for snapshot in document.get("topology_snapshots", [])
):
    raise SystemExit("strict process resource probes were silently unsupported")
PY
