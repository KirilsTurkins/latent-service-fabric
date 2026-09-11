"""Finite real-byte fixture/copy checks; no Node or Docker process is launched."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.optimization_docker import fixtures
from tools.optimization_runner import fixtures as legacy

ROOT = Path(__file__).resolve().parents[2]
STOP = {"container_id": "a" * 64, "exit_code": 0, "running": False, "child_reaped": True,
        "output_closed": True, "copy_tasks_joined": True, "invokes": 0}


class DensityFixtures(unittest.TestCase):
    def test_all_32_are_distinct_and_original_five_bytes_stay_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # A valid empty component is sufficient for this byte-transform unit
            # test; actual build/Node acceptance uses the maintained guest export.
            component = root / "base.wasm"
            component.write_bytes(b"\0asm\x0d\0\x01\0")
            old = legacy.materialize(component, root / "old")
            value = fixtures.materialize(component, root / "new", root=root, repository=ROOT)
            self.assertEqual(len(value["publications"]), 32)
            self.assertEqual(len({row["component"]["sha256"] for row in value["publications"]}), 32)
            for index, row in enumerate(value["publications"]):
                self.assertEqual(row["index"], index)
                self.assertEqual(row["service"], fixtures.SERVICES[index])
                wasm = (root / row["component"]["path"]).read_bytes()
                self.assertTrue(wasm.startswith(component.read_bytes()))
                if index:
                    self.assertEqual(wasm[-1], index)
                    self.assertIn(b"optimization-working-set-v1", wasm)
                capsule = json.loads((root / row["capsule"]["path"]).read_bytes())
                deployment = json.loads((root / row["deployment"]["path"]).read_bytes())
                self.assertEqual(capsule["component"]["digest"], row["component"]["sha256"])
                self.assertEqual(deployment["spec"]["release"], row["component"]["sha256"])
                self.assertEqual(capsule["metadata"], {"name": row["service"], "tenant": "optimization"})
                if index < 5:
                    for new_key, old_key in (("component", "component"), ("capsule", "manifest"),
                                             ("contracts", "contracts"), ("deployment", "deployment")):
                        self.assertEqual((root / row[new_key]["path"]).read_bytes(), old[index][old_key].read_bytes())
            self.assertEqual(component.read_bytes(), b"\0asm\x0d\0\x01\0")

    def test_config_changes_only_declared_density_and_loopback_fields(self):
        expected = legacy.node_configuration(Path("/data"))
        expected["dataDirectory"] = "/data"
        expected["bind"] = "127.0.0.1:7071"
        expected["cache"]["entries"] = 32
        expected["catalogs"] = {"releaseEntries": 64, "deployments": 64}
        self.assertEqual(fixtures.node_configuration(), expected)
        self.assertEqual(expected["limits"]["maximumConnections"], 32)

    def test_core_module_is_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            component = root / "base.wasm"
            component.write_bytes(b"\0asm\x01\0\0\0")
            with self.assertRaisesRegex(ValueError, "not-component"):
                fixtures.materialize(component, root / "new", root=root, repository=ROOT)
            self.assertFalse((root / "new").exists())


class StoppedTemplateCopies(unittest.TestCase):
    def test_exact_stopped_copy_preserves_empty_directories_bytes_and_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "template"
            (source / "empty").mkdir(parents=True)
            (source / "catalog").mkdir()
            (source / "catalog/state.json").write_bytes(b'{"actual":"node-produced"}\n')
            (source / "catalog/state.json").chmod(0o600)
            receipt = fixtures.seal_template(source, density=32, stop_receipt=STOP)
            copied = fixtures.copy_template(source, root / "copy", receipt)
            self.assertEqual(copied["inventory"], fixtures.inventory(source))
            self.assertEqual(fixtures.inventory(root / "copy"), fixtures.inventory(source))
            self.assertTrue((root / "copy/empty").is_dir())
            self.assertEqual(copied["source_stop"], STOP)

    def test_live_failed_unreaped_invoked_or_untyped_receipts_cannot_seal(self):
        with tempfile.TemporaryDirectory() as temporary:
            for key, value in (("running", True), ("exit_code", 1), ("child_reaped", False),
                               ("output_closed", False), ("copy_tasks_joined", False),
                               ("invokes", 1), ("invokes", False), ("container_id", "a" * 12)):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "clean-zero-invoke-stop"):
                    fixtures.seal_template(Path(temporary), density=1, stop_receipt={**STOP, key: value})

    def test_changed_template_and_changed_receipt_fail_before_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "template"
            source.mkdir()
            (source / "state").write_bytes(b"a")
            receipt = fixtures.seal_template(source, density=8, stop_receipt=STOP)
            crossed = copy.deepcopy(receipt)
            crossed["inventory"]["bytes"] = "0"
            for supplied in (crossed, receipt):
                if supplied is receipt:
                    (source / "state").write_bytes(b"b")
                with self.assertRaisesRegex(ValueError, "receipt-mismatch"):
                    fixtures.copy_template(source, root / "copy", supplied)
                self.assertFalse((root / "copy").exists())

    def test_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "template"
            source.mkdir()
            try:
                (source / "link").symlink_to(root / "outside")
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(ValueError, "entry-type"):
                fixtures.seal_template(source, density=1, stop_receipt=STOP)


if __name__ == "__main__":
    unittest.main()
