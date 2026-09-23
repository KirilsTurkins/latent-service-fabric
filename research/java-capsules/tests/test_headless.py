"""Test the reactor-port boundary without substituting mocks for guest execution."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("headless", PROJECT / "headless.py")
headless = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(headless)


class HeadlessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.output = self.root / "input", self.root / "output"
        self.source.mkdir()
        for name, value in {
            "definitions.h": "#pragma once\n",
            "exceptions.h": "#if TEAVM_UNIX\n#endif\n",
            "memory.c": "#if defined(__EMSCRIPTEN__)\n#endif\n",
            "main.c": "int main(int argc, char** argv) {\n    teavm_beforeInit();\n"
                      "    meth_otr_Fiber_startMain(teavm_parseArguments(argc, argv));\n"
                      "    meth_otr_EventQueue_process();\n    return 0;\n}\n",
            "all.c": '#include "main.c"\n',
            "classes/dev/latent/probe/Probe.c": "/* actual generated Java goes here */\n",
            "classes/org/teavm/runtime/GC.c": "/* GC is never replaced */\n",
        }.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        # Fixtures are not a compiler qualification. Production accepts only the
        # pinned upstream runtime hashes; no override flag is exposed to callers.
        self.hashes = {name: headless.sha256(self.source / name) for name in headless.RUNTIME_HASHES}
        self.patch = mock.patch.object(headless, "RUNTIME_HASHES", self.hashes)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_preserves_original_and_every_application_and_gc_file(self):
        before = headless.inputs(self.source)
        receipt = headless.prepare(self.source, self.output)
        self.assertEqual(before, headless.inputs(self.source))
        self.assertEqual(receipt["qualification"], "not-qualified")
        self.assertEqual(receipt["lsfExecution"], "not-attempted")
        for name in before.keys() - receipt["runtimeEdits"].keys():
            self.assertEqual(headless.sha256(self.output / name), before[name])
        self.assertNotIn("EventQueue_process", (self.output / "main.c").read_text())
        self.assertEqual(len(receipt["runtimeEdits"]), 4)

    def test_rejects_runtime_drift_before_copy(self):
        (self.source / "memory.c").write_text("changed runtime")
        with self.assertRaisesRegex(ValueError, "hash-drift"):
            headless.prepare(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_rejects_main_layout_drift_before_copy(self):
        path = self.source / "main.c"
        path.write_text(path.read_text().replace("meth_otr_EventQueue_process();", "changed();"))
        with self.assertRaisesRegex(ValueError, "layout-drift"):
            headless.prepare(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_rejects_duplicated_layout_marker(self):
        with self.assertRaisesRegex(ValueError, "layout-drift"):
            headless.replace_once("marker marker", "marker", "")

    def test_never_overwrites_previous_attempt(self):
        self.output.mkdir()
        marker = self.output / "previous-evidence"
        marker.write_text("retain")
        with self.assertRaises(FileExistsError):
            headless.prepare(self.source, self.output)
        self.assertEqual(marker.read_text(), "retain")

    def test_rejects_overlapping_output(self):
        for output in (self.source, self.source / "nested", self.root):
            with self.assertRaisesRegex(ValueError, "overlaps-input"):
                headless.prepare(self.source, output)

    def test_rejects_symlinked_root_and_files(self):
        link = self.root / "link"
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            headless.prepare(link, self.output)
        (self.source / "extra").symlink_to(self.source / "main.c")
        with self.assertRaisesRegex(ValueError, "symlink"):
            headless.prepare(self.source, self.output)

    def test_rejects_missing_actual_java(self):
        (self.source / "classes/dev/latent/probe/Probe.c").unlink()
        with self.assertRaisesRegex(ValueError, "missing-generated-input"):
            headless.prepare(self.source, self.output)

    def test_exception_lowering_is_preserved_and_libc_is_not_recompiled_with_eh(self):
        self.output.mkdir()
        lib = self.root / "lib"
        runtime = lib / "libc/wasi/libc-top-half/musl/src/setjmp/wasm32/rt.c"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("bundled runtime")
        with mock.patch.object(headless, "SJ_LJ_SHA256", headless.sha256(runtime)):
            commands = headless.compile_commands("zig", lib, self.output)
        for _, command in commands[:2]:
            self.assertIn("-wasm-enable-sjlj", command)
            self.assertIn("-wasm-use-legacy-eh=false", command)
            self.assertNotIn("-DTEAVM_USE_SETJMP=0", command)
        self.assertNotIn("-mexception-handling", commands[-1][1])
        self.assertIn("-Wl,--max-memory=67108864", commands[-1][1])
        self.assertTrue((self.output / "sjlj-input.json").is_file())

    def test_rejects_sjlj_runtime_drift(self):
        self.output.mkdir()
        runtime = self.root / "libc/wasi/libc-top-half/musl/src/setjmp/wasm32/rt.c"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("not the pinned runtime")
        with self.assertRaisesRegex(ValueError, "sjlj-runtime-drift"):
            headless.compile_commands("zig", self.root, self.output)
        self.assertFalse((self.output / "sjlj-input.json").exists())

    def test_missing_bundled_sjlj_support_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "missing-pinned-zig"):
            headless.compile_commands("zig", self.root, self.output)


if __name__ == "__main__":
    unittest.main()
