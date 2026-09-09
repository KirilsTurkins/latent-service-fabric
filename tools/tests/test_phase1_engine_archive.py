"""Tiny synthetic transport fixtures; full population needs actual semantic replay."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import phase0_evidence
from tools import validate_phase1_archive as verify


class EngineArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="engine-archive-bound-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ordinal = 0

    def inputs(self, kind):
        self.ordinal += 1
        source = self.root / f"input-{self.ordinal}"
        source.mkdir()
        value = {"schema": f"latent.optimization.{kind}-aggregate.v1", "profile": "full", "status": "complete",
                 "population_complete": True, "attempt_count_complete": True, "synthetic_transport_only": True}
        (source / "aggregate.json").write_bytes(verify.canonical(value))
        (source / "suite.json").write_bytes(b'{"synthetic_transport_only":true}\n')
        (source / "raw.log").write_bytes(b"preserved actual archive transport bytes\n")
        return source, self.root / f"output-{self.ordinal}", value

    def test_engine_and_external_replay_correct_kind_with_default_bound(self):
        for kind in ("engine", "engine-warm"):
            for split in (False, True):
                source, output, value = self.inputs(kind)
                validator = "validate_backend_revision_suite" if kind == "engine" else "validate_revision_suite"
                other = "validate_revision_suite" if kind == "engine" else "validate_backend_revision_suite"
                with self.subTest(kind=kind, split=split), patch.object(verify, validator, return_value=value) as replay:
                    with patch.object(verify, other) as wrong:
                        with patch.object(phase0_evidence, "extract_tar_stream", wraps=phase0_evidence.extract_tar_stream) as extract:
                            manifest = package.package(source, output, None, split_archive=split)
                replay.assert_called_once()
                wrong.assert_not_called()
                self.assertEqual(extract.call_args.kwargs, {})
                self.assertEqual(verify.verify_package(output, replay=False), manifest)

    def test_engine_cannot_acquire_codec_two_gib_override(self):
        for kind in ("engine", "engine-warm"):
            source, _, _ = self.inputs(kind)
            rows = [verify.file_reference(source / "aggregate.json", source)]
            rows.extend({"path": f"bounded-{index}.log", "bytes": str(256 * 1024**2), "sha256": "sha256:" + "0" * 64}
                        for index in range(4))
            manifest = {"schema": "latent.phase1.archive-manifest.v1", "archive": {
                "path": verify.ARCHIVE, "bytes": "20", "sha256": "sha256:" + "0" * 64},
                "files": rows, "total_bytes": str(sum(int(row["bytes"]) for row in rows))}
            (source / verify.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "expanded byte bound"):
                verify.load_manifest(source)
        self.assertEqual((verify.MAX_EXPANDED, verify.MAX_COMPRESSED, verify.MAX_SPLIT_COMPRESSED),
                         (1024**3, 99_000_000, 198_000_000))

    def test_only_complete_full_replayed_population_is_publishable(self):
        for kind in ("engine", "engine-warm"):
            validator = "validate_backend_revision_suite" if kind == "engine" else "validate_revision_suite"
            for mutation in ({"profile": "smoke"}, {"status": "incomplete"}, {"status": "failed"},
                             {"population_complete": False}, {"population_complete": 1},
                             {"attempt_count_complete": False}, {"attempt_count_complete": 1}):
                source, output, value = self.inputs(kind)
                changed = dict(value, **mutation)
                (source / "aggregate.json").write_bytes(verify.canonical(changed))
                with self.subTest(kind=kind, mutation=mutation), patch.object(verify, validator, return_value=changed):
                    with self.assertRaisesRegex(ValueError, "requires complete full-population"):
                        package.package(source, output, None)
                self.assertFalse(output.exists())

    def test_rehashed_aggregate_must_equal_replayed_evidence(self):
        for kind in ("engine", "engine-warm"):
            source, output, value = self.inputs(kind)
            validator = "validate_backend_revision_suite" if kind == "engine" else "validate_revision_suite"
            with patch.object(verify, validator, return_value=dict(value, changed_semantics=True)):
                with self.assertRaisesRegex(ValueError, "differs from replayed"):
                    package.package(source, output, None)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
