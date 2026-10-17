"""Pinned source/ownership controls, not default net/http execution evidence."""
import hashlib
from pathlib import Path
import re
import tempfile
import unittest

from tools.go_guest import activation, http_context, runtime, sdk

FIXTURES = Path(__file__).parent / 'fixtures/go-http-context'
SDK = runtime.ROOT / 'sdk/go-guest'


class GoHttpContextTests(unittest.TestCase):
    def original(self):
        return (FIXTURES / 'streaming.go.in').read_text()

    def test_all_original_calls_and_resource_owners_remain_byte_identical(self):
        original = self.original()
        adapted = http_context.generated_source(original)
        self.assertEqual(adapted[:adapted.index('\n\nfunc OpenContext')].replace(
            '\tlsfHTTPContext "context"\n', ''), original)
        for name in http_context.PREIMAGES:
            self.assertEqual(adapted.count('func ' + name + 'Context('), 1)
        self.assertEqual(adapted.count('witAsync.SubtaskWait('), original.count('witAsync.SubtaskWait('))
        self.assertNotIn('go func', adapted[len(original):])

    def test_every_pinned_call_rejects_marshalling_or_ownership_drift(self):
        original = self.original()
        for name in http_context.PREIMAGES:
            with self.subTest(name=name):
                changed = original.replace('func ' + name + '(', '// changed\nfunc ' + name + '(', 1)
                # Change inside the authenticated function rather than its documentation.
                changed = re.sub(r'(func ' + name + r'\([^\n]+\{\n)', r'\1\tpanic("changed")\n', changed, count=1)
                with self.assertRaisesRegex(ValueError, 'generated-source-drift:' + name):
                    http_context.generated_source(changed)

    def test_own_finish_restores_only_untransferred_argument_and_reads_only_returned_results(self):
        adapted = http_context.generated_source(self.original())
        finish = re.search(r'(?ms)^func FinishContext\(.*?^\}', adapted)[0]
        self.assertEqual(finish.count('target.TakeHandle()'), 1)
        self.assertIn('status == witAsync.LSF_HTTP_START_CANCELLED { target.SetHandle(argumentHandle) }', finish)
        self.assertLess(finish.index('if ctx.Err()'), finish.index('target.TakeHandle()'))
        self.assertLess(finish.index('if status != 2'), finish.index('switch uint8('))
        self.assertEqual(finish.count('target.SetHandle('), 1)
        self.assertNotIn('LSF_HTTP_RETURN_CANCELLED { target.SetHandle', finish)
        self.assertLess(finish.index('defer pinner.Unpin()'), finish.index('SubtaskWaitContext('))

    def test_exact_dispatcher_profiles_preserve_timers_checkpoints_and_initializer_edges(self):
        original = (FIXTURES / 'async.go.in').read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(), activation.ASYNC_SHA256)
        with tempfile.TemporaryDirectory() as temporary:
            dependency = Path(temporary)
            target = dependency / 'wit/async/async.go'
            target.parent.mkdir(parents=True)
            target.write_bytes(original)
            for profile in sorted(activation.PROFILES):
                with self.subTest(profile=profile):
                    _, before = activation.async_source(dependency, SDK,
                        checkpoints=profile in activation.CHECKPOINT_PROFILES,
                        timers=profile in activation.TIMER_PROFILES,
                        initializers=profile == activation.INITIALIZER_PROFILE)
                    after = http_context.async_source(before, SDK)
                    self.assertIn('case STATUS_RETURNED, LSF_HTTP_START_CANCELLED, LSF_HTTP_RETURN_CANCELLED:', after)
                    self.assertIn('if (<-channel) != STATUS_RETURNED', after)
                    self.assertIn('!pending || registered != channel', after)
                    self.assertEqual(after.count('status = lsfHTTPSubtaskCancel(handle)'), 1)
                    self.assertLess(after.index('waitableJoin(handle, 0)'), after.index('status = lsfHTTPSubtaskCancel(handle)'))
                    if profile in activation.TIMER_PROFILES:
                        self.assertIn('event2 == STATUS_RETURNED && lsfHandleTimerEvent(event1)', after)
                        self.assertIn('refreshTimers || lsfRunnableActivationTasks()', after)
                    if profile == activation.INITIALIZER_PROFILE:
                        self.assertIn('lsfActivationInitialize()', after)
            self.assertEqual(target.read_bytes(), original)

    def test_context_facade_requires_explicit_selection_and_actual_streaming_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for selected in (False, True):
                module = root / str(selected)
                raw = module / 'latent_http_0_3_0_streaming/wit_bindings.go'
                raw.parent.mkdir(parents=True)
                raw.write_text(self.original())
                self.assertEqual(sdk.install(SDK, module, http_context=selected), selected)
                self.assertEqual((module / 'lsf/streaming/context.go').is_file(), selected)
                self.assertEqual('func OpenContext(' in raw.read_text(), selected)
                self.assertNotIn('runtime.AddCleanup', raw.read_text())
            empty = root / 'no-http'
            empty.mkdir()
            self.assertFalse(sdk.install(SDK, empty, http_context=True))
            self.assertFalse((empty / 'lsf/streaming').exists())

    def test_wrong_identity_duplicate_call_and_repeated_derivation_fail_closed(self):
        original = self.original()
        for changed in (original.replace(http_context.IDENTITY, 'latent:http/streaming@9.0.0'),
                        original + '\n' + re.search(r'(?ms)^func Open\(.*?^\}', original)[0],
                        http_context.generated_source(original)):
            with self.subTest(kind=changed[:50]), self.assertRaises(ValueError):
                http_context.generated_source(changed)


if __name__ == '__main__':
    unittest.main()
