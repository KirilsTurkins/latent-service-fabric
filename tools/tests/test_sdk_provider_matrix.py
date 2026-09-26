import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.phase2_operator_process import WorkflowError
from tools.sdk_provider_scenario import ASSERTIONS, LANGUAGES
from tools.verify_sdk_provider_matrix import verify


class ProviderMatrixTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.receipts = {}
        for language in LANGUAGES:
            self.receipts[language] = {
                "schemaVersion": "latent.sdk.provider.workflow.evidence.v1", "language": language,
                "scope": "separate-node-authenticated-provider-guests",
                "identities": dict.fromkeys(("node", "cli", "fixture", "participant0"), "sha256:" + "a" * 64),
                "participant": {"schemaVersion": "latent.sdk.provider.workflow.result.v1", "language": language,
                                "assertions": dict.fromkeys(ASSERTIONS, True),
                                "activationIds": [f"{language}-activation-{index}" for index in range(9)],
                                "operationId": f"{language}-policy-create", "auditAttempt": None,
                                "transport": "numeric-loopback-http2-protobuf-v1"},
                "upstream": {"requests": 5, "authorized": 5, "unexpected": 0, "holds": 4, "closedHolds": 4},
                "nodeShutdown": {"reaped": True, "record": {"clean": True, "report": {"clean": True, "providers": {"clean": True}}}},
                "browserQualified": False, "installedBundleQualified": False,
            }
        self.write()

    def write(self):
        for language, receipt in self.receipts.items():
            (self.directory / f"{language}.json").write_text(json.dumps(receipt), encoding="utf-8")

    def test_exact_six_language_contract(self):
        result = verify(self.directory)
        self.assertIs(result["passed"], True)
        self.assertEqual(set(result["languages"]), LANGUAGES)
        self.assertEqual(result["assertionsPerLanguage"], 18)

    def test_missing_or_empty_receipt_cannot_reuse_other_languages(self):
        path = self.directory / "dotnet.json"
        path.unlink()
        with self.assertRaises(WorkflowError):
            verify(self.directory)
        path.write_bytes(b"")
        with self.assertRaises(WorkflowError):
            verify(self.directory)

    def test_mixed_inputs_and_participant_labels_fail_closed(self):
        original = copy.deepcopy(self.receipts)
        for field in ("node", "cli", "fixture", "participant0"):
            self.receipts = copy.deepcopy(original)
            self.receipts["go"]["identities"][field] = "sha256:" + "b" * 64 if field != "participant0" else "unknown"
            self.write()
            with self.assertRaises(WorkflowError):
                verify(self.directory)
        self.receipts = copy.deepcopy(original)
        self.receipts["go"]["participant"]["language"] = "rust"
        self.write()
        with self.assertRaises(WorkflowError):
            verify(self.directory)

    def test_false_checks_leaks_and_invented_profiles_are_not_passes(self):
        changes = (
            ("participant", "assertions", "httpGuest", False),
            ("upstream", "closedHolds", 3), ("upstream", "unexpected", 1),
            ("upstream", "requests", 4), ("upstream", "authorized", True),
            ("nodeShutdown", "reaped", False),
            ("nodeShutdown", "record", "report", "providers", "clean", False),
            ("browserQualified", True), ("installedBundleQualified", True),
        )
        original = copy.deepcopy(self.receipts)
        for change in changes:
            self.receipts = copy.deepcopy(original)
            target = self.receipts["c"]
            for key in change[:-2]:
                target = target[key]
            target[change[-2]] = change[-1]
            self.write()
            with self.assertRaises(WorkflowError):
                verify(self.directory)


if __name__ == "__main__":
    unittest.main()
