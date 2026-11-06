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
                    'consumption': {'cpuFuel': '5000000', 'peakMemoryBytes': '16777216',
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

    def test_reported_node_peak_must_cover_simultaneous_heap_and_stack(self):
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 67108864, 'wallTimeLimitMillis': 120000}
        decoded = row('stack-gc')
        live = probe.observed(decoded, 'stack-gc')['memory']
        minimum = live['heapAlloc'] + live['stackInuse']
        actual = {'processReaped': True, 'exitCode': 0, 'decoded': decoded,
            'response': {'outcomeKnown': True, 'data': {'resolvedRevision': 'selected',
                'consumption': {'cpuFuel': '5000000', 'peakMemoryBytes': str(minimum),
                    'wallTimeMicros': '10000', **{key: '0' for key in probe.ZERO_EFFECTS}}}}}
        self.assertEqual(probe.invocation(actual, 'stack-gc', budget, 'selected')
                         ['consumption']['peakMemoryBytes'], minimum)
        actual['response']['data']['consumption']['peakMemoryBytes'] = str(minimum - 1)
        with self.assertRaisesRegex(RuntimeError, 'live-guest-memory-exceeds-node-peak'):
            probe.invocation(actual, 'stack-gc', budget, 'selected')

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
                        patch.object(reference.producer_selection, 'validate_receipt', return_value={'headSha': 'a' * 40}), \
                        patch.object(reference, 'prepared', side_effect=RuntimeError('tuple-drift')
                            if stage == 'tuple' else None,
                            return_value=(binaries, {}, {'originalInvocations': 27})), \
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

    def test_current_producer_rejects_wrong_owner_unsuccessful_or_unverified_artifact(self):
        owner = reference.producer_selection
        sha, run_id = 'a' * 40, 42
        run = {'id': run_id, 'path': owner.WORKFLOW, 'event': 'push', 'head_branch': 'development',
               'status': 'completed', 'conclusion': 'success', 'head_sha': sha,
               'repository': {'id': owner.REPOSITORY_ID}, 'head_repository': {'id': owner.REPOSITORY_ID}}
        job = {'id': 43, 'run_id': run_id, 'head_sha': sha, 'name': owner.JOB,
               'status': 'completed', 'conclusion': 'success',
               'steps': [{'name': name, 'status': 'completed', 'conclusion': 'success'} for name in owner.STEPS]}
        artifact = {'id': 44, 'name': 'go-guest-upstream-' + sha, 'expired': False,
                    'size_in_bytes': 123, 'digest': 'sha256:' + 'b' * 64,
                    'workflow_run': {'id': run_id, 'head_sha': sha, 'head_branch': 'development',
                                     'repository_id': owner.REPOSITORY_ID,
                                     'head_repository_id': owner.REPOSITORY_ID}}
        jobs = {'total_count': 1, 'jobs': [job]}
        artifacts = {'total_count': 1, 'artifacts': [artifact]}
        selected = owner.validate_metadata(run, jobs, artifacts, run_id)
        import hashlib
        selected.update(workflowSha256=hashlib.sha256((owner.ROOT / owner.WORKFLOW).read_bytes()).hexdigest(),
                        sourceComparison={'consumerHead': 'c' * 40, 'relevantChangedFiles': 0,
                                          'comparisonFiles': 2, 'comparisonFileLimit': 299})
        with patch.object(owner, 'current_head', return_value='c' * 40):
            self.assertEqual(owner.validate_receipt(selected), selected)
        self.assertEqual((selected['runId'], selected['jobId'], selected['artifactId']), (42, 43, 44))
        def copy(value): return json.loads(json.dumps(value))
        for target, field, replacement in (
                ('run', 'conclusion', 'failure'), ('run', 'event', 'pull_request'),
                ('run', 'head_branch', 'release'), ('run', 'path', 'other.yml'),
                ('job', 'conclusion', 'failure'), ('job', 'head_sha', 'c' * 40),
                ('artifact', 'digest', None), ('artifact', 'digest', 'sha256:' + 'x' * 64),
                ('artifact', 'expired', True), ('artifact', 'size_in_bytes', 1024**3 + 1)):
            checked_run, checked_jobs, checked_artifacts = copy(run), copy(jobs), copy(artifacts)
            values = {'run': checked_run, 'job': checked_jobs['jobs'][0],
                      'artifact': checked_artifacts['artifacts'][0]}
            values[target][field] = replacement
            with self.subTest(target=target, field=field, replacement=replacement), self.assertRaises(RuntimeError):
                owner.validate_metadata(checked_run, checked_jobs, checked_artifacts, run_id)
        for mutate in ('foreign-repository', 'failed-step', 'missing-step', 'foreign-artifact', 'duplicate-artifact', 'truncated-jobs'):
            checked_run, checked_jobs, checked_artifacts = copy(run), copy(jobs), copy(artifacts)
            if mutate == 'foreign-repository': checked_run['head_repository']['id'] += 1
            if mutate == 'failed-step': checked_jobs['jobs'][0]['steps'][0]['conclusion'] = 'failure'
            if mutate == 'missing-step': checked_jobs['jobs'][0]['steps'].pop()
            if mutate == 'foreign-artifact': checked_artifacts['artifacts'][0]['workflow_run']['id'] += 1
            if mutate == 'duplicate-artifact':
                checked_artifacts['artifacts'].append(copy(artifact))
                checked_artifacts['total_count'] = 2
            if mutate == 'truncated-jobs': checked_jobs['total_count'] += 1
            with self.subTest(mutate=mutate), self.assertRaises(RuntimeError):
                owner.validate_metadata(checked_run, checked_jobs, checked_artifacts, run_id)
        bad_receipt = copy(selected)
        bad_receipt['artifactName'] = 'some-other-artifact'
        with self.assertRaisesRegex(RuntimeError, 'Go-cost-producer-receipt'):
            owner.validate_receipt(bad_receipt)

    def test_producer_selection_can_skip_expired_artifact_but_never_an_invalid_run(self):
        owner = reference.producer_selection
        def api(path):
            if path.startswith('actions/workflows/'):
                return {'workflow_runs': [{'id': 42}, {'id': 41}]}
            if path.startswith('actions/runs/'):
                return {'path': path}
            self.fail('unexpected API path')
        def metadata(run, jobs, artifacts, requested, *, allow_expired=False):
            self.assertEqual(allow_expired, True)
            return None if requested == 42 else {'runId': requested}
        with patch.object(owner, 'validate_run'), patch.object(owner, 'validate_metadata', side_effect=metadata), \
                patch.object(owner, 'bind_source', side_effect=lambda receipt, api: receipt):
            self.assertEqual(owner.select(api=api), {'runId': 41})
        with patch.object(owner, 'validate_run', side_effect=RuntimeError('invalid-run')), \
                self.assertRaisesRegex(RuntimeError, 'invalid-run'):
            owner.select(api=api)
        with self.assertRaisesRegex(RuntimeError, 'run-id'):
            owner.select('42\nartifact_id=43', api=api)

    def test_producer_source_and_workflow_are_bound_to_consumer_before_download(self):
        import base64
        owner = reference.producer_selection
        producer, consumer = 'a' * 40, 'b' * 40
        comparison = {'status': 'ahead', 'base_commit': {'sha': producer},
                      'merge_base_commit': {'sha': producer},
                      'files': [{'filename': 'tools/go_runtime_cost_probe.py'},
                                {'filename': 'docs/development/go-runtime-costs.md'}]}
        raw = (owner.ROOT / owner.WORKFLOW).read_bytes()
        recipe = {'type': 'file', 'path': owner.WORKFLOW, 'encoding': 'base64',
                  'size': len(raw), 'content': base64.b64encode(raw).decode('ascii')}
        def api(path):
            if path.startswith('compare/'):
                self.assertIn(producer + '...' + consumer, path)
                return comparison
            self.assertEqual(path, 'contents/' + owner.WORKFLOW + '?ref=' + producer)
            return recipe
        with patch.object(owner, 'current_head', return_value=consumer):
            selected = owner.bind_source({'headSha': producer}, api)
        self.assertEqual(selected['sourceComparison']['consumerHead'], consumer)
        self.assertEqual(selected['sourceComparison']['relevantChangedFiles'], 0)
        for row in ({'filename': 'tools/requirements.lock'}, {'filename': 'crates/latent-core/src/budget.rs'},
                    {'filename': 'docs/other.md', 'previous_filename': owner.WORKFLOW}):
            with self.subTest(row=row), self.assertRaisesRegex(RuntimeError, 'Go-cost-producer-source-'):
                owner.validate_comparison(dict(comparison, files=[row]), producer, consumer)
        with self.assertRaisesRegex(RuntimeError, 'nonancestor-comparison'):
            owner.validate_comparison(dict(comparison, merge_base_commit={'sha': consumer}), producer, consumer)
        with self.assertRaisesRegex(RuntimeError, 'nonancestor-comparison'):
            owner.validate_comparison(dict(comparison, files=[{'filename': 'docs/x'}] * 300), producer, consumer)
        recipe['content'] = base64.b64encode(b'changed').decode('ascii')
        recipe['size'] = len(b'changed')
        with patch.object(owner, 'current_head', return_value=consumer), \
                self.assertRaisesRegex(RuntimeError, 'recipe-changed'):
            owner.bind_source({'headSha': producer}, api)

    def test_current_source_rejects_relevant_untracked_and_ignored_files(self):
        owner = reference.producer_selection
        head = b'a' * 40 + b'\n'
        def inspect(changes=b'', untracked=b'', ignored=b''):
            outputs = [SimpleNamespace(stdout=value) for value in (head, changes, untracked, ignored)]
            with patch.object(owner.subprocess, 'run', side_effect=outputs) as command:
                result = owner.current_head()
            self.assertEqual(command.call_count, 4)
            self.assertIn('--ignored', command.call_args_list[3].args[0])
            return result
        self.assertEqual(inspect(untracked=b'tools/go_cost_producer.py\0'), 'a' * 40)
        for field, value in (('changes', b'tools/ci/contracts/python/other.json\0'),
                             ('untracked', b'tools/untracked-helper.py\0'),
                             ('ignored', b'tools/__pycache__/unexpected.pyc\0')):
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'Go-cost-producer-un'):
                inspect(**{field: value})

    def test_current_go_source_mismatch_is_rejected_before_inspecting_or_executing_products(self):
        import hashlib
        from tools import qualify_sdk_scratch as scratch
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            old = b'{"recorded":"old"}'
            (directory / 'source-inputs.json').write_bytes(old)
            (directory / 'qualification.json').write_text(json.dumps({
                'schemaVersion': 'latent.go-capsule.qualification.v1', 'status': 'passed',
                'sourceIdentityDigest': hashlib.sha256(old).hexdigest()}), encoding='utf-8')
            with patch.object(scratch, 'current_inputs', return_value={'recorded': 'new'}) as current, \
                    self.assertRaisesRegex(RuntimeError, 'scratch-original-source-mismatch'):
                scratch.prepared(directory, 'go')
            current.assert_called_once_with('go')

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
        source = (Path(__file__).parent / 'fixtures/go_runtime_costs/wasip1-3337.stderr.txt').read_bytes()
        value = reference.stack_placement_observation(source)
        self.assertEqual(value['compilerFrameBytes'], 16424)
        self.assertEqual(value['arrayStackOffset'], 40)
        self.assertEqual(value['checksumCopyStackOffset'], 8232)
        self.assertFalse(value['referenceExecuted'])
        self.assertFalse(value['finalComponentPlacementInferredFromReferenceAlone'])
        for changed in (b'unknown', source * 2, source.replace(b'Get\tSP', b'Get\tR0'),
                        source + b'moved to heap: frame', source.replace(b'locals=0x4028', b'locals=0x1000'),
                        source.replace(b'locals=0x4028', b'locals=0x8028'), b'x' * 262145):
            with self.subTest(changed=changed[:100]), self.assertRaisesRegex(RuntimeError, 'Go-cost-'):
                reference.stack_placement_observation(changed)

    def test_retained_pinned_wasm_diagnostics_prove_the_real_array_initialization_and_checksum_copy(self):
        import hashlib
        source = (Path(__file__).parent / 'fixtures/go_runtime_costs/wasip1-3337.stderr.txt').read_bytes()
        self.assertEqual(len(source), 36849)
        self.assertEqual(hashlib.sha256(source).hexdigest(),
            'fe791676509f5193a9833b94371079e8fd336692f878ae03be289ed19ae980cd')
        self.assertNotIn(b'main.frame', source)
        self.assertIn(b'locals=0x4028', source)
        self.assertEqual(reference.stack_placement_observation(source)['ordinaryArrayBytes'], 8192)

    def test_wasm_reference_rejects_wrong_initialization_copy_source_line_and_other_function(self):
        source = (Path(__file__).parent / 'fixtures/go_runtime_costs/wasip1-3337.stderr.txt').read_bytes()
        for changed in (source.replace(b'I32Const\t$8192', b'I32Const\t$8191'),
                source.replace(b'MemoryFill', b'MemoryCopy'), source.replace(b'MemoryCopy', b'MemoryFill'),
                source.replace(b'main.go:7)', b'main.go:8)'),
                source.replace(b'I64Const\t$8232', b'I64Const\t$8233'),
                source.replace(b'main.costRecursive STEXT', b'main.other STEXT'),
                source.replace(b'Call\tmain.costRecursive(SB)', b'Call\tmain.other(SB)'),
                source.replace(b'main.go:18)', b'main.go:19)'), source + b'frame escapes to heap'):
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
                        return b'go version go1.27.3 linux/amd64\n'
                    check.assertEqual(args[1], 'build')
                    check.assertIn('-gcflags=lsf-cost-stack-proof=-m=2 -S', args)
                    (output / 'logs/01-stack-reference-compile-not-execute.stderr.txt').write_bytes(
                        (Path(__file__).parent / 'fixtures/go_runtime_costs/wasip1-3337.stderr.txt').read_bytes())
                    return b''
            with patch.object(reference, 'Commands', ControlledCommands), \
                    patch.object(reference.shutil, 'which', return_value=str(compiler)):
                value = reference.stack_placement_reference(output)
            self.assertEqual(value['compilerFrameBytes'], 16424)
            self.assertFalse(value['referenceExecuted'])


    def test_actual_programme_grants_activation_only_to_the_explicit_v5_component(self):
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 67108864, 'wallTimeLimitMillis': 120000}
        runtime = [{'capability': capability, 'policy': capability + '-allow'} for capability in
            ('latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0', 'latent:random/random@0.1.0')]
        class Cancellation:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        for profile in fixture.PROFILES:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                target = {'budget': budget, 'grants': [], 'generation': 1}
                client = SimpleNamespace(call=lambda *args: {
                    'data': {'operation': {'publication': {'id': 'exact-publication'}}}})
                node = SimpleNamespace(startup_record={'providers': []}, close=lambda: None)
                def grants(_client, _node, _signed, targets, publications, record, *, language):
                    self.assertEqual(language, 'go')
                    self.assertEqual(publications, {'greeting': 'exact-publication'})
                    targets['greeting'] = dict(target, grants=runtime)
                def activation(_client, _node, _signed, selected, publication):
                    self.assertEqual(profile, 'go-component-activation-v5', 'capability-not-imported')
                    self.assertEqual(selected['grants'], runtime)
                    return dict(selected, grants=runtime + [{'capability': reference.original.oracle.ACTIVATION,
                        'policy': 'activation-allow'}])
                def selected(_client, actual):
                    expected = runtime + ([{'capability': reference.original.oracle.ACTIVATION,
                        'policy': 'activation-allow'}] if profile == 'go-component-activation-v5' else [])
                    self.assertEqual(actual['grants'], expected)
                    self.assertEqual(actual['budget'], budget)
                    raise RuntimeError('stop-after-exact-target-before-invocation')
                with patch.multiple(reference, owned_cancellation=Cancellation,
                        RecordingClient=lambda *args, **kwargs: client,
                        connect=lambda *args: node, deploy=lambda *args: target,
                        selected_revision=selected, write_json=lambda *args: None), \
                        patch.object(reference.original, 'configuration', return_value=Path('owned-node.json')), \
                        patch.object(reference.original, 'runtime_grants', side_effect=grants), \
                        patch.object(reference.original, 'install_activation', side_effect=activation) as install, \
                        self.assertRaisesRegex(RuntimeError, 'stop-after-exact-target-before-invocation'):
                    reference.programme({'latent': Path('latent'), 'latentd': Path('latentd')},
                        Path('signed'), Path(temporary), profile)
                self.assertEqual(install.call_count, int(profile == 'go-component-activation-v5'))


if __name__ == '__main__':
    unittest.main()
