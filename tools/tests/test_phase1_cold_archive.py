"""Cold evidence uses the same bounded archive and mandatory semantic replay."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import validate_phase1_archive as verify
from tools.tests.cold_revision_fixtures import Fixture


class ColdArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="phase1-cold-archive-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.fixture = Fixture(self.source)
        self.aggregate = verify.validate_backend_revision_suite(self.source / "suite.json")
        self.output = self.root / "package"
        self.policy = self.root / "absent-policy.json"
        self.save(self.aggregate)

    def save(self, aggregate):
        (self.source / "aggregate.json").write_bytes(verify.canonical(aggregate))

    def test_complete_smoke_is_recognized_but_cannot_be_published_as_full(self):
        self.assertEqual(verify.evidence_kind(self.source), "cold")
        with self.assertRaisesRegex(ValueError, "requires complete full-population"):
            package.package(self.source, self.output, self.policy)
        self.assertFalse(self.output.exists())

    def test_complete_full_dispatch_replays_extracted_bytes_before_publication(self):
        value = {**self.aggregate, "profile": "full", "status": "complete"}
        self.save(value)

        def replay(path):
            self.assertNotEqual(path.parent, self.source)
            self.assertFalse(self.output.exists())
            self.assertEqual(path.read_bytes(), (self.source / "suite.json").read_bytes())
            return value

        with patch.object(verify, "validate_backend_revision_suite", side_effect=replay) as called:
            package.package(self.source, self.output, self.policy)
            called.assert_called_once()
        self.assertFalse((self.output / "measurement-policy.json").exists())

    def test_rehashed_removed_compiler_proof_fails_real_replay_before_publication(self):
        row = self.fixture.suite["runs"][1]["raw"]
        raw = json.loads((self.source / row["path"]).read_bytes())
        raw["final_observer"]["snapshot"]["compiler"] = None
        self.fixture.replace(row, raw)
        with self.assertRaisesRegex(ValueError, "cold-candidate-pool-unobserved"):
            package.package(self.source, self.output, self.policy)
        self.assertFalse(self.output.exists())

    def test_rehashed_changed_statistic_and_unknown_version_are_rejected(self):
        changed = copy.deepcopy(self.aggregate)
        changed["validated_calls"] = "153"
        self.save(changed)
        with self.assertRaisesRegex(ValueError, "differs from replayed"):
            package.package(self.source, self.output, self.policy)
        self.assertFalse(self.output.exists())
        self.save({**self.aggregate, "schema": "latent.optimization.cold-aggregate.v2"})
        with self.assertRaisesRegex(ValueError, "unsupported evidence schema"):
            verify.evidence_kind(self.source)


if __name__ == "__main__":
    unittest.main()
