import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tools import go_runtime_cost_fixture as fixture
from tools import go_runtime_cost_probe as probe
from tools import qualify_go_runtime_costs as reference
from tools.go_capsule_project import create
from tools.rust_capsule_project import snapshot


def row(mode='baseline'):
    fields = {'beforeHeapAlloc': 1048576, 'heapAlloc': fixture.HEAP_BYTES,
        'beforeStackInuse': 65536, 'stackInuse': 1048576, 'heapSys': 16777216,
        'stackSys': 1048576, 'sys': 20971520, 'beforeNumGC': 1, 'numGC': 3, 'goroutines': 3}
    return [{'ok': '|'.join(['cost', 'mode=' + mode, 'fresh=1', 'value=42'] +
                            [key + '=' + str(fields[key]) for key in probe.FIELDS])}]


class GoRuntimeCosts(unittest.TestCase):
    def test_same_ordinary_source_has_explicit_default_and_v5_profiles_with_original_sdk_and_budgets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = []
            for index, profile in enumerate(fixture.PROFILES):
                original = snapshot(create(root / ('original-' + str(index)), 'greeting', runtime_profile=profile))
                app, record = fixture.project(root / ('actual-' + str(index)), profile)
                actual = snapshot(app)
                self.assertEqual(set(actual), set(original))
                self.assertEqual([n for n in actual if actual[n] != original[n]], ['sdk-lock.json', 'src/main.go'])
                self.assertEqual(actual['capsule-project.json'], original['capsule-project.json'])
                self.assertEqual(json.loads(actual['capsule-project.json'])['limits']['memoryBytes'], 67108864)
                self.assertFalse(record['compilerExecuted'])
                self.assertEqual(record['signedExecution'], 'not-run')
                self.assertFalse(record['logicalQueueResultNativeOwnersClaimed'])
                sources.append(actual['src/main.go'])
            self.assertEqual(sources[0], sources[1])

    def test_fixture_has_no_initializer_workers_explicit_yield_or_new_application_runtime_facade(self):
        self.assertIn('var costCalls uint32', fixture.GO)
        self.assertNotIn('func init(', fixture.GO)
        for token in ('Gosched', 'lsfRegister', 'lsfObserve', 'LockOSThread', 'SetMaxStack', 'time.Sleep'):
            self.assertNotIn(token, fixture.GO)
        self.assertIn('costCalls != 1', fixture.GO)
        self.assertEqual(fixture.MODES, ('baseline', 'stack-gc', 'heap-gc'))
        self.assertNotIn('costTasks', fixture.GO)

    def test_live_stack_and_heap_bytes_survive_real_gc_and_suspension_before_checksum_and_release(self):
        for token in ('//go:noinline', 'var frame [8192]byte', 'costRecursive(32', 'runtime.GC()',
                      '<-release', '34467840', 'runtime.KeepAlive(value)', '391722', '12*1024*1024'):
            self.assertIn(token, fixture.GO)
        self.assertLess(fixture.GO.index('live := costReadMemory()'), fixture.GO.index('close(release)'))
        self.assertLess(fixture.GO.index('runtime.GC()'), fixture.GO.index('for _, item := range frame'))

    def test_unknown_profile_refuses_before_creating_an_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'not-created'
            with self.assertRaisesRegex(RuntimeError, 'explicit-existing-profile'):
                fixture.project(target, 'unapproved')
            self.assertFalse(target.exists())

    def test_actual_stats_parser_keeps_source_data_separate_from_physical_qualification(self):
        for mode in probe.POSITIVE_MODES:
            value = probe.observed(row(mode), mode)
            self.assertTrue(value['fresh'])
            self.assertFalse(value['physicalMemoryAccountingQualified'])
            self.assertFalse(value['logicalUnusedKindsQualified'])
        with self.assertRaisesRegex(RuntimeError, 'no-exhaustion-success'):
            probe.observed(row('tasks-8'), 'tasks-8')

    def test_success_requires_real_reaped_known_result_revision_original_budget_and_zero_effects(self):
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 67108864, 'wallTimeLimitMillis': 120000}
        def actual():
            return {'processReaped': True, 'exitCode': 0, 'decoded': row('stack-gc'),
                'response': {'outcomeKnown': True, 'data': {'resolvedRevision': 'selected',
                    'consumption': {'cpuFuel': '5000000', 'peakMemoryBytes': '3145728',
                        'wallTimeMicros': '10000', **{key: '0' for key in probe.ZERO_EFFECTS}}}}}
        receipt = probe.invocation(actual(), 'stack-gc', budget, 'selected')
        self.assertEqual(receipt['consumption']['cpuFuel'], 5000000)
        self.assertFalse(receipt['fullCostMatrixQualified'])
        self.assertFalse(receipt['physicalMemoryAccountingQualified'])
        for key, value in [('cpuFuel', 1000000001), ('peakMemoryBytes', 67108865),
                           ('wallTimeMicros', 120000001), ('effectCount', 1)]:
            changed = actual()
            changed['response']['data']['consumption'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'original-admitted-budget'):
                probe.invocation(changed, 'stack-gc', budget, 'selected')
        for field, value in [('processReaped', False), ('exitCode', 4)]:
            changed = actual()
            changed[field] = value
            with self.assertRaisesRegex(RuntimeError, 'real-known-reaped'):
                probe.invocation(changed, 'stack-gc', budget, 'selected')
        changed = actual()
        changed['response']['outcomeKnown'] = False
        with self.assertRaisesRegex(RuntimeError, 'real-known-reaped'):
            probe.invocation(changed, 'stack-gc', budget, 'selected')
        with self.assertRaisesRegex(RuntimeError, 'exact-published-revision'):
            probe.invocation(actual(), 'stack-gc', budget, 'foreign')

    def test_consumption_cannot_accept_boolean_negative_private_or_unbounded_integer_fields(self):
        for value in (True, -1, 'private', '1.0', str(2**64)):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, 'finite-consumption'):
                probe.integer(value)

    def test_original_profile_programmes_keep_real_baselines_and_fresh_calls_after_each_live_gc_case(self):
        self.assertEqual(reference.CASES, {
            'go-component-async-v1': [('baseline', 'baseline')],
            'go-component-activation-v5': [('baseline', 'baseline'), ('live-stack-GC', 'stack-gc'),
                ('fresh-after-stack-GC', 'baseline'), ('live-heap-GC', 'heap-gc'),
                ('fresh-after-heap-GC', 'baseline')]})
        self.assertEqual(sum(map(len, reference.CASES.values())), 6)
        self.assertEqual(reference.original.oracle.OWNER_LIMITS,
            {'tasks': 16, 'executors': 2, 'queuedWork': 2, 'waits': 4,
             'timers': 2, 'results': 2, 'nativeOwners': 2})

    def test_idle_requires_actual_complete_rows_cells_and_original_quota_retirement(self):
        def inventory():
            return {'topology': {'available': True, 'complete': True, 'entries': [
                {'name': name, 'ownership': 'activation-scoped', 'activeCount': '0'}
                for name in reference.original.oracle.LIVE_ROWS]},
                'queueDepth': 0, 'quotas': {'usage': {'activations': 0, 'memoryBytes': 0}},
                'cellCapacity': [{'observationAvailable': True, 'active': 0, 'quarantined': 0}]}
        current = inventory()
        client = SimpleNamespace(deadline=100, call=lambda *args: {'data': {'inventory': current}})
        with patch.object(reference.time, 'monotonic', return_value=1):
            self.assertEqual(reference.idle(client)['attempts'], 1)
        current = inventory()
        current['topology']['entries'].pop()
        with self.assertRaisesRegex(RuntimeError, 'actual-physical-owner-rows'):
            reference.idle(client)
        for dimension in ('owner', 'quota', 'cell', 'queue'):
            current = inventory()
            if dimension == 'owner': current['topology']['entries'][0]['activeCount'] = '1'
            if dimension == 'quota': current['quotas']['usage']['memoryBytes'] = 1
            if dimension == 'cell': current['cellCapacity'][0]['quarantined'] = 1
            if dimension == 'queue': current['queueDepth'] = 1
            with self.subTest(dimension=dimension), patch.object(reference.time, 'monotonic', side_effect=[1, 5]), \
                    self.assertRaisesRegex(RuntimeError, 'physical-retirement-deadline'):
                reference.idle(client)

    def test_failed_tuple_cannot_build_or_run_and_failed_build_cannot_write_success(self):
        for stage in ('tuple', 'build'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                producer = root / 'producer.json'
                producer.write_bytes(b'{}')
                binaries = {}
                for name in ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts',
                             'examples/capsule_authoring'):
                    selected = root / name.replace('/', '-')
                    selected.write_bytes(b'not-an-executable')
                    binaries[name] = selected
                output = root / 'output'
                with patch.object(reference.sys, 'platform', 'linux'), \
                        patch.object(reference.os, 'geteuid', return_value=1000, create=True), \
                        patch.object(reference.original, 'validate_producer', return_value={}), \
                        patch.object(reference.original, 'prepared', side_effect=RuntimeError('tuple-drift')
                            if stage == 'tuple' else None,
                            return_value=(binaries, {}, {'originalInvocations': 27}, {})), \
                        patch.object(reference, 'stack_placement_reference', return_value={}), \
                        patch.object(reference, 'build_component', side_effect=RuntimeError('build-failed')) as build, \
                        patch.object(reference, 'programme', side_effect=AssertionError('guest before build')) as run, \
                        self.assertRaisesRegex(RuntimeError, 'tuple-drift|build-failed'):
                    reference.qualify(output, root / 'normal', producer)
                run.assert_not_called()
                self.assertEqual(build.call_count, 0 if stage == 'tuple' else 1)
                record = json.loads((output / 'FAILED.json').read_bytes())
                self.assertEqual(record['status'], 'failed')
                self.assertFalse(record['newNativeBuild'])
                self.assertFalse((output / 'qualification.json').exists())

    def test_private_unknown_duplicate_reordered_or_foreign_mode_observations_are_rejected(self):
        for value in ([{'ok': 'private'}], [{'err': 'memory'}], row() * 2,
                      [{'ok': row()[0]['ok'] + '|private=secret'}], row('foreign')):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, 'Go-cost-'):
                probe.observed(value, 'baseline')
        for replacement in ('heapAlloc=1', 'sys=1'):
            changed = row()[0]['ok'].replace('beforeHeapAlloc=1048576', replacement)
            with self.assertRaisesRegex(RuntimeError, 'exact-field-order'):
                probe.observed([{'ok': changed}], 'baseline')

    def test_invalid_finite_counters_and_stale_or_fabricated_growth_are_not_cost_evidence(self):
        for field, old, invalid in [('goroutines', '3', '0'), ('numGC', '3', str(2**32)),
                ('heapAlloc', str(fixture.HEAP_BYTES), str(2**64)), ('heapSys', '16777216', '-1')]:
            changed = row()[0]['ok'].replace(field + '=' + old, field + '=' + invalid)
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'Go-cost-'):
                probe.observed([{'ok': changed}], 'baseline')
        for mode, old, invalid in [('stack-gc', 'stackInuse=1048576', 'stackInuse=65536'),
                ('heap-gc', 'heapAlloc=' + str(fixture.HEAP_BYTES), 'heapAlloc=1048576'),
                ('stack-gc', 'numGC=3', 'numGC=1')]:
            changed = row(mode)[0]['ok'].replace(old, invalid)
            with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, 'Go-cost-'):
                probe.observed([{'ok': changed}], mode)

    def test_recursive_reference_uses_the_identical_complete_owned_function_without_execution(self):
        source = fixture.stack_reference_source().decode()
        body = fixture.GO[fixture.GO.index('//go:noinline\nfunc costRecursive('):fixture.GO.index('\nfunc costStack(')]
        self.assertEqual(source, 'package main\n\nimport "runtime"\n\n' + body + '\nfunc main() {}\n')
        self.assertNotIn('go func', source)
        self.assertIn('runtime.GC()', source)

    def test_compiler_reference_requires_actual_function_local_stack_address_and_bounded_frame(self):
        source = b'main.costRecursive STEXT size=500 args=0x28 locals=0x2040 funcid=0x0\nMOVD $main.frame+48(SP), R0\n'
        value = reference.stack_placement_observation(source)
        self.assertEqual(value['compilerFrameBytes'], 8256)
        self.assertFalse(value['referenceExecuted'])
        self.assertFalse(value['finalComponentPlacementInferredFromReferenceAlone'])
        for changed in (b'unknown', source * 2, source.replace(b'main.frame+48(SP)', b'heap'),
                        source + b'moved to heap: frame', source.replace(b'0x2040', b'0x1000'),
                        source.replace(b'0x2040', b'0x4000'), b'x' * 262145):
            with self.subTest(changed=changed[:100]), self.assertRaisesRegex(RuntimeError, 'Go-cost-'):
                reference.stack_placement_observation(changed)

    def test_small_generic_stack_growth_cannot_be_mistaken_for_two_recursive_live_stacks(self):
        value = row('stack-gc')[0]['ok']
        weak = value.replace('stackInuse=1048576', 'stackInuse=73728')
        with self.assertRaisesRegex(RuntimeError, 'real-stack-growth'):
            probe.observed([{'ok': weak}], 'stack-gc')

    def test_reference_module_is_beneath_the_go_temporary_root_that_ignores_root_go_mod(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiler = root / 'go-not-executable'
            compiler.write_bytes(b'controlled-compiler-identity-only')
            output = root / 'placement'
            check = self
            class ControlledCommands:
                def __init__(self, work, logs, environment, **bounds):
                    check.assertEqual(work, output / 'project')
                    check.assertEqual(logs, output)
                    check.assertNotEqual(str(work), environment['TMPDIR'])
                    check.assertEqual((work / 'main.go').read_bytes(), fixture.stack_reference_source())
                    check.assertIn(b'module lsf-cost-stack-proof', (work / 'go.mod').read_bytes())
                    check.assertEqual(bounds, {'deadline_seconds': 240, 'command_seconds': 180})
                    self.records = []
                    (output / 'logs').mkdir()
                def run(self, stage, *args):
                    self.records.append({'stage': stage, 'exitCode': 0})
                    if stage == 'stack-reference-compiler-version':
                        return b'go version go1.27.2 linux/amd64\n'
                    check.assertEqual(args[1], 'build')
                    check.assertIn('-gcflags=lsf-cost-stack-proof=-m=2 -S', args)
                    (output / 'logs/01-stack-reference-compile-not-execute.stderr.txt').write_bytes(
                        b'main.costRecursive STEXT size=500 args=0x28 locals=0x2040 funcid=0x0\n'
                        b'MOVD $main.frame+48(SP), R0\n')
                    return b''
            with patch.object(reference, 'Commands', ControlledCommands), \
                    patch.object(reference.shutil, 'which', return_value=str(compiler)):
                value = reference.stack_placement_reference(output)
            self.assertEqual(value['compilerFrameBytes'], 8256)
            self.assertFalse(value['referenceExecuted'])


if __name__ == '__main__':
    unittest.main()
