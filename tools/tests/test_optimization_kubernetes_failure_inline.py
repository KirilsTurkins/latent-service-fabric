"""Original failed client bytes; never fabricate a complete campaign fixture."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.optimization_evidence.common import EvidenceError, canonical, sha256
from tools.optimization_kubernetes import failure_inline as evidence, model

FIXTURE = Path(__file__).parent / "fixtures/kubernetes-failure-02"
RELEASE = "sha256:cd0f08b79b549c5be86ae3b88622cd5b8aa42ce7a4acaa3b6692e3562fe8dd66"


class InlineFailureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "failure-outputs/2"
        shutil.copytree(FIXTURE, self.output)
        self.parent = {"plan": json.loads((self.output / "plan.json").read_bytes()),
            "commands": [json.loads(line) for line in (self.output / "parent-commands.ndjson").read_bytes().splitlines()],
            "acknowledgements": [json.loads(line) for line in (self.output / "parent-acks.ndjson").read_bytes().splitlines()]}
        self.owners = {}
        for index in (0, 14):
            command = json.loads(self.parent["commands"][index]["line"])
            target, group = command["targets"][0], command["group"]
            owner = {"app_process_id": target["app_process_id"], "endpoint": target["endpoint"],
                     "arm": "lsf" if group == 0 else "native", "density": 1, "group": group,
                     "container_id": target["owner_ref"].removeprefix("owner-")}
            if group == 0:
                owner["release_digests"] = {model.SERVICES[0]: RELEASE}
            self.owners[target["owner_ref"]] = owner

    def check(self):
        return evidence.client_prefix(self.root, self.parent, self.owners)

    def test_original_failed_session_replays_all_thirty_offers_and_stays_failed(self):
        before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        result = self.check()
        self.assertEqual(result["offers"], "30")
        self.assertEqual(result["summary"]["status"], "failed")
        self.assertEqual(result["summary"]["reason"], "session-connect-failed")
        self.assertEqual([row["phase"]["offers"] for row in result["phases"]], [1, 1, 1, 2, 8, 1, 4, 4, 8])
        self.assertEqual(set(result["inventories"]), {"0/ready", "0/served", "0/final"})
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.output.iterdir()})

    def test_publication_metadata_projects_its_release_digest_into_real_client_prefix(self):
        owners = {}
        # fixture_set returns one metadata dictionary per service, as used by
        # normal Kubernetes replay; the prefix requires its release string.
        releases = {model.SERVICES[0]: {"release": RELEASE, "capsule": {"metadata": "retained separately"}}}
        for index in (0, 14):
            command = json.loads(self.parent["commands"][index]["line"])
            target = command["targets"][0]
            original = self.owners[target["owner_ref"]]
            owners[target["owner_ref"]] = evidence._prefix_owner(original, target, command["group"], releases)
        result = evidence.client_prefix(self.root, self.parent, owners)
        self.assertEqual(result["offers"], "30")
        self.assertEqual(result["summary"]["reason"], "session-connect-failed")

    def test_payload_corruption_rejects_even_after_all_attempt_prefix_hashes_are_rebound(self):
        path = self.output / "attempts.jsonl"
        original = path.read_bytes()
        first = json.loads(original.splitlines()[0])
        previous = first["attempt"]["response"]["payload_sha256"].encode()
        changed = original.replace(previous, b"sha256:" + b"0" * 64, 1)
        self.assertEqual(len(changed), len(original))
        path.write_bytes(changed)
        for row in self.parent["acknowledgements"]:
            ref = row["ack"]["attempts"]
            ref["sha256"] = sha256(changed[:int(ref["bytes"])])
        summary = json.loads((self.output / "summary.json").read_bytes())
        summary["attempts"]["sha256"] = sha256(changed)
        (self.output / "summary.json").write_bytes(canonical(summary) + b"\n")
        with self.assertRaises(EvidenceError):
            self.check()

    def test_connect_failure_cannot_be_relabelled_success_with_rehashed_event_receipts(self):
        path = self.output / "events.jsonl"
        events = [json.loads(line) for line in path.read_bytes().splitlines()]
        events[16]["payload"]["result"]["status"] = "passed"
        data, offset = bytearray(), 0
        for event, parent in zip(events, self.parent["acknowledgements"]):
            line = canonical(event) + b"\n"
            parent["ack"]["event_record"] = {"path": "events.jsonl", "offset": str(offset),
                                            "bytes": str(len(line)), "sha256": sha256(line)}
            offset += len(line)
            data.extend(line)
        path.write_bytes(data)
        with self.assertRaisesRegex(EvidenceError, "failed-connect-result"):
            self.check()

    def test_extra_native_offer_or_missing_terminal_ack_cannot_disappear(self):
        path = self.output / "attempts.jsonl"
        original = path.read_bytes()
        row = json.loads(original.splitlines()[0])
        row.update(arm="native", group=1, global_ordinal=30)
        path.write_bytes(original + canonical(row) + b"\n")
        with self.assertRaises(EvidenceError):
            self.check()
        path.write_bytes(original)
        self.parent["acknowledgements"].pop()
        with self.assertRaisesRegex(EvidenceError, "client-prefix-count"):
            self.check()

    def test_failure_summary_and_replaced_target_owner_reject(self):
        path = self.output / "summary.json"
        original = path.read_bytes()
        summary = json.loads(original)
        summary.update(status="complete", reason=None)
        path.write_bytes(canonical(summary))
        with self.assertRaisesRegex(EvidenceError, "failed-summary"):
            self.check()
        path.write_bytes(original)
        changed = deepcopy(self.owners)
        next(iter(changed.values()))["app_process_id"] += 1
        with self.assertRaises(EvidenceError):
            evidence.client_prefix(self.root, self.parent, changed)


if __name__ == "__main__":
    unittest.main()
