"""Structural cleanup boundary only; these projections cannot qualify campaigns."""
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SOURCE = {"commit": "2f7e3b1616056ba11a7e97ac613cdc3f416eb8c0",
          "tree": "d9b5d8fa0035145ddfbc0e77ef03b101d2a486c4", "clean": True,
          "cargo_lock_sha256": "sha256:08974270174575379a10e4f83920755aba00a33b61d2f8e63e5b05b6ea6695d1"}
ERROR = [{"reason": "kubernetes-worker-exec-stderr", "stage": "owned-resources", "type": "EvidenceError"}]


def historical_projection():
    return {"profile": "smoke", "run_id": "smoke-03", "owner": "lsf-112-8c22b65b1529",
            "namespace": "lsf-112-8c22b65b1529-smoke-03", "namespace_uid": "1e40c576-a29b-45be-b497-dad8f8f826bd",
            "source": copy.deepcopy(SOURCE), "source_after": copy.deepcopy(SOURCE),
            "cleanup": {"schema": "latent.optimization.kubernetes-cleanup.v1", "errors": copy.deepcopy(ERROR),
                        "namespace_absent": True, "remote_removed": False, "private_tls_removed": True}}


class KubernetesSuiteSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads((ROOT / "tools/optimization_kubernetes/schemas/suite.schema.json").read_bytes())
        keys = historical_projection().keys()
        cls.validator = Draft202012Validator({"$defs": cls.schema["$defs"], "type": "object",
            "required": list(keys), "properties": {key: cls.schema["properties"][key] for key in keys},
            "$ref": "#/$defs/cleanupOutcome"})

    def test_schema_and_historical_projection(self):
        Draft202012Validator.check_schema(self.schema)
        self.assertIn({"$ref": "#/$defs/cleanupOutcome"}, self.schema["allOf"])
        self.validator.validate(historical_projection())

    def test_every_historical_identity_guard_rejects_the_error_elsewhere(self):
        for key, value in (("profile", "full"), ("run_id", "smoke-04"), ("owner", "lsf-112-000000000000"),
                           ("namespace", "another-namespace"), ("namespace_uid", "different-uid")):
            with self.subTest(key=key):
                row = historical_projection()
                row[key] = value
                self.assertFalse(self.validator.is_valid(row))
                row["cleanup"].update(errors=[], remote_removed=True)
                self.validator.validate(row)

    def test_both_exact_source_receipts_are_required(self):
        for key in ("source", "source_after"):
            for field, value in (("commit", "0" * 40), ("tree", "0" * 40),
                                 ("cargo_lock_sha256", "sha256:" + "0" * 64), ("clean", False)):
                with self.subTest(key=key, field=field):
                    row = historical_projection()
                    row[key][field] = value
                    self.assertFalse(self.validator.is_valid(row))

    def test_exact_error_and_unremoved_original_are_preserved(self):
        changes = ([], ERROR * 2, [{**ERROR[0], "reason": "different-error"}],
                   [{**ERROR[0], "stage": "another-stage"}], [{**ERROR[0], "type": "OtherError"}],
                   [{**ERROR[0], "extra": True}])
        for errors in changes:
            with self.subTest(errors=errors):
                row = historical_projection()
                row["cleanup"]["errors"] = errors
                self.assertFalse(self.validator.is_valid(row))
        row = historical_projection()
        row["cleanup"]["remote_removed"] = True
        self.assertFalse(self.validator.is_valid(row))

    def test_other_suites_require_both_clean_cleanup_fields(self):
        for profile in ("smoke", "full"):
            for errors, removed in (([], False), (ERROR, False), (ERROR, True)):
                with self.subTest(profile=profile, errors=errors, removed=removed):
                    row = historical_projection()
                    row.update(profile=profile, run_id="new-run")
                    row["cleanup"].update(errors=copy.deepcopy(errors), remote_removed=removed)
                    self.assertFalse(self.validator.is_valid(row))

    def test_missing_guards_and_cleanup_fields_never_enable_exception(self):
        for key in historical_projection():
            with self.subTest(key=key):
                row = historical_projection()
                del row[key]
                self.assertFalse(self.validator.is_valid(row))
        for key in historical_projection()["cleanup"]:
            with self.subTest(cleanup_key=key):
                row = historical_projection()
                del row["cleanup"][key]
                self.assertFalse(self.validator.is_valid(row))


if __name__ == "__main__":
    unittest.main()
