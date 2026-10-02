"""Independent lossless fixture vectors; these do not qualify any remote node."""
import copy
import unittest

from tools.transaction_node_participant import Contract, FixtureError, explicit_retry_request, lookup_request


class TransactionFixtureWire(unittest.TestCase):
    def setUp(self):
        self.contract = Contract()

    def test_optional_zero_and_maximum_versions_use_exact_wire_bits(self):
        # Dispatcher revision is tag 2; uint64 never becomes a float.
        message = self.contract.messages["DispatcherGeneration"]
        self.assertEqual([(item["name"], item["number"]) for item in message], [("owner_epoch", 1), ("revision", 2)])
        maximum = {"owner_epoch": "18446744073709551615", "revision": "0"}
        expected = b"\x08\xff\xff\xff\xff\xff\xff\xff\xff\xff\x01\x10\x00"
        self.assertEqual(self.contract.encode("DispatcherGeneration", maximum), expected)
        self.assertEqual(self.contract.decode("DispatcherGeneration", expected), maximum)
        for value in (18446744073709551615, 1.0, "01", "-1", "18446744073709551616", True):
            with self.subTest(value=value), self.assertRaises(FixtureError):
                self.contract.encode("DispatcherGeneration", {"owner_epoch": value})

    def test_precondition_absence_false_and_present_empty_are_distinct(self):
        self.assertEqual(self.contract.encode("ExpectedVersion", {"key": b"k"}), b"\x0a\x01k")
        self.assertEqual(self.contract.encode("ExpectedVersion", {"key": b"k", "absent": False}), b"\x0a\x01k\x10\x00")
        self.assertEqual(self.contract.encode("ExpectedVersion", {"key": b"k", "version": b""}), b"\x0a\x01k\x1a\x00")
        value = self.contract.decode("ExpectedVersion", b"\x0a\x01k\x10\x00")
        self.assertIs(value["absent"], False)
        self.assertNotIn("version", value)
        with self.assertRaises(FixtureError):
            self.contract.encode("ExpectedVersion", {"key": b"k", "absent": True, "version": b"v"})

    def test_request_and_response_reject_duplicate_unknown_and_wrong_wire_fields(self):
        for data in (b"\x08\x01\x08\x02", b"\x18\x01", b"\x0a\x00", b"\x08\x80", b"\x08" + b"\xff" * 10):
            with self.subTest(data=data), self.assertRaises(FixtureError):
                self.contract.decode("DispatcherGeneration", data)
        with self.assertRaises(FixtureError):
            self.contract.encode("DispatcherGeneration", {"invented_authority": "grant"})

    def test_utf8_binary_map_and_presence_survive_an_invocation_fixture(self):
        request = {"activation_id": "call-λ", "payload": b"\0\xff\x80", "media_type": "application/test",
                   "metadata": {"second": "value-λ", "first": ""}, "budget": {"cpu_fuel": "0", "memory_bytes": "18446744073709551615"}}
        encoded = self.contract.encode("InvokeRequest", request)
        decoded = self.contract.decode("InvokeRequest", encoded)
        for key, value in request.items():
            if key == "budget":
                self.assertEqual(decoded[key]["memory_bytes"], value["memory_bytes"])
            else:
                self.assertEqual(decoded[key], value)
        with self.assertRaises(FixtureError):
            self.contract.decode("NamespaceSelector", b"\x0a\x01\xff")

    def test_bounded_lists_and_exact_sixteen_operation_closure(self):
        self.assertEqual(len(self.contract.operations), 16)
        self.assertEqual({name for name in self.contract.operations if name.startswith("lookup_")}, {"lookup_command", "lookup_commit"})
        values = [{"key": b"k", "absent": True}] * 129
        with self.assertRaises(FixtureError):
            self.contract.encode("InvokeCommandRequest", {"expected_versions": values})
        with self.assertRaises(FixtureError):
            self.contract.encode("CommandInspection", {"fingerprint_sha256": b"x" * (2 * 1024 * 1024 + 1)})


class TransactionFixtureRecovery(unittest.TestCase):
    def setUp(self):
        self.original = {"profile": {"profile": "phase4"}, "command": {"namespace": {"tenant": "tenant", "namespace": "state", "incarnation": "original"},
                         "operation": "update", "client_key": "same-business-key"}, "input_format": "original", "invocation": {"payload": b"original"},
                         "expected_versions": [{"key": b"k", "version": b"old-version"}]}
        self.inspection = {"outcome": 4, "metadata_durable": True, "application_state_committed": False,
                           "command_id": "command", "attempt_id": "attempt", "proven_abort": {"command_id": "command",
                           "attempt_id": "attempt", "transaction_id": "transaction", "owner_fence": bytes(range(32))}}

    def test_current_read_publication_never_changes_original_command_scope(self):
        before = copy.deepcopy(self.original)
        first = lookup_request(self.original, {"id": "publication-one", "tenant": "tenant"})
        second = lookup_request(self.original, {"id": "publication-two", "tenant": "tenant"})
        self.assertEqual(first["command"], second["command"])
        self.assertNotEqual(first["authorization_publication"], second["authorization_publication"])
        self.assertEqual(self.original, before)
        second["command"]["namespace"]["incarnation"] = "changed"
        self.assertEqual(self.original, before)

    def test_explicit_attempt_copies_original_input_scope_and_cas_with_observed_fence(self):
        before = copy.deepcopy(self.original)
        result = explicit_retry_request(self.original, self.inspection, "explicit-next-attempt")
        self.assertEqual({key: value for key, value in result.items() if key != "retry_attempt"}, before)
        self.assertEqual(result["retry_attempt"], {"request_id": "explicit-next-attempt", "expected_abort": self.inspection["proven_abort"]})
        self.assertEqual(self.original, before)
        Contract().encode("RetryAttempt", result["retry_attempt"])

    def test_transport_loss_rejection_success_expiry_and_uncertain_abort_cannot_create_an_attempt(self):
        for outcome in (1, 2, 3, 5, 6, 7):
            inspection = copy.deepcopy(self.inspection)
            inspection["outcome"] = outcome
            with self.subTest(outcome=outcome), self.assertRaises(FixtureError):
                explicit_retry_request(self.original, inspection, "retry")
        for field, value in (("metadata_durable", False), ("application_state_committed", True), ("proven_abort", None)):
            inspection = copy.deepcopy(self.inspection)
            inspection[field] = value
            with self.subTest(field=field), self.assertRaises(FixtureError):
                explicit_retry_request(self.original, inspection, "retry")
        changed = copy.deepcopy(self.inspection)
        changed["proven_abort"]["attempt_id"] = "different"
        with self.assertRaises(FixtureError):
            explicit_retry_request(self.original, changed, "retry")


if __name__ == "__main__":
    unittest.main()
