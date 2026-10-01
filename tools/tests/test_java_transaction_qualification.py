"""Qualification-oracle tests. Synthetic frames are not node execution evidence."""
from __future__ import annotations

import base64
import copy
import json
import time
import unittest

from tools.java_transaction_qualification import http, inputs


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def token(kind=b"NV", generation=2):
    return kind + b"\x02" + bytes([17]) * 32 + b"".join(
        value.to_bytes(8, "little") for value in (1, generation, 1, 1))


def result(disposition="committed", count="18446744073709551615"):
    frame = [{"ok": {"count": count, "view-version": list(token()),
                     "key-version": {"none": None}}}]
    query = disposition == "query"
    return {"profile": "transaction-http-v1", "disposition": disposition,
            "representation": "application-result", "command-id": None if query else "1" * 64,
            "attempt-id": None if query else "2" * 64,
            "state-view": base64.b64encode(token()).decode(), "effect-ids": [] if query else ["3" * 64],
            "result-expires-at": None if query else "18446744073709551615",
            "delivery-failure": None, "abort-fence": None,
            "result": {"media-type": http.VALUE_MEDIA, "body-base64": base64.b64encode(encoded(frame)).decode(),
                       "error-code": None, "error-message": None}}


HEADERS = [("Content-Type", http.RESULT_MEDIA), ("Cache-Control", "no-store")]


class SchemaAssetOracle(unittest.TestCase):
    def schema_files(self):
        from tools.java_transaction_qualification import packaging
        files = {path: b"original-captured-bytes" for path in packaging.SCHEMA_ASSETS}
        files[packaging.CODEC_ASSET] = b"original-captured-compatible-reader"
        files["application-schema-inputs.json"] = encoded({
            "schemaVersion": "latent.java.application-schema-inputs.v1",
            "variant": "writer-v2",
            "sourceDigest": inputs.digest(files["src/dev/latent/app/Capsule.java"]),
            "publicationReviewGranted": False, "componentCompiled": False,
            "stateExecutionQualified": False})
        return files

    def test_original_schema_source_assets_remain_exact_and_do_not_grant_review(self):
        from tools.java_transaction_qualification import packaging
        files = self.schema_files()
        selected = packaging.schema_assets(files)
        self.assertEqual(selected, files)
        self.assertTrue(all(selected[path] is files[path] for path in selected))
        self.assertEqual(packaging.schema_assets({"state-schema.json": b"original"}), {})

    def test_schema_asset_selection_refuses_missing_changed_source_and_invented_qualification(self):
        from tools.java_transaction_qualification import packaging
        for change in ("missing-codec", "changed-source", "invented-review"):
            files = self.schema_files()
            if change == "missing-codec":
                del files["src/dev/latent/app/AggregateCodec.java"]
            elif change == "changed-source":
                files["src/dev/latent/app/Capsule.java"] += b"changed"
            else:
                declaration = inputs.decode(files["application-schema-inputs.json"])
                declaration["publicationReviewGranted"] = True
                files["application-schema-inputs.json"] = encoded(declaration)
            with self.subTest(change=change), self.assertRaises(ValueError):
                packaging.schema_assets(files)

