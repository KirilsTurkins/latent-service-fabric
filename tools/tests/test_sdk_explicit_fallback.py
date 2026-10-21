import copy
from pathlib import Path
import tempfile
import unittest

from tools import sdk_explicit_fallback_fixture as fixture
from tools import sdk_explicit_fallback_node as node
from tools.rust_capsule_project import snapshot
from tools.phase2_operator_process import WorkflowError


def result(language='c', seed=7, alternate=42, trap=False):
    """A reader model only; it is never marked actual-component evidence."""
    return {'processReaped': True, 'exitCode': 4 if trap else 0,
        'decoded': None if trap else fixture.expected(language, seed, alternate),
        'response': {'outcomeKnown': True, 'error': {'code': 'guest-trap' if trap else ''},
            'data': {'terminalState': 'guest_trap' if trap else 'completed'}}}


class ExplicitFallbackControls(unittest.TestCase):
    def test_actual_frozen_reader_api_routes_compiler_and_signer_products(self):
        from tools import qualify_sdk_explicit_fallback as qualifier
        prepared = Path('controlled-prepared-products')
        actual = qualifier.native.native_products(prepared)
        selected = qualifier.selected_tools(actual)
        self.assertEqual(selected, {
            'capsule_contracts': prepared / 'native/examples-capsule_contracts',
            'package': prepared / 'native/examples-package',
            'capsule_authoring': prepared / 'native/examples-capsule_authoring'})
        # Receipt keys are deliberately different from the callable reader API.
        for changed in ({**actual, 'examples/package': actual['package']},
                {k: v for k, v in actual.items() if k != 'capsule_contracts'},
                {('examples/' + k if k == 'capsule_authoring' else k): v for k, v in actual.items()}):
            with self.assertRaises(WorkflowError):
                qualifier.selected_tools(changed)

    def test_normal_project_changes_only_the_application_source(self):
        for language in fixture.LANGUAGES:
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                if language == 'c':
                    from tools.c_capsule_project import create
                else:
                    from tools.go_capsule_project import create
                original = snapshot(create(root / 'original', 'greeting'))
                app, proof = fixture.project(language, root / 'fallback')
                selected = snapshot(app)
                path = proof['sourcePath']
                self.assertEqual(set(original), set(selected))
                self.assertEqual({p: d for p, d in original.items() if p != path},
                    {p: d for p, d in selected.items() if p != path})
                self.assertNotEqual(original[path], selected[path])
                self.assertFalse(proof['sdkProfileAndLimitsChanged'])
                self.assertFalse(proof['filesystemGrantAdded'])

    def test_fallback_and_deliberate_trap_follow_the_exact_native_refusal(self):
        c = fixture.C
        self.assertLess(c.index('fopen('), c.index('cause != ENOTSUP'))
        self.assertLess(c.index('cause != ENOTSUP'), c.index('if (trapped) __builtin_trap()'))
        self.assertLess(c.index('if (trapped) __builtin_trap()'), c.index('unsigned alternate = seed * 5 + 7'))
        go = fixture.GO
        self.assertLess(go.index('os.Open('), go.index('!errors.Is(err, errors.ErrUnsupported)'))
        self.assertLess(go.index('errno != syscall.ENOSYS'), go.index('alternate := seed * 5 + 7'))
        self.assertLess(go.index('!errors.Is(err, errors.ErrUnsupported)'), go.index('if mode == "trap"'))
        self.assertIn('seed <= 1000', c)
        self.assertIn('seed > 1000', go)
        self.assertEqual(fixture.CASES, (('open', 7, 42), ('open', 11, 62), ('trap', 13, None), ('open', 19, 102)))

    def test_reader_requires_the_actual_seed_dependent_alternate_and_native_marker(self):
        for language in fixture.LANGUAGES:
            row = result(language, 11, 62)
            self.assertEqual(node.outcome(language, row, 11, 62)['alternate'], 62)
            for changed in (result(language, 7, 42), result('go' if language == 'c' else 'c', 11, 62)):
                with self.assertRaises(WorkflowError):
                    node.outcome(language, changed, 11, 62)
            for wrong in ('wrong-native-refusal', 'unexpected-success', 'unsupported|seed=11|alternate=42|fresh=1',
                    'unsupported|seed=11|alternate=62|fresh=2'):
                changed = copy.deepcopy(row)
                changed['decoded'] = [{'ok': 'fallback|' + language + '|' + wrong}]
                with self.assertRaises(WorkflowError):
                    node.outcome(language, changed, 11, 62)
            with self.assertRaises(WorkflowError):
                fixture.expected(language, True, 12)

    def test_terminal_trap_never_accepts_timeout_unknown_or_nonreaped_result(self):
        self.assertFalse(node.outcome('go', result(trap=True), 13, None)['preciseInstructionCauseProved'])
        for section, key, wrong in ((None, 'exitCode', 0), (None, 'processReaped', False),
                ('response', 'outcomeKnown', False), ('error', 'code', 'deadline-exceeded'),
                ('data', 'terminalState', 'cancelled')):
            changed = result(trap=True)
            target = changed if section is None else changed['response'] if section == 'response' else changed['response'][section]
            target[key] = wrong
            with self.assertRaises(WorkflowError):
                node.outcome('go', changed, 13, None)

    def test_native_counters_keep_exact_canonical_finite_types(self):
        self.assertEqual(node.unsigned('0'), 0)
        self.assertEqual(node.unsigned(str(2**64 - 1)), 2**64 - 1)
        for value in (False, 0, '', '00', '-1', '+1', '1.0', str(2**64)):
            with self.assertRaises(WorkflowError):
                node.unsigned(value)

    def test_real_wire_mixed_u32_and_u64_consumption_rejects_aliases_and_effects(self):
        value = {'cpuFuel': '195271', 'peakMemoryBytes': '9995232', 'outboundRequests': 0,
            'effectCount': 0, 'childCalls': 0, 'logBytes': '0', 'stateReadBytes': '0',
            'stateWriteBytes': '0', 'blobReadBytes': '0', 'blobWriteBytes': '0'}
        budget = {'cpuFuel': 1_000_000_000, 'memoryBytes': 16 * 1024**2}
        node.consumption(value, budget)
        for key in ('outboundRequests', 'effectCount', 'childCalls'):
            for bad in (False, '0', -1, 1, 2**32):
                changed = {**value, key: bad}
                with self.subTest(key=key, bad=bad), self.assertRaises(WorkflowError):
                    node.consumption(changed, budget)
        for key in ('cpuFuel', 'peakMemoryBytes', 'logBytes', 'stateReadBytes', 'blobWriteBytes'):
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                node.consumption({**value, key: 0}, budget)

    def test_cleanup_preserves_primary_but_refuses_an_otherwise_successful_result(self):
        def close():
            raise OSError('controlled-cleanup-refusal')
        record = {}
        with self.assertRaisesRegex(RuntimeError, 'controlled-primary'):
            with node.owned_cleanup(close, record):
                raise RuntimeError('controlled-primary')
        self.assertEqual(record, {'cleanupRefused': True})
        with self.assertRaises(OSError):
            with node.owned_cleanup(close, {}):
                pass


if __name__ == '__main__':
    unittest.main()
