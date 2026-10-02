"""Bounded HTTP receipt interpretation; no host execution/authority is claimed."""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import unittest

from tools.generate_transaction_contracts import requirements
from tools.transaction_contracts import ENVELOPE_BYTES, ENVELOPE_NODES, VALUE_BYTES, content, decode_envelope, envelope

ROOT = Path(__file__).resolve().parents[2]


def source():
    return dict(publicationId="publication-a", revisionId="revision-a", releaseDigest="sha256:" + "1" * 64,
        componentDigest="sha256:" + "2" * 64, routeGeneration="18446744073709551615",
        contractDigest="sha256:" + "3" * 64, stateSchema="sha256:" + "4" * 64,
        inputFormat="input-v1", resultFormat="result-v1")


def retention(*, available=True, record_format="lsf-command-result-v1"):
    return dict(recordFormat=record_format, recordVersion=1, requiredRecordIds=["command-a"],
        payloadAvailable=available, payloadExpiresAtUnixMillis="1000", identityExpiresAtUnixMillis="2000",
        remainingRecoveryMillis="100")


def committed():
    value = dict(kind="response", profile="lsf-transaction-v1", outcome="committed",
        metadataDurable=True, applicationStateCommitted=True, commandId="command-a", attemptId="attempt-a",
        receiptId="receipt-a", sourceIdentity=source(), retention=retention(), resultFormat="result-v1",
        result=dict(bytes="AAEC/w==", mediaType="application/octet-stream", metadata=[["business", ""]]))
    value["commitReceipt"] = dict(commandId="command-a", attemptId="attempt-a", transactionId="transaction-a",
        receiptId="receipt-a", committedVersion="YTE6NQ==", committedAtUnixMillis="18446744073709551615",
        effectIds=["effect-a"], sourceIdentity=source())
    value["effects"] = [dict(effectId="effect-a", commandId="command-a", commandAttemptId="attempt-a",
        dispatchAttempt=4294967295, disposition="uncertain-after-dispatch", occurredAtUnixMillis="0",
        retention=retention(record_format="lsf-effect-intent-v1"), providerProfile="approved-provider-v1")]
    return value


