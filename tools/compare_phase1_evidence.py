#!/usr/bin/env python3
"""Compare Phase1 observations with a verified Phase0 reference; incompatible deltas stay null."""

import argparse
from pathlib import Path
import sys

try:
    from .phase1_evidence.common import EvidenceError, hash_file, reference, require, write_json
    from .phase1_evidence.comparison import compare
    from .phase1_evidence.phase0 import load_reference
    from .phase1_evidence.replay import validate_aggregate
except ImportError:
    from phase1_evidence.common import EvidenceError, hash_file, reference, require, write_json
    from phase1_evidence.comparison import compare
    from phase1_evidence.phase0 import load_reference
    from phase1_evidence.replay import validate_aggregate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1", required=True, type=Path)
    parser.add_argument("--phase0", required=True, type=Path)
    parser.add_argument("--phase0-runs", type=Path, help="Optional extracted runs directory for reverified, matched warm-echo populations")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        candidate = validate_aggregate(args.phase1)
        prior, validation, warm = load_reference(args.phase0, args.phase0_runs)
        root = args.output.parent
        candidate_reference = reference(args.phase1, root)
        retained_reference = root / "phase0-reference.json"
        if retained_reference.resolve() != args.phase0.resolve():
            if retained_reference.exists():
                require(hash_file(retained_reference) == hash_file(args.phase0), "different-retained-phase0-reference")
            else:
                with retained_reference.open("xb") as destination:
                    destination.write(args.phase0.read_bytes())  # Bounded by load_reference above.
        result = {"schema": "latent.phase1.measurement-comparison.v1", "phase1_completion": "incomplete",
                  "observational_only": True, "candidate": candidate_reference,
                  "reference": reference(retained_reference, root), "reference_validation": validation,
                  **compare(candidate, prior, warm)}
        write_json(args.output, result)
    except (ValueError, OSError, KeyError) as error:
        print("Phase 1 comparison failed: " + (str(error) if isinstance(error, EvidenceError) else "invalid-evidence"), file=sys.stderr)
        return 2
    print("Comparison retained " + str(result["summary"]["comparable_metrics"]) + " comparable metrics; incompatible observations remain explicit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
