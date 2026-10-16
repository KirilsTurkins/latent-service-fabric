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
    def test_private_wasm_frame_observer_preserves_original_sources_and_bounds_the_overlay(self):
        from tools.diagnose_go_timer_failure import PATHS, overlay_sources
        original = {name: (runtime.ROOT / name).read_bytes() for name in PATHS}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            identities, overlays = overlay_sources(runtime.ROOT, output)
            self.assertEqual(len(overlays), 3)
            for private, source in overlays:
                self.assertTrue(private.is_relative_to(output))
                self.assertEqual(source.read_bytes(), original[source.relative_to(runtime.ROOT).as_posix()])
                self.assertNotEqual(private.read_bytes(), source.read_bytes())
            observer = (output / 'private-source' / PATHS[0]).read_text()
            self.assertIn('downcast_ref::<wasmtime::WasmBacktrace>()', observer)
            self.assertIn('frames().iter().take(32)', observer)
            self.assertNotIn('format!("{error:?}")', observer)
            self.assertTrue(all(value['originalDigest'] != value['privateDigest'] for value in identities.values()))

    def test_private_frame_output_excludes_native_messages_and_rejects_unbounded_or_unexpected_data(self):
        from tools.diagnose_go_timer_failure import frames_from_output
        def encode(value):
            return b'LSF_GO_WASM_FRAME ' + json.dumps(value).encode() + b'\n'
        frame = {'function': 'runtime.(*mheap).allocSpan', 'functionIndex': 42,
                 'functionOffset': 12, 'moduleOffset': 1000}
        self.assertEqual(frames_from_output(b'native configuration secret\n' + encode(frame)), [frame])
        invalid = [{**frame, 'nativeError': 'secret'}, {**frame, 'function': 'path with spaces'},
                   {**frame, 'function': 'x' * 161}, {**frame, 'functionIndex': -1},
                   {**frame, 'moduleOffset': 2**64}, {**frame, 'functionOffset': True}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'output-shape'):
                frames_from_output(encode(value))
        with self.assertRaisesRegex(ValueError, 'output-shape'):
            frames_from_output(encode(frame) * 33)

    def test_private_frame_observer_refuses_drift_before_writing_a_partial_overlay(self):
        from tools.diagnose_go_timer_failure import PATHS, overlay_sources
        with tempfile.TemporaryDirectory() as temporary:
            root, output = Path(temporary) / 'source', Path(temporary) / 'diagnostic'
            for name in PATHS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((runtime.ROOT / name).read_bytes())
            engine = root / PATHS[1]
            engine.write_text(engine.read_text().replace('wasm_backtrace_max_frames(None)', 'changed_config()'))
            before = {name: (root / name).read_bytes() for name in PATHS}
            with self.assertRaisesRegex(ValueError, 'source-drift'):
                overlay_sources(root, output)
            self.assertFalse(output.exists())
            self.assertEqual({name: (root / name).read_bytes() for name in PATHS}, before)

    def test_activation_dispatcher_rejects_changed_dependency_before_transformation(self):
        from tools.go_guest import activation
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'wit/async/async.go'
            source.parent.mkdir(parents=True)
            source.write_text('package async // substituted dispatcher')
            with self.assertRaisesRegex(ValueError, 'dispatcher-source-drift'):
                activation.async_source(root, runtime.ROOT / 'sdk/go-guest')
            self.assertEqual(source.read_text(), 'package async // substituted dispatcher')

    def test_activation_export_refuses_missing_and_synchronous_entry_before_writing(self):
        from tools.go_guest import activation
        for source in ('package main\nfunc main() {}\n',
                       '//go:wasmexport execute\nfunc execute() { wasm_export_task_return_run() }\n'):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / 'wit_exports.go'
                path.write_text(source)
                with self.assertRaisesRegex(ValueError, 'go-activation-'):
                    activation.exports(root)
                self.assertEqual(path.read_text(), source)

    def test_activation_selection_is_explicit_and_retains_default_profile(self):
        from tools.go_guest import activation
        from tools.go_application_dependencies import selection
        self.assertEqual(selection()['runtimeProfile'], 'go-component-async-v1')
        self.assertEqual(selection({'runtimeProfile': activation.PROFILE})['runtimeProfile'], activation.PROFILE)
        self.assertEqual(selection({'runtimeProfile': activation.CHECKPOINT_PROFILE})['runtimeProfile'], activation.CHECKPOINT_PROFILE)
        with self.assertRaisesRegex(ValueError, 'profile-not-installed'):
            selection({'runtimeProfile': 'unbounded-native-threads'})

    def test_checkpoints_cover_selected_open_modules_but_preserve_dispatcher_and_standard_runtime(self):
        from tools.go_guest import checkpoints
        from tools.rust_capsule_project import digest
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated, output = root / 'module', root / 'overlay'
            output.mkdir()
            names = ['app/main.go', 'vendor/example.org/arbitrary-worker/worker.go',
                     'vendor/go.bytecodealliance.org/pkg/wit/async/async.go', 'standard/runtime.go']
            paths = [generated / name for name in names]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'package fixture\nfunc Run(){}\n')
            originals = {path: path.read_bytes() for path in paths}
            packages = [{'Dir': str(path.parent), 'GoFiles': [path.name], 'Standard': index == 3}
                        for index, path in enumerate(paths)]
            def execute(label, tool, request, destination):
                selected = json.loads(request.read_bytes())
                self.assertEqual({row['path'] for row in selected}, {str(path) for path in paths[:2]})
                destination.mkdir()
                rows = []
                for index, row in enumerate(selected):
                    adapted = destination / (str(index) + '.go')
                    adapted.write_bytes(originals[Path(row['path'])] + b'// compiler checkpoint\n')
                    rows.append({'path': row['path'], 'adapted': str(adapted), 'sites': [{'line': 2, 'column': 12, 'suspendable': True}],
                                 'upstreamDigest': digest(originals[Path(row['path'])]), 'adaptedDigest': digest(adapted.read_bytes())})
                return json.dumps(rows)
            replacements, records = checkpoints.transform(SimpleNamespace(run=execute), generated, packages, {paths[0]}, output)
            self.assertEqual(set(replacements), {str(path) for path in paths[:2]})
            self.assertEqual(len(records), 2)
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original)

    def test_checkpoint_parser_cannot_return_an_unselected_source(self):
        from tools.go_guest import checkpoints
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'module/main.go'
            source.parent.mkdir()
            source.write_text('package fixture\nfunc Run(){}\n')
            compiler = SimpleNamespace(run=lambda *arguments: json.dumps([{'path': str(root / 'foreign.go')}]))
            with self.assertRaisesRegex(ValueError, 'returned-unselected-source'):
                checkpoints.transform(compiler, source.parent,
                    [{'Dir': str(source.parent), 'GoFiles': [source.name]}], {source}, root)

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
