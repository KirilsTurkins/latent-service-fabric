"""Owned attempts, real subprocess failures and installed-operator package assembly."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.dev_workflow import build, build_cache, common, paths, project, snapshot, state
from tools.tests.test_dev_contracts import descriptor


class BuildAttempts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root, self.source = self.directory / "controller", self.directory / "source"
        paths.new_directory(self.root)
        paths.new_directory(self.source)
        paths.new_directory(self.source / "src")
        self.python = Path(sys.executable).resolve()
        self.descriptor = descriptor()
        self.descriptor["build"].update(argv=["python", "-I", "stage.py"],
            hostTargets=["windows-x86_64", "linux-x86_64"], timeoutSeconds=10,
            tools=[{"name": "python", "path": self.python.name, "version": "3.13.5",
                    "sha256": paths.digest_file(self.python.parent, self.python.name, 268435456)[0]}])

    def inputs(self, program: bytes):
        paths.write_new(self.source / "src/stage.py", program)
        record, _ = snapshot.observe(self.source, ["src"])
        paths.write_new(self.source / "snapshot.json", common.encode(record))
        return record

    def execute(self, cli: Path | None = None):
        return build.execute(self.root, self.source, self.descriptor, self.python.parent,
            trusted=project.trust_identity(self.descriptor), cli=cli or self.python)

    def test_failed_attempts_are_fresh_and_preserve_accepted_build(self):
        record = self.inputs(b"from pathlib import Path\nimport sys\nPath('../output').mkdir()\nsys.exit(1)\n")
        accepted = {"sourceDirectory": "earlier", "receipt": {"source": "earlier"}}
        state.atomic(self.root, "last-build.json", accepted)
        for _ in range(6 if os.name == "posix" else 2):
            with self.assertRaisesRegex(common.DevError, "guest-build-failed"):
                self.execute()
            self.assertEqual(state.load(self.root, "last-build.json"), accepted)
            self.assertFalse((self.source / "output").exists())
            self.assertEqual(snapshot.observe(self.source, ["src"])[0], record)
            attempts = list((self.root / "builds").iterdir())
            self.assertLessEqual(len(attempts), build_cache.MAX_ATTEMPTS)
            self.assertTrue(all(build_cache.owner(item)["state"] == "failed" for item in attempts))

    def test_build_key_separates_source_recipe_tools_abi_host_target_and_packager(self):
        record = self.inputs(b"pass\n")
        def key(record=record, value=self.descriptor, host="linux-x86_64", packager="sha256:" + "a" * 64):
            return build_cache.identity(record, value, project.trust_identity(value), host, packager)
        initial = key()
        self.assertNotEqual(initial, key(record={**record, "identity": "sha256:" + "d" * 64}))
        self.assertNotEqual(initial, key(host="windows-x86_64"))
        self.assertNotEqual(initial, key(packager="sha256:" + "b" * 64))
        for modify in (lambda v: v["build"]["argv"].append("--changed"),
                       lambda v: v["build"]["tools"][0].update(sha256="sha256:" + "c" * 64),
                       lambda v: v["template"].update(revision="d" * 40)):
            changed = copy.deepcopy(self.descriptor)
            modify(changed)
            self.assertNotEqual(initial, key(value=changed))
        with patch.object(build_cache, "HOST_ABI", "next-reviewed-abi"):
            self.assertNotEqual(initial, key())

    def test_changed_tool_is_rejected_before_allocating_or_running(self):
        self.inputs(b"raise AssertionError('must not execute')\n")
        self.descriptor["build"]["tools"][0]["sha256"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(common.DevError, "guest-tool-digest-mismatch"):
            self.execute()
        self.assertFalse((self.root / "builds").exists())

    def test_observed_cache_overflow_reaps_compiler_and_retains_no_success(self):
        self.inputs(b"from pathlib import Path\nimport time\nPath('../oversized').write_bytes(b'x'*8192)\ntime.sleep(60)\n")
        with patch.object(build_cache, "MAX_BYTES", 4096), self.assertRaisesRegex(common.DevError, "build-cache-byte-limit"):
            self.execute()
        attempt, = (self.root / "builds").iterdir()
        self.assertEqual(build_cache.owner(attempt)["state"], "failed")
        self.assertFalse((self.root / "last-build.json").exists())

    def test_reaped_deadline_can_be_cleaned_without_claiming_remote_outcome(self):
        self.inputs(b"import time\ntime.sleep(60)\n")
        self.descriptor["build"]["timeoutSeconds"] = 1
        with self.assertRaisesRegex(common.DevError, "(?:owned-process-command-deadline|build-deadline-exceeded)") as error:
            self.execute()
        self.assertFalse(error.exception.uncertain)
        attempt, = (self.root / "builds").iterdir()
        self.assertEqual(build_cache.owner(attempt)["state"], "failed")

    @unittest.skipUnless(os.name == "posix", "anchored Linux cache removal")
    def test_uncertain_attempts_are_retained_at_capacity(self):
        record = self.inputs(b"pass\n")
        for _ in range(build_cache.MAX_ATTEMPTS):
            attempt, _, _ = build_cache.allocate(self.root, self.source, record, self.descriptor,
                project.trust_identity(self.descriptor), "linux-x86_64", "sha256:" + "a" * 64)
            build_cache.transition(attempt, "uncertain")
        with self.assertRaisesRegex(common.DevError, "build-cache-full-retained-or-uncertain"):
            self.execute()
        self.assertEqual(len(list((self.root / "builds").iterdir())), build_cache.MAX_ATTEMPTS)

    @unittest.skipUnless(os.environ.get("LSF_DEV_PACKAGER") and os.environ.get("LSF_DEV_BUILD_INPUTS"),
                         "requires actual installed operator and maintained compiled component inputs")
    def test_actual_packager_cache_hit_tampering_and_separate_source_tree(self):
        inputs = Path(os.environ["LSF_DEV_BUILD_INPUTS"])
        payload = self.source / "src/payload"
        paths.new_directory(payload)
        manifest = common.decode(paths.read(inputs, "package-source.json"))
        names = {"package-source.json", "deployment.json", *(item["source"] for item in manifest["layers"])}
        for name in sorted(names):
            paths.relative(name)
            destination = payload / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            paths.write_new(destination, paths.read(inputs, name))
        # This probe stages an already compiled maintained guest. It does not
        # qualify a language compiler; package assembly itself is the real CLI.
        self.inputs(b"import shutil\nshutil.copytree('payload','../output')\n")
        self.descriptor["artifacts"].update(component="output/component.wasm")
        cli = Path(os.environ["LSF_DEV_PACKAGER"])
        first = self.execute(cli)
        self.assertFalse((self.source / "output").exists())
        self.assertEqual(self.execute(cli), first)
        self.assertEqual(len(list((self.root / "builds").iterdir())), 1)
        saved = {"snapshot": first["source"], "trust": first["recipe"], "descriptor": self.descriptor}
        working, receipt = build.accepted(self.root, saved)
        self.assertEqual(receipt, first)
        (working / "output/contracts.json").write_bytes(b"{}")
        with self.assertRaisesRegex(common.DevError, "built-artifact-modified-before-use"):
            build.accepted(self.root, saved)
        with self.assertRaisesRegex(common.DevError, "built-artifact-modified-before-use"):
            self.execute(cli)
        self.assertEqual(state.load(self.root, "last-build.json")["receipt"], first)


if __name__ == "__main__":
    unittest.main()
