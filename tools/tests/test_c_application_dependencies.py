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
    def closure(self, sources=None, *, cpp=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        project, library, work, output = (root / name for name in ("project", "outside-library", "work", "output"))
        for path in (project, library, work, output): path.mkdir()
        (library / ("pure.cpp" if cpp else "pure.c")).write_bytes(b'#include "transitive.h"\nint pure(int x) { return helper(x); }\n')
        (library / "transitive.h").write_bytes(b"static int helper(int x) { return x * 7; }\n")
        (project / MANIFEST).write_bytes(canonical({"formatVersion": 1, "language": "c", "selection": {"target": "wasm32-wasi"},
            "nativeLocks": [], "artifacts": [{"id": "unknown-library/1", "role": "application", "format": "directory",
                "mount": "dependencies/unknown", "source": {"path": "../outside-library"}, "dependencies": [],
                "metadata": {"cSources": sources or ["pure.cpp" if cpp else "pure.c"], "includeDirectories": ["."], "defines": {"FEATURE": "1"}, "license": "MIT"}}],
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
        from tools.c_application_dependencies import CDependencyError
        closure.lock['selection']['target'] = 'x86_64-linux'
        with self.assertRaises(CDependencyError) as refused:
            selected(closure, compiler_digest=digest(b'c'), runtime_digest=digest(b'r'))
        self.assertEqual(refused.exception.code, 'c-selected-target-not-maintained-profile')

    def test_include_or_source_escape_and_uncaptured_source_fail(self):
        root, closure = self.closure()
        for change in ({"includeDirectories": ["../outside-library"]}, {"cSources": ["missing.c"]}, {"cSources": ["native.S"]}):
            with self.subTest(change=change):
                original = dict(closure.lock["artifacts"][0]["metadata"])
                closure.lock["artifacts"][0]["metadata"].update(change)
                with self.assertRaises(DependencyError):
                    selected(closure, compiler_digest=digest(b"c"), runtime_digest=digest(b"r"))
                closure.lock["artifacts"][0]["metadata"] = original

        from tools.c_application_dependencies import CDependencyError
        _root, cpp = self.closure(cpp=True)
        with self.assertRaises(CDependencyError) as refused:
            selected(cpp, compiler_digest=digest(b'c'), runtime_digest=digest(b'r'))
        self.assertEqual(refused.exception.code, 'c-cpp-source-not-maintained-profile')

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


class CSourceCapacity(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)

    def test_captured_source_count_is_finite_across_artifacts(self):
        from copy import deepcopy
        from tools.c_application_dependencies import MAX_SOURCE_UNITS
        self.assertEqual(MAX_SOURCE_UNITS, 256)
        project, library, work, output = (self.root / name for name in ("project", "outside", "work", "output"))
        for path in (project, library, work, output):
            path.mkdir()
        names = [f"unit-{i:03}.c" for i in range(MAX_SOURCE_UNITS + 1)]
        for i, name in enumerate(names):
            (library / name).write_text(f"int source_{i}(void) {{ return {i}; }}\n")
        manifest = {"formatVersion": 1, "language": "c", "selection": {"target": "wasm32-wasi"},
            "nativeLocks": [], "artifacts": [{"id": "outside/capacity/1", "role": "application",
                "format": "directory", "mount": "dependencies/capacity", "source": {"path": str(library)},
                "dependencies": [], "metadata": {"cSources": names[:MAX_SOURCE_UNITS], "includeDirectories": ["."]}}],
            "transformations": []}
        (project / MANIFEST).write_bytes(canonical(manifest))
        (project / LOCK).write_bytes(canonical(capture(project)))
        closure = prepare(project, work, output, "c")
        options = {"compiler_digest": digest(b"compiler"), "runtime_digest": digest(b"runtime")}
        self.assertEqual(len(selected(closure, **options).sources), MAX_SOURCE_UNITS)
        row = closure.lock["artifacts"][0]
        row["metadata"]["cSources"] = names
        with self.assertRaisesRegex(DependencyError, "c-dependency-recipe-limit"):
            selected(closure, **options)

        second = deepcopy(row)
        row["metadata"]["cSources"] = names[:128]
        second["metadata"]["cSources"] = names[128:]
        second["id"] = "outside/second/1"
        second["mount"] = "dependencies/second"
        (work / second["mount"]).mkdir()
        closure.lock["artifacts"].append(second)
        with self.assertRaisesRegex(DependencyError, "c-dependency-recipe-limit"):
            selected(closure, **options)

    @unittest.skipUnless(__import__('os').name == 'posix', "captured compiler isolation is Linux-only")
    def test_owned_response_groups_preserve_order_and_reject_injection(self):
        from types import SimpleNamespace
        from tools.c_guest.compiler import Compiler, _link_response_bytes
        destination = self.root / 'compiled'
        destination.mkdir()
        objects = [destination / f'dependency-{i:04}.o' for i in range(4)]
        for obj in objects:
            obj.write_bytes(b'owned')
        compiler = Compiler.__new__(Compiler)
        protected = []
        compiler.isolation = SimpleNamespace(protect_inputs=protected.append)
        command = ['cc', 'before', str(objects[1]), str(objects[0]), 'middle',
                   str(objects[3]), str(objects[2]), 'after']
        compacted, responses = compiler._dependency_link_responses(command, objects, destination)
        self.assertEqual(compacted, ['cc', 'before', '@' + str(responses[0][0]), 'middle',
                                     '@' + str(responses[1][0]), 'after'])
        self.assertEqual([row[2] for row in responses], [[1, 0], [3, 2]])
        self.assertEqual(responses[0][0].read_bytes(), _link_response_bytes([objects[1], objects[0]]))
        self.assertEqual(responses[1][0].read_bytes(), _link_response_bytes([objects[3], objects[2]]))
        self.assertEqual(protected, [row[0] for row in responses])
        slash, quote = chr(92), chr(34)
        difficult = Path('/tmp/one' + slash + 'slash/with' + slash + quote + 'quote #/@nested.rsp.o')
        expected = (quote + '/tmp/one' + slash + 'slash/with' + slash * 3 + quote
                    + 'quote #/@nested.rsp.o' + quote + chr(10)).encode()
        self.assertEqual(_link_response_bytes([difficult]), expected)
        for path in (Path('relative.o'), Path('/tmp/name\n-Wl,--allow-undefined.o'), Path("/tmp/quote's.o")):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'response path'):
                _link_response_bytes([path])
        with self.assertRaisesRegex(ValueError, 'response count'):
            _link_response_bytes([Path('/tmp/object.o')] * 257)
        with self.assertRaisesRegex(ValueError, 'response byte limit'):
            _link_response_bytes([Path('/' + 'x' * 32700)] * 33)

    def test_larger_source_selection_keeps_compiler_and_object_byte_limits(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.c_guest.compiler import Compiler
        compiler = Compiler.__new__(Compiler)
        compiler.sdk, compiler.platform, compiler.commands = self.root / 'sdk', None, None
        compiler.compiler_edges = None
        compiler.isolation = SimpleNamespace(receipt={}, observe_inputs=lambda _path: [])
        compiler.validate_static_libraries = lambda *_args: None
        compiler.check_unchanged = lambda: None
        with self.assertRaisesRegex(ValueError, 'between 1 and 256'):
            compiler.compile([self.root / 'any.c'] * 257, self.root, 'service', self.root / 'refused')
        application = self.root / 'application.c'
        application.write_text('int app(void) { return 1; }\n')
        dependencies = tuple(self.root / f'source-{i:03}.c' for i in range(65))
        for source in dependencies:
            source.write_text('int value;\n')
        outputs = []
        def run(*args):
            if args[0] == 'zig' and '-c' in args:
                path = Path(args[args.index('-o') + 1])
                with path.open('wb') as out:
                    out.truncate(4 * 1024 * 1024 if not outputs else 1)
                outputs.append(path)
            return ''
        compiler.run = run
        def generate(_run, _wit, _world, destination, _platform, **_kwargs):
            destination.mkdir()
            return destination, {}
        with patch('tools.c_guest.compiler.generate', generate):
            with self.assertRaisesRegex(ValueError, 'dependency object byte limit'):
                compiler.compile([application, *dependencies], self.root, 'service', self.root / 'compiled',
                                 dependency_sources=dependencies)
        self.assertEqual(len(outputs), 2)


if __name__ == "__main__":
    unittest.main()
