"""LLVM linking metadata controls; these bytes do not claim compiler execution."""
from pathlib import Path
import tempfile
import unittest

from tools.application_dependencies import LOCK, MANIFEST, capture, prepare
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical, digest
from tools.c_application_dependencies import archive_members, selected, wasm_object
from tools.c_static_symbols import MAX_NAME_BYTES, MAX_SYMBOL_BYTES, MAX_SYMBOLS, strong_symbols
from tools.tests.test_c_application_dependencies import archive


def unsigned(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result + bytes([value]))


def name(value):
    raw = value.encode() if isinstance(value, str) else value
    return unsigned(len(raw)) + raw


def symbol(kind, flags, value="pure"):
    start = bytes([kind]) + unsigned(flags)
    if kind in (0, 2, 4, 5):
        return start + b"\0" + (name(value) if not flags & 0x10 or flags & 0x40 else b"")
    if kind == 1:
        fields = b"" if flags & 0x10 else b"\x07\x03" if flags & 3 == 3 else b"\0\0\x07"
        return start + name(value) + fields
    return start + b"\0"


def table(rows):
    payload = unsigned(len(rows)) + b"".join(rows)
    return b"\x08" + unsigned(len(payload)) + payload


def object_with(rows):
    payload = name("linking") + b"\x02" + table(rows)
    return b"\0asm\x01\0\0\0\0" + unsigned(len(payload)) + payload


