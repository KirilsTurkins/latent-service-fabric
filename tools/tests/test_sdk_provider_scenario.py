import copy
import tempfile
import unittest
from pathlib import Path

from tools.phase2_operator_process import WorkflowError
from tools.sdk_provider_http_fixture import mode
from tools.sdk_provider_scenario import ASSERTIONS, validate_result


class ParticipantContractTests(unittest.TestCase):
    def result(self):
        return {"schemaVersion": "latent.sdk.provider.workflow.result.v1", "language": "rust",
                "assertions": dict.fromkeys(ASSERTIONS, True),
                "activationIds": [f"rust-invocation-{index}" for index in range(6)],
                "operationId": "rust-policy-create", "auditAttempt": "18446744073709551615",
                "transport": "numeric-loopback-http2-protobuf-v1"}

    def test_complete_finite_result(self):
        result = self.result()
        self.assertEqual(validate_result(result, "rust"), result)

    def test_missing_false_or_invented_evidence_is_rejected(self):
        missing = self.result()
        del missing["assertions"]["httpGuest"]
        false = self.result()
        false["assertions"]["clientOwnersReaped"] = False
        number = self.result()
        number["assertions"]["clientOwnersReaped"] = 1
        extra = self.result()
        extra["assertions"]["productionCertified"] = True
        for result in (missing, false, number, extra):
            with self.assertRaises(WorkflowError):
                validate_result(result, "rust")

    def test_recovery_identity_and_exact_u64_are_required(self):
        for key, value in (("auditAttempt", "0"), ("auditAttempt", "01"),
                           ("auditAttempt", "18446744073709551616"), ("auditAttempt", 1),
                           ("operationId", "different"), ("language", "go"),
                           ("activationIds", ["rust-same"] * 6)):
            result = copy.deepcopy(self.result())
            result[key] = value
            with self.assertRaises(WorkflowError):
                validate_result(result, "rust")

    def test_rendezvous_tokens_cannot_be_paths_or_unbounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertEqual(mode(directory), "reply")
            path = directory / "mode"
            for value in (b"../escape", b"hold-../escape", b"reply\n", b"hold-" + b"a" * 64):
                path.write_bytes(value)
                with self.assertRaises(ValueError):
                    mode(directory)
            path.write_bytes(b"hold-rust-cancel")
            self.assertEqual(mode(directory), "hold-rust-cancel")


if __name__ == "__main__":
    unittest.main()
