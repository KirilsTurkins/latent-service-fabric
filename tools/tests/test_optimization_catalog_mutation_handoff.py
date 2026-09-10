"""Unit handoff graphs; synthetic identities never qualify as measurement evidence."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from tools.optimization_backend_revision.catalog_mutations import data, evidence, model
from tools.optimization_evidence.common import EvidenceError, canonical, sha256

COMMIT = "a" * 40


class Documents:
    """Small, hash-bound JSON artifacts for the isolated persistence validator."""

    def __init__(self):
        self.values = {}

    def put(self, path, value):
        body = canonical(value) + b"\n"
        reference = {"path": path, "bytes": str(len(body)), "sha256": sha256(body)}
        self.values[path] = deepcopy(value)
        return reference

    def json(self, reference):
        value = deepcopy(self.values[reference["path"]])
        body = canonical(value) + b"\n"
        if reference != {"path": reference["path"], "bytes": str(len(body)), "sha256": sha256(body)}:
            raise EvidenceError("test-document-reference-crossed")
        return value


def fixture(mode="allocation"):
    selected_row = next(row for row in model.population("smoke")
                        if row["variant"] == "control" and row["shape"] == "distinct" and row["mode"] == mode)
    selected = model.plan("smoke", **selected_row)
    documents = Documents()
    marker = data.marker(selected, COMMIT, nonce="1" * 32)
    identity = {"device": "17", "inode": "99", "marker": marker,
                "marker_sha256": sha256(canonical(marker) + b"\n")}
    owner_ref = documents.put("owner.json", marker)
    reserve_ref = documents.put("reserve.json", {
        "source": "statvfs-f_bavail-times-f_frsize", "available_bytes": str(data.MAX_TREE_BYTES),
        "required_bytes": "0", "scope": "native-filesystem-available-not-host-backing-capacity"})
    first = selected_row["sequence_ordinal"] - int(model.is_reopen(mode))
    cleanup_ref = documents.put("cleanup.json", {
        "removed": True, "data_identity": identity, "sequence_ordinals": [first, first + 1],
        "filesystem_reserve": reserve_ref,
        "close_walk": {"scope": "one-post-exit-generated-root-walk-before-removal",
            "regular_files": "3", "directories_including_root": "3", "logical_file_bytes": "4096",
            "allocated_file_bytes": "12288", "maximum_file_bytes": "2048", "complete": True,
            "symlinks_or_special_files": False, "cross_device_entries": False}})
    raw_ref = documents.put("initial-raw.json", {"unit_fixture": True})
    source_process = {"process_id": 202, "start_time_ticks": "20"}
    wrapper_process = {"process_id": 201, "start_time_ticks": "19"}
    profiled = model.profiled(mode)
    post_exit = documents.put("post-exit.json", {
        "schema": data.REOPEN_SCHEMA, "data_identity": identity,
        "initial_process": source_process if profiled else wrapper_process,
        "catalog": {"path": data.CATALOG_PATH, "bytes": "2048", "sha256": sha256(b"unit catalog")},
        "initial_raw": raw_ref})
    row = {**selected_row, "data_owner": owner_ref, "cleanup": cleanup_ref,
           "process": wrapper_process, "probe_process": source_process if profiled else None,
           "raw": raw_ref, "post_exit": None if model.is_reopen(mode) else post_exit,
           "reopen_input": post_exit if model.is_reopen(mode) else None}
    previous = {**selected_row, "mode": "allocation" if profiled else "initial", "status": "passed",
                "sequence_ordinal": first, "data_owner": owner_ref, "post_exit": post_exit,
                "data_identity": deepcopy(identity)}
    return SimpleNamespace(row=row, checked={"data_identity": deepcopy(identity)},
        records=[previous] if model.is_reopen(mode) else [], documents=documents,
        selected=selected, source={"source": {"commit": COMMIT}})


def validate(value):
    evidence.persistence(value.row, value.checked, value.records, value.documents,
                         value.selected, value.source)


def replace_document(value, field, mutate):
    reference = value.row[field]
    document = value.documents.json(reference)
    mutate(document)
    value.row[field] = value.documents.put(reference["path"], document)


class CatalogMutationHandoffTests(unittest.TestCase):
    def test_initial_handoff_uses_source_child_for_profile_and_wrapper_for_normal(self):
        for mode in ("initial", "allocation"):
            value = fixture(mode)
            with self.subTest(mode=mode):
                validate(value)
            self.assertNotEqual(value.row["process"], {"process_id": 202, "start_time_ticks": "20"})

    def test_profile_handoff_rejects_wrapper_pid_or_crossed_source_start_time(self):
        replacements = ({"process_id": 201, "start_time_ticks": "19"},
                        {"process_id": 202, "start_time_ticks": "21"},
                        {"process_id": 203, "start_time_ticks": "20"})
        for process in replacements:
            value = fixture()
            replace_document(value, "post_exit", lambda receipt: receipt.update(initial_process=process))
            with self.subTest(process=process), self.assertRaisesRegex(EvidenceError, "catalog-post-exit-source-binding"):
                validate(value)

    def test_normal_handoff_cannot_substitute_an_unrelated_profile_source(self):
        value = fixture("initial")
        replace_document(value, "post_exit", lambda receipt: receipt.update(
            initial_process={"process_id": 202, "start_time_ticks": "20"}))
        with self.assertRaisesRegex(EvidenceError, "catalog-post-exit-source-binding"):
            validate(value)

    def test_initial_handoff_binds_raw_root_and_catalog_path_and_bounds(self):
        changes = (
            ("initial_raw", {"path": "foreign.json", "bytes": "1", "sha256": sha256(b"x")}),
            ("data_identity", {**fixture().checked["data_identity"], "inode": "100"}),
            ("catalog", {"path": "../catalog.json", "bytes": "2048", "sha256": sha256(b"unit catalog")}),
            ("catalog", {"path": data.CATALOG_PATH, "bytes": "0", "sha256": sha256(b"unit catalog")}),
            ("catalog", {"path": data.CATALOG_PATH, "bytes": str(1024**3 + 1), "sha256": sha256(b"unit catalog")}),
        )
        for field, replacement in changes:
            value = fixture()
            replace_document(value, "post_exit", lambda receipt: receipt.update({field: replacement}))
            with self.subTest(field=field, value=replacement), self.assertRaises(EvidenceError):
                validate(value)

    def test_adjacent_reopen_accepts_both_normal_and_profiled_initial_owners(self):
        for mode in ("reopen", "allocation-reopen"):
            with self.subTest(mode=mode):
                validate(fixture(mode))

    def test_profiled_reopen_rejects_size_mode_arm_shape_repetition_and_nonadjacency(self):
        changes = (("populated_size", 128), ("mode", "initial"), ("mode", "allocation-reopen"),
                   ("variant", "candidate"), ("shape", "shared"), ("repetition", 2),
                   ("sequence_ordinal", 0), ("status", "failed"))
        for field, replacement in changes:
            value = fixture("allocation-reopen")
            value.records[-1][field] = replacement
            with self.subTest(field=field, value=replacement), self.assertRaisesRegex(
                    EvidenceError, "catalog-reopen-not-adjacent-same-root"):
                validate(value)
        value = fixture("allocation-reopen")
        value.records.clear()
        with self.assertRaisesRegex(EvidenceError, "catalog-reopen-not-adjacent-same-root"):
            validate(value)

    def test_reopen_rejects_crossed_root_owner_receipt_or_unexpected_post_exit(self):
        for field in ("data_identity", "data_owner", "post_exit", "reopen_input"):
            value = fixture("allocation-reopen")
            if field == "data_identity":
                value.records[-1][field]["inode"] = "100"
            elif field == "data_owner":
                value.records[-1][field] = {**value.row[field], "path": "foreign-owner.json"}
            elif field == "post_exit":
                value.row[field] = deepcopy(value.row["reopen_input"])
            else:
                value.row[field] = {**value.row[field], "path": "foreign-post-exit.json"}
            with self.subTest(field=field), self.assertRaisesRegex(
                    EvidenceError, "catalog-reopen-not-adjacent-same-root"):
                validate(value)

    def test_reopen_marker_rejects_crossed_source_commit(self):
        value = fixture("allocation-reopen")
        value.source["source"]["commit"] = "b" * 40
        with self.assertRaisesRegex(EvidenceError, "catalog-mutation-data-marker-selection"):
            validate(value)

    def test_cleanup_cannot_claim_another_root_or_adjacent_owner_pair(self):
        changes = (("removed", False), ("sequence_ordinals", [0, 1]),
                   ("data_identity", {**fixture().checked["data_identity"], "device": "18"}))
        for field, replacement in changes:
            value = fixture("allocation-reopen")
            replace_document(value, "cleanup", lambda receipt: receipt.update({field: replacement}))
            with self.subTest(field=field), self.assertRaisesRegex(
                    EvidenceError, "catalog-parent-data-not-removed-or-crossed"):
                validate(value)


class CatalogMutationMarkerTests(unittest.TestCase):
    def test_strict_identity_binds_canonical_marker_bytes_and_exact_selection(self):
        value = fixture()
        identity = value.checked["data_identity"]
        self.assertEqual(data.validate_identity(identity, value.selected, COMMIT), identity)
        for field, replacement in (("device", True), ("inode", "0"), ("inode", 99),
                                   ("marker_sha256", sha256(canonical(identity["marker"]))),
                                   ("marker_sha256", sha256(b"crossed")), ("extra", "unplanned")):
            damaged = deepcopy(identity)
            damaged[field] = replacement
            with self.subTest(field=field, value=replacement), self.assertRaises(EvidenceError):
                data.validate_identity(damaged, value.selected, COMMIT)

    def test_marker_rejects_boolean_populations_foreign_source_and_unknown_fields(self):
        value = fixture()
        marker = value.checked["data_identity"]["marker"]
        changes = (("repetition", True), ("populated_size", True), ("populated_size", 128),
                   ("variant", "candidate"), ("shape", "shared"), ("group", "another-owner"),
                   ("source_commit", "b" * 40), ("schema", data.REOPEN_SCHEMA),
                   ("nonce", "A" * 32), ("nonce", "1" * 31), ("extra", "unplanned"))
        for field, replacement in changes:
            damaged = deepcopy(marker)
            damaged[field] = replacement
            with self.subTest(field=field, value=replacement), self.assertRaises(EvidenceError):
                data.validate_marker(damaged, value.selected, COMMIT)
        for commit in ("A" * 40, "a" * 39, 1, None):
            with self.subTest(commit=commit), self.assertRaises(EvidenceError):
                data.validate_marker(marker, value.selected, commit)
