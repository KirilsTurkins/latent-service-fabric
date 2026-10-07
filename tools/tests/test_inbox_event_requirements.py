import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.rust_capsule_project import create, snapshot
from tools.transaction_guest_project import (
    EVENT_REQUIREMENTS, HTTP_REQUIREMENTS, INPUT_FORMAT, RESULT_FORMAT,
    augment, event_requirements, package_effect_requirements,
    package_event_requirements, put_once_requirements,
)


def captured():
    project = {"name": "inbox-aggregate", "service": "examples/inbox-aggregate",
               "world": "examples:transactional-aggregate/service@1.0.0"}
    files = {}
    augment(files, project, event_values=True)
    return project, files


class InboxEventRequirementsTests(unittest.TestCase):
    def test_authored_aggregate_captures_exact_companion_schema_and_bounded_event_asset(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = create(Path(temporary) / "project", "transactional-aggregate", "inbox-aggregate")
            files = snapshot(source)
            project = json.loads(files["capsule-project.json"])
            companion = json.loads(files["transaction-binding.json"])
            requirements = json.loads(files[EVENT_REQUIREMENTS])
            self.assertEqual(requirements, event_requirements(project, files["transaction-binding.json"]))
            self.assertEqual(requirements["scope"]["companionDigest"],
                             "sha256:" + hashlib.sha256(files["transaction-binding.json"]).hexdigest())
            self.assertEqual(requirements["scope"]["stateSchema"], companion["stateSchema"])
            self.assertEqual(requirements["intent"]["payload"], {
                "kind": "bounded-event-value", "maximumBytes": 8,
                "mediaType": "application/vnd.lsf.aggregate-v1", "metadata": "empty"})
            self.assertEqual(requirements["authority"], {
                "installed": False, "ruleGranted": False, "executionQualified": False})
            self.assertIn(b'features = ["transaction"]', files["Cargo.toml"])
            self.assertNotIn(HTTP_REQUIREMENTS, files)

    def test_event_packaging_retains_captured_bytes_and_refuses_every_authority_or_scope_drift(self):
        project, files = captured()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.assertEqual(package_event_requirements(output, project, files),
                             (EVENT_REQUIREMENTS, "asset", "application/json"))
            self.assertEqual((output / EVENT_REQUIREMENTS).read_bytes(), files[EVENT_REQUIREMENTS])
        original = json.loads(files[EVENT_REQUIREMENTS])
        for section, key, forged in (
            ("scope", "companionDigest", "sha256:" + "0" * 64),
            ("scope", "namespace", "foreign"),
            ("scope", "stateSchema", "sha256:" + "0" * 64),
            ("adapter", "payloadFormat", "unknown-event-format"),
            ("intent", "operation", "publish"),
            ("authority", "ruleGranted", True),
        ):
            changed = copy.deepcopy(original)
            changed[section][key] = forged
            with self.subTest(section=section, key=key), tempfile.TemporaryDirectory() as temporary:
                modified = dict(files, **{EVENT_REQUIREMENTS: json.dumps(changed).encode()})
                with self.assertRaisesRegex(ValueError, "deferred-event-requirements-drift"):
                    package_event_requirements(Path(temporary), project, modified)
                self.assertFalse((Path(temporary) / EVENT_REQUIREMENTS).exists())
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(ValueError, "companion-required"):
            package_event_requirements(Path(temporary), project, {EVENT_REQUIREMENTS: files[EVENT_REQUIREMENTS]})

    def test_event_selector_requires_exact_authored_world_and_companion_operations(self):
        project, files = captured()
        for world in ("examples:order-draft/service@1.0.0", "unknown:aggregate/service@1.0.0"):
            with self.subTest(world=world), self.assertRaises(ValueError):
                event_requirements(dict(project, world=world), files["transaction-binding.json"])
        original = json.loads(files["transaction-binding.json"])
        for key, forged in (("namespace", "foreign"), ("operations", original["operations"][:-1]),
                            ("stateSchema", "not-a-schema-digest")):
            changed = copy.deepcopy(original)
            changed[key] = forged
            with self.subTest(key=key), self.assertRaises(ValueError):
                event_requirements(project, json.dumps(changed).encode())
        files_without_event = {}
        augment(files_without_event, project)
        self.assertNotIn(EVENT_REQUIREMENTS, files_without_event)
        self.assertIsNone(package_event_requirements(Path("unused-output"), project, files_without_event))

    def test_original_http_exact_payload_and_order_draft_notification_packaging_remain_strict(self):
        project, files = captured()
        aggregate = put_once_requirements(project, files["transaction-binding.json"])
        self.assertEqual(aggregate["intent"]["binding"], "qualified-http")
        draft_project = dict(project, world="examples:order-draft/service@1.0.0")
        companion = json.loads(files["transaction-binding.json"])
        companion["namespace"] = "order-drafts-blue"
        companion["operations"] = [
            {"operation": name, "mode": mode, "inputFormat": INPUT_FORMAT, "resultFormat": RESULT_FORMAT}
            for name, mode in (("edit", "strict-command"), ("query", "fresh-query"))]
        raw_companion = json.dumps(companion).encode()
        draft = put_once_requirements(draft_project, raw_companion)
        self.assertEqual(draft["intent"]["binding"], "draft-http")
        self.assertEqual(draft["contract"]["maximumBodyBytes"], len(b"draft-change-v1:blue"))
        captured_http = {"transaction-binding.json": raw_companion,
                         HTTP_REQUIREMENTS: json.dumps(draft).encode()}
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(package_effect_requirements(Path(temporary), draft_project, captured_http),
                             (HTTP_REQUIREMENTS, "asset", "application/json"))
            self.assertEqual((Path(temporary) / HTTP_REQUIREMENTS).read_bytes(), captured_http[HTTP_REQUIREMENTS])
        changed = copy.deepcopy(draft)
        changed["intent"]["payload"]["bytes"] = "Zm9yZWlnbg=="
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(ValueError, "deferred-http-requirements-drift"):
            package_effect_requirements(Path(temporary), draft_project,
                                        dict(captured_http, **{HTTP_REQUIREMENTS: json.dumps(changed).encode()}))


if __name__ == "__main__":
    unittest.main()
