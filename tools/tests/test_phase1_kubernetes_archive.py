"""Small transport fixtures with substituted semantic replay; no benchmark claims."""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import phase1_kubernetes_archive as kubernetes
from tools import validate_phase1_archive as archive
from tools.optimization_evidence.common import canonical, sha256


class KubernetesArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="kubernetes-archive-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.output = self.root / "source", self.root / "publication"
        self.source.mkdir()
        for name in ("run", "smoke", "bootstrap", "cluster-cleanup"):
            (self.source / name).mkdir()
        self.owner = "lsf-112-0123456789ab"
        self.original = {"schema": "latent.optimization.docker-aggregate.v1", "status": "complete",
                         "profile": "full", "suite_sha256": "sha256:" + "b" * 64}
        dependency_source = self.root / "dependency-source"
        dependency_source.mkdir()
        self.dependency = self.root / "docker-package"
        self.dependency.mkdir()
        (dependency_source / "aggregate.json").write_bytes(canonical(self.original) + b"\n")
        for name in ("build", "run", "smoke"):
            (dependency_source / name).mkdir()
            (dependency_source / name / "opaque.json").write_bytes(b"{}\r\n")
        (dependency_source / "build" / "never_execute.py").write_bytes(b"raise RuntimeError('evidence executed')\n")
        self.dependency_manifest = package.create_archive(dependency_source, self.dependency, self.root / "unused",
                                                          split_archive=True)
        self.reference = {"schema": kubernetes.REFERENCE_SCHEMA, "archive": self.dependency_manifest["archive"],
            "manifest": archive.file_reference(self.dependency / archive.MANIFEST, self.dependency),
            "aggregate": archive.file_reference(self.dependency / "aggregate.json", self.dependency)}
        (self.source / "docker-reference.json").write_bytes(canonical(self.reference) + b"\n")
        (self.source / "bootstrap" / "bootstrap.json").write_bytes(b"{}\r\n")
        (self.source / "cluster-cleanup" / "cleanup.json").write_bytes(b"{}\r\n")
        self.values, self.derived = {}, {}
        for profile, name in (("full", "run"), ("smoke", "smoke")):
            pairs = kubernetes.model.repetitions(profile)
            plan = kubernetes.model.plan(profile, owner=self.owner)
            offers = plan["workload"]["logical_offers"]
            suite = {"profile": profile}
            (self.source / name / "suite.json").write_bytes(canonical(suite) + b"\n")
            self.derived[profile] = {"status": "passed", "profile": profile, "owner": self.owner,
                                    "plan": plan, "source": {"commit": "d" * 40},
                                    "run_id": "full-02" if profile == "full" else "smoke-04",
                                    "build_source": {"commit": "a" * 40},
                                    "images": {"image_id": "sha256:" + "c" * 64},
                                    "bootstrap": {"identity": "same-bootstrap"}, "finished_nanos": "100"}
            self.values[profile] = {"schema": kubernetes.aggregate.SCHEMA, "status": "complete", "profile": profile,
                "plan": plan, "completed_paired_run": True, "full_population_completed": profile == "full",
                "acceptance_qualified": profile == "full", "validated_pairs": pairs, "logical_offers": offers,
                "acceptance_scope": "complete-descriptive-deployment-comparison", "exact_effective_cpu_match": False,
                "suite_sha256": sha256(canonical(suite) + b"\n"), "build_source": {"commit": "a" * 40},
                "images": {"image_id": "sha256:" + "c" * 64},
                "counts": {"offers": offers, "successful": offers, "seed_management_rpcs": "0", "seed_invokes": "0",
                           "measured_application_owners": 44 * pairs, "client_owners": pairs},
                **{name: [{"case": "arithmetic-fixture", "metrics": {"value": None}}]
                   for name in kubernetes.aggregate.TABLES}}
        self.cleanup = {"started_nanos": "101", "finished_nanos": "102"}
        self.retain()

    def retain(self):
        result = self.values["full"]
        outputs = {"aggregate.json": canonical(result) + b"\n",
                   "docker-aggregate.json": canonical(self.original) + b"\n"}
        outputs.update({name.replace("_", "-") + ".csv": kubernetes.docker_aggregate._csv_bytes(result[name])
                        for name in kubernetes.aggregate.TABLES})
        for name, data in outputs.items():
            (self.source / name).write_bytes(data)
        manifest = {"schema": kubernetes.model.PREFIX + "aggregate-files.v1", "profile": "full",
            "suite_sha256": result["suite_sha256"], "docker_suite_sha256": self.original["suite_sha256"],
            "csv_null": "literal-null", "files": [{"path": name, "bytes": str(len(data)), "sha256": sha256(data)}
                                                    for name, data in outputs.items()]}
        (self.source / "manifest.json").write_bytes(canonical(manifest) + b"\n")
        (self.source / "smoke" / "aggregate.json").write_bytes(canonical(self.values["smoke"]) + b"\n")

    def mocks(self):
        stack = ExitStack()
        stack.enter_context(patch.object(kubernetes, "DOCKER_ARCHIVE_SHA256", self.reference["archive"]["sha256"]))
        stack.enter_context(patch.object(archive, "verify_docker"))
        stack.enter_context(patch.object(kubernetes.replay, "validate", side_effect=self.replay))
        stack.enter_context(patch.object(kubernetes.aggregate, "aggregate", side_effect=lambda row, _: self.values[row["profile"]]))
        stack.enter_context(patch.object(kubernetes.docker_aggregate, "aggregate", return_value=self.original))
        stack.enter_context(patch.object(kubernetes, "_cluster_cleanup", return_value=self.cleanup))
        stack.enter_context(patch("subprocess.Popen", side_effect=AssertionError("archive source must stay inert")))
        return stack

    def replay(self, root, build, docker, bootstrap):
        self.assertEqual(build.parent, docker.parent)
        self.assertNotEqual(build.parent, self.root / "dependency-source")
        self.assertEqual((build / "never_execute.py").read_bytes(), b"raise RuntimeError('evidence executed')\n")
        self.assertEqual(bootstrap, root.parent / "bootstrap")
        return self.derived["full" if root.name == "run" else "smoke"], {"status": "passed", "original": True}

    def verify(self):
        with self.mocks():
            return kubernetes.verify(self.source, docker_package=self.dependency)

    def snapshot(self, root):
        return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def test_complete_split_package_replays_dependency_and_both_campaigns_without_execution(self):
        before, dependency_before = self.snapshot(self.source), self.snapshot(self.dependency)
        with self.mocks(), patch.object(kubernetes.replay, "validate", side_effect=self.replay) as replayed:
            manifest = package.package(self.source, self.output, self.root / "unused", split_archive=True,
                                       docker_package=self.dependency)
            self.assertEqual(archive.verify_package(self.output, docker_package=self.dependency), manifest)
        self.assertEqual([call.args[0].name for call in replayed.call_args_list], ["run", "smoke", "run", "smoke"])
        self.assertEqual(self.snapshot(self.source), before)
        self.assertEqual(self.snapshot(self.dependency), dependency_before)
        self.assertEqual({row["path"] for row in manifest["files"]}, set(before))

    def test_separate_smoke_cleanup_completion_must_precede_cluster_teardown(self):
        completion = {"started_nanos": "101", "finished_nanos": "103", "new_guest_invokes": 0}
        self.derived["smoke"]["cleanup_completion"] = completion
        with self.assertRaisesRegex(ValueError, "cluster-cleanup-precedes-completion"):
            self.verify()
        self.cleanup = {"started_nanos": "104", "finished_nanos": "105"}
        self.assertEqual(self.verify()["smoke_cleanup_completion"], completion)
        self.assertEqual(self.derived["smoke"]["finished_nanos"], "100")

    def test_dependency_is_required_before_packaging_and_only_for_kubernetes(self):
        with self.assertRaisesRegex(ValueError, "requires --docker-package"):
            package.package(self.source, self.output, self.root / "unused")
        self.assertFalse(self.output.exists())
        with self.assertRaisesRegex(ValueError, "only valid for Kubernetes"):
            archive.verify_package(self.dependency, docker_package=self.dependency)
        self.assertEqual(archive.archive_file_limit("kubernetes"), 5000)
        self.assertEqual(archive.archive_bounds("kubernetes")[0], 1024**3)
        self.assertEqual(archive.MAX_SPLIT_COMPRESSED, 198_000_000)
        self.assertEqual(archive.MAX_PART_BYTES, 50_000_000)

    def test_original_dependency_hash_is_not_replaceable(self):
        with self.assertRaisesRegex(ValueError, "not-original-campaign"):
            kubernetes.verify(self.source, docker_package=self.dependency)

    def test_dependency_reference_and_extracted_bytes_are_rechecked(self):
        original = kubernetes.phase0_evidence.extract_tar_stream

        def changed(stream, destination, label, **options):
            result = original(stream, destination, label, **options)
            if label == "original Docker dependency":
                (destination / "build" / "opaque.json").write_bytes(b"changed")
            return result

        with self.mocks(), patch.object(kubernetes.phase0_evidence, "extract_tar_stream", side_effect=changed), \
             self.assertRaisesRegex(ValueError, "extraction-checksum"):
            kubernetes.verify(self.source, docker_package=self.dependency)
        value = deepcopy(self.reference)
        value["manifest"]["sha256"] = "sha256:" + "0" * 64
        (self.source / "docker-reference.json").write_bytes(canonical(value))
        with self.assertRaisesRegex(ValueError, "reference-mismatch"):
            self.verify()

    def test_changed_table_manifest_or_smoke_bytes_cannot_qualify(self):
        for name, reason in (("phase-rows.csv", "table-bytes"), ("manifest.json", "table-manifest"),
                             ("smoke/aggregate.json", "smoke-aggregate"), ("docker-aggregate.json", "table-bytes")):
            with self.subTest(name=name):
                (self.source / name).write_bytes(b"{}\n")
                with self.assertRaisesRegex(ValueError, reason):
                    self.verify()
                self.retain()

    def test_population_flags_and_owner_types_are_strict(self):
        baseline = deepcopy(self.values)
        for profile in ("full", "smoke"):
            for field, value in (("validated_pairs", True), ("acceptance_qualified", 1),
                                 ("full_population_completed", 0), ("logical_offers", "1")):
                with self.subTest(profile=profile, field=field):
                    self.values = deepcopy(baseline)
                    self.values[profile][field] = value
                    self.retain()
                    with self.assertRaisesRegex(ValueError, "complete full and smoke"):
                        self.verify()
        self.values = deepcopy(baseline)
        self.values["smoke"]["counts"]["client_owners"] = True
        self.retain()
        with self.assertRaisesRegex(ValueError, "owner-populations"):
            self.verify()

    def test_private_bootstrap_subtree_is_rejected_even_when_empty(self):
        (self.source / "bootstrap" / "private").mkdir()
        with self.assertRaisesRegex(ValueError, "private-credentials"):
            self.verify()

    def test_cleanup_is_mandatory_and_after_both_campaigns(self):
        self.cleanup["started_nanos"] = "99"
        with self.assertRaisesRegex(ValueError, "cleanup-precedes"):
            self.verify()
        self.cleanup["started_nanos"] = "101"
        with self.mocks(), patch.object(kubernetes, "_cluster_cleanup", side_effect=ValueError("actual-cleanup-failed")), \
             self.assertRaisesRegex(ValueError, "actual-cleanup-failed"):
            kubernetes.verify(self.source, docker_package=self.dependency)

    def test_crossed_dependency_bootstrap_and_unrecognized_extra_roots_reject(self):
        self.derived["smoke"]["bootstrap"] = {"identity": "different"}
        with self.assertRaisesRegex(ValueError, "crossed-bootstrap"):
            self.verify()
        self.derived["smoke"]["bootstrap"] = self.derived["full"]["bootstrap"]
        (self.source / "unrecognized.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "unrecognized-root"):
            self.verify()

    def failure_fixture(self):
        attempts = self.source / "attempts"
        attempts.mkdir()
        failed = attempts / "smoke-01"
        failed.mkdir()
        # These deliberately opaque rows exercise indexing, not recovery semantics.
        (failed / "suite.json").write_bytes(b'{"failure":{"reason":"original failure"}}\r\n')
        (failed / "api.ndjson").write_bytes(b'{"failure":"original transport failure"}\r\n')
        recovered = {"schema": kubernetes.model.PREFIX + "campaign-recovery.v1",
                     "started_nanos": "60", "finished_nanos": "80", "new_guest_invokes": 0}
        (failed / "recovery.json").write_bytes(canonical(recovered) + b"\n")
        row = {"directory": "smoke-01", "qualified": False,
               **{key: archive.file_reference(failed / (key + ".json"), attempts) for key in ("suite", "recovery")}}
        index = {"schema": kubernetes.model.PREFIX + "failed-attempts.v1", "attempts": [row]}
        (attempts / "index.json").write_bytes(canonical(index) + b"\n")
        return attempts, index, recovered

    def prior_smoke_fixture(self):
        root = self.source / "prior-smokes"
        campaign = root / "smoke-03"
        campaign.mkdir(parents=True)
        (campaign / "suite.json").write_bytes(b'{"profile":"smoke"}\n')
        (campaign / "aggregate.json").write_bytes(canonical(self.values["smoke"]) + b"\n")
        index = {"schema": kubernetes.model.PREFIX + "prior-smokes.v1", "campaigns": [{
            "directory": "smoke-03", **{key: archive.file_reference(campaign / (key + ".json"), root)
                                          for key in ("suite", "aggregate")}}]}
        (root / "index.json").write_bytes(canonical(index) + b"\n")
        derived = {**self.derived["smoke"], "run_id": "smoke-03", "finished_nanos": "70",
                   "cleanup_completion": {"finished_nanos": "80"}}
        return root, index, (self.values["smoke"], derived, {"status": "passed", "original": True})

    def prior_smokes(self):
        return kubernetes._prior_smokes(self.source, self.root / "dependency-source",
            self.source / "bootstrap", self.derived["full"], {"status": "passed", "original": True}, "101")

    def test_prior_completed_smoke_replays_separately_without_changing_current_offer_counts(self):
        root, index, prior = self.prior_smoke_fixture()
        before = self.snapshot(root)
        with patch.object(kubernetes, "_campaign", return_value=prior) as replayed:
            result = self.prior_smokes()
        replayed.assert_called_once_with(root / "smoke-03", self.root / "dependency-source",
                                         self.source / "bootstrap", "smoke")
        self.assertEqual(result["index"], index)
        self.assertEqual(result["campaigns"][0]["aggregate"]["logical_offers"], "300")
        self.assertEqual(self.values["full"]["logical_offers"], "9926")
        self.assertEqual(self.snapshot(root), before)

    def test_prior_smoke_requires_matching_bytes_dependencies_and_cleanup_order(self):
        root, index, prior = self.prior_smoke_fixture()
        path = root / "smoke-03/aggregate.json"
        original_bytes = path.read_bytes()
        path.write_bytes(b"changed")
        with patch.object(kubernetes, "_campaign", return_value=prior) as replayed, self.assertRaises(ValueError):
            self.prior_smokes()
        replayed.assert_not_called()
        path.write_bytes(original_bytes)
        for field, value in (("images", {"wrong": "image"}), ("run_id", "smoke-02"),
                             ("cleanup_completion", {"finished_nanos": "102"})):
            with self.subTest(field=field):
                changed = (prior[0], {**prior[1], field: value}, prior[2])
                with patch.object(kubernetes, "_campaign", return_value=changed), self.assertRaises(ValueError):
                    self.prior_smokes()
        with patch.object(kubernetes, "_campaign", side_effect=ValueError("prior-semantic-failure")), \
             self.assertRaisesRegex(ValueError, "prior-semantic-failure"):
            self.prior_smokes()

    def test_prior_smoke_index_rejects_duplicate_unindexed_and_wrong_path_entries(self):
        root, original, prior = self.prior_smoke_fixture()
        for change in ("duplicate", "path", "name", "unindexed"):
            with self.subTest(change=change):
                index = deepcopy(original)
                if change == "duplicate":
                    index["campaigns"] *= 2
                elif change == "path":
                    index["campaigns"][0]["suite"]["path"] = "smoke-03/aggregate.json"
                elif change == "name":
                    index["campaigns"][0]["directory"] = "../smoke-03"
                else:
                    (root / "unindexed").mkdir()
                (root / "index.json").write_bytes(canonical(index))
                with patch.object(kubernetes, "_campaign", return_value=prior), self.assertRaises(ValueError):
                    self.prior_smokes()

    def test_indexed_failed_attempt_is_replayed_without_adding_qualified_offers(self):
        attempts, index, recovered = self.failure_fixture()
        before = self.snapshot(attempts)
        with self.mocks(), patch.object(kubernetes, "_failure", return_value=recovered) as replayed:
            result = kubernetes.verify(self.source, docker_package=self.dependency)
        replayed.assert_called_once_with(attempts / "smoke-01", self.source / "bootstrap")
        self.assertEqual(result["failed_attempts"], {"index": index, "recoveries": [recovered]})
        self.assertEqual(result["full"]["logical_offers"], "9926")
        self.assertEqual(result["smoke"]["logical_offers"], "300")
        self.assertEqual(self.snapshot(attempts), before)

    def test_failed_index_requires_exact_paths_unique_coverage_and_false_qualification(self):
        attempts, baseline, recovered = self.failure_fixture()
        variants = []
        for key, value in (("directory", "../smoke-01"), ("qualified", 0), ("qualified", True)):
            mutated = deepcopy(baseline)
            mutated["attempts"][0][key] = value
            variants.append(mutated)
        mutated = deepcopy(baseline)
        mutated["attempts"][0]["suite"]["path"] = "smoke-01/api.ndjson"
        variants.append(mutated)
        mutated = deepcopy(baseline)
        mutated["attempts"] *= 2
        variants.append(mutated)
        for mutated in variants:
            with self.subTest(index=mutated):
                (attempts / "index.json").write_bytes(canonical(mutated))
                with patch.object(kubernetes, "_failure", return_value=recovered), self.assertRaises(ValueError):
                    kubernetes._failed_attempts(self.source, self.source / "bootstrap", "101")
        (attempts / "index.json").write_bytes(canonical(baseline))
        (attempts / "unindexed").mkdir()
        with patch.object(kubernetes, "_failure", return_value=recovered), \
             self.assertRaisesRegex(ValueError, "index-coverage"):
            kubernetes._failed_attempts(self.source, self.source / "bootstrap", "101")

    def test_failed_attempt_hash_recovery_validation_and_final_cleanup_order_are_required(self):
        attempts, index, recovered = self.failure_fixture()
        path = attempts / "smoke-01" / "suite.json"
        original = path.read_bytes()
        path.write_bytes(b"changed")
        with patch.object(kubernetes, "_failure", return_value=recovered) as checked, self.assertRaises(ValueError):
            kubernetes._failed_attempts(self.source, self.source / "bootstrap", "101")
        checked.assert_not_called()
        path.write_bytes(original)
        with patch.object(kubernetes, "_failure", side_effect=ValueError("actual-recovery-rejected")), \
             self.assertRaisesRegex(ValueError, "actual-recovery-rejected"):
            kubernetes._failed_attempts(self.source, self.source / "bootstrap", "101")
        with patch.object(kubernetes, "_failure", return_value=recovered), \
             self.assertRaisesRegex(ValueError, "recovery-after-cluster-cleanup"):
            kubernetes._failed_attempts(self.source, self.source / "bootstrap", "79")
        changed = {**recovered, "finished_nanos": "81"}
        with patch.object(kubernetes, "_failure", return_value=changed), \
             self.assertRaisesRegex(ValueError, "return-binding"):
            kubernetes._failed_attempts(self.source, self.source / "bootstrap", "101")

    def test_inline_failed_attempt_returns_original_suite_without_recovery_or_qualified_offers(self):
        attempts = self.source / "attempts"
        failed = attempts / "smoke-02"
        failed.mkdir(parents=True)
        original = {"failure": {"reason": "original failure"}, "started_nanos": "50", "finished_nanos": "80"}
        (failed / "suite.json").write_bytes(canonical(original) + b"\n")
        index = {"schema": kubernetes.model.PREFIX + "failed-attempts.v1", "attempts": [{"directory": "smoke-02",
            "qualified": False, "suite": archive.file_reference(failed / "suite.json", attempts), "recovery": None}]}
        (attempts / "index.json").write_bytes(canonical(index))
        dependency = self.root / "dependency-source"
        with patch.object(kubernetes, "_failure", return_value=original) as replayed:
            result = kubernetes._failed_attempts(self.source, self.source / "bootstrap", "101", dependency=dependency)
        replayed.assert_called_once_with(failed, self.source / "bootstrap", build_root=dependency / "build", docker_root=dependency / "run")
        self.assertEqual(result["recoveries"], [original])
        with patch.object(kubernetes, "_failure", return_value=original), self.assertRaisesRegex(ValueError, "inline-recovery"):
            kubernetes._failed_attempts(self.source, self.source / "bootstrap", "101")
        (failed / "recovery.json").write_bytes(b"{}")
        with patch.object(kubernetes, "_failure", return_value=original), self.assertRaisesRegex(ValueError, "inline-recovery"):
            kubernetes._failed_attempts(self.source, self.source / "bootstrap", "101", dependency=dependency)
if __name__ == "__main__":
    unittest.main()
