"""Archive adapter/transport tests; substituted replay is not workload evidence."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import phase1_docker_archive as docker
from tools import validate_phase1_archive as archive


class DockerArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="docker-archive-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.output = self.root / "source", self.root / "publication"
        self.source.mkdir()
        for name in ("build", "run", "smoke"):
            (self.source / name).mkdir()
        self.values = {}
        for profile, name in (("full", "run"), ("smoke", "smoke")):
            pairs = docker.model.repetitions(profile)
            plan = docker.model.plan(profile)
            self.values[profile] = {
                "schema": docker.aggregate.SCHEMA, "profile": profile, "status": "complete",
                "plan": plan, "completed_paired_run": True,
                "full_population_completed": profile == "full", "acceptance_qualified": profile == "full",
                "validated_pairs": pairs, "logical_offers": plan["logical_offers"],
                "counts": {"offers": plan["logical_offers"], "successful": plan["logical_offers"],
                           "seed_management_rpcs": "88", "seed_invokes": "0",
                           "measured_application_owners": str(44 * pairs), "client_owners": str(pairs),
                           "all_containers_removed": str(45 * pairs + 3), "api_calls": "0"},
                "build_source": {"commit": "a" * 40}, "images": {"image_id": "sha256:" + "b" * 64},
            }
            (self.source / name / "suite.json").write_bytes(archive.canonical({"profile": profile}))
        # These are opaque transport fixtures, not a fabricated valid build.
        (self.source / "build" / "docker-builds.json").write_bytes(b"{}\r\n")
        (self.source / "build" / "must_not_execute.py").write_bytes(b"raise RuntimeError('archived source executed')\n")
        (self.source / "run" / "original.log").write_bytes(b"original\r\nbytes\x00\xff")
        self.retain()

    def retain(self):
        for path, profile in ((self.source / "aggregate.json", "full"),
                              (self.source / "smoke" / "aggregate.json", "smoke")):
            path.write_bytes(archive.canonical(self.values[profile]) + b"\n")

    def bytes(self, root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*") if path.is_file()}

    def replay(self, root, build):
        self.assertEqual(build, root.parent / "build")
        self.assertIn(root.name, ("run", "smoke"))
        profile = json.loads((root / "suite.json").read_bytes())["profile"]
        return {"status": "passed", "profile": profile}

    def assemble(self, derived):
        return self.values[derived["profile"]]

    def verify(self):
        with patch.object(docker.evidence, "validate", side_effect=self.replay), \
             patch.object(docker.aggregate, "aggregate", side_effect=self.assemble):
            return docker.verify(self.source)

    def publish(self, **options):
        return package.package(self.source, self.output, self.root / "unused-policy", **options)

    def test_discriminator_preserves_all_existing_archive_bounds(self):
        self.assertEqual(archive.evidence_kind(self.source), "docker")
        self.assertEqual(archive.archive_bounds("docker"), (1024**3, 1024**3))
        self.assertEqual(archive.MAX_FILES, 5000)
        self.assertEqual(archive.MAX_COMPRESSED, 99_000_000)
        self.assertEqual(archive.MAX_SPLIT_COMPRESSED, 198_000_000)
        self.assertEqual(archive.MAX_PART_BYTES, 50_000_000)

    def test_package_replays_both_extracted_campaigns_and_preserves_original_bytes(self):
        before = self.bytes(self.source)
        calls = []

        def extracted_replay(root, build):
            self.assertNotEqual(root.parent, self.source)
            self.assertFalse(self.output.exists())
            self.assertEqual(self.bytes(root.parent), before)
            calls.append((root, build))
            return self.replay(root, build)

        with patch.object(docker.evidence, "validate", side_effect=extracted_replay), \
             patch.object(docker.aggregate, "aggregate", side_effect=self.assemble), \
             patch("subprocess.Popen", side_effect=AssertionError("archive must not execute")):
            manifest = self.publish()
        self.assertEqual([row[0].name for row in calls], ["run", "smoke"])
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertEqual({row["path"] for row in manifest["files"]}, set(before))
        self.assertEqual(self.bytes(self.source), before)
        self.assertEqual((self.output / "aggregate.json").read_bytes(), before["aggregate.json"])

    def test_split_transport_uses_the_same_semantic_replay(self):
        with patch.object(docker.evidence, "validate", side_effect=self.replay) as checked, \
             patch.object(docker.aggregate, "aggregate", side_effect=self.assemble):
            manifest = self.publish(split_archive=True)
            self.assertEqual(archive.verify_package(self.output), manifest)
        self.assertEqual(checked.call_count, 4)
        self.assertFalse((self.output / archive.ARCHIVE).exists())
        parts = json.loads((self.output / archive.PARTS_MANIFEST).read_bytes())
        self.assertEqual(len(parts["parts"]), 2)

    def test_each_retained_aggregate_must_exactly_equal_replay(self):
        for profile in ("full", "smoke"):
            with self.subTest(profile=profile):
                original = deepcopy(self.values)
                self.values[profile]["changed_metric"] = "1"
                with patch.object(docker.evidence, "validate", side_effect=self.replay), \
                     patch.object(docker.aggregate, "aggregate", side_effect=self.assemble), \
                     self.assertRaisesRegex(ValueError, "differs from replayed"):
                    docker.verify(self.source)
                self.values = original

    def test_missing_smoke_cannot_publish_and_does_not_edit_source(self):
        (self.source / "smoke" / "aggregate.json").unlink()
        before = self.bytes(self.source)
        with patch.object(docker.evidence, "validate", side_effect=self.replay), \
             patch.object(docker.aggregate, "aggregate", side_effect=self.assemble), \
             self.assertRaises(ValueError):
            self.publish()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.bytes(self.source), before)

    def test_profile_swap_and_unvalidated_campaign_fail_before_aggregation(self):
        for value in ({"status": "passed", "profile": "smoke"},
                      {"status": "failed", "profile": "full"}):
            with self.subTest(value=value), \
                 patch.object(docker.evidence, "validate", return_value=value), \
                 patch.object(docker.aggregate, "aggregate") as assembled, \
                 self.assertRaisesRegex(ValueError, "campaign-profile"):
                docker.verify(self.source)
            assembled.assert_not_called()

    def test_flags_and_fixed_population_require_exact_types_and_values(self):
        baseline = deepcopy(self.values)
        for profile in ("full", "smoke"):
            mutations = (("schema", "other"), ("profile", "other"), ("status", "failed"),
                         ("completed_paired_run", 1), ("full_population_completed", 1),
                         ("acceptance_qualified", 0), ("validated_pairs", True),
                         ("logical_offers", "299"), ("plan", {}))
            for field, value in mutations:
                with self.subTest(profile=profile, field=field):
                    self.values = deepcopy(baseline)
                    self.values[profile][field] = value
                    self.retain()
                    with self.assertRaisesRegex(ValueError, "complete full and smoke populations"):
                        self.verify()
        self.values = baseline
        self.retain()

    def test_incomplete_offers_successes_seeds_or_owners_cannot_publish(self):
        baseline = deepcopy(self.values)
        for profile in ("full", "smoke"):
            for field in baseline[profile]["counts"].keys() - {"api_calls"}:
                with self.subTest(profile=profile, field=field):
                    self.values = deepcopy(baseline)
                    self.values[profile]["counts"][field] = "999999"
                    self.retain()
                    with self.assertRaisesRegex(ValueError, "offer-and-owner-populations"):
                        self.verify()
        self.values = baseline
        self.retain()

    def test_crossed_build_or_image_identity_rejects_even_matching_aggregates(self):
        for key in ("build_source", "images"):
            with self.subTest(key=key):
                original = deepcopy(self.values)
                self.values["smoke"][key] = {"crossed": True}
                self.retain()
                with self.assertRaisesRegex(ValueError, "crossed-build-or-images"):
                    self.verify()
                self.values = original
                self.retain()

    def test_separately_bound_collector_commits_need_not_relabel_the_build(self):
        self.values["full"]["source"] = {"commit": "c" * 40}
        self.values["smoke"]["source"] = {"commit": "d" * 40}
        self.retain()
        self.assertEqual(set(self.verify()), {"full", "smoke"})

    def test_replay_failure_never_publishes_or_discards_originals(self):
        before = self.bytes(self.source)
        with patch.object(docker.evidence, "validate", side_effect=ValueError("actual-replay-failed")), \
             self.assertRaisesRegex(ValueError, "actual-replay-failed"):
            self.publish()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.bytes(self.source), before)


if __name__ == "__main__":
    unittest.main()
