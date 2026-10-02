"""Source-only stopped-candidate and ordering tests; no native grant evidence."""
from __future__ import annotations

import copy
from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.java_transaction_qualification import configuration as cfg, evidence, inputs, policies, provider, staging
from tools import run_java_transaction_http_qualification as conductor
from tools.tests.test_java_transaction_campaign import retirement

BOOT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
START = 1_000_000_000
WALL = 1_700_000_000_000_000_000


def observed_time(now=START + 5_000_000_000, *, wall=None, boot=BOOT):
    result = ExitStack()
    result.enter_context(patch.object(staging, "boot_id", return_value=boot))
    result.enter_context(patch.object(staging.time, "monotonic_ns", return_value=now))
    result.enter_context(patch.object(staging.time, "time_ns", return_value=WALL + now - START if wall is None else wall))
    return result


def original_clock():
    return {"bootId": BOOT, "startedMonotonicNanos": START, "startedUnixNanos": WALL,
            "deadlineMonotonicNanos": START + 120_000_000_000, "timeoutSeconds": 120}


def publications():
    return {name: "publication:sha256:" + str(index) * 64
            for index, name in enumerate(inputs.VARIANTS) if name != "forbidden-http"}


class ClockOracle(unittest.TestCase):
    def test_pause_consumes_original_deadline_without_renewing_or_certifying_continuity(self):
        clock = original_clock()
        with observed_time(START + 5_000_000_000):
            first = staging.deadline(clock, 120)
        with observed_time(START + 110_000_000_000):
            resumed = staging.deadline(clock, 120)
        self.assertEqual(first, resumed)
        self.assertEqual(clock, original_clock())
        self.assertNotIn("continuityProven", clock)

    def test_expiry_boot_change_wall_drift_and_deadline_extension_refuse(self):
        for change in ("expired", "boot", "wall", "extended"):
            clock = original_clock()
            now, boot, wall = START + 5_000_000_000, BOOT, None
            if change == "expired":
                now = clock["deadlineMonotonicNanos"]
            elif change == "boot":
                boot = "ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee"
            elif change == "wall":
                wall = WALL + now - START + 1_000_000_001
            else:
                clock["deadlineMonotonicNanos"] += 1
            with self.subTest(change=change), observed_time(now, boot=boot, wall=wall), self.assertRaises(ValueError):
                staging.deadline(clock, 120)

    def test_boolean_overflow_unknown_clock_fields_and_changed_timeout_refuse(self):
        for key, value in (("timeoutSeconds", True), ("startedMonotonicNanos", -1),
                           ("startedUnixNanos", 2**64), ("continuityProven", True)):
            clock = dict(original_clock(), **{key: value})
            with self.subTest(key=key), observed_time(), self.assertRaises(ValueError):
                staging.deadline(clock, 120)
        with observed_time(), self.assertRaises(ValueError):
            staging.deadline(original_clock(), 119)


