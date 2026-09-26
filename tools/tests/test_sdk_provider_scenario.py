import copy
import tempfile
import unittest
from pathlib import Path

from tools.phase2_operator_process import WorkflowError, startup_diagnostic
from tools.sdk_provider_http_fixture import mode
from tools.sdk_provider_scenario import ASSERTIONS, participant_diagnostic, validate_result


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
        result["auditAttempt"] = None
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

    def test_only_bounded_stage_diagnostics_are_exposed(self):
        self.assertEqual(participant_diagnostic(
            b'{"stage":"provider-invocation","reason":"rpc-or-runtime","category":3,"grpcStatus":7}'),
            "provider-invocation-rpc-or-runtime-category-3-grpc-7")
        self.assertEqual(participant_diagnostic(
            b'{"stage":"go-participant","reason":"participant-httpguest-failed"}\n'),
            "go-participant-participant-httpguest-failed-category-unavailable-grpc-unavailable")
        for value in (b"", b"x" * 513, b"not-json", b"[]", b"\xff",
                      b'{"stage":"provider","reason":"Authorization: Bearer token"}',
                      b'{"stage":"provider","reason":"failed","message":"secret"}'):
            self.assertEqual(participant_diagnostic(value), "unavailable")

    def test_startup_failure_exposes_only_the_nodes_closed_stage_and_code(self):
        self.assertEqual(startup_diagnostic(b"latentd: startup: unavailable\n"), "startup-unavailable")
        self.assertEqual(startup_diagnostic(b"latentd: configuration: invalid-argument\r\n"),
                         "configuration-invalid-argument")
        for value in (b"", b"x" * 161, b"latentd: secret-value: unavailable\n",
                      b"latentd: startup: secret-value\n", b"latentd: startup: unavailable\nsecret\n"):
            self.assertEqual(startup_diagnostic(value), "unavailable")


if __name__ == "__main__":
    unittest.main()
