"""Immutable data-only staging controls; these do not execute a signed guest."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import patch

from tools import java_fiber_fault_inputs as inputs


class JavaFiberFaultInputsTests(unittest.TestCase):
    def origin(self):
        return [
            {"id": inputs.RUN, "head_sha": inputs.HEAD,
             "head_branch": "fix/sdk-java-model-counts-20261118", "event": "pull_request",
             "path": ".github/workflows/java-guest-feasibility.yml", "status": "completed", "conclusion": "failure"},
            {"id": inputs.JOB, "run_id": inputs.RUN, "status": "completed", "conclusion": "failure",
             "name": "Actual Java sources, SDK ownership and enforced node", "steps": [
                 {"name": "Prepare the opt-in Java fibers and reference JDK controls", "status": "completed", "conclusion": "success"},
                 {"name": "Execute signed activation threads with actual physical cleanup", "status": "completed", "conclusion": "failure"}]},
            {"id": inputs.ARTIFACT, "expired": False, "name": "java-guest-feasibility-" + inputs.MERGE,
             "size_in_bytes": inputs.ARCHIVE[0], "digest": "sha256:" + inputs.ARCHIVE[1],
             "workflow_run": {"id": inputs.RUN, "head_sha": inputs.HEAD}}]

    def fixture(self, root, *, duplicate=False, symlink=False):
        source, component, wit = b"unchanged source", b"retained component", b"original world"
        record = {"fixture": "threads", "profile": "teavm-activation-fibers-v1",
                  "status": "component-built-unqualified", "qualification": "pending", "nodeExecution": "not-run",
                  "componentDigest": "sha256:" + hashlib.sha256(component).hexdigest(),
                  "sourceDigest": "sha256:" + hashlib.sha256(source).hexdigest(),
                  "completableModel": {"status": "actual-locked-classlib-model-passed", "modelMethodBodies": 205,
                                       "actualGeneratedCallbacks": 28,
                                       "fieldReferences": "actual-declared-and-inherited-types-passed"}}
        files = {"src/Capsule.java": source, "build/component.wasm": component,
                 "wit/service.wit": wit, "FIBERS-COMPILE.json": json.dumps(record).encode()}
        path = root / "archive.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w") as archive:
                for name, data in files.items():
                    member = zipfile.ZipInfo(inputs.PREFIX + name)
                    if symlink and name == "src/Capsule.java":
                        member.create_system = 3
                        member.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(member, data)
                if duplicate:
                    archive.writestr(inputs.PREFIX + "src/Capsule.java", source)
                archive.writestr("unselected/private/compiler-cache", b"must never be staged")
        pins = {name: inputs.identity(data) for name, data in files.items()}
        return path, files, pins

    def test_origin_requires_exact_failed_stage_not_an_earlier_setup_failure(self):
        original = self.origin()
        inputs.validate_origin(*original)
        for index, key, bad in ((0, "head_sha", "wrong"), (0, "event", "workflow_dispatch"),
                                (0, "conclusion", "success"), (1, "id", 1), (1, "steps", []),
                                (2, "expired", True), (2, "digest", "sha256:" + "0" * 64),
                                (2, "workflow_run", {"id": inputs.RUN, "head_sha": "wrong"})):
            values = deepcopy(original)
            values[index][key] = bad
            with self.subTest(index=index, key=key), self.assertRaises(ValueError):
                inputs.validate_origin(*values)
        values = deepcopy(original)
        values[1]["steps"][0]["conclusion"] = "failure"
        with self.assertRaisesRegex(ValueError, "original-stage"):
            inputs.validate_origin(*values)

    def test_only_four_verified_inputs_are_staged_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, files, pins = self.fixture(root)
            with patch.object(inputs, "ARCHIVE", inputs.identity(archive.read_bytes())), \
                    patch.object(inputs, "FILES", pins), \
                    patch("subprocess.Popen", side_effect=AssertionError("no execution")):
                inputs.stage(archive, root / "out", files["src/Capsule.java"])
            observed = {p.relative_to(root / "out").as_posix() for p in (root / "out").rglob("*") if p.is_file()}
            self.assertEqual(observed, set(files) | {"fault-inputs.json"})
            for name, data in files.items():
                self.assertEqual((root / "out" / name).read_bytes(), data)
            report = json.loads((root / "out/fault-inputs.json").read_bytes())
            self.assertFalse(report["runtimeQualified"])
            self.assertFalse(report["guestCompiled"])

    def test_digest_source_and_existing_output_mismatches_fail_closed(self):
        for variant in ("archive", "member", "source", "output"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive, files, pins = self.fixture(root)
                archive_pin = inputs.identity(archive.read_bytes())
                expected = files["src/Capsule.java"]
                if variant == "archive":
                    archive_pin = (archive_pin[0], "0" * 64)
                elif variant == "member":
                    pins["build/component.wasm"] = (pins["build/component.wasm"][0], "0" * 64)
                elif variant == "source":
                    expected += b"changed"
                else:
                    (root / "out").mkdir()
                    (root / "out/sentinel").write_bytes(b"keep")
                with patch.object(inputs, "ARCHIVE", archive_pin), patch.object(inputs, "FILES", pins), \
                        self.assertRaises(ValueError):
                    inputs.stage(archive, root / "out", expected)
                if variant == "output":
                    self.assertEqual((root / "out/sentinel").read_bytes(), b"keep")
                else:
                    self.assertFalse((root / "out").exists())

    def test_duplicate_and_symlink_members_never_reach_output(self):
        for variant in ("duplicate", "symlink"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive, files, pins = self.fixture(root, **{variant: True})
                with patch.object(inputs, "ARCHIVE", inputs.identity(archive.read_bytes())), \
                        patch.object(inputs, "FILES", pins), self.assertRaises(ValueError):
                    inputs.stage(archive, root / "out", files["src/Capsule.java"])
                self.assertFalse((root / "out").exists())

    def test_metadata_reads_are_bounded_and_refuse_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").write_bytes(b"abcd")
            self.assertEqual(inputs.bounded(root / "data", 4), b"abcd")
            with self.assertRaisesRegex(ValueError, "input-bound"):
                inputs.bounded(root / "data", 3)
            with patch.object(Path, "is_symlink", return_value=True), self.assertRaisesRegex(ValueError, "regular-input"):
                inputs.bounded(root / "data", 4)

    def test_workflow_is_branch_scoped_read_only_and_keeps_original_failure(self):
        workflow = (inputs.ROOT / ".github/workflows/java-fiber-fault.yml").read_text()
        for required in ("github.event.pull_request.number == 2156", "github.event.pull_request.head.repo.full_name == github.repository",
                         "github.head_ref == 'fix/sdk-java-model-counts-20261118'", "contents: read", "actions: read",
                         "--features java-checkpoint-gc-trap-diagnostic", "--ignored --exact --nocapture",
                         "runtime::signed_java_threads_spin_join_and_thread_local_use_real_activation_fibers",
                         "set -euo pipefail", "if: always()", "save-if: false", "head -c 75006715"):
            self.assertIn(required, workflow)
        for forbidden in ("workflow_dispatch:", "continue-on-error:", "qualify_java_fibers.py",
                          "gradle", "javac", "--all-features", "|| true"):
            self.assertNotIn(forbidden, workflow)


if __name__ == "__main__":
    unittest.main()