class QualificationOracle(unittest.TestCase):
    def test_duplicate_and_nonfinite_input_documents_refuse(self):
        for raw in (b'{"schemaVersion":1,"schemaVersion":1}', b'{"v":NaN}', b'{"v":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                inputs.decode(raw)

    def test_original_unsigned_maximum_and_absence_survive_decoding(self):
        observed = http.response(200, encoded(result()), HEADERS)
        aggregate = http.aggregate(observed)
        self.assertEqual(aggregate["count"], "18446744073709551615")
        self.assertEqual(aggregate["key-version"], {"none": None})

    def test_numeric_or_overflowing_unsigned_values_never_qualify(self):
        for count in (1, "01", "-1", "18446744073709551616"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                http.aggregate(result(count=count))

    def test_present_key_version_is_distinct_from_absent_and_zero(self):
        value = result()
        frame = [{"ok": {"count": "1", "view-version": list(token()),
                         "key-version": {"some": list(token(b"SV"))}}}]
        value["result"]["body-base64"] = base64.b64encode(encoded(frame)).decode()
        self.assertIn("some", http.aggregate(value)["key-version"])
        frame[0]["ok"]["key-version"] = {"none": []}
        value["result"]["body-base64"] = base64.b64encode(encoded(frame)).decode()
        with self.assertRaises(ValueError):
            http.aggregate(value)

    def test_opaque_token_requires_exact_canonical_format_and_positive_epochs(self):
        for raw in (token()[:-1], b"NV\x01" + token()[3:], token()[:59] + bytes(8)):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                http.view_token(base64.b64encode(raw).decode())
        valid = base64.b64encode(token()).decode()
        with self.assertRaises(ValueError):
            http.view_token(valid + "=")

    def test_fresh_query_has_no_durable_command_and_reports_same_view(self):
        value = result("query")
        self.assertEqual(http.fresh_query(http.response(200, encoded(value), HEADERS))["count"],
                         "18446744073709551615")
        value["state-view"] = base64.b64encode(token(generation=3)).decode()
        with self.assertRaises(ValueError):
            http.fresh_query(http.response(200, encoded(value), HEADERS))

    def test_query_cannot_adopt_effects_or_original_command_identity(self):
        for field, data in (("effect-ids", ["3" * 64]), ("command-id", "1" * 64)):
            value = result("query")
            value[field] = data
            with self.subTest(field=field), self.assertRaises(ValueError):
                http.response(200, encoded(value), HEADERS)

    def test_replay_preserves_original_bytes_identity_and_horizons(self):
        original = result()
        for field, value in (("command-id", "4" * 64), ("attempt-id", "4" * 64),
                             ("effect-ids", []), ("result-expires-at", "18446744073709551614"),
                             ("state-view", base64.b64encode(token(generation=3)).decode()),
                             ("result", result(count="1")["result"])):
            changed = copy.deepcopy(original)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                http.replay(original, changed)
        delivery = copy.deepcopy(original)
        delivery["delivery-failure"] = "permission-denied"
        http.replay(original, delivery)

    def test_expired_receipt_never_reconstitutes_application_result(self):
        value = result()
        value.update(representation="receipt-only", result=None)
        observed = http.response(410, encoded(value), HEADERS)
        self.assertEqual(observed["command-id"], "1" * 64)
        self.assertIsNone(observed["result"])
        with self.assertRaises(ValueError):
            http.aggregate(observed)

    def test_host_headers_and_closed_result_fields_refuse_historical_sessions(self):
        for headers in (HEADERS + [("Set-Cookie", "session=value")],
                        HEADERS + [("Content-Type", http.RESULT_MEDIA)]):
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                http.response(200, encoded(result()), headers)
        value = result()
        value["invented-committed"] = True
        with self.assertRaises(ValueError):
            http.response(200, encoded(value), HEADERS)

    def test_abort_requires_original_server_issued_proof_and_same_identities(self):
        value = result("aborted")
        value.update(representation="receipt-only", result=None)
        with self.assertRaises(ValueError):
            http.response(409, encoded(value), HEADERS)
        value["abort-fence"] = {"command-id": value["command-id"], "attempt-id": value["attempt-id"],
                                "transaction-id": "4" * 64, "owner-fence": base64.b64encode(bytes(32)).decode()}
        http.response(409, encoded(value), HEADERS)
        value["abort-fence"]["attempt-id"] = "5" * 64
        with self.assertRaises(ValueError):
            http.response(409, encoded(value), HEADERS)

    def test_network_campaign_is_bounded_by_original_deadline_and_loopback_authority(self):
        for authority, deadline, count in (("remote.example:443", time.monotonic() + 10, 1),
                                            ("localhost:65536", time.monotonic() + 10, 1),
                                            ("localhost:1234", time.monotonic() - 1, 1),
                                            ("localhost:1234", time.monotonic() + 10, 129)):
            with self.subTest(authority=authority), self.assertRaises(ValueError):
                http.Http(authority, deadline, maximum_requests=count)


if __name__ == "__main__":
    unittest.main()