class StaticSymbolTests(unittest.TestCase):
    def closure(self, archives):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        project, work, output = (root / value for value in ("project", "work", "output"))
        for path in (project, work, output):
            path.mkdir()
        declarations = []
        for index, raw in enumerate(archives):
            path = root / f"unknown-{index}.a"
            path.write_bytes(raw)
            declarations.append({"id": f"developer-private-{index}/1", "role": "application", "format": "file",
                "mount": f"dependencies/unknown-{index}.a", "source": {"path": str(path)}, "dependencies": [],
                "metadata": {"archiveProfile": self.profile(raw), "license": "MIT"}})
        (project / MANIFEST).write_bytes(canonical({"formatVersion": 1, "language": "c",
            "selection": {"target": "wasm32-wasi"}, "nativeLocks": [], "artifacts": declarations,
            "transformations": []}))
        (project / LOCK).write_bytes(canonical(capture(project)))
        return prepare(project, work, output, "c")

    def profile(self, raw):
        return {"formatVersion": 1, "target": "wasm32-wasi", "compilerDigest": digest(b"compiler-model"),
            "compilerDistributionDigest": digest(b"distribution-model"), "runtimeDigest": digest(b"runtime-model"),
            "checkpointProfile": "closed-synchronous-v1", "members": archive_members(raw)}

    def select(self, closure):
        return selected(closure, compiler_digest=digest(b"compiler-model"), runtime_digest=digest(b"runtime-model"),
                        compiler_distribution_digest=digest(b"distribution-model"))

    def test_defined_functions_data_globals_events_and_tables_are_strong(self):
        rows = [symbol(kind, 0, f"defined-{kind}") for kind in (0, 1, 2, 4, 5)]
        rows += [symbol(0, 4, "hidden-but-linked"), symbol(3, 2)]
        self.assertEqual(strong_symbols(table(rows)), ["defined-0", "defined-1", "defined-2", "defined-4",
                                                      "defined-5", "hidden-but-linked"])
        self.assertEqual(wasm_object(object_with(rows))["strongSymbols"], strong_symbols(table(rows)))

    def test_undefined_weak_local_and_common_do_not_conflict_with_strong(self):
        rows = [symbol(0, flags, "same") for flags in (0, 1, 2, 0x10, 0x50)]
        rows += [symbol(1, flags, "same") for flags in (1, 2, 3, 0x10)]
        self.assertEqual(strong_symbols(table(rows)), ["same"])

    def test_two_strong_definitions_in_one_object_fail(self):
        with self.assertRaisesRegex(DependencyError, "duplicate-strong-symbol"):
            strong_symbols(table([symbol(0, 0), symbol(1, 4)]))

    def test_distinct_unused_members_with_duplicate_symbols_fail_before_linking(self):
        raw = archive([("first.o/", object_with([symbol(0, 0)])),
                       ("unused.o/", object_with([symbol(0, 0)]))])
        with self.assertRaisesRegex(DependencyError, "duplicate-strong-symbol"):
            archive_members(raw)

    def test_separate_archives_cannot_hide_duplicate_strong_symbols(self):
        closure = self.closure([archive([("first.o/", object_with([symbol(0, 0)]))]),
                                archive([("second.o/", object_with([symbol(0, 0)]))])])
        with self.assertRaisesRegex(DependencyError, "duplicate-strong-symbol"):
            self.select(closure)

    def test_current_observed_profile_accepts_unknown_archives_offline(self):
        closure = self.closure([archive([("first.o/", object_with([symbol(0, 0, "first")]))]),
                                archive([("second.o/", object_with([symbol(0, 0, "second")]))])])
        result = self.select(closure)
        self.assertEqual(len(result.archives), 2)
        self.assertFalse(result.receipt["networkResolution"])
        self.assertEqual([row["id"] for row in result.receipt["artifacts"]],
                         ["developer-private-0/1", "developer-private-1/1"])
        closure.check_unchanged()

    def test_stale_compiler_distribution_runtime_target_and_checkpoint_fail(self):
        closure = self.closure([archive([("first.o/", object_with([symbol(0, 0)]))])])
        metadata = closure.lock["artifacts"][0]["metadata"]
        original = metadata["archiveProfile"]
        for field, replacement in (("compilerDigest", digest(b"old-compiler")),
                ("compilerDistributionDigest", digest(b"old-sysroot")), ("runtimeDigest", digest(b"old-runtime")),
                ("target", "wasm64-wasi"), ("checkpointProfile", "unobserved-threaded-v1")):
            with self.subTest(field=field):
                metadata["archiveProfile"] = {**original, field: replacement}
                with self.assertRaisesRegex(DependencyError, "current-observed-abi-profile-or-source-rebuild"):
                    self.select(closure)
        metadata["archiveProfile"] = original
        with self.assertRaisesRegex(DependencyError, "current-observed-abi-profile-or-source-rebuild"):
            selected(closure, compiler_digest=digest(b"compiler-model"), runtime_digest=digest(b"runtime-model"))

    def test_truncation_bad_utf8_nul_repeated_table_and_trailing_symbol_fail(self):
        good = table([symbol(0, 0)])
        bad = [good[:-1], good + good, table([symbol(0, 0, b"\xff")]),
               table([symbol(0, 0, b"bad\0name")]), b"\x08\x02\0\0",
               b"\x08\x06\x80\x80\x80\x80\x80\0"]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaisesRegex(DependencyError, "malformed"):
                strong_symbols(raw)

    def test_symbol_counts_individual_names_and_total_name_bytes_are_bounded(self):
        too_many = unsigned(MAX_SYMBOLS + 1)
        cases = [b"\x08" + unsigned(len(too_many)) + too_many,
                 table([symbol(0, 0, "n" * (MAX_NAME_BYTES + 1))]),
                 table([symbol(0, 2, "n" * MAX_NAME_BYTES)] * (MAX_SYMBOL_BYTES // MAX_NAME_BYTES + 1))]
        for raw in cases:
            with self.subTest(size=len(raw)), self.assertRaisesRegex(DependencyError, "table-limit"):
                strong_symbols(raw)

    def test_tls_unknown_flags_and_invalid_local_or_common_imports_fail(self):
        cases = [(0, 0x100), (0, 8), (6, 0), (0, 3), (0, 0x12), (1, 0x12), (1, 0x13)]
        for kind, flags in cases:
            with self.subTest(kind=kind, flags=flags), self.assertRaises(DependencyError):
                strong_symbols(table([symbol(kind, flags)]))

    def test_core_validator_visits_every_member_including_unused_members(self):
        raw = archive([("first.o/", object_with([symbol(0, 0, "first")])),
                       ("unused.o/", object_with([symbol(0, 0, "unused")]))])
        visited = []
        def validate(name, payload):
            visited.append((name, digest(payload)))
            if name == "unused.o":
                raise ValueError("closed-validator-denial")
        with self.assertRaisesRegex(ValueError, "closed-validator-denial"):
            archive_members(raw, validator=validate)
        self.assertEqual([row[0] for row in visited], ["first.o", "unused.o"])

    def test_static_capture_preserves_public_header_resource_and_offline_closure(self):
        from tools.c_dependency_fixture import use_static_archive
        from tools.application_dependencies import document
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            project, library, resources = (root / value for value in ("project", "library", "resources"))
            for path in (project, library, resources):
                path.mkdir()
            (library / "qualified.c").write_bytes(b"int pure(void) { return 42; }\n")
            (library / "qualified.h").write_bytes(b"int pure(void);\n")
            (resources / "greeting.inc").write_bytes(b"72,101,108,108,111,0\n")
            parser = root / "parser.h"
            parser.write_bytes(b"/* capture-only model header */\n")
            artifacts = [
                {"id": "developer-owned/qualification/1", "role": "application", "format": "directory",
                 "mount": "dependencies/library", "source": {"path": str(library)},
                 "dependencies": ["zserge/jsmn/1.1.0", "developer-owned/resource/1"],
                 "metadata": {"cSources": ["qualified.c"], "includeDirectories": ["."]}},
                {"id": "zserge/jsmn/1.1.0", "role": "application", "format": "file",
                 "mount": "dependencies/parser/jsmn.h", "source": {"path": str(parser)},
                 "dependencies": [], "metadata": {"includeDirectories": ["."]}},
                {"id": "developer-owned/resource/1", "role": "resource", "format": "directory",
                 "mount": "dependencies/resources", "source": {"path": str(resources)},
                 "dependencies": [], "metadata": {"includeDirectories": ["."]}}]
            (project / MANIFEST).write_bytes(canonical({"formatVersion": 1, "language": "c",
                "selection": {"target": "wasm32-wasi"}, "nativeLocks": [], "artifacts": artifacts, "transformations": []}))
            (project / LOCK).write_bytes(canonical(capture(project)))
            for path in (*library.iterdir(), *resources.iterdir(), parser):
                path.unlink()
            raw = archive([("pure.o/", object_with([symbol(0, 0)]))])
            path = root / "library.a"
            path.write_bytes(raw)
            report = use_static_archive(project, path, self.profile(raw), root / "static-originals")
            self.assertEqual(report["archiveDigest"], digest(raw))
            self.assertEqual(list((root / "static-originals").iterdir()), [])
            work, output = root / "work", root / "output"
            work.mkdir(); output.mkdir()
            closure = prepare(project, work, output, "c")
            inputs = self.select(closure)
            self.assertEqual(len(inputs.archives), 1)
            self.assertEqual(inputs.sources, ())
            self.assertEqual((work / "dependencies/developer-header/qualified.h").read_bytes(), b"int pure(void);\n")
            self.assertEqual((work / "dependencies/resources/greeting.inc").read_bytes(), b"72,101,108,108,111,0\n")
            self.assertEqual(document(project / LOCK)["language"], "c")
            closure.check_unchanged()

    def test_archive_source_recipe_denies_missing_resolved_libraries_before_compiler(self):
        from tools.c_capsule_project import create
        from tools.c_static_archive_build import build
        import json
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            project = create(root / "project", "greeting")
            output = root / "failed-archive"
            with self.assertRaisesRegex(ValueError, "resolved application dependencies"):
                build(project, output, "https://github.com/example/application")
            report = json.loads((output / "STATIC-ARCHIVE-FAILED.json").read_text())
            self.assertEqual(report["stage"], "application-dependencies")
            self.assertFalse((output / "library.a").exists())
            self.assertFalse((output / "STATIC-ARCHIVE-COMPLETE.json").exists())


if __name__ == "__main__":
    unittest.main()