class CandidateOracle(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        for name in ("client", "node", "recipient", "tls", "portable", "packages"):
            (self.root / name).mkdir(mode=0o700)
        (self.root / "packages/signed").mkdir(mode=0o700)
        (self.root / "recipient-token").write_bytes(b"source-only-fixture-secret")
        self.full = self.root / "full.json"
        self.full.write_bytes(evidence.encoded({"state": {"operations": [{"fixtureOnly": True}]}}))
        self.bootstrap = self.root / "bootstrap.json"
        self.bootstrap.write_bytes(evidence.encoded({"state": {"operations": [], "clockCheckpoint": "original-clock"}}))
        self.collector = evidence.Evidence(self.root / "evidence")
        self.collector.write("original.stdout", b"original stopped source observation")
        self.collector.passed("source-observation", {"nativeExecutionQualified": False})
        self.client = SimpleNamespace(node=None, calls=17, evidence=self.collector)
        self.node = SimpleNamespace(process=None, ordinal=1, directory=self.root / "node", shutdown=[{
            "reaped": True, "record": {"report": retirement()}}])
        stopped = dict.fromkeys(provider.COUNTERS, 0)
        stopped.update(schemaVersion="latent.synthetic.put-once-recipient.v1", providerIncarnation="a" * 64,
                       recipientDeliveryQualified=False, connections=0, refusedConnections=0)
        self.peer = SimpleNamespace(directory=self.root / "recipient", port=32123, incarnation="a" * 64,
                                    shutdown={"reaped": True, "record": stopped})
        self.args = SimpleNamespace(output=self.root, resume_candidate=self.root / staging.NAME,
            candidate_digest=None, native_source_commit="a" * 40, conductor_source_commit="b" * 40,
            portable=self.root / "portable", timeout=120)
        self.record = {"nativeTools": {"fixture": inputs.digest(b"source-only-native-identity")},
                       "collectorDigests": {"fixture": inputs.digest(b"source-only-collector")},
                       "originalInputs": [{"signedNodeExecutionQualified": False}]}
        self.prepared = {"bootstrap": "bootstrap.json", "full": "full.json", "signed": "packages/signed",
            "authority": "localhost:32124", "origin": {"scheme": "https", "host": "localhost", "port": 32123},
            "publications": publications(), "proposals": {"fixtureOnly": True}, "mutations": [{"fixtureOnly": True}],
            "catalog": {"sourceOnly": "original receipts"}, "hosts": {"sourceOnly": "original native tuple"}}

    def capture(self):
        with observed_time():
            result = staging.capture(self.root, original_clock(), self.args, self.record,
                                     self.prepared, self.client, self.node, self.peer)
        self.args.candidate_digest = result["digest"]
        return result

    def retain(self, *, tools=None, collectors=None):
        with observed_time():
            return staging.retain(self.args, self.record["nativeTools"] if tools is None else tools,
                                  self.record["collectorDigests"] if collectors is None else collectors)

    def replace_document(self, value):
        # A changed review digest still cannot bypass a closed-envelope guard.
        raw = evidence.encoded(value)
        self.args.resume_candidate.write_bytes(raw)
        self.args.candidate_digest = inputs.digest(raw)

    def test_exact_stopped_candidate_keeps_original_inputs_sessions_paths_and_clock(self):
        self.capture()
        original = self.args.resume_candidate.read_bytes()
        retained, deadline = self.retain()
        self.assertEqual(retained["prepared"], self.prepared)
        self.assertEqual((retained["node"]["ordinal"], retained["cliCalls"], retained["recipient"]["session"]), (1, 17, 1))
        self.assertEqual((retained["recipient"]["port"], retained["recipient"]["incarnation"]), (32123, "a" * 64))
        self.assertEqual(deadline, original_clock()["deadlineMonotonicNanos"] / 1_000_000_000)
        config = staging.configuration(self.root, retained["prepared"])
        self.assertEqual(config.path, self.bootstrap)
        self.assertEqual(config.value["state"]["clockCheckpoint"], "original-clock")
        self.assertEqual(self.args.resume_candidate.read_bytes(), original)
        self.assertFalse((self.root / staging.CLAIM).exists())

    def test_changed_unknown_or_removed_retained_files_refuse_without_consumption(self):
        self.capture()
        raw = self.full.read_bytes()
        for change in ("changed", "unknown", "missing"):
            if change == "changed":
                self.full.write_bytes(raw + b" ")
            elif change == "unknown":
                (self.root / "unexpected").write_bytes(b"new")
            else:
                self.full.unlink()
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.retain()
            self.full.write_bytes(raw)
            if (self.root / "unexpected").exists():
                (self.root / "unexpected").unlink()
            self.assertFalse((self.root / staging.CLAIM).exists())

    def test_source_tools_collector_and_exact_review_digest_drift_refuse(self):
        self.capture()
        for change in ("source", "tools", "collector", "digest"):
            original_source, original_digest = self.args.native_source_commit, self.args.candidate_digest
            tools, collectors = self.record["nativeTools"], self.record["collectorDigests"]
            if change == "source":
                self.args.native_source_commit = "c" * 40
            elif change == "tools":
                tools = {"fixture": inputs.digest(b"changed-native")}
            elif change == "collector":
                collectors = {"fixture": inputs.digest(b"changed-collector")}
            else:
                self.args.candidate_digest = inputs.digest(b"another reviewed document")
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.retain(tools=tools, collectors=collectors)
            self.args.native_source_commit, self.args.candidate_digest = original_source, original_digest
        self.assertFalse((self.root / staging.CLAIM).exists())

    def test_capture_requires_positive_teardown_and_no_application_provider_requests(self):
        for change in ("live", "not-reaped", "native-owner", "provider-request"):
            node, peer = copy.deepcopy(self.node), copy.deepcopy(self.peer)
            if change == "live":
                node.process = object()
            elif change == "not-reaped":
                peer.shutdown["reaped"] = False
            elif change == "native-owner":
                node.shutdown[0]["record"]["report"]["liveStores"] = 1
            else:
                peer.shutdown["record"].update(requests=1, connections=1)
            with self.subTest(change=change), self.assertRaises(ValueError):
                staging.capture(self.root, original_clock(), self.args, self.record,
                                self.prepared, self.client, node, peer)
            self.assertFalse(self.args.resume_candidate.exists())

    def test_unknown_envelope_fields_boolean_counts_and_escaping_paths_refuse(self):
        self.capture()
        original = inputs.decode(self.args.resume_candidate.read_bytes())
        for change in ("approval", "calls", "session", "path", "requests"):
            value = copy.deepcopy(original)
            if change == "approval":
                value["approved"] = True
            elif change == "calls":
                value["cliCalls"] = True
            elif change == "session":
                value["recipient"]["session"] = True
            elif change == "path":
                value["prepared"]["signed"] = "../another-package"
            else:
                value["recipient"]["shutdown"]["record"].update(requests=1, connections=1)
            self.replace_document(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.retain()
        for relative in ("../escape", "/absolute", "a\\b", "a//b", "a/./b", "x\nsecret", "é" * 257):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                staging.path(self.root, relative)

    def test_candidate_use_is_one_shot_and_preserves_original_review_bytes_on_failure(self):
        self.capture()
        before = self.args.resume_candidate.read_bytes()
        staging.claim(self.root, self.args.candidate_digest)
        used = (self.root / staging.CLAIM).read_bytes()
        with self.assertRaises(FileExistsError):
            staging.claim(self.root, self.args.candidate_digest)
        with self.assertRaises(ValueError):
            self.retain()
        self.assertEqual((self.root / staging.CLAIM).read_bytes(), used)
        self.assertEqual(self.args.resume_candidate.read_bytes(), before)
        self.assertNotIn("applicationStateCommitted", inputs.decode(used))

    def test_census_refuses_hardlinks_excessive_entries_and_directory_depth(self):
        link = self.root / "linked.json"
        link.hardlink_to(self.full)
        with self.assertRaises(ValueError):
            staging.files(self.root)
        link.unlink()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(4097):
                (root / str(index)).touch()
            with self.assertRaises(ValueError):
                staging.files(root)
        with tempfile.TemporaryDirectory() as temporary:
            root, current = Path(temporary), Path(temporary)
            for _ in range(17):
                current /= "deep"
                current.mkdir()
            with self.assertRaises(ValueError):
                staging.files(root)


class EvidenceResumeOracle(unittest.TestCase):
    def test_retention_preserves_exclusive_bytes_cases_and_remaining_capacity(self):
        with tempfile.TemporaryDirectory() as temporary:
            original = evidence.Evidence(Path(temporary) / "evidence")
            original.passed("source-only", {"nativeExecutionQualified": False})
            before = (original.directory / "case-source-only.json").read_bytes()
            resumed = evidence.Evidence.retain(original.directory, original.summary())
            with self.assertRaises(FileExistsError):
                resumed.write("case-source-only.json", b"replacement")
            resumed.write("next.stdout", b"new bounded observation")
            self.assertEqual(resumed.cases, original.cases)
            self.assertEqual(resumed.total, original.total + len(b"new bounded observation"))
            self.assertEqual((original.directory / "case-source-only.json").read_bytes(), before)

    def test_unknown_file_changed_bytes_boolean_size_and_duplicate_or_unknown_cases_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            original = evidence.Evidence(Path(temporary) / "evidence")
            original.passed("source-only", {"nativeExecutionQualified": False})
            for change in ("unknown-file", "changed", "boolean", "duplicate", "nonstring", "missing-case"):
                value = copy.deepcopy(original.summary())
                if change == "unknown-file":
                    (original.directory / "unexpected").touch()
                elif change == "changed":
                    value["files"][0]["digest"] = inputs.digest(b"replacement")
                elif change == "boolean":
                    value["files"][0]["bytes"] = True
                elif change == "duplicate":
                    value["cases"] *= 2
                elif change == "nonstring":
                    value["cases"] = [{}]
                else:
                    value["cases"] = ["uncaptured-case"]
                with self.subTest(change=change), self.assertRaises(ValueError):
                    evidence.Evidence.retain(original.directory, value)
                if (original.directory / "unexpected").exists():
                    (original.directory / "unexpected").unlink()


class CatalogAndOrderingOracle(unittest.TestCase):
    def test_original_catalog_observation_uses_only_bounded_release_and_policy_reads(self):
        calls, published = [], publications()

        def call(*arguments):
            calls.append(arguments)
            if arguments[0] == "release":
                name = arguments[2].removeprefix("java-publish-")
                return {"data": {"receipt": {"publication": {"id": published[name]}, "originalOperation": arguments[2]}}}
            self.assertEqual(arguments[:2], ("policy", "--kind"))
            self.assertIn(arguments[2], ("provider-binding", "policy"))
            self.assertEqual(arguments[3:5], ("list", "--page-size"))
            # The actual disposable native store refuses requests above 16.
            self.assertLessEqual(int(arguments[5]), 16)
            return {"data": {"policies": [], "catalogGeneration": "18446744073709551615", "nextPageToken": None}}

        observed = staging.catalog(SimpleNamespace(call=call), published)
        self.assertEqual(len(calls), 6)
        self.assertEqual(set(observed["publications"]), set(published))
        self.assertTrue(all(row[:2] == ("release", "operation") or row[-3:] == ("list", "--page-size", "16")
                            for row in calls))
        self.assertTrue(all("apply" not in row and "publish-package" not in row for row in calls))

    def test_populated_paged_overflowing_and_foreign_catalogs_refuse(self):
        for change in ("populated", "paged", "overflow", "foreign"):
            def call(*arguments):
                if arguments[0] == "release":
                    name = arguments[2].removeprefix("java-publish-")
                    value = publications()[name] if change != "foreign" else "publication:sha256:" + "f" * 64
                    return {"data": {"receipt": {"publication": {"id": value}}}}
                return {"data": {"policies": [{}] if change == "populated" else [],
                    "catalogGeneration": str(2**64) if change == "overflow" else "1",
                    "nextPageToken": "page" if change == "paged" else None}}
            with self.subTest(change=change), self.assertRaises(ValueError):
                staging.catalog(SimpleNamespace(call=call), publications())

    def test_resume_refuses_profile_or_catalog_drift_before_any_policy_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            full = root / "full.json"
            full.write_bytes(evidence.encoded({"state": {"operations": ["original"]}}))
            prepared = {"hosts": {"profile": "original"}, "catalog": {"generation": "original"},
                        "publications": publications(), "proposals": {"reviewedBytes": "original"}, "mutations": [{"original": True}]}
            for change in ("profile", "catalog"):
                events = []
                node = SimpleNamespace(start=lambda path: events.append(("start", path)), stop=lambda: events.append(("stop",)))
                with self.subTest(change=change), ExitStack() as patches:
                    patches.enter_context(patch.object(conductor.lifecycle, "inspect", return_value=SimpleNamespace(
                        value={"profile": "changed"} if change == "profile" else prepared["hosts"])))
                    patches.enter_context(patch.object(staging, "catalog", return_value={"generation": "changed"}))
                    apply = patches.enter_context(patch.object(conductor.policies, "apply_retained"))
                    with self.assertRaises(ValueError):
                        conductor.resume_authority(SimpleNamespace(), SimpleNamespace(node="native-source-only"),
                            SimpleNamespace(path=root / "bootstrap.json"), node, full, prepared)
                    apply.assert_not_called()
                    self.assertEqual(len(events), 0 if change == "profile" else 1)

    def test_resume_applies_same_proposal_object_only_after_original_read_fences(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            full = root / "full.json"
            full.write_bytes(evidence.encoded({"state": {"operations": ["original"]}}))
            prepared = {"hosts": {"profile": "original"}, "catalog": {"generation": "original"},
                        "publications": publications(), "proposals": {"reviewedBytes": "original"}, "mutations": [{"original": True}]}
            events = []
            node = SimpleNamespace(start=lambda path: events.append(("start", path)), stop=lambda: events.append(("stop",)))
            client = SimpleNamespace(evidence=SimpleNamespace(record=lambda *_: None))

            def apply(actual_client, proposals, mutations):
                self.assertIs(actual_client, client)
                self.assertIs(proposals, prepared["proposals"])
                self.assertIs(mutations, prepared["mutations"])
                events.append(("apply",))
                return {"sourceOnly": "mutation callback observed"}

            with ExitStack() as patches:
                patches.enter_context(patch.object(conductor.lifecycle, "inspect", side_effect=lambda *_a, **_k:
                    (events.append(("inspect",)), SimpleNamespace(value=prepared["hosts"]))[1]))
                patches.enter_context(patch.object(staging, "catalog", side_effect=lambda *_:
                    (events.append(("catalog",)), prepared["catalog"])[1]))
                patches.enter_context(patch.object(conductor.policies, "apply_retained", side_effect=apply))
                patches.enter_context(patch.object(conductor.lifecycle, "admission_lease_interval",
                                                  side_effect=lambda _: events.append(("original-lease",))))
                result = conductor.resume_authority(client, SimpleNamespace(node="native-source-only"),
                    SimpleNamespace(path=root / "bootstrap.json"), node, full, prepared)
            self.assertEqual([row[0] for row in events], ["inspect", "start", "catalog", "apply", "stop", "original-lease", "start"])
            self.assertEqual(result, {"sourceOnly": "mutation callback observed"})
            self.assertEqual(prepared["proposals"], {"reviewedBytes": "original"})

    def test_preparation_stops_before_policy_apply_and_namespace_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collector = evidence.Evidence(root / "evidence")
            client = SimpleNamespace(directory=root, calls=7, evidence=collector)
            configuration = cfg.Configuration(root / "bootstrap.json", {"state": {"operations": []}}, "localhost:1234", {})
            events = []
            node = SimpleNamespace(start=lambda path: events.append(("start", path)), stop=lambda: events.append(("stop",)))
            proposals = {"bindings": {"fixture-binding": {"nativeExecutionQualified": False}}, "policies": {}}
            with ExitStack() as patches:
                patches.enter_context(patch.object(conductor.lifecycle, "publish", return_value=publications()))
                patches.enter_context(patch.object(staging, "catalog", return_value={"sourceOnly": "original"}))
                patches.enter_context(patch.object(conductor.lifecycle, "admission_lease_interval", return_value=None))
                patches.enter_context(patch.object(conductor.cfg, "installed", return_value=[{"fixtureOnly": True}]))
                patches.enter_context(patch.object(conductor.lifecycle, "inspect", return_value=SimpleNamespace(value={"profile": "original"})))
                patches.enter_context(patch.object(conductor.policies, "documents", return_value=proposals))
                apply = patches.enter_context(patch.object(conductor.policies, "apply"))
                retained_apply = patches.enter_context(patch.object(conductor.policies, "apply_retained"))
                create = patches.enter_context(patch.object(conductor.lifecycle, "create_namespace"))
                prepared = conductor.prepare_authority(client, SimpleNamespace(node="native-source-only"), root, [],
                    SimpleNamespace(incarnation="a" * 64), configuration, node, retained=True)
            self.assertEqual([row[0] for row in events], ["start", "stop"])
            self.assertEqual(prepared[2], proposals)
            self.assertEqual(prepared[5][0]["operationId"], "java-reviewed-provider-binding-fixture-binding")
            apply.assert_not_called()
            retained_apply.assert_not_called()
            create.assert_not_called()

    def test_candidate_modes_require_explicit_paired_resume_and_exclude_combined_preparation(self):
        for prepared, file, digest, expected in ((False, None, None, "run"), (True, None, None, "prepare"),
                (False, Path("candidate.json"), "sha256:" + "a" * 64, "resume")):
            self.assertEqual(staging.mode(SimpleNamespace(prepare_authority_only=prepared,
                resume_candidate=file, candidate_digest=digest)), expected)
        for prepared, file, digest in ((True, Path("candidate.json"), "sha256:" + "a" * 64),
                (1, None, None),
                (False, None, "sha256:" + "a" * 64), (False, Path("candidate.json"), None)):
            with self.assertRaises(ValueError):
                staging.mode(SimpleNamespace(prepare_authority_only=prepared, resume_candidate=file, candidate_digest=digest))


class RetainedPolicyProgramOracle(unittest.TestCase):
    def test_frozen_policy_bytes_ids_and_preconditions_survive_extra_read_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []
            proposals = {"bindings": {"fixture-binding": {"nativeExecutionQualified": False, "description": "bounded-é"}},
                         "policies": {"fixture-policy": {"nativeExecutionQualified": False}}}

            def call(*arguments):
                calls.append(arguments)
                return {"outcomeKnown": True, "data": {"receipt": {"operationId": arguments[arguments.index("--operation-id") + 1]}}}

            client = SimpleNamespace(directory=Path(temporary), calls=17, call=call)
            mutations = policies.prepare_mutations(client, proposals)
            original = {row["file"]: (client.directory / row["file"]).read_bytes() for row in mutations}
            self.assertFalse(calls)
            self.assertIn(b"\\u00e9", original[mutations[0]["file"]])
            client.calls = 31
            receipts = policies.apply_retained(client, proposals, mutations)
            self.assertEqual(len(calls), 2)
            self.assertEqual(set(receipts), {"fixture-binding", "fixture-policy"})
            for row, arguments in zip(mutations, calls):
                self.assertEqual(arguments[arguments.index("--operation-id") + 1], row["operationId"])
                self.assertEqual(arguments[-2:], ("--expected-generation", 0))
                self.assertEqual((client.directory / row["file"]).read_bytes(), original[row["file"]])

    def test_any_later_document_or_mutation_drift_refuses_before_first_apply(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []
            client = SimpleNamespace(directory=Path(temporary), calls=17, call=lambda *args: calls.append(args))
            proposals = {"bindings": {"fixture-binding": {"nativeExecutionQualified": False}},
                         "policies": {"fixture-policy": {"nativeExecutionQualified": False}}}
            mutations = policies.prepare_mutations(client, proposals)
            for field, value in (("operationId", "new-operation"), ("expectedGeneration", 1),
                                 ("expectedGeneration", False), ("file", "../another.json"),
                                 ("digest", inputs.digest(b"changed")), ("bytes", True)):
                changed = copy.deepcopy(mutations)
                changed[-1][field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    policies.apply_retained(client, proposals, changed)
                self.assertFalse(calls)
            (client.directory / mutations[-1]["file"]).write_bytes(b"{\"changed\":true}")
            with self.assertRaises(ValueError):
                policies.apply_retained(client, proposals, mutations)
            self.assertFalse(calls)

    def test_uncertain_native_apply_is_not_retried_and_no_later_mutation_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []

            def call(*arguments):
                calls.append(arguments)
                raise RuntimeError("source-only-unknown-native-disposition")

            client = SimpleNamespace(directory=Path(temporary), calls=17, call=call)
            proposals = {"bindings": {"fixture-binding": {"nativeExecutionQualified": False}},
                         "policies": {"fixture-policy": {"nativeExecutionQualified": False}}}
            mutations = policies.prepare_mutations(client, proposals)
            with self.assertRaises(RuntimeError):
                policies.apply_retained(client, proposals, mutations)
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
