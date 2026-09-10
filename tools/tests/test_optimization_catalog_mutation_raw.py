"""Actual dirty Linux receipts exercise replay; they never qualify release results."""
from copy import deepcopy
import gzip
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import unittest

from tools.optimization_backend_revision.catalog_mutations import events, fixtures, model
from tools.optimization_backend_revision.catalog_mutations.evidence import persistence
from tools.optimization_backend_revision.catalog_mutations.parse import parse
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import EvidenceError, sha256, uint
from tools.optimization_evidence.resources import clean, process

FIXTURE = Path(__file__).parent / "fixtures/catalog_mutation_diagnostic"


def restore(destination):
    """Restore bounded individual gzip files, without extracting an archive."""
    manifest = json.loads((FIXTURE / "manifest.json").read_bytes())
    if manifest["qualifying"] is not False or not 1 <= len(manifest["files"]) <= 64:
        raise AssertionError("diagnostic fixture scope or file bound")
    total, names = 0, set()
    for row in manifest["files"]:
        name = row["original_path"]
        relative = PurePosixPath(name)
        if (relative.is_absolute() or relative.as_posix() != name or name in names
                or any(part in (".", "..") for part in relative.parts)
                or "\\" in name or ":" in name or not relative.parts
                or re.fullmatch(r"retained/[0-9]{2}\.gz", row["path"]) is None):
            raise AssertionError("diagnostic fixture path")
        names.add(name)
        stored = FIXTURE / row["path"]
        if stored.is_symlink() or not stored.is_file() or stored.stat().st_size > 1024**2:
            raise AssertionError("diagnostic compressed file bound")
        compressed = stored.read_bytes()
        if str(len(compressed)) != row["bytes"] or sha256(compressed) != row["sha256"]:
            raise AssertionError("diagnostic compressed bytes changed")
        with gzip.open(stored, "rb") as stream:
            body = stream.read(1024**2 + 1)
        total += len(body)
        if len(body) > 1024**2 or total > 2 * 1024**2:
            raise AssertionError("diagnostic expanded byte bound")
        if str(len(body)) != row["original_bytes"] or sha256(body) != row["original_sha256"]:
            raise AssertionError("original diagnostic bytes changed")
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(body)
    if str(total) != manifest["original_total_bytes"]:
        raise AssertionError("diagnostic total bytes changed")
    return manifest


class ActualCatalogMutationRawTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="catalog-mutation-replay-")
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        cls.manifest = restore(cls.root)
        cls.artifacts = Artifacts(cls.root, inventory(cls.root))
        cls.fixture = fixtures.load(cls.manifest["echo"], cls.artifacts)
        suite = json.loads((cls.root / "diagnostic-suite.json").read_bytes())
        if suite["qualifying"] is not False or len(suite["runs"]) != 4:
            raise AssertionError("actual diagnostic population changed")
        cls.rows = suite["runs"]
        cls.raw = {(row["shape"], row["mode"]): cls.artifacts.json(row["raw"]) for row in cls.rows}

    def replay(self, row, value=None, previous=()):
        selected = model.plan("smoke", **{key: row[key] for key in model.SELECTORS})
        identity = self.artifacts.json(row["identity"])
        self.assertTrue(identity["source"]["dirty"])
        self.assertIs(identity["build"]["qualifying"], False)
        self.assertIs(identity["diagnostic"]["qualifying"], False)
        self.assertEqual(identity["diagnostic"]["source_snapshot"], self.manifest["source_snapshot"])
        self.assertEqual(self.artifacts.json(row["plan"]), selected)
        owner = process(row["process"], "artifact-identity-helper", identity["binary"]["sha256"])
        self.assertTrue(clean(row["process"]))
        raw = deepcopy(self.raw[row["shape"], row["mode"]]) if value is None else value
        checked = parse(raw, selected, identity, self.fixture, row, self.artifacts)
        self.assertEqual(checked["process_identity"], [owner[0], uint(owner[1])])
        events.parse(row, self.artifacts, tuple(checked["process_identity"]), raw)
        persistence(row, checked, previous, self.artifacts, selected, identity)
        return {**row, **checked}

    def initial(self, shape="distinct"):
        row = next(row for row in self.rows if row["shape"] == shape and row["mode"] == "initial")
        return row, deepcopy(self.raw[shape, "initial"])

    @staticmethod
    def labeled(value, label):
        return next(row for row in value["samples"] if row.get("label") == label)

    def test_all_four_actual_owners_replay_with_real_events_and_same_root_handoffs(self):
        results = []
        for row, commands in zip(self.rows, (40, 6, 41, 6), strict=True):
            with self.subTest(shape=row["shape"], mode=row["mode"]):
                result = self.replay(row, previous=results)
                self.assertEqual(result["validated_commands"], str(commands))
                self.assertEqual(result["validated_invocations"], "0")
                self.assertEqual(result["allocation_frames"], [])
                self.assertTrue(result["attempt_count_complete"])
                self.assertEqual(result["operations"]["resolves"]["returned_error"],
                                 "2" if row["mode"] == "initial" and row["shape"] == "distinct"
                                 else "1" if row["mode"] == "initial" else "0")
                results.append(result)
        self.assertEqual(sum(int(row["validated_commands"]) for row in results), 93)
        source_after = json.loads((self.root / "source-after.json").read_bytes())
        self.assertEqual(source_after["status"], "unchanged")
        self.assertIs(source_after["qualifying"], False)
        self.assertEqual(source_after["snapshot"], self.manifest["source_snapshot"])

    def test_command_ordinal_cannot_skip_a_public_call(self):
        row, value = self.initial()
        self.labeled(value, "unchanged-apply")["ordinal"] = "8"
        with self.assertRaisesRegex(EvidenceError, "catalog-mutation-command-lineage"):
            self.replay(row, value)

    def test_current_pin_must_advance_for_each_actual_mutation(self):
        for label in model.MUTATIONS:
            row, value = self.initial()
            self.labeled(value, label + "/current-pin")["result"]["generation"] = "1"
            with self.subTest(label=label), self.assertRaisesRegex(EvidenceError, "catalog-mutation-public-proof"):
                self.replay(row, value)

    def test_old_pin_policy_and_generation_cannot_change_with_current_state(self):
        for changed in ("policy", "resolved-generation"):
            row, value = self.initial("shared")
            if changed == "policy":
                self.labeled(value, "weight-update/old-policy")["result"]["execution"]["limits"]["cpuFuel"] = "1"
            else:
                self.labeled(value, "weight-update/old-named")["result"]["generation"] = "3"
            with self.subTest(changed=changed), self.assertRaisesRegex(EvidenceError, "catalog-mutation-public-proof"):
                self.replay(row, value)

    def test_versioned_receipts_keep_delete_stamp_and_create_only_precondition(self):
        for changed in ("deleted-stamp", "reapply-precondition", "reapply-stamp"):
            row, value = self.initial()
            if changed == "deleted-stamp":
                self.labeled(value, "delete")["outcome"]["result"]["deleted"]["object_generation"] = "4"
            elif changed == "reapply-precondition":
                self.labeled(value, "reapply")["expected_generation"] = "3"
            else:
                self.labeled(value, "reapply")["outcome"]["result"]["deployment"]["object_generation"] = "1"
            with self.subTest(changed=changed), self.assertRaisesRegex(EvidenceError, "catalog-mutation-public-receipt"):
                self.replay(row, value)

    def test_deleted_get_is_absent_even_while_the_old_pin_remains_live(self):
        for shape in model.SHAPES:
            row, value = self.initial(shape)
            stale = deepcopy(self.labeled(value, "weight-update/get")["result"])
            self.labeled(value, "delete/get")["result"] = stale
            with self.subTest(shape=shape), self.assertRaisesRegex(EvidenceError, "catalog-mutation-public-proof"):
                self.replay(row, value)

    def test_observer_sequence_cannot_hide_an_extra_completed_operation(self):
        row, value = self.initial()
        after = self.labeled(value, "unchanged-apply")["observer_after"]
        after["started"] = after["finished"] = after["last"]["sequence"] = "4"
        with self.assertRaisesRegex(EvidenceError, "catalog-mutation-work-sequence"):
            self.replay(row, value)

    def test_cpu_capture_must_bracket_the_actual_public_future(self):
        for side in ("cpu_before", "cpu_after"):
            row, value = self.initial()
            mutation = self.labeled(value, "unchanged-apply")
            if side == "cpu_before":
                mutation[side]["collector_finished_nanos"] = str(int(mutation["started_nanos"]) + 1)
            else:
                mutation[side]["collector_started_nanos"] = str(int(mutation["finished_nanos"]) - 1)
            with self.subTest(side=side), self.assertRaisesRegex(EvidenceError, "engine-cpu-owner-or-capture-crossed"):
                self.replay(row, value)

    def test_unplanned_operation_after_final_checkpoint_cannot_be_dropped(self):
        row, value = self.initial()
        value["samples"].append(deepcopy(self.labeled(value, "reapply/get")))
        with self.assertRaisesRegex(EvidenceError, "catalog-mutation-unplanned-row"):
            self.replay(row, value)

    def test_reopen_cannot_claim_the_other_actual_root_handoff(self):
        first = self.replay(self.rows[0])
        with self.assertRaisesRegex(EvidenceError, "catalog-reopen-not-adjacent-same-root"):
            self.replay(self.rows[3], previous=[first])


if __name__ == "__main__":
    unittest.main()