class TransactionReceiptTests(unittest.TestCase):
    def test_committed_cleanup_and_uncertain_effect_keep_original_commit(self):
        value = committed()
        value["cleanupFailure"] = "cleanup-unavailable"
        self.assertIs(envelope(value), value)
        self.assertTrue(value["applicationStateCommitted"])
        self.assertEqual(value["effects"][0]["disposition"], "uncertain-after-dispatch")
        self.assertNotEqual(value["sourceIdentity"]["releaseDigest"], value["sourceIdentity"]["componentDigest"])

    def test_retained_rejection_uses_original_old_application_format_without_state_commit(self):
        value = committed()
        del value["commitReceipt"], value["effects"]
        value.update(outcome="rejected", applicationStateCommitted=False, resultFormat="result-old-v1")
        value["sourceIdentity"]["resultFormat"] = "result-old-v1"
        self.assertIs(envelope(value), value)
        self.assertEqual(base64.b64decode(value["result"]["bytes"]), b"\0\1\2\xff")
        for changes in ({"applicationStateCommitted": True}, {"provenAbort": dict(commandId="command-a",
                attemptId="attempt-a", transactionId="transaction-a", ownerFence="YQ==")}, {"resultFormat": "result-active-v2"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                envelope({**value, **changes})

    def test_expired_payload_keeps_known_commit_but_unknown_never_supplies_abort_proof(self):
        value = committed()
        value["retention"]["payloadAvailable"] = False
        del value["result"], value["resultFormat"]
        self.assertIs(envelope(value), value)
        self.assertEqual(value["outcome"], "committed")
        fence = dict(commandId="command-a", attemptId="attempt-a", transactionId="transaction-a", ownerFence="YQ==")
        for outcome in ("unknown", "expired", "in-progress", "recovery-required"):
            unknown = dict(kind="response", profile="lsf-transaction-v1", outcome=outcome,
                metadataDurable=False, applicationStateCommitted=False)
            envelope(unknown)
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                envelope({**unknown, "provenAbort": fence})
            with self.assertRaises(ValueError):
                envelope({**unknown, "applicationStateCommitted": True})

    def test_abort_fence_is_specific_to_old_attempt_and_not_structural_authority(self):
        value = dict(kind="response", profile="lsf-transaction-v1", outcome="aborted", metadataDurable=True,
            applicationStateCommitted=False, commandId="command-a", attemptId="attempt-a", receiptId="abort-receipt",
            retention=retention(available=False))
        envelope(value)  # A durable abort alone says nothing about physical-owner retirement.
        fence = dict(commandId="command-a", attemptId="attempt-a", transactionId="transaction-a", ownerFence="YQ==")
        envelope({**value, "provenAbort": fence})
        for changes in ({"attemptId": "new-attempt"}, {"ownerFence": ""}, {"ownerFence": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                envelope({**value, "provenAbort": {**fence, **changes}})

    def test_fresh_query_has_view_and_no_durable_command_or_effect_identity(self):
        value = dict(kind="response", profile="lsf-transaction-v1", outcome="query-returned",
            metadataDurable=False, applicationStateCommitted=False, sourceIdentity=source(), resultFormat="result-v1",
            result=dict(bytes="", mediaType="application/octet-stream", metadata=[]),
            viewIdentity=dict(namespace="app", incarnation="i1", version="YTE6NQ==", stateSchema=source()["stateSchema"]))
        envelope(value)
        for changes in ({"commandId": "command-a"}, {"effects": []}, {"retention": retention()},
                {"viewVersion": "Yg=="}, {"resultFormat": "future-v2"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                envelope({**value, **changes})

    def test_receipt_links_unknown_formats_and_full_width_integers_fail_closed(self):
        paths = [(["commitReceipt", "attemptId"], "foreign-attempt"),
            (["commitReceipt", "sourceIdentity", "componentDigest"], "sha256:" + "5" * 64),
            (["commitReceipt", "committedAtUnixMillis"], "18446744073709551616"),
            (["commitReceipt", "committedVersion"], ""), (["sourceIdentity", "publicationId"], "é" * 129),
            (["retention", "recordVersion"], True), (["retention", "recordVersion"], 2),
            (["retention", "recordFormat"], "future-format"), (["retention", "payloadExpiresAtUnixMillis"], "3000"),
            (["effects", 0, "commandAttemptId"], "foreign-attempt"), (["effects", 0, "disposition"], "future-disposition"),
            (["effects", 0, "dispatchAttempt"], True), (["effects", 0, "dispatchAttempt"], 4294967296),
            (["effects", 0, "retention", "recordFormat"], "lsf-command-result-v1")]
        for path, replacement in paths:
            value, owner = committed(), None
            owner = value
            for key in path[:-1]:
                owner = owner[key]
            owner[path[-1]] = replacement
            with self.subTest(path=path, replacement=replacement), self.assertRaises(ValueError):
                envelope(value)
        value = committed()
        value["effects"].append(copy.deepcopy(value["effects"][0]))
        with self.assertRaises(ValueError):
            envelope(value)
        value = committed()
        value["effects"][0]["disposition"] = "administratively-terminated"
        with self.assertRaises(ValueError):
            envelope(value)
        value["effects"][0]["managementOperationReceiptId"] = "management-receipt"
        envelope(value)

    def test_decoded_result_and_envelope_traversal_are_bounded_before_schema_recursion(self):
        value = committed()
        value["result"]["bytes"] = base64.b64encode(b"x" * VALUE_BYTES).decode()
        envelope(value)
        value["result"]["bytes"] = base64.b64encode(b"x" * (VALUE_BYTES + 1)).decode()
        with self.assertRaises(ValueError):
            envelope(value)
        for media in ("text/plain\n", "text/plain\t", "application/é"):
            with self.subTest(media=media), self.assertRaises(ValueError):
                content(dict(bytes="", mediaType=media, metadata=[]))
        with self.assertRaisesRegex(ValueError, "traversal-limit"):
            envelope([None] * ENVELOPE_NODES)
        nested = None
        for _ in range(34):
            nested = [nested]
        with self.assertRaisesRegex(ValueError, "traversal-limit"):
            envelope(nested)
        with self.assertRaises(ValueError):
            envelope({"kind": "response", "unknown": "\ud800"})

    def test_six_guest_and_external_profiles_are_complete_and_independent(self):
        value = requirements()
        self.assertEqual(value, json.loads((ROOT / "sdk/profile/transaction-requirements-v1.json").read_text(encoding="utf-8")))
        self.assertEqual(len(value["languages"]), 6)
        self.assertTrue(value["independentQualification"])
        self.assertFalse(value["guest"]["executionQualified"])
        self.assertFalse(value["externalClient"]["transportExecutionQualified"])
        self.assertEqual(sum(len(item["operations"]) for item in value["guest"]["requiredInterfaces"]), 13)
        self.assertEqual(sum(len(item["operations"]) for item in value["externalClient"]["requiredServices"]), 11)
        self.assertNotEqual(value["guest"]["profile"], value["externalClient"]["profile"])

    def test_raw_http_decoder_rejects_duplicate_fields_and_deep_json_before_lifting(self):
        value = committed()
        value["result"]["metadata"] = [["business", "[{}]\\\"quoted"]]
        self.assertEqual(decode_envelope(json.dumps(value).encode("utf-8")), value)
        duplicate = json.dumps(value).replace('"profile": "lsf-transaction-v1"',
            '"profile": "future", "profile": "lsf-transaction-v1"').encode()
        with self.assertRaisesRegex(ValueError, "duplicate-json-field"):
            decode_envelope(duplicate)
        for raw in (b"[" * 35 + b"null" + b"]" * 35, b"[0," * 17000 + b"0" + b"]" * 17000,
                b" " * (ENVELOPE_BYTES + 1), b'{"profile":"\xff"}', b'{"profile":NaN}'):
            with self.subTest(prefix=raw[:32]), self.assertRaises(ValueError):
                decode_envelope(raw)


if __name__ == "__main__":
    unittest.main()
