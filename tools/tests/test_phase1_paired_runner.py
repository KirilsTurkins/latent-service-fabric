"""Controlled runs must preserve failed attempts and reject changed inputs."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_phase1_paired as runner


class PairedRunnerTests(unittest.TestCase):
    def test_control_artifact_cannot_escape_or_change_after_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "fixture"
            fixture.write_bytes(b"original")
            reference = runner.reference(fixture, root)
            self.assertEqual(runner.checked_reference(root, reference), fixture)
            for name in ("../fixture", "/fixture", "a/../../fixture", "C:/fixture", "a\\fixture"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    runner.checked_reference(root, {**reference, "path": name})
            fixture.write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError, "hash/size mismatch"):
                runner.checked_reference(root, reference)

    @unittest.skipUnless(sys.platform == "linux", "actual Linux process identity and working directory")
    def test_historical_child_runs_in_declared_source_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "historical"
            source.mkdir()
            receipt = {}
            raw = runner.bounded_run([sys.executable, "-c", "import os; print(os.getcwd())"],
                                     root / "child.log", 2, os.environ.copy(), receipt, cwd=source)
            self.assertEqual(raw.decode().strip(), str(source))
            self.assertTrue(receipt["reaped"])
            self.assertTrue(receipt["output_closed"])
            self.assertEqual(receipt["exit_code"], 0)

    def test_failed_control_is_retained_and_candidate_never_started(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "evidence"
            output.mkdir()
            target = root / "target"
            component = target / "capsules/echo/echo-capsule.wasm"
            component.parent.mkdir(parents=True)
            component.write_bytes(b"test guest")
            for name in ("capsule.json", "contracts.json", "build.json"):
                (component.parent / name).write_text("{}\n")
            binary = target / "collector"
            binary.write_bytes(b"test executable")
            capsule = target / "capsule.json"
            capsule.write_text("{}\n")
            for logical in runner.HISTORICAL_METHOD_SOURCES:
                path = root / logical
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("// retained historical source\n")
            receipt = output / "reproduction/control/build-receipt.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text("{}\n")
            binary_sha, binary_bytes = runner.digest(binary)
            guest_sha, guest_bytes = runner.digest(component)
            identity = {"source": {"dirty": False, "commit": runner.HISTORICAL_COMMIT},
                        "binary": {"sha256": binary_sha, "bytes": str(binary_bytes)},
                        "fixtures": [{"name": "echo", "sha256": guest_sha, "bytes": str(guest_bytes)}]}

            def fail(command, log, timeout, env, receipt=None, cwd=None):
                log.write_text("attempt failed\n")
                receipt.update({"process_id": 123, "start_time_ticks": "456", "reaped": True,
                                "output_closed": True, "exit_code": 7})
                raw = Path(command[command.index("--output-json") + 1])
                raw.write_text('{"partial":true}\n')
                raise RuntimeError("driver exited 7")

            with (patch.object(runner, "retain_control", return_value=(identity, binary, component, capsule)),
                  patch.object(runner, "source_identity", return_value=identity["source"]),
                  patch.object(runner, "build_candidate_fixture"),
                  patch.object(runner, "build", return_value=binary),
                  patch.object(runner, "capture", return_value=identity),
                  patch.object(runner, "host", return_value={"os": "Linux"}),
                  patch.object(runner, "bounded_run", side_effect=fail) as child):
                with self.assertRaisesRegex(RuntimeError, "exited 7"):
                    runner.run("smoke", output, target, root, root)
                self.assertEqual(child.call_count, 1)
            suite = json.loads((output / "suite.json").read_text())
            self.assertEqual(len(suite["runs"]), 1)
            attempt = suite["runs"][0]
            self.assertEqual((attempt["arm"], attempt["status"]), ("control", "failed"))
            self.assertEqual(attempt["raw"]["path"], "pair-01/control/baseline.json")
            process = json.loads((output / attempt["process"]["path"]).read_text())
            self.assertEqual(process["exit_code"], 7)
            self.assertTrue(json.loads((output / attempt["cleanup"]["path"]).read_text())["removed"])
            self.assertTrue(any(row["path"].endswith("collector.log") for row in suite["artifacts"]))


if __name__ == "__main__":
    unittest.main()
