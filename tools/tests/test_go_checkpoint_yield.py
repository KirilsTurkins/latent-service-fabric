"""Pinned dispatcher/source controls, not a signed guest or scheduler receipt."""
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from tools.go_guest import activation, checkpoints, runtime

ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / 'sdk/go-guest'
UPSTREAM = ROOT / 'tools/tests/fixtures/go-http-context/async.go.in'
LEGACY_TEMPLATE = b'//go:linkname lsfActivationYield runtime.lsfActivationYield\nfunc lsfActivationYield() {\n\t// Each caller parks before a second queue entry is possible. The original\n\t// task admission bounds the entire queue; it cannot accumulate callbacks.\n\tchannel := make(chan unit)\n\tstate.yielding = append(state.yielding, channel)\n\t(<-channel)\n}\n'


class GoCheckpointYieldQueue(unittest.TestCase):
    def make_dependency(self, root):
        path = root / 'wit/async/async.go'
        path.parent.mkdir(parents=True)
        path.write_bytes(UPSTREAM.read_bytes())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), activation.ASYNC_SHA256)
        return root

    def test_exact_pinned_dispatcher_routes_both_yields_to_fifo_for_all_checkpoint_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            dep = self.make_dependency(Path(temporary))
            for flags in ({'checkpoints': True}, {'checkpoints': True, 'timers': True},
                          {'checkpoints': True, 'timers': True, 'initializers': True}):
                with self.subTest(flags=flags):
                    _, source = activation.async_source(dep, SDK, **flags)
                    self.assertEqual(source.count('yielding    *lsfYieldWait'), 1)
                    self.assertEqual(source.count('yieldTail   *lsfYieldWait'), 1)
                    self.assertEqual(source.count('func lsfPublishYield('), 1)
                    self.assertEqual(source.count('func lsfTakeYields('), 1)
                    self.assertEqual(source.count('lsfQueueYield(channel)'), 2)
                    self.assertNotIn('state.yielding = append(', source)
                    self.assertIn('yielding := lsfTakeYields()', source)
                    self.assertIn('next := yielding.next\n\t\tyielding.next = nil\n\t\tyielding.channel <- unit{}', source)
                    self.assertEqual(source.count('timerWaits []*lsfTimerWait'), int(bool(flags.get('timers'))))
                    original = ('func Yield() {\n\tchannel := make(chan unit)\n'
                                '\tlsfQueueYield(channel)\n\t(<-channel)\n}')
                    self.assertIn(original, source)
                    for name in ('lsfPublishYield', 'lsfTakeYields'):
                        self.assertIn('//go:noinline\n//go:nosplit\nfunc ' + name + '(', source)

    def test_tracked_legacy_capture_keeps_exact_old_v2_v3_and_v4_output(self):
        expected = (
            ({'checkpoints': True}, 'd7d075c80b141a5abd4a39e319905fc43abcc3a85e54e99188229e441d10291d'),
            ({'checkpoints': True, 'timers': True}, '76d4df47e12e062c6d7b37ff5f7c3351111ca21f2e2874c035d926724ed271eb'),
            ({'checkpoints': True, 'timers': True, 'initializers': True}, '4223de32df53a952a64324f7d838ef4d428d90f52a65b636e9d93575da0db972'),
        )
        self.assertEqual(hashlib.sha256(LEGACY_TEMPLATE).hexdigest(), checkpoints.LEGACY_YIELD_SHA256)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dep = self.make_dependency(root / 'dep')
            runtime_dir = root / 'legacy-sdk/runtime'; runtime_dir.mkdir(parents=True)
            (runtime_dir / 'checkpoint_async.go.in').write_bytes(LEGACY_TEMPLATE)
            for name in ('activation_async.go.in', 'timer_async.go.in'):
                (runtime_dir / name).write_bytes((SDK / 'runtime' / name).read_bytes())
            for flags, expected_digest in expected:
                with self.subTest(flags=flags):
                    _, source = activation.async_source(dep, runtime_dir.parent, **flags)
                    self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), expected_digest)
                    self.assertIn('state.yielding = append(state.yielding, channel)', source)
                    self.assertNotIn('lsfYieldWait', source)

    def test_unknown_or_tampered_captured_template_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dep = self.make_dependency(root / 'dep')
            runtime_dir = root / 'sdk/runtime'; runtime_dir.mkdir(parents=True)
            path = runtime_dir / 'checkpoint_async.go.in'
            for raw in (LEGACY_TEMPLATE + b'\n', (SDK / 'runtime/checkpoint_async.go.in').read_bytes() + b'\n', b'unknown'):
                with self.subTest(length=len(raw)):
                    path.write_bytes(raw)
                    with self.assertRaisesRegex(ValueError, 'go-checkpoint-dispatcher-template-drift'):
                        checkpoints.checkpoint_yield_template(runtime_dir.parent)
                    with self.assertRaisesRegex(ValueError, 'go-checkpoint-dispatcher-template-drift'):
                        activation.async_source(dep, runtime_dir.parent, checkpoints=True)

    def test_fifo_capture_requires_the_exact_matching_owner_control(self):
        for content in (None, (SDK/'runtime/checkpoint_queue_test.go.in').read_bytes() + b'\n'):
            with self.subTest(present=content is not None), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); runtime_dir = root/'sdk/runtime'; runtime_dir.mkdir(parents=True)
                for name in ('checkpoint_async.go.in','checkpoint_transform.go.in','checkpoint_transform_test.go.in'):
                    (runtime_dir/name).write_bytes((SDK/'runtime'/name).read_bytes())
                if content is not None: (runtime_dir/'checkpoint_queue_test.go.in').write_bytes(content)
                build = root/'build'; build.mkdir()
                calls = []
                compiler = SimpleNamespace(root=build, sdk=runtime_dir.parent, paths={}, materials={},
                    commands=SimpleNamespace(root=build, environment={}), run=lambda *args: calls.append(args))
                with self.assertRaises((FileNotFoundError, ValueError)):
                    checkpoints.prepare(compiler)
                self.assertEqual(calls, [])

    def test_legacy_checkpoint_owner_keeps_original_control_inputs(self):
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); runtime_dir = root / 'legacy-sdk/runtime'; runtime_dir.mkdir(parents=True)
            (runtime_dir / 'checkpoint_async.go.in').write_bytes(LEGACY_TEMPLATE)
            for name in ('checkpoint_transform.go.in', 'checkpoint_transform_test.go.in'):
                (runtime_dir / name).write_bytes((SDK / 'runtime' / name).read_bytes())
            compiler = SimpleNamespace(root=root, sdk=runtime_dir.parent, paths={}, materials={},
                commands=SimpleNamespace(root=root, environment={}))
            def run(label, *args):
                calls.append((label, args))
                if label == 'checkpoint-parser-host': return 'linux amd64'
                if label == 'checkpoint-parser-build': (root / 'checkpoint-parser/go-checkpoints').write_bytes(b'legacy-control')
                return ''
            compiler.run = run
            checkpoints.prepare(compiler)
            self.assertEqual([row[0] for row in calls], ['checkpoint-parser-host','checkpoint-parser-controls','checkpoint-parser-build'])
            self.assertEqual(calls[1][1], ('go','test','-count=1',root/'checkpoint-parser/main.go',root/'checkpoint-parser/main_test.go'))
            self.assertFalse((root/'checkpoint-parser/checkpoint_queue.go').exists())

    def test_unmodified_noncheckpoint_dispatcher_keeps_the_original_single_yield(self):
        with tempfile.TemporaryDirectory() as temporary:
            dep = self.make_dependency(Path(temporary))
            _, source = activation.async_source(dep, SDK)
            self.assertIn('yielding    chan unit', source)
            self.assertIn('state.yielding = channel', source)
            self.assertNotIn('lsfYieldWait', source)

    def test_mutated_upstream_or_projection_shape_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            dep = self.make_dependency(Path(temporary))
            path = dep / 'wit/async/async.go'
            path.write_bytes(path.read_bytes() + b'\n// drift\n')
            with self.assertRaisesRegex(ValueError, 'dispatcher-source-drift'):
                activation.async_source(dep, SDK, checkpoints=True)
            sdk = Path(temporary) / 'sdk'; (sdk / 'runtime').mkdir(parents=True)
            template = (SDK / 'runtime/checkpoint_async.go.in').read_text()
            (sdk / 'runtime/checkpoint_async.go.in').write_text(template.replace('lsfPublishYield(waiter)', 'unknown(waiter)'))
            with self.assertRaisesRegex(ValueError, 'overlay-contract-drift'):
                checkpoints.checkpoint_queue_control_source(sdk)

    def test_existing_checkpoint_owner_selects_the_source_projected_controls(self):
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = {'GOOS': 'wasip1', 'GOARCH': 'wasm', 'GOFLAGS': '-overlay=guest.json'}
            compiler = SimpleNamespace(root=root, sdk=SDK, paths={}, materials={},
                commands=SimpleNamespace(root=root, environment=dict(initial)))
            def run(label, *args):
                calls.append((label, args, dict(compiler.commands.environment)))
                if label == 'checkpoint-parser-host': return 'linux amd64'
                if label == 'checkpoint-parser-build': (root / 'checkpoint-parser/go-checkpoints').write_bytes(b'host-control')
                return ''
            compiler.run = run
            checkpoints.prepare(compiler)
            self.assertEqual([row[0] for row in calls], ['checkpoint-parser-host','checkpoint-parser-controls','checkpoint-parser-build'])
            control = calls[1]
            self.assertEqual(control[1][:4], ('go','test','-count=1',root/'checkpoint-parser/main.go'))
            self.assertIn(root/'checkpoint-parser/checkpoint_queue.go', control[1])
            self.assertIn(root/'checkpoint-parser/checkpoint_queue_test.go', control[1])
            self.assertEqual(compiler.commands.environment, initial)
            self.assertEqual(compiler.commands.root, root)
            self.assertEqual((root/'checkpoint-parser/checkpoint_queue_test.go').read_bytes(),
                (SDK/'runtime/checkpoint_queue_test.go.in').read_bytes())
            self.assertIn('checkpointQueueBeforePublish(channel)', (root/'checkpoint-parser/checkpoint_queue.go').read_text())
            self.assertEqual((control[2]['GOOS'],control[2]['GOARCH']), ('linux','amd64'))


if __name__ == '__main__':
    unittest.main()
