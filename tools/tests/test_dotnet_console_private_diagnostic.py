"""Private observer guards; none of these controls execute a guest or host build."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import diagnose_dotnet_console_failure as diagnostic
from tools import dotnet_console_diagnostic_inputs as acquisition
from tools.dotnet_guest.project import create
from tools.dotnet_standard_console_fixture import declare
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT, inventory, snapshot


class ConsolePrivateDiagnostic(unittest.TestCase):
    def encoded(self, **changes):
        value = {'trapVariant': 'cannot-enter-component', 'available': True, 'truncated': False,
                 'frames': [{'functionIndex': 7, 'functionOffset': 2, 'moduleOffset': 12}]}
        value.update(changes)
        return diagnostic.PREFIX + json.dumps(value).encode() + b'\n'

    def test_overlay_authenticates_original_host_and_changes_only_private_observer(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, overlays = diagnostic.overlay_sources(ROOT, Path(temporary))
            self.assertEqual(set(source), set(diagnostic.PREIMAGES))
            text = overlays[0][0].read_text(encoding='utf-8')
            self.assertIn('wasmtime::Trap::CannotBlockSyncTask', text)
            self.assertIn('"trapVariant": private_variant', text)
            self.assertIn('"guest-fault"', text)  # Original public classifier survives.
            self.assertNotIn('format!("{error', text)
            engine = overlays[1][0].read_text(encoding='utf-8')
            self.assertIn('WasmBacktraceDetails::Disable', engine)
            self.assertIn('wasm_backtrace_max_frames(std::num::NonZeroUsize::new(32))', engine)
            self.assertEqual(diagnostic.digest(overlays[0][1].read_bytes()), source[diagnostic.frames.PATHS[0]]['original'])

    def test_changed_host_preimage_refuses_before_any_overlay_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'output'; output.mkdir()
            for name in diagnostic.PREIMAGES:
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(b'changed')
            with self.assertRaisesRegex(WorkflowError, 'original-preimage'):
                diagnostic.overlay_sources(root, output)
            self.assertEqual(list(output.iterdir()), [])

    def test_closed_variant_capture_excludes_arbitrary_error_and_surrounding_output(self):
        actual = diagnostic.capture(b'private unrelated text\n' + self.encoded())
        self.assertEqual(actual['records'][0]['trapVariant'], 'cannot-enter-component')
        self.assertNotIn('private unrelated', json.dumps(actual))
        self.assertFalse(actual['rawNodeOutputRetained'])
        for value in ('raw native message', {'private': 'value'}, None):
            with self.subTest(value=value), self.assertRaises((WorkflowError, TypeError)):
                diagnostic.capture(self.encoded(trapVariant=value))
        with self.assertRaisesRegex(WorkflowError, 'closed-trap-variant'):
            diagnostic.capture(self.encoded(error='private message'))

    def test_frame_capture_enforces_global_32_and_record_16_limits(self):
        frames = [{'functionIndex': i, 'functionOffset': i, 'moduleOffset': i} for i in range(32)]
        value = diagnostic.capture(self.encoded(frames=frames) + self.encoded())
        self.assertEqual(sum(len(row['frames']) for row in value['records']), 32)
        self.assertTrue(value['records'][1]['truncated'])
        with self.assertRaisesRegex(WorkflowError, 'record-bound'):
            diagnostic.capture(self.encoded() * 17)
        with self.assertRaisesRegex(WorkflowError, 'numeric-shape'):
            diagnostic.capture(self.encoded(frames=[{'functionIndex': True, 'functionOffset': 0, 'moduleOffset': 0}]))

    def test_fixed_artifact_members_exclude_tool_closures_keys_and_source_payloads(self):
        good = ('dotnet-capsule-dependencies/native-binaries/latentd',
            'dotnet-capsule-dependencies/builds/shipping/wit/deps/clock/package.wit',
            'dotnet-standard-console/build/component.wasm')
        for name in good: self.assertTrue(acquisition.selected(name), name)
        bad = ('dotnet-standard-console/outside/library/Library.cs',
            'dotnet-standard-console/build/compiler-inputs.json',
            'dotnet-capsule-dependencies/native-binaries/../credential',
            'dotnet-capsule-dependencies/builds/shipping/signing-key.json',
            '/dotnet-standard-console/build/component.wasm')
        for name in bad: self.assertFalse(acquisition.selected(name), name)

    def project_fixture(self, root):
        project = create(root / 'original-project', 'greeting'); declare(project)
        original = root / 'retained'; original.mkdir()
        (original / 'source-inputs.json').write_bytes(inventory(snapshot(project)))
        recipes = ('examples/echo-contract/capsule.json', 'examples/echo-contract/deployment.json',
                   'tools/rust_capsule_build.py')
        (original / 'recipe-inputs.json').write_bytes(inventory({name: (ROOT / name).read_bytes() for name in recipes}))
        return original

    def test_declared_public_metadata_has_exact_source_and_recipe_membership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); original = self.project_fixture(root)
            selected = diagnostic.authenticated_project(original, root / 'recreated')
            self.assertEqual(set(selected), {'capsule-project.json', 'vendor/lsf/Cargo.toml', 'wit/world.wit',
                'wit/deps/clock/package.wit', 'wit/deps/log/package.wit', 'wit/deps/random/package.wit'})
            self.assertNotIn('src/Main.cs', selected)

    def test_changed_or_extra_original_WIT_cannot_be_reconstructed_as_authentic(self):
        for extra in (False, True):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); original = self.project_fixture(root)
                path = original / 'source-inputs.json'; value = json.loads(path.read_bytes())
                if extra: value['wit/extra.wit'] = value['wit/world.wit']
                else: value['wit/world.wit']['digest'] = 'sha256:' + '0' * 64
                path.write_bytes(json.dumps(value).encode())
                with self.assertRaisesRegex(WorkflowError, 'original-(WIT-membership|public-source-byte)'):
                    diagnostic.authenticated_project(original, root / 'recreated')

    def test_inventory_uses_real_capture_shape_and_refuses_foreign_paths(self):
        raw = inventory({'wit/world.wit': b'world service {}'})
        self.assertEqual(set(diagnostic.inventory_rows(raw)), {'wit/world.wit'})
        for name in ('../outside', '/host/file', 'C:/host', 'wit//bad'):
            with self.subTest(name=name), self.assertRaisesRegex(WorkflowError, 'inventory-row'):
                diagnostic.inventory_rows(json.dumps({name: {'digest': 'sha256:' + '0' * 64, 'size': 1}}).encode())


    def test_remaining_deadline_never_extends_and_expired_commands_refuse(self):
        from unittest.mock import patch
        with patch.object(diagnostic.time, 'monotonic', return_value=95):
            self.assertEqual(diagnostic.remaining(100), 5)
            self.assertEqual(diagnostic.remaining(200), 30)
            with self.assertRaisesRegex(WorkflowError, 'original-deadline'):
                diagnostic.remaining(95)

    def test_reuse_requires_exact_binary_source_component_and_overlay_identity(self):
        from tools.phase3_resource_identity import file_identity
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'host'; binary.write_bytes(b'private host')
            original = {'qualification': False, 'sourceCommit': diagnostic.TESTED,
                'component': diagnostic.COMPONENT, 'sourceOverlays': {'host': 'overlay'},
                'privateHost': file_identity(binary), 'originalNativeInputs': {'native': 'input'},
                'observerPrefix': diagnostic.PREFIX.decode().strip(), 'support': {'support': 'input'},
                'scope': 'private-diagnostic-only;not-production'}
            self.assertEqual(diagnostic.validate_reuse(original, binary, {'host': 'overlay'},
                {'native': 'input'}, {'support': 'input'}), file_identity(binary))
            for key in ('sourceCommit', 'sourceOverlays', 'component', 'originalNativeInputs', 'support'):
                changed = {**original, key: 'different'}
                with self.subTest(key=key), self.assertRaisesRegex(WorkflowError, 'reuse-identity'):
                    diagnostic.validate_reuse(changed, binary, {'host': 'overlay'},
                        {'native': 'input'}, {'support': 'input'})
            binary.write_bytes(b'changed')
            with self.assertRaisesRegex(WorkflowError, 'reuse-identity'):
                diagnostic.validate_reuse(original, binary, {'host': 'overlay'},
                    {'native': 'input'}, {'support': 'input'})


    def test_build_support_contains_only_unchanged_reviewed_generic_functions(self):
        import ast
        from tools import dotnet_console_build_support as support
        source = (ROOT / 'tools/dotnet_console_build_support.py').read_bytes()
        self.assertIn(diagnostic.digest(source), (ROOT / 'tools/diagnose_dotnet_console_failure.py').read_text())
        tree = ast.parse(source)
        self.assertEqual([node.name for node in tree.body if isinstance(node, ast.FunctionDef)],
            ['retain_private_cargo', 'locked_registry_inputs', 'private_target'])
        self.assertEqual(support.ORIGIN, '1c420914b72bff605422a9077fa3eea34af321a3')
        self.assertEqual(support.ORIGIN_DIGEST,
            'sha256:b6873e35d7122fbf1a46371c9e064ca514b3ea40d85600eac99d3733b01c1a45')

    def test_private_workflow_is_explicit_default_off_and_preserves_original_native_limit(self):
        from tools import ci_lane_inventory as ci_lanes
        model = ci_lanes.workflow_model((ROOT / '.github/workflows/dotnet-guest.yml').read_text())
        toolchain = model['jobs']['toolchain']
        self.assertEqual(toolchain['timeout-minutes'], 75)
        self.assertEqual(toolchain['if'], "${{ github.event_name != 'workflow_dispatch' || !inputs.observe-console-failure }}")
        private = model['jobs']['console-private']
        self.assertEqual(private['timeout-minutes'], 20)
        self.assertEqual(private['if'], "${{ github.event_name == 'workflow_dispatch' && inputs.observe-console-failure }}")
        self.assertTrue(any('console-observer.py' in step.get('run', '') for step in private['steps']))


if __name__ == '__main__': unittest.main()
