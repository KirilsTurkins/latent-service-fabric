"""Explicit catalog byte limit with tiny lossless streams; no large fixtures."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.artifact_identity_evidence import common, runs
from tools.artifact_identity_runner import files, run
from tools.optimization_backend_revision.catalog import allocations, collect, evidence, model
from tools.optimization_cache_lookup import allocations as lookup
from tools.optimization_evidence.common import canonical

LEGACY, OWNERSHIP, CATALOG = (value * 1024**2 for value in (64, 128, 256))
ROOT = Path(__file__).resolve().parents[2]


class CatalogFoldedTests(unittest.TestCase):
    def test_selected_catalog_cap_is_finite_and_strictly_typed_before_io(self):
        self.assertEqual(common.folded_limit(CATALOG), CATALOG)
        for value in (None, True, False, -1, 0, CATALOG + 1, float(CATALOG), str(CATALOG)):
            for action in (lambda: files.compress_folded(None, None, maximum_bytes=value),
                    lambda: common.folded(None, maximum_bytes=value),
                    lambda: lookup.folded_attribution(None, maximum_bytes=value),
                    lambda: run.profile_reports(None, None, None, None, 0, 0, maximum_folded_bytes=value),
                    lambda: runs.allocation(None, None, None, maximum_folded_bytes=value)):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unsupported-folded-byte-bound"):
                    action()

    def test_catalog_stream_is_lossless_and_still_rejected_by_older_limits(self):
        # Select a real public limit first, then scale only the byte guards.
        real_limit = common.folded_limit
        tiny = lambda value: real_limit(value) // 1024**2
        payload = b"selected 1\n" * 16  # 176 bytes: above 128, below 256.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "allocations.folded"
            path.write_bytes(payload)
            with patch.object(files, "folded_limit", side_effect=tiny):
                for options in ({}, {"maximum_bytes": OWNERSHIP}):
                    with self.assertRaisesRegex(ValueError, "artifact-file-bound"):
                        files.compress_folded(path, root, **options)
                    self.assertEqual(path.read_bytes(), payload)
                reference = files.compress_folded(path, root, maximum_bytes=CATALOG)
            compressed = root / reference["path"]
            self.assertEqual(gzip.decompress(compressed.read_bytes()), payload)
            self.assertFalse(path.exists())
            for reader, module in ((common.folded, common), (lookup.folded_attribution, lookup)):
                with patch.object(module, "folded_limit", side_effect=tiny):
                    for options in ({}, {"maximum_bytes": OWNERSHIP}):
                        with self.assertRaises(ValueError):
                            reader(compressed, **options)
                    expected = {"rows": "16", "total": "16"} if module is common else (16, 0)
                    self.assertEqual(reader(compressed, maximum_bytes=CATALOG), expected)
                    compressed.write_bytes(gzip.compress(b"selected 1\n" * 24, mtime=0))
                    with self.assertRaises(ValueError):
                        reader(compressed, maximum_bytes=CATALOG)
                    compressed.write_bytes(gzip.compress(payload, mtime=0))

    def test_catalog_plan_rejects_missing_historical_or_crossed_caps_before_builds(self):
        import jsonschema
        schemas = [json.loads((ROOT / f"benchmarks/optimization/catalog-{name}.schema.json").read_bytes())
                   for name in ("suite", "aggregate")]
        for profile in ("smoke", "full"):
            plan = model.suite_plan(profile)
            self.assertEqual(plan["maximum_folded_expanded_bytes"], str(CATALOG))
            for schema in schemas:
                validator = jsonschema.Draft202012Validator({"$ref": "#/$defs/plan", "$defs": schema["$defs"]})
                validator.validate(plan)
                for cap in (None, str(LEGACY), str(OWNERSHIP), str(CATALOG + 1), CATALOG, True):
                    changed = deepcopy(plan)
                    if cap is None:
                        del changed["maximum_folded_expanded_bytes"]
                    else:
                        changed["maximum_folded_expanded_bytes"] = cap
                    with self.assertRaises(jsonschema.ValidationError):
                        validator.validate(changed)
                    value = dict.fromkeys("builds runner_source runner_source_after status reason elapsed_nanos normal_elapsed_nanos "
                                          "allocation_elapsed_nanos tools symbols runs artifacts".split())
                    value.update(schema=model.SCHEMA, profile=profile, plan=changed)
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory) / "suite.json"
                        path.write_bytes(canonical(value))
                        with self.assertRaisesRegex(ValueError, "catalog-suite-plan-crossed"):
                            evidence.validate_suite(path)

    def test_catalog_collection_selects_cap_without_running_a_child(self):
        selection = next(row for row in model.population("smoke") if row["mode"] == "allocation")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runs").mkdir()
            build = {"builds": {selection["variant"]: {"executables": {"backend": {"path": "probe"}}}},
                     "harness": {"echo": {"component": {"path": "echo"}}}}
            suite = {"runs": [], "tools": {name: {"path": name} for name in ("heaptrack", "heaptrack_print", "zstd")}}
            with patch.object(collect, "_host", return_value={}), patch.object(collect, "cgroup", return_value={}), \
                    patch.object(model, "identity", return_value={"unit_dispatch_only": True}), \
                    patch.object(collect, "collect_probe", side_effect=RuntimeError("stop-before-process")) as probe:
                with self.assertRaisesRegex(RuntimeError, "stop-before-process"):
                    collect._child(selection, SimpleNamespace(profile="smoke"), root, build, suite, root,
                                   root, root, {}, 0, lambda: None)
            self.assertEqual(probe.call_args.kwargs["maximum_folded_bytes"], CATALOG)
            self.assertIsNone(probe.call_args.args[3])

    def test_extraction_whole_and_selected_replay_use_the_same_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "heaptrack.zst").write_bytes(b"mock raw transport")
            def command(argv, log, *args, **kwargs):
                log.write_bytes(b"mock helper output")
                if "--print-flamegraph" in argv:
                    Path(argv[-1]).write_bytes(b"selected 1\n")
            with patch.object(run, "command", side_effect=command), \
                    patch.object(run, "compress_folded", wraps=files.compress_folded) as compress:
                run.profile_reports(root / "heaptrack", "printer", "zstd", root, 0, 1024,
                                    maximum_folded_bytes=CATALOG)
            self.assertEqual([call.kwargs for call in compress.call_args_list], [{"maximum_bytes": CATALOG}] * 2)
        refs = {name: {"path": name + (".folded.gz" if name in ("allocations", "peak") else "")}
                for name in ("raw", "report", "interpreted", "allocations", "peak")}
        rows = {name: {"path": name} for name in ("report.process.json", "interpreted.process.json", "allocations.log", "peak.log",
                "allocations.log.process.json", "peak.log.process.json")}
        artifacts = SimpleNamespace(rows=rows, path=lambda ref: Path(ref["path"]), json=lambda ref: {})
        record = {"case": "default-success", "profile_refs": refs, "command": ["heaptrack", "--output", "prefix", "/probe"]}
        suite = {"tools": {name: {"sha256": "unused"} for name in ("heaptrack_print", "zstd")}}
        whole = {"command": "/probe", "allocation_count": "1", "peak_live_bytes": "1"}
        with patch.object(runs, "helper"), patch.object(runs, "replay", return_value=whole), \
                patch.object(runs, "folded", return_value={"total": "1"}) as folded:
            self.assertEqual(runs.allocation(record, suite, artifacts, maximum_folded_bytes=CATALOG), whole)
        self.assertEqual([call.kwargs for call in folded.call_args_list], [{"maximum_bytes": CATALOG}] * 2)
        counts = {"allocation_count": 1, "allocated_bytes": 1, "peak_live_bytes": 1, "live_bytes": 0, "remaining_allocations": 0}
        state = SimpleNamespace(folded_labels={"selected"}, statistics=[counts] * 3, named_count=1, unresolved_count=0)
        with patch.object(allocations, "proof", return_value={"demangled": "selected", "raw": "raw_selected"}), \
                patch.object(lookup, "replay_attribution", return_value=(whole, state)), \
                patch.object(lookup, "folded_attribution", return_value=(1, 1)) as selected:
            result = allocations.attribute(record, {}, {}, {}, artifacts, whole, 256)
        selected.assert_called_once_with(Path("allocations.folded.gz"), {"selected"}, maximum_bytes=CATALOG)
        self.assertEqual(result["status"], "available")
