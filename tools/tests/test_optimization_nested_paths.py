"""Relative replay retains exact nested-file association and path rejection."""
from contextlib import chdir
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.artifact_identity_runner.files import reference
from tools.optimization_backend_revision.evidence import Artifacts as BackendArtifacts, validate_suite
from tools.optimization_cache_lookup.files import Artifacts as CacheArtifacts
from tools.optimization_evidence.common import canonical, read_json
from tools.tests.cache_behavior_fixtures import Fixture as BehaviorFixture
from tools.tests.test_optimization_backend_revision_suite import Fixture as BackendFixture


ROOT = Path(__file__).resolve().parents[2]


class NestedPathReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nested-path-replay-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()

    def test_real_behavior_graph_replays_identically_from_relative_root(self):
        for variant in ("control", "candidate"):
            with self.subTest(variant=variant):
                fixture = BehaviorFixture(self.directory / variant, variant)
                absolute = fixture.parse()
                with chdir(self.directory):
                    fixture.root = Path(variant)
                    relative = fixture.parse()
                self.assertEqual(canonical(absolute), canonical(relative))
                self.assertEqual(relative["samples"], "80")

    def test_whole_backend_suite_and_fresh_relative_cli_replay_match(self):
        root = self.directory / "backend"
        root.mkdir()
        fixture = BackendFixture(root)
        absolute = validate_suite(fixture.root / "suite.json")
        with chdir(self.directory):
            relative = validate_suite(Path("backend/suite.json"))
        self.assertEqual(canonical(absolute), canonical(relative))
        self.assertEqual(relative["validated_calls"], "12")
        output = self.directory / "cli-aggregate.json"
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools/validate_optimization_backend_revision.py"),
             "backend/suite.json", "--output", str(output)],
            cwd=self.directory, capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
        self.assertLess(len(completed.stdout) + len(completed.stderr), 4096)
        self.assertEqual(canonical(absolute), canonical(read_json(output)))

    def containers(self, root, rows):
        yield BackendArtifacts(root, rows, set())
        yield CacheArtifacts(root, rows)

    def test_nested_binding_works_for_absolute_relative_and_normalized_roots(self):
        root = self.directory / "evidence"
        parent = root / "nested"
        parent.mkdir(parents=True)
        target = parent / "metadata.json"
        target.write_text('{"identity":"owned"}\n', encoding="utf-8")
        rows = [reference(target, root)]
        nested = reference(target, parent)
        with chdir(self.directory):
            for form in (root, Path("evidence"), Path("evidence/nested/..")):
                for artifacts in self.containers(form, rows):
                    with self.subTest(kind=type(artifacts).__module__, root=str(form)):
                        actual = artifacts.nested(form / "nested", nested)
                        self.assertEqual(actual, target)

    def test_relative_fix_preserves_path_digest_size_and_registration_rejections(self):
        root = self.directory / "evidence"
        parent = root / "nested"
        parent.mkdir(parents=True)
        target = parent / "metadata.json"
        target.write_bytes(b"owned\n")
        unregistered = parent / "unregistered.json"
        unregistered.write_bytes(b"other\n")
        rows = [reference(target, root)]
        nested = reference(target, parent)
        rejected = [
            dict(nested, sha256="sha256:" + "0" * 64),
            dict(nested, bytes=str(int(nested["bytes"]) + 1)),
            reference(unregistered, parent),
            *[dict(nested, path=name) for name in
              ("../metadata.json", "/metadata.json", "nested\\metadata.json", "C:/metadata.json")],
        ]
        with chdir(self.directory):
            for form in (root, Path("evidence")):
                for artifacts in self.containers(form, rows):
                    for row in rejected:
                        with self.subTest(kind=type(artifacts).__module__, root=str(form), row=row):
                            with self.assertRaises(ValueError):
                                artifacts.nested(form / "nested", row)

    def test_fresh_hash_cannot_replace_the_registered_nested_identity(self):
        root = self.directory / "evidence"
        parent = root / "nested"
        parent.mkdir(parents=True)
        target = parent / "metadata.json"
        original = b"original\n"
        with chdir(self.directory):
            for form in (root, Path("evidence")):
                target.write_bytes(original)
                rows = [reference(target, root)]
                containers = list(self.containers(form, rows))
                target.write_bytes(b"replacement\n")
                rehashed = reference(target, parent)
                for artifacts in containers:
                    with self.subTest(kind=type(artifacts).__module__, root=str(form)):
                        with self.assertRaisesRegex(ValueError, "unregistered-.*nested-artifact"):
                            artifacts.nested(form / "nested", rehashed)


if __name__ == "__main__":
    unittest.main()
