"""Captured C closure and bounded actual static member-format inspection."""
from pathlib import Path
import tempfile
import unittest

from tools.application_dependencies import MANIFEST, LOCK, capture, prepare
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical, digest
from tools.c_application_dependencies import archive_members, selected, wasm_object


def archive(rows, magic=b"!<arch>\n"):
    result = bytearray(magic)
    for name, data in rows:
        header = name.ljust(16) + "0".ljust(12) + "0".ljust(6) + "0".ljust(6) + "100644".ljust(8) + str(len(data)).ljust(10) + "`\n"
        result += header.encode() + data + (b"\n" if len(data) & 1 else b"")
    return bytes(result)


def object_bytes(features=b"\0"):
    linking = b"\x07linking\x02"
    selected = b"\x0ftarget_features" + features
    return b"\0asm\x01\0\0\0\0" + bytes([len(linking)]) + linking + b"\0" + bytes([len(selected)]) + selected


class CDependencies(unittest.TestCase):
    def closure(self, sources=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        project, library, work, output = (root / name for name in ("project", "outside-library", "work", "output"))
        for path in (project, library, work, output): path.mkdir()
        (library / "pure.c").write_bytes(b'#include "transitive.h"\nint pure(int x) { return helper(x); }\n')
        (library / "transitive.h").write_bytes(b"static int helper(int x) { return x * 7; }\n")
        (project / MANIFEST).write_bytes(canonical({"formatVersion": 1, "language": "c", "selection": {"target": "wasm32-wasi"},
            "nativeLocks": [], "artifacts": [{"id": "unknown-library/1", "role": "application", "format": "directory",
                "mount": "dependencies/unknown", "source": {"path": "../outside-library"}, "dependencies": [],
                "metadata": {"cSources": sources or ["pure.c"], "includeDirectories": ["."], "defines": {"FEATURE": "1"}, "license": "MIT"}}],
            "transformations": []}))
        (project / LOCK).write_bytes(canonical(capture(project)))
        return root, prepare(project, work, output, "c")

    def test_unknown_source_and_transitive_header_are_selected_offline(self):
        root, closure = self.closure()
        selected_inputs = selected(closure, compiler_digest=digest(b"compiler"), runtime_digest=digest(b"runtime"))
        self.assertEqual(selected_inputs.sources, (root / "work/dependencies/unknown/pure.c",))
        self.assertEqual(selected_inputs.includes, (root / "work/dependencies/unknown",))
        self.assertEqual(selected_inputs.defines, ("FEATURE=1",))
        self.assertTrue((selected_inputs.includes[0] / "transitive.h").is_file())
        closure.check_unchanged()

    def test_include_or_source_escape_and_uncaptured_source_fail(self):
        root, closure = self.closure()
        for change in ({"includeDirectories": ["../outside-library"]}, {"cSources": ["missing.c"]}, {"cSources": ["native.S"]}):
            with self.subTest(change=change):
                original = dict(closure.lock["artifacts"][0]["metadata"])
                closure.lock["artifacts"][0]["metadata"].update(change)
                with self.assertRaises(DependencyError):
                    selected(closure, compiler_digest=digest(b"c"), runtime_digest=digest(b"r"))
                closure.lock["artifacts"][0]["metadata"] = original

    def test_shell_build_configuration_and_flag_injection_fail(self):
        _root, closure = self.closure()
        for key, value in (("configure", "./configure"), ("compilerOptions", ["--sysroot=/secret"]), ("defines", {"MACRO": "-include=/secret"})):
            with self.subTest(key=key):
                original = dict(closure.lock["artifacts"][0]["metadata"])
                closure.lock["artifacts"][0]["metadata"][key] = value
                with self.assertRaises(DependencyError):
                    selected(closure, compiler_digest=digest(b"c"), runtime_digest=digest(b"r"))
                closure.lock["artifacts"][0]["metadata"] = original

    def test_relocatable_wasm_members_preserve_feature_identity(self):
        payload = object_bytes(b"\x01+\x0bbulk-memory")
        members = archive_members(archive([("pure.o/", payload)]))
        self.assertEqual(members[0]["name"], "pure.o")
        self.assertEqual(members[0]["digest"], digest(payload))
        self.assertEqual(members[0]["targetFeatures"], {"bulk-memory": "+"})

    def test_host_native_and_thin_archives_are_rejected(self):
        for payload in (b"\x7fELF", b"MZ native dll", b"\xcf\xfa\xed\xfe"):
            with self.subTest(payload=payload), self.assertRaisesRegex(DependencyError, "host-native"):
                archive_members(archive([("pure.o/", payload)]))
        with self.assertRaisesRegex(DependencyError, "thin"):
            archive_members(archive([], magic=b"!<thin>\n"))

    def test_member_paths_duplicates_overflow_and_missing_linking_fail(self):
        for rows in [[("../escape/", object_bytes())], [("x.o/", object_bytes()), ("x.o/", object_bytes())],
                     [("x.o/", b"\0asm\x01\0\0\0")]]:
            with self.subTest(rows=rows), self.assertRaises(DependencyError):
                archive_members(archive(rows))
        with self.assertRaises(DependencyError):
            archive_members(archive([("x.o/", object_bytes())])[:-4])

    def test_unqualified_thread_or_memory_abi_requires_runtime_qualification(self):
        for name in (b"atomics", b"memory64", b"shared-mem"):
            with self.subTest(name=name), self.assertRaisesRegex(DependencyError, "unqualified-runtime"):
                wasm_object(object_bytes(b"\x01+" + bytes([len(name)]) + name))


if __name__ == "__main__":
    unittest.main()
