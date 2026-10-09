"""Runtime overlays preserve pinned sources and separate scheduler from authority."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.go_guest import runtime


def sources():
    return {
        "runtime/lock_futex.go": "func beforeIdle(int64, int64) (*g, bool) { return nil, false }\n",
        "runtime/lock_sema.go": "func beforeIdle(int64, int64) (*g, bool) { return nil, false }\n",
        "runtime/lock_js.go": "func beforeIdle(now, pollUntil int64) (gp *g, otherReady bool) { return nil, false }\n",
        "runtime/lock_wasip1.go": "func beforeIdle(int64, int64) (*g, bool) {\n\treturn nil, false\n}\n",
        "runtime/proc.go": "gp, otherReady := beforeIdle(now, pollUntil)\n",
        "runtime/os_wasip1.go": (
            "//go:wasmimport wasi_snapshot_preview1 clock_time_get\n//go:noescape\n"
            "func clock_time_get(clock_id clockid, precision timestamp, time *timestamp) errno\n"
            "//go:wasmimport wasi_snapshot_preview1 random_get\n//go:noescape\n"
            "func random_get(buf *byte, bufLen size) errno\n"),
        "syscall/fs_wasip1.go": "//go:wasmimport wasi_snapshot_preview1 random_get\n//go:noescape\nfunc random_get(buf *byte, bufLen size) Errno\n",
        "syscall/syscall_wasip1.go": "//go:wasmimport wasi_snapshot_preview1 clock_time_get\n//go:noescape\nfunc clock_time_get(id clockid, precision timestamp, time *timestamp) Errno\n",
    }


class GoRuntimeOverlayTests(unittest.TestCase):
    def fixture(self, root, prepared=True):
        text = sources()
        if prepared:
            runtime.install_scheduler(text)
        original = {name: value.encode() for name, value in text.items()}
        goroot = root / "go"
        for name, data in original.items():
            path = goroot / "src" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        contracts = {name: hashlib.sha256(data).hexdigest() for name, data in original.items()}
        return goroot, original, contracts

    def test_compiler_assembly_preserves_upstream_and_verifies_all_derived_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot, original, upstream = self.fixture(root, prepared=False)
            (goroot / "VERSION").write_text("go1.27.2\n")
            (goroot / "bin").mkdir()
            (goroot / "bin/go").write_bytes(b"pinned-host-compiler")
            patched = sources()
            runtime.install_scheduler(patched)
            expected = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in patched.items()}
            with patch.dict(runtime.UPSTREAM_PREIMAGES, upstream, clear=True), patch.dict(runtime.PREIMAGES, expected, clear=True):
                prepared = runtime.prepare_compiler(goroot, root / "derived")
                runtime.checked_sources(prepared, expected)
                with self.assertRaises(ValueError):
                    runtime.prepare_compiler(goroot, prepared)
            self.assertEqual((prepared / "bin/go").read_bytes(), b"pinned-host-compiler")
            for name, data in original.items():
                self.assertEqual((goroot / "src" / name).read_bytes(), data)

    def test_wrong_compiler_version_and_source_drift_refuse_before_assembly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot, original, upstream = self.fixture(root, prepared=False)
            (goroot / "VERSION").write_text("go1.27.1\n")
            with patch.dict(runtime.UPSTREAM_PREIMAGES, upstream, clear=True):
                output = root / "wrong-version"
                with self.assertRaisesRegex(ValueError, "version-drift"):
                    runtime.prepare_compiler(goroot, output)
                self.assertFalse(output.exists())
                (goroot / "VERSION").write_text("go1.27.2\n")
                path = goroot / "src/runtime/proc.go"
                path.write_bytes(original["runtime/proc.go"] + b"drift")
                output = root / "wrong-source"
                with self.assertRaisesRegex(ValueError, "source-drift"):
                    runtime.prepare_compiler(goroot, output)
                self.assertFalse(output.exists())

    def test_scheduler_and_lsf_overlays_preserve_sources_and_separate_wasi_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot, original, contracts = self.fixture(root)
            with patch.dict(runtime.PREIMAGES, contracts, clear=True):
                upstream = runtime.scheduler_overlay(goroot, root / "upstream")
                strict = runtime.overlay(goroot, root / "strict")
            upstream_rows = json.loads(upstream.read_text())["Replace"]
            strict_rows = json.loads(strict.read_text())["Replace"]
            self.assertEqual(len(upstream_rows), 5)
            self.assertEqual(len(strict_rows), 8)
            for name in original:
                self.assertEqual((goroot / "src" / name).read_bytes(), original[name])
            os_source = str(goroot / "src/runtime/os_wasip1.go")
            self.assertNotIn(os_source, upstream_rows)
            self.assertNotIn("wasi_snapshot_preview1", Path(strict_rows[os_source]).read_text())
            for name in ("runtime/lock_wasip1.go", "runtime/proc.go"):
                key = str(goroot / "src" / name)
                self.assertEqual(Path(upstream_rows[key]).read_bytes(), Path(strict_rows[key]).read_bytes())
            hook = Path(strict_rows[str(goroot / "src/runtime/lock_wasip1.go")]).read_text()
            self.assertIn("func wasiOnIdle(callback func() bool)", hook)
            self.assertIn("!netWaiters && onIdle()", hook)
            self.assertEqual((goroot / "src/runtime/os_wasip1.go").read_bytes(), original["runtime/os_wasip1.go"])

    def test_each_upstream_source_drift_refuses_before_any_overlay_is_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot, original, contracts = self.fixture(root)
            with patch.dict(runtime.PREIMAGES, contracts, clear=True):
                for index, name in enumerate(original):
                    with self.subTest(source=name):
                        path = goroot / "src" / name
                        path.write_bytes(original[name] + b"drift\n")
                        output = root / f"refused-{index}"
                        with self.assertRaisesRegex(ValueError, "go-runtime-source-drift"):
                            runtime.overlay(goroot, output)
                        self.assertFalse(output.exists())
                        path.write_bytes(original[name])

    def test_protected_roots_and_existing_output_refuse_without_modifying_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot, original, contracts = self.fixture(root)
            existing = root / "existing"
            existing.mkdir()
            with patch.dict(runtime.PREIMAGES, contracts, clear=True):
                for output in (goroot, goroot / "overlay", root, existing):
                    with self.subTest(output=output), self.assertRaises(ValueError):
                        runtime.scheduler_overlay(goroot, output)
            for name, data in original.items():
                self.assertEqual((goroot / "src" / name).read_bytes(), data)
