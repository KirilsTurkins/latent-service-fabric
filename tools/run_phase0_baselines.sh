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

# This gate is intentionally mandatory. It verifies every checked-in contract,
# builds both real Wasm components, and exercises the lower-level containment
# suite. A missing target or external tool therefore cannot silently skip the
# baseline fixtures.
tools/validate_contracts.sh

ECHO_CAPSULE="${TARGET_ROOT}/capsules/echo/capsule.json"
CONTAINMENT_COMPONENT="${TARGET_ROOT}/capsules/containment/containment-capsule.wasm"
STAGED_DIR="${TARGET_ROOT}/phase0-baseline/staged-containment"

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
cargo build -p latentd --bin phase0-baseline --release --locked

"${TARGET_ROOT}/release/phase0-baseline" \
    --capsule "${STAGED_DIR}/capsule.json" \
    --output-json "${OUTPUT_DIR}/raw-results.json" \
    --output-report "${OUTPUT_DIR}/BASELINE.md" \
    --mode "${MODE}" \
    --pool-capacity "${LSF_BASELINE_POOL_CAPACITY:-2}" \
    --pool-queue-capacity "${LSF_BASELINE_QUEUE_CAPACITY:-4}" \
    --runtime-workers "${LSF_BASELINE_RUNTIME_WORKERS:-2}" \
    --rss-growth-allowance-bytes "${LSF_BASELINE_RSS_ALLOWANCE_BYTES:-67108864}" \
    --fd-growth-allowance "${LSF_BASELINE_FD_ALLOWANCE:-2}"

python3 - "${OUTPUT_DIR}/raw-results.json" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
document = json.loads(path.read_text(encoding="utf-8"))
if document.get("schema_version") != "latent.phase0.baseline.v1":
    raise SystemExit("unexpected Phase 0 baseline schema")
if document.get("status") != "pass":
    failures = [
        check.get("name", "unknown")
        for check in document.get("checks", [])
        if not check.get("passed", False)
    ]
    raise SystemExit(f"Phase 0 baseline invariants failed: {failures}")
if not document.get("activation_samples"):
    raise SystemExit("Phase 0 baseline emitted no activation samples")
if not any(
    snapshot.get("probe_supported")
    for snapshot in document.get("process_snapshots", [])
):
    raise SystemExit("strict process resource probes were silently unsupported")
PY
