import json
import unittest

from generate import ROOT, read_contract
from validate import request_error, response_error, unsigned_decimal, validate, validate_value


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile, cls.messages, cls.enums = read_contract()

    def test_shared_contract_is_current(self):
        self.assertEqual(validate(), (68, 16))

    def test_exact_operation_profile(self):
        self.assertEqual([operation["name"] for operation in self.profile["operations"]], [
            "Invoke", "Cancel", "GetActivation", "GetPolicy", "ListPolicies", "ListCapabilities", "ApplyPolicy", "GetPolicyOperation",
        ])

    def test_unsigned_inputs_are_not_json_numbers(self):
        for value in (0, 9007199254740993, True, None, "-1", "01", "18446744073709551616"):
            with self.subTest(value=value):
                self.assertFalse(unsigned_decimal(value))
                with self.assertRaises(ValueError):
                    validate_value({"type": "uint64"}, value, self.messages, self.enums)

    def test_optional_presence_is_not_empty_or_null(self):
        field = {"type": "ApplyPolicyRequest"}
        for value in ({}, {"operation_id": "", "expected_generation": "0"}):
            validate_value(field, value, self.messages, self.enums)
        with self.assertRaises(ValueError):
            validate_value(field, {"expected_generation": None}, self.messages, self.enums)
        self.assertEqual(request_error("ApplyPolicyRequest", {}), "missing-generation")
        self.assertEqual(request_error("ApplyPolicyRequest", {"expected_generation": "0", "operation_id": ""}), "invalid-operation-id")

    def test_all_enum_bits_and_unknown_values_are_preserved(self):
        for kind in self.enums:
            for number in (-2147483648, -1, 0, 91, 2147483647):
                validate_value({"type": kind}, number, self.messages, self.enums)
            for number in (-2147483649, 2147483648):
                with self.assertRaises(ValueError):
                    validate_value({"type": kind}, number, self.messages, self.enums)

    def test_pagination_defaults_are_not_unified(self):
        self.assertEqual(request_error("ListPoliciesRequest", {}), "missing-page")
        self.assertEqual(request_error("ListPoliciesRequest", {"page": {"page_size": 0}}), "invalid-page-size")
        self.assertIsNone(request_error("ListCapabilitiesRequest", {"deployment_id": "deployment-a"}))
        self.assertIsNone(request_error("ListCapabilitiesRequest", {"deployment_id": "deployment-a", "page": {"page_size": 0}}))
        self.assertIsNone(request_error("ListCapabilitiesRequest", {"deployment_id": "deployment-a", "page": {"page_size": 128}}))
        for kind, maximum in (("ListPoliciesRequest", 117), ("ListCapabilitiesRequest", 160)):
            request = {"deployment_id": "deployment-a", "page": {"page_size": 1, "page_token": "x" * (maximum + 1)}}
            self.assertEqual(request_error(kind, request), "invalid-page-token")

    def test_no_fabricated_capability_limits_or_authority_fields(self):
        response_fields = {field["name"] for field in self.messages["ListCapabilitiesResponse"]}
        self.assertNotIn("ceiling", response_fields)
        self.assertNotIn("credentials", response_fields)
        with self.assertRaises(ValueError):
            validate_value({"type": "ListCapabilitiesRequest"}, {"principal": "admin"}, self.messages, self.enums)

    def test_oneof_contradictions_are_preserved_for_rejection(self):
        value = {"success": {}, "platform_failure": {"code": "future-code"}}
        validate_value({"type": "InvokeResponse"}, value, self.messages, self.enums)
        self.assertEqual(response_error("InvokeResponse", value, self.messages), "contradictory-oneof")

    def test_unsupported_wire_evidence_is_bounded_not_authority(self):
        field = {"type": "UnsupportedWireValue"}
        validate_value(field, {"field": "phase", "value": "x" * 256}, self.messages, self.enums)
        with self.assertRaises(ValueError):
            validate_value(field, {"field": "phase", "value": "x" * 257}, self.messages, self.enums)

    def test_wire_field_numbers_and_presence_match_authority(self):
        invocation = {field["name"]: field for field in self.messages["InvokeResponse"]}
        self.assertEqual(invocation["publication_id"]["number"], 10)
        self.assertTrue(invocation["publication_id"]["optional"])
        self.assertEqual(invocation["release_digest"]["number"], 3)
        self.assertNotIn("optional", invocation["release_digest"])
        failure = {field["name"]: field for field in self.messages["PlatformError"]}
        self.assertEqual(failure["detail_items"]["number"], 5)
        policy = {field["name"]: field for field in self.messages["ApplyPolicyRequest"]}
        self.assertTrue(policy["policy"]["optional"])
        self.assertTrue(policy["expected_generation"]["optional"])

    def test_recovery_receipt_matches_original_not_current_policy(self):
        fixtures = json.loads((ROOT / "sdk/profile/fixtures.json").read_text(encoding="utf-8"))
        cases = {case["name"]: case["value"] for case in fixtures["cases"]}
        self.assertEqual(cases["apply-retains-original-receipt"]["receipt"], cases["operation-recovery-original-receipt"]["receipt"])
        self.assertNotIn("receipt", cases["operation-recovery-not-retained-is-unknown"])
        self.assertNotIn("audit_ack", cases["policy-response-has-no-fabricated-audit"])
        self.assertEqual(cases["observed-receipt-audit-outcome-independent"]["outcome"], 3)
        self.assertEqual(cases["observed-receipt-audit-outcome-independent"]["audit_ack"]["status"], 2)

    def test_unknown_audit_header_retains_independent_sequence_without_enum(self):
        fixtures = json.loads((ROOT / "sdk/profile/fixtures.json").read_text(encoding="utf-8"))
        cases = {case["name"]: case["value"] for case in fixtures["cases"]}
        for kind in ("ResponseMetadata", "ClientFailure"):
            field = next(field for field in self.messages[kind] if field["name"] == "audit_attempt_sequence")
            self.assertTrue(field["optional"])
            self.assertEqual(field["type"], "uint64")
        for name in ("unknown-audit-header-and-max-attempt", "failed-rpc-unknown-audit-header-and-max-attempt"):
            self.assertEqual(cases[name]["audit_status"], "future-state")
            self.assertEqual(cases[name]["audit_attempt_sequence"], "18446744073709551615")
            self.assertNotIn("audit_ack", cases[name])
        self.assertNotIn("audit_attempt_sequence", cases["policy-response-has-no-fabricated-audit"])
        self.assertEqual(cases["unknown-audit-enum-and-status"]["audit_attempt_sequence"], "0")
        known = cases["observed-receipt-audit-outcome-independent"]
        self.assertEqual(known["audit_attempt_sequence"], known["audit_ack"]["attempt_sequence"])


if __name__ == "__main__":
    unittest.main()
