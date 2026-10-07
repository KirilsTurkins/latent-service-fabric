"""Generator failure receipts distinguish confirmed retirement from cleanup failure."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.application_dependency_tools import execute, specification
from tools.build_process import BuildProcessError
from tools.build_snapshot import canonical, digest


class GeneratorFailureReceipts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        (self.inputs / "header.h").write_bytes(b"#define SELECTED 17\n")
        self.tool = self.root / "generator"
        self.tool.write_bytes(b"#!/bin/sh\ncp /inputs/header.h /outputs/generated.h\n")

    def failed(self, reason):
        # The native control driver separately runs actual Bubblewrap and deadline/descendant retirement.
        selected = specification(self.tool, [], self.inputs, tool_version="finite-v1")
        with patch("tools.application_dependency_tools.sys.platform", "linux"), \
                patch("tools.application_dependency_tools.shutil.which", return_value="/recorded/bwrap"), \
                patch("tools.application_dependency_tools.read_bytes", side_effect=lambda _path: b"selected-tool"), \
                patch("tools.application_dependency_tools.specification", return_value=selected), \
                patch("tools.application_dependency_tools.run_bounded_result", side_effect=BuildProcessError(reason)):
            approved = digest(canonical(selected))
            receipt = self.root / "receipt.json"
            with self.assertRaisesRegex(BuildProcessError, "^" + reason + "$" ):
                execute(self.tool, [], self.inputs, self.root / "outputs", receipt,
                        tool_version="finite-v1", approved_identity=approved)
        return json.loads(receipt.read_text(encoding="utf-8"))

    def test_cleanup_and_ownership_failures_never_claim_reaped(self):
        for reason in ("process-cleanup", "process-ownership", "process-ownership-retired"):
            with self.subTest(reason=reason):
                self.root = self.root / reason
                self.root.mkdir()
                record = self.failed(reason)
                self.assertEqual(record["status"], "failed")
                self.assertEqual(record["cleanup"], "unconfirmed")
                self.assertNotIn("failureReason", record)


class GeneratorNativeFailureReceipts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "linux" or not shutil.which("bwrap"):
            if os.environ.get("LSF_REQUIRE_COMPILER_ISOLATION") == "1":
                raise RuntimeError("required generator namespace tools are missing")
            raise unittest.SkipTest("actual generator retirement requires Linux Bubblewrap")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        (self.inputs / "header.h").write_bytes(b"#define SELECTED 17\n")
        self.tool = self.root / "generator"

    def native_failure(self, source, reason, **limits):
        self.tool.write_text(source, encoding="ascii")
        self.tool.chmod(0o700)
        approved = digest(canonical(specification(self.tool, [], self.inputs, tool_version="finite-v1")))
        outputs, receipt = self.root / "outputs", self.root / "receipt.json"
        with self.assertRaisesRegex(BuildProcessError, "^" + reason + "$" ):
            execute(self.tool, [], self.inputs, outputs, receipt,
                    tool_version="finite-v1", approved_identity=approved, **limits)
        progress = outputs / "progress"
        size = progress.stat().st_size
        time.sleep(0.1)
        self.assertEqual(progress.stat().st_size, size, "failed generator descendant remains active")
        record = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["cleanup"], "reaped")
        self.assertEqual(record["failureReason"], reason)
        self.assertNotIn("exitCode", record)
        self.assertNotIn("outputs", record)

    def test_actual_deadline_keeps_failed_status_and_reaped_descendants(self):
        self.native_failure('#!/bin/sh\nprintf x > /outputs/progress\n'
            'while :; do printf x >> /outputs/progress; done &\nwait\n',
            "command-deadline", timeout_seconds=0.25)

    def test_actual_output_overflow_keeps_failed_status_and_reaped_descendants(self):
        self.native_failure('#!/bin/sh\nprintf x > /outputs/progress\n'
            'while :; do printf x >> /outputs/progress; done &\n'
            'while :; do printf 012345678901234567890123456789; done\n',
            "command-output-limit", maximum_output_bytes=4096)


class GeneratorSandboxDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        GeneratorNativeFailureReceipts.setUpClass()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="generator-host-discovery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        (self.inputs / "header.h").write_bytes(b"#define SELECTED 17\n")
        self.tool = self.root / "generator"
        self.tool.write_bytes(b"#!/bin/sh\ncat /inputs/header.h > /outputs/generated.h\n")
        self.tool.chmod(0o700)
        self.sandbox = Path(shutil.which("bwrap")).resolve(strict=True)

    def test_discovered_host_sandbox_alias_executes_with_canonical_byte_identity(self):
        alias = self.root / "host-bwrap"
        alias.symlink_to(self.sandbox)
        approved = digest(canonical(specification(self.tool, [], self.inputs, tool_version="finite-v1")))
        outputs, receipt = self.root / "outputs", self.root / "receipt.json"
        with patch("tools.application_dependency_tools.shutil.which", return_value=str(alias)):
            observed = execute(self.tool, [], self.inputs, outputs, receipt,
                               tool_version="finite-v1", approved_identity=approved)
        self.assertEqual(observed["status"], "succeeded")
        self.assertEqual(observed["cleanup"], "reaped")
        self.assertEqual(observed["sandboxDigest"], digest(self.sandbox.read_bytes()))
        self.assertEqual((outputs / "generated.h").read_bytes(), b"#define SELECTED 17\n")
        self.assertEqual((self.inputs / "header.h").read_bytes(), b"#define SELECTED 17\n")
        self.assertEqual(json.loads(receipt.read_bytes()), observed)

    def test_untrusted_executable_input_and_output_links_still_fail_before_dispatch(self):
        from tools.application_dependency_store import DependencyError
        tool_link, input_link, output_link = (self.root / name for name in
                                             ("tool-link", "input-link", "output-link"))
        tool_link.symlink_to(self.tool)
        input_link.symlink_to(self.inputs, target_is_directory=True)
        target = self.root / "unrelated-output"
        target.mkdir()
        (target / "original.bin").write_bytes(b"unrelated original")
        output_link.symlink_to(target, target_is_directory=True)
        approved = digest(canonical(specification(self.tool, [], self.inputs, tool_version="finite-v1")))
        for tool, inputs, outputs in ((tool_link, self.inputs, self.root / "tool-output"),
                                     (self.tool, input_link, self.root / "input-output"),
                                     (self.tool, self.inputs, output_link)):
            with self.subTest(tool=tool, inputs=inputs, outputs=outputs), \
                    patch("tools.application_dependency_tools.run_bounded_result") as dispatched:
                with self.assertRaisesRegex(DependencyError, "dependency-link-denied"):
                    execute(tool, [], inputs, outputs, self.root / "denied-receipt.json",
                            tool_version="finite-v1", approved_identity=approved)
                dispatched.assert_not_called()
                self.assertFalse((self.root / "denied-receipt.json").exists())
        self.assertEqual((target / "original.bin").read_bytes(), b"unrelated original")


if __name__ == "__main__":
    unittest.main()
