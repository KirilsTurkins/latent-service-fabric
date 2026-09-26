"""Synthetic contract checks; manual OCI measurements are separate evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_oci import SUITE, validate_observations
from tools.phase3_resource_rust import artifact_from_cargo


def report():
    owner = {"processId": 1, "threadCount": 1, "socketCount": 0, "residentMemoryBytes": 4096}
    rows = []
    for ceiling in (1, 2):
        for kind in ("token", "dns", "redirect"):
            for phase in ("fixed", "active", "recovery", "cold", "warm", "warm", "warm", "shutdown"):
                active, closed = phase == "active", phase == "shutdown"
                rows.append({"kind": kind, "ceiling": ceiling, "phase": phase, "os": dict(owner),
                    "elapsedNanos": "1" if phase in ("cold", "warm") else None,
                    "usage": {"inFlight": ceiling if active else 0, "retainedPackages": 0,
                              "retainedBytes": 0, "closed": closed},
                    "bearer": {"activeAcquisitions": int(active and kind == "token"),
                        "waitingAcquisitions": ceiling - 1 if active and kind == "token" else 0,
                        "reservedAcquisitionBytes": 0, "retainedTokenBytes": 0,
                        "maximumTokenBytes": 1024, "cachedTokens": 0, "closed": closed},
                    "network": {"connections": 0, "reservedConnectionBytes": 0,
                        "maximumConnections": 2, "maximumConnectionBytes": 65536,
                        "activeResolvers": int(active and kind == "dns"),
                        "waitingResolvers": ceiling - 1 if active and kind == "dns" else 0,
                        "reservedResolverBytes": 160, "retainedDnsAnswers": 0,
                        "reservedRedirectBytes": ceiling * 16384 if active and kind == "redirect" else 0,
                        "closed": closed}})
    return {"schemaVersion": "latent.phase3.oci-resource.v1", "status": "checkpoint-passed",
            "ceilings": [1, 2], "cyclesPerPool": 4, "universalPerformanceClaim": False,
            "fixed": dict(owner), "retired": dict(owner), "observations": rows}


class OciResourceTests(unittest.TestCase):
    def test_library_artifact_ignores_ordinary_rlib_but_requires_exact_test_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            manifest = root / SUITE.manifest
            source = manifest.parent / SUITE.source
            executable = root / "target/debug/deps/synthetic-oci"
            for path in (manifest, source, executable):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic")
            tested = {"reason": "compiler-artifact", "manifest_path": str(manifest),
                "target": {"name": SUITE.target, "kind": ["lib"], "src_path": str(source)},
                "profile": {"test": True}, "executable": str(executable)}
            ordinary = {**tested, "profile": {"test": False}, "executable": None}
            finished = {"reason": "build-finished", "success": True}

            def parse(rows):
                return artifact_from_cargo(b"\n".join(json.dumps(row).encode() for row in rows), root, suite=SUITE)

            self.assertEqual(parse([ordinary, tested, finished])[0].executable, executable)
            for rows in ([ordinary, finished], [tested, tested, finished],
                         [{**tested, "target": {**tested["target"], "kind": ["test"]}}, finished],
                         [{**tested, "executable": str(source)}, finished]):
                with self.assertRaises(WorkflowError):
                    parse(rows)

    def test_retained_resolver_configuration_is_distinct_from_active_ownership(self):
        self.assertTrue(validate_observations(report(), None))
        for group, field in (("network", "activeResolvers"), ("network", "waitingResolvers"),
                             ("network", "connections"), ("network", "reservedRedirectBytes"),
                             ("bearer", "activeAcquisitions"), ("bearer", "waitingAcquisitions"),
                             ("usage", "inFlight"), ("usage", "retainedBytes")):
            changed = report()
            changed["observations"][2][group][field] = 1
            with self.assertRaisesRegex(WorkflowError, "ownership-retained"):
                validate_observations(changed, None)

    def test_incomplete_population_unbounded_cost_or_unreaped_peer_cannot_pass(self):
        original = report()
        changed = copy.deepcopy(original)
        changed["observations"].pop()
        with self.assertRaisesRegex(WorkflowError, "population"):
            validate_observations(changed, None)
        for group, field, value in (("network", "connections", 3), ("network", "reservedConnectionBytes", 65537),
                                    ("bearer", "retainedTokenBytes", 1025), ("usage", "inFlight", True)):
            changed = copy.deepcopy(original)
            changed["observations"][1][group][field] = value
            with self.assertRaises(WorkflowError):
                validate_observations(changed, None)
        changed = copy.deepcopy(original)
        changed["retired"]["socketCount"] = 1
        with self.assertRaisesRegex(WorkflowError, "peer-retirement"):
            validate_observations(changed, None)
        changed = copy.deepcopy(original)
        changed["observations"][4]["bearer"]["retainedTokenBytes"] = 1
        with self.assertRaisesRegex(WorkflowError, "cache-plateau"):
            validate_observations(changed, None)


if __name__ == "__main__":
    unittest.main()
