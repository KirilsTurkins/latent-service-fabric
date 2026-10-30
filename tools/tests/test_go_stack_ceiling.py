"""Source/preimage/profile controls, not emitted Go stack-limit execution."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.go_guest import activation, runtime, stacks
from tools.tests.test_go_runtime_overlay import sources as base_sources

ORIGINAL = (runtime.ROOT / 'tools/tests/fixtures/go_runtime_stack_go1_27_3.go.txt').read_text(encoding='utf-8')


class StackCeiling(unittest.TestCase):
    def test_whole_pinned_source_derivation_is_exactly_three_guards_and_inverts(self):
        self.assertEqual(hashlib.sha256(ORIGINAL.encode()).hexdigest(), stacks.PREIMAGES['runtime/stack.go'])
        derived = stacks.stack_source(ORIGINAL)
        allocation = '\tif uintptr(n) > lsfMaximumStackBytes { lsfStackLimitExceeded() }\n'
        copy = '\tif newsize > lsfMaximumStackBytes { lsfStackLimitExceeded() }\n'
        self.assertEqual(derived.count(allocation), 1)
        self.assertEqual(derived.count(copy), 2)
        self.assertEqual(derived.replace(allocation, '').replace(copy, ''), ORIGINAL)
        alloc = derived.split('func stackalloc(n uint32) stack {', 1)[1].split('func stackfree(', 1)[0]
        self.assertLess(alloc.index('stack size not a power of 2'), alloc.index(allocation))
        self.assertLess(alloc.index(allocation), alloc.index('if debug.efence'))
        copied = derived.split('func copystack(gp *g, newsize uintptr) {', 1)[1].split('\n}', 1)[0]
        self.assertLess(copied.index(copy), copied.index('gcController.addScannableStack'))
        self.assertLess(copied.index(copy), copied.index('stackalloc(uint32(newsize))'))
        growth = derived.split('func newstack() {', 1)[1].split('\n}', 1)[0]
        self.assertLess(growth.index(copy), growth.index('newsize > maxstacksize'))
        self.assertLess(growth.index(copy), growth.index('copystack(gp, newsize)'))

    def test_any_unreviewed_or_already_derived_source_is_refused(self):
        for text in (ORIGINAL + '\n', ORIGINAL.replace('func stackalloc(', 'func changed('),
                     ORIGINAL.replace('func copystack(', 'func copystack(\nfunc copystack('),
                     stacks.stack_source(ORIGINAL), ''):
            with self.subTest(bytes=len(text)), self.assertRaisesRegex(ValueError, 'source-drift'):
                stacks.stack_source(text)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'go/src/runtime/stack.go'; source.parent.mkdir(parents=True)
            source.write_bytes(ORIGINAL.encode('utf-8'))
            bridge = root/'sdk/runtime/stack_bridge.go.in'; bridge.parent.mkdir(parents=True)
            original_bridge = (runtime.ROOT/'sdk/go-guest/runtime/stack_bridge.go.in').read_bytes()
            self.assertEqual(hashlib.sha256(original_bridge).hexdigest(), stacks.BRIDGE_SHA256)
            for altered in (original_bridge.replace(b'1048576',b'2097152'), original_bridge+b'\n'):
                bridge.write_bytes(altered)
                sources = {'runtime/os_wasip1.go':'original'}
                with self.assertRaisesRegex(ValueError, 'bridge-source-drift'):
                    stacks.runtime_sources(root/'go',sources,root/'sdk')
                self.assertEqual(sources, {'runtime/os_wasip1.go':'original'})

    def test_actual_overlay_routes_only_the_explicit_complete_profile(self):
        # Earlier authenticated overlays are controlled inputs here. Exercise
        # the real final overlay routing/writer, not a copy of its selector.
        upstream = b'//go:wasmimport wasi_snapshot_preview1 adapter_monotonic_clock_set_paused\n'
        def checked(_root, contracts):
            if contracts == runtime.PREIMAGES:
                return base_sources()
            if contracts == stacks.PREIMAGES:
                return {'runtime/stack.go': ORIGINAL}
            return {'net/net_fake.go': 'controlled original network'}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); go = root / 'go'; go.mkdir()
            package = root / 'package/wit/runtime'; package.mkdir(parents=True)
            (package / 'runtime.go').write_bytes(upstream)
            with patch.object(runtime, 'checked_sources', side_effect=checked), \
                    patch.object(runtime, 'closed_network_source', side_effect=lambda text: text), \
                    patch.object(runtime, 'GO_PACKAGE_RUNTIME_SHA256', hashlib.sha256(upstream).hexdigest()), \
                    patch.object(activation, 'runtime_sources'), \
                    patch.object(activation, 'async_source', return_value=(root/'original.go', 'controlled async')), \
                    patch('tools.go_guest.managed_idle.runtime_sources'), \
                    patch('tools.go_guest.queues.runtime_sources'), \
                    patch.object(stacks, 'checked_sources', side_effect=checked):
                results = []
                for selected in (False, True):
                    out = root / str(selected)
                    path = runtime.overlay(go, out, root/'package', activation=True, checkpoints=True,
                        timers=True, initializers=True, managed_idle=True, queued_work=True,
                        bounded_stacks=selected)
                    results.append({Path(a).name: Path(b).read_text(encoding='utf-8')
                        for a, b in json.loads(path.read_text())['Replace'].items()})
            old, new = results
            self.assertNotIn('stack.go', old)
            self.assertEqual(new.pop('stack.go'), stacks.stack_source(ORIGINAL))
            bridge = (runtime.ROOT/'sdk/go-guest/runtime/stack_bridge.go.in').read_text()
            self.assertEqual(new['os_wasip1.go'], old['os_wasip1.go']+'\n'+bridge)
            new['os_wasip1.go'] = old['os_wasip1.go']
            self.assertEqual(old, new)

    def test_incomplete_or_nonboolean_stack_selection_has_no_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); go = root/'go'; go.mkdir()
            for selected in (True, 1, 'true'):
                out = root/'overlay'
                with patch.object(runtime, 'checked_sources', return_value={}), \
                        self.assertRaisesRegex(ValueError, 'bounded-stacks-requires-complete'):
                    runtime.overlay(go, out, bounded_stacks=selected)
                self.assertFalse(out.exists())

    def test_host_parser_preparation_clears_guest_overlay_and_restores_environment(self):
        from types import SimpleNamespace
        from tools.go_guest.checkpoints import prepare
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = {'GOFLAGS':'-mod=vendor -overlay=guest-only.json','GOOS':'wasip1','GOARCH':'wasm'}
            calls = []
            compiler = SimpleNamespace(root=root,sdk=runtime.ROOT/'sdk/go-guest',paths={},materials={},
                commands=SimpleNamespace(root=root,environment=dict(initial)))
            def run(label, *args):
                calls.append((label,dict(compiler.commands.environment)))
                if label == 'checkpoint-parser-host': return 'linux amd64'
                if label == 'checkpoint-parser-build':
                    (root/'checkpoint-parser/go-checkpoints').write_bytes(b'controlled unexecuted host tool')
                return ''
            compiler.run = run
            prepare(compiler)
            self.assertEqual([label for label,_ in calls],
                ['checkpoint-parser-host','checkpoint-parser-controls','checkpoint-parser-build'])
            for _,env in calls:
                self.assertEqual((env['GOOS'],env['GOARCH'],env['GOFLAGS']),('linux','amd64','-mod=readonly'))
            self.assertEqual(compiler.commands.environment,initial)
            self.assertEqual(compiler.commands.root,root)

    def test_normal_project_capture_distribution_and_receipt_bind_the_selected_profile(self):
        from tools.go_capsule_project import create, snapshot, validate
        from tools.go_application_dependencies import selection
        from tools import dev_tool_distribution as distribution, guest_runtime_receipts as receipts
        from tools.go_capsule_build import RECIPE
        from tools.dev_workflow.common import digest, encode
        from tools.rust_capsule_project import inventory
        self.assertEqual(selection()['runtimeProfile'], 'go-component-async-v1')
        self.assertIn(stacks.PROFILE, activation.QUEUE_PROFILES)
        self.assertIn(stacks.PROFILE, activation.MANAGED_PROFILES)
        self.assertIn('tools/go_guest/stacks.py', RECIPE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create(root/'app', 'greeting', runtime_profile=stacks.PROFILE)
            files = snapshot(app); project, _, _ = validate(files)
            self.assertEqual(project['runtimeProfile'], stacks.PROFILE)
            self.assertEqual(selection({'runtimeProfile': stacks.PROFILE})['runtimeProfile'], stacks.PROFILE)
            self.assertEqual(project['limits']['memoryBytes'], 67_108_864)
            bridge = 'vendor/lsf/sdk/go-guest/runtime/stack_bridge.go.in'
            self.assertEqual(files[bridge], (runtime.ROOT/'sdk/go-guest/runtime/stack_bridge.go.in').read_bytes())
            distribution.recipe(root/'distribution', 'go')
            self.assertEqual((root/'distribution/recipe/tools/go_guest/stacks.py').read_bytes(),
                (runtime.ROOT/'tools/go_guest/stacks.py').read_bytes())
            output = root/'receipt'; output.mkdir()
            material = [{'name':'build-recipe','digest':digest(b'controlled recipe'),'size':17}]
            receipts.emit(output,'go',stacks.PROFILE,files,inventory(files),b'controlled component',material,
                graph=None,binding_digest=digest(b'controlled binding'),configuration={'profile':stacks.PROFILE})
            value = receipts.read((output/'standard-runtime-selection.json').read_bytes())
            receipts.verify_build(value,'go',files,inventory(files),b'controlled component',material)
            self.assertEqual((value['qualification'],value['authority']),('unknown','none'))
            files['capsule-project.json'] = encode({**project, 'runtimeProfile':'go-component-activation-v6'})
            with self.assertRaisesRegex(ValueError, 'stale-source'):
                receipts.verify_build(value,'go',files,inventory(files),b'controlled component',material)

if __name__ == '__main__':
    unittest.main()
