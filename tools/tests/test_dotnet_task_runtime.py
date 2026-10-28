"""Authority and retirement gates for the ordinary managed-task programme."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import dotnet_task_runtime_fixture as fixture, dotnet_task_runtime_probe as probe
from tools.dotnet_guest import project, runtime
from tools.run_rust_capsule_workflow import run


class ManagedTaskProgramme(unittest.TestCase):
    def test_async_activation_declaration_preserves_sdk_and_adds_no_network_or_grants(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = project.create(Path(temporary) / 'greeting', 'greeting')
            before = (app / 'sdk-lock.json').read_bytes()
            fixture.declare(app)
            project.validate(project.snapshot(app))
            wit = (app / 'wit/world.wit').read_text(encoding='utf-8')
            self.assertIn('greet: async func(', wit)
            self.assertIn(runtime.ACTIVATION, wit)
            self.assertIn(runtime.WALL, wit)
            self.assertNotIn(runtime.HTTP, wit)
            self.assertIn(runtime.RANDOM, wit)
            self.assertEqual((app / 'sdk-lock.json').read_bytes(), before)
            self.assertNotIn('grants', (app / 'capsule-project.json').read_text(encoding='utf-8'))
            with self.assertRaisesRegex(RuntimeError, 'canonical-greeting'): fixture.declare(app)

    def test_wrong_language_combined_campaign_or_nonboolean_selector_refuses_before_inputs(self):
        for keywords in ({'language': 'rust', 'dotnet_task_runtime': True},
                         {'language': 'dotnet', 'dotnet_task_runtime': 1},
                         {'language': 'dotnet', 'dotnet_task_runtime': True, 'noncrypto_entropy': True}):
            with self.subTest(keywords=keywords), self.assertRaisesRegex(RuntimeError, 'task-runtime-language'):
                run(Path('missing'), Path('missing'), Path('missing'), Path('missing'), **keywords)

    def test_failed_activation_binding_never_adds_grants_or_deploys(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(directory=Path(temporary), call=Mock(return_value={
                'outcomeKnown': False, 'category': 'uncertain'}))
            target = {'grants': [{'capability': runtime.CLOCK, 'policy': 'clock'}],
                      'service': 'examples/my-greeting', 'generation': 3}
            node = SimpleNamespace(startup_record={'providers': [{
                'id': 'activation-tasks', 'capability': runtime.ACTIVATION, 'profile': 'observed-profile',
                'configurationDigest': 'sha256:' + 'a' * 64}]})
            denied = {'processReaped': True, 'exitCode': 4,
                'response': {'outcomeKnown': True, 'error': {'code': 'permission-denied'}}}
            targets = {'greeting': copy.deepcopy(target)}
            with patch('tools.rust_capsule_node.call', return_value=denied), \
                    patch('tools.rust_capsule_node.deploy') as deploy:
                with self.assertRaisesRegex(RuntimeError, 'binding-apply'):
                    probe.grant(client, node, Path(temporary), targets, {'greeting': 'publication'}, {'invocations': []})
                deploy.assert_not_called()
            self.assertEqual(targets['greeting'], target)

    def test_each_runtime_grant_is_omitted_independently_and_refuses_before_guest_entry(self):
        for fuel in ('0', '1'):
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                denied = {'processReaped': True, 'exitCode': 4, 'response': {'outcomeKnown': True,
                    'error': {'code': 'permission-denied'}, 'data': {'consumption': {
                        'cpuFuel': fuel, 'peakMemoryBytes': '0', 'outboundRequests': '0',
                        'logBytes': '0', 'effectCount': '0'}}}}
                client = SimpleNamespace(directory=directory, call=Mock(return_value={
                    'outcomeKnown': True, 'category': 'success'}))
                node = SimpleNamespace(startup_record={'providers': [
                    {'id': 'activation-tasks', 'capability': runtime.ACTIVATION, 'profile': 'activation-owned-v1',
                     'configurationDigest': 'sha256:' + 'a' * 64},
                    {'id': 'wall-tasks', 'capability': runtime.WALL, 'profile': 'activation-wall-v1',
                     'configurationDigest': 'sha256:' + 'b' * 64}]})
                targets = {'greeting': {'service': 'examples/my-greeting', 'generation': 3,
                    'grants': [{'capability': runtime.CLOCK, 'policy': 'clock'}]}}
                observed = []
                def deployed(*args, grants, **keywords):
                    observed.append(copy.deepcopy(grants))
                    return {**targets['greeting'], 'generation': 3 + len(observed), 'grants': grants}
                def entropy(*args):
                    result = args[-1]
                    result['noncryptoEntropyAuthority'] = {'scope': 'fixture-only'}
                    result['noncryptoEntropyGrantDenied'] = denied
                    target = args[-2]
                    return {**target, 'grants': [*target['grants'], {'capability': runtime.RANDOM, 'policy': 'random'}]}
                result = {'invocations': []}
                with self.subTest(fuel=fuel), patch('tools.rust_capsule_node.call', return_value=denied), \
                        patch('tools.rust_capsule_node.deploy', side_effect=deployed), \
                        patch.object(probe.entropy_grants, 'grant', side_effect=entropy):
                    if fuel != '0':
                        with self.assertRaisesRegex(RuntimeError, 'single-required-grant'):
                            probe.grant(client, node, directory, targets, {'greeting': 'publication'}, result)
                        self.assertNotIn('dotnetTaskRuntimeAuthority', result)
                    else:
                        probe.grant(client, node, directory, targets, {'greeting': 'publication'}, result)
                        all_grants = {runtime.CLOCK, runtime.WALL, runtime.ACTIVATION, runtime.RANDOM}
                        evidence = result['dotnetTaskRuntimeAuthority']['singleMissingGrantDenials']
                        self.assertEqual({row['missingCapability'] for row in evidence}, all_grants)
                        self.assertEqual(len(evidence), 4)
                        for grants, missing in zip(observed[1:-1], evidence):
                            self.assertEqual({row['capability'] for row in grants}, all_grants - {missing['missingCapability']})
                        self.assertEqual({row['capability'] for row in observed[-1]}, all_grants)

    def test_every_case_requires_known_reaped_bounded_zero_effect_execution_and_retirement(self):
        target = {'budget': {'cpuFuel': 1000, 'memoryBytes': 10000}}
        original = {'processReaped': True, 'response': {'outcomeKnown': True, 'data': {
            'consumption': {'cpuFuel': '17', 'peakMemoryBytes': '100', 'outboundRequests': '0',
                'logBytes': '0', 'effectCount': '0'}}}}
        for mutation in ('none', 'unreaped', 'unknown', 'fuel', 'memory', 'outbound', 'effects'):
            row = copy.deepcopy(original)
            if mutation == 'unreaped': row['processReaped'] = False
            elif mutation == 'unknown': row['response']['outcomeKnown'] = False
            elif mutation != 'none':
                key, value = {'fuel': ('cpuFuel', '1001'), 'memory': ('peakMemoryBytes', '10001'),
                    'outbound': ('outboundRequests', '1'), 'effects': ('effectCount', '1')}[mutation]
                row['response']['data']['consumption'][key] = value
            result = {'invocations': [], 'providerIdle': [], 'samples': []}
            with self.subTest(mutation=mutation), patch('tools.rust_capsule_node.call', return_value=row), \
                    patch('tools.rust_capsule_node.assert_value') as values, \
                    patch('tools.rust_capsule_node.provider_idle', return_value={'idle': True}), \
                    patch('tools.rust_capsule_node.sample', return_value={'retired': True}):
                if mutation != 'none':
                    with self.assertRaisesRegex(RuntimeError, 'consumption-or-reaping'):
                        probe.probe(None, target, None, result, 0)
                    self.assertNotIn('dotnetTaskRuntime', result)
                else:
                    probe.probe(None, target, None, result, 0)
                    self.assertEqual(len(result['invocations']), len(fixture.CASES))
                    self.assertEqual(len(result['samples']), len(fixture.CASES))
                    self.assertEqual([args.args[2] for args in values.call_args_list],
                        [[{'ok': fixture.expected(mode)}] for mode in fixture.CASES])
                    self.assertFalse(result['dotnetTaskRuntime']['cpuPreemptionQualified'])


class RootReturnNormalControls(unittest.TestCase):
    def test_marker_parser_requires_real_close_pending_and_original_bounds(self):
        from tools.dotnet_root_return import positive_sequence
        from tools.phase2_operator_process import WorkflowError
        prefix = b'LSF-GO-NODE-STOP-TIMER-V1|'
        lines = [b'pending|root-close|1|2|0|0', b'pending|wait-pending|2|2|1|1',
                 b'drain|root-close|3|1|1|1', b'drain|wait-pending|4|1|1|1']
        encode = lambda values: b'\n'.join(prefix+x for x in values)+b'\n'
        self.assertEqual([r['sequence'] for r in positive_sequence(encode(lines))], [1, 2, 3, 4])
        for bad in (lines[:1]+[b'pending|wait-pending|1|2|1|1']+lines[2:],
                    [b'pending|root-close|1|1|0|0']+lines[1:],
                    lines[:3]+[b'drain|wait-pending|4|1|17|1'],
                    lines[:3]+[b'drain|wait-pending|2|1|1|1'],
                    lines[:1]+[b'pending|wait-pending|0|2|1|1']+lines[2:],
                    lines[:3]+[b'drain|next-entered|4|1|1|1'],
                    lines+[b'overflow'], lines+[b'foreign|root-close|5|1|0|0']):
            with self.subTest(bad=bad), self.assertRaises((WorkflowError, ValueError)):
                positive_sequence(encode(bad))
        with self.assertRaises((WorkflowError, ValueError)):
            positive_sequence(b'x'*262145)

    def test_exact_normal_programme_preserves_caps_and_only_two_observer_ids(self):
        from tools import dotnet_root_return as selected
        self.assertEqual([(t, m) for t, m, _ in selected.STEPS], [
            ('examples', 1), ('foreign', 2), ('examples', 3), ('foreign', 4), ('examples', 5),
            ('foreign', 6), ('examples', 8), ('foreign', 6), ('examples', 9), ('foreign', 6), ('examples', 6)])
        self.assertEqual(len({a for _, _, a in selected.STEPS}), 11)
        self.assertEqual([(m, a) for _, m, a in selected.STEPS if a.startswith('node-stop-')],
            [(1, 'node-stop-pending'), (2, 'node-stop-drain')])
        self.assertEqual(selected.OWNER_CAPS, {'tasks': 8, 'executors': 2, 'queuedWork': 8,
            'waits': 16, 'timers': 8, 'results': 8, 'nativeOwners': 8})
        self.assertNotIn(7, [m for _, m, _ in selected.STEPS])
        self.assertEqual(len(selected.STEPS)+len(selected.PROFILES), 15)


    def test_retention_closes17_and_keeps_component_before_shape_refusal(self):
        import hashlib
        import json
        from tools import dotnet_root_return as selected
        from tools.phase2_operator_process import WorkflowError
        self.assertEqual(len(selected.PROBE_SOURCES), 17)
        for count, extra in ((17, False), (16, False), (17, True)):
            with self.subTest(count=count, unsafe_extra=extra), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); compiled = root/'compiled'; generated = compiled/'generated'
                generated.mkdir(parents=True); output = root/'output'; output.mkdir()
                # Parser-only fixture bytes, never a real compiled programme.
                component = b'\0asm\x0d\0\x01\0'; (compiled/'component.wasm').write_bytes(component)
                outputs = {}
                for name in selected.PROBE_SOURCES[:count]:
                    raw = ('// parser control '+name).encode(); (generated/name).write_bytes(raw)
                    outputs[name] = hashlib.sha256(raw).hexdigest()
                if extra: outputs['../outside.cs'] = '0'*64
                if count == 17 and not extra:
                    names, records = selected.stage_probe_sources(compiled, output, {'outputs': outputs}, compiler_returned=True)
                    self.assertEqual(tuple(names), selected.PROBE_SOURCES); self.assertEqual(len(records), 17)
                else:
                    with self.assertRaises(WorkflowError):
                        selected.stage_probe_sources(compiled, output, {'outputs': outputs}, compiler_returned=True)
                report = json.loads((output/'probe-capture-inventory.json').read_bytes())
                self.assertEqual(report['csharpCount'], count+int(extra))
                self.assertFalse(report['captureComplete'])
                self.assertEqual((output/'component.wasm').read_bytes(), component)
                self.assertEqual(len(list((output/'probe-inputs').glob('*.cs'))), count)
                self.assertFalse((output/'outside.cs').exists())




class RootReturnSupplementalControls(unittest.TestCase):
    def test_pinned_flat_u32_auxiliary_has_complete_normal_inverse(self):
        from tools.dotnet_guest import async_exports as a
        from tools.rust_capsule_project import ROOT
        normal = (ROOT/'sdk/dotnet-guest/tests/fixtures/root-join-cause/ProbeInterop.normal.cs.fixture').read_text()
        selected, receipt = a.diagnostic_join_cause(a.JOIN_CAUSE_FILE, normal)
        self.assertEqual(selected.replace(a.JOIN_CAUSE_SELECTED, a.JOIN_CAUSE_NORMAL), normal)
        self.assertEqual(receipt['normalSha256'], a.JOIN_CAUSE_NORMAL_SHA256)
        self.assertFalse(receipt['physicalRetirementQualified'])
        self.assertFalse(receipt['originalTrapQualified'])
        # All-feature inventory and ordinary Go builds share the same ignored
        # test registration; unavailable diagnostic prerequisites must refuse.
        rust = (ROOT/'crates/latent-wasmtime/tests/local_service.rs').read_text()
        signature = 'async fn dotnet_join_cause_borrows_one_word_before_unchanged_native_finalization() {'
        prefix, remaining = rust.split(signature, 1)
        body = remaining.split('\n#[tokio::test(', 1)[0]
        attributes = prefix.rsplit('\n\n', 1)[1]
        self.assertNotIn('#[cfg', attributes)
        self.assertIn('#[tokio::test(', attributes)
        self.assertIn('#[ignore = "Requires a separately reviewed NORMAL+auxiliary signed .NET fixture owner"]', attributes)
        condition = (r'feature = "development-test-host",\s*'
                     r'target_os = "linux",\s*target_arch = "x86_64"')
        self.assertRegex(body, r'^\s*#\[cfg\(all\(\s*'+condition+r'\s*\)\)\]\s*\{')
        self.assertRegex(body, r'#\[cfg\(not\(all\(\s*'+condition+
            r'\s*\)\)\)\]\s*\{\s*panic!\(\s*'
            r'"requires the reviewed development-test-host Linux x86_64 fixture"\s*\);\s*\}\s*\}\s*$')
        self.assertEqual(body.count('feature = "development-test-host"'), 2)
        # The signed fixture must use the capsule's tenant at every native edge.
        self.assertIn('capsule.metadata.tenant.expect("captured capsule tenant")', body)
        self.assertIn('Signers::for_tenant(DOTNET_CAPSULE_BUILD_TYPE, &tenant)', body)
        self.assertIn('.admit_package(&tenant, upload,', body)
        self.assertIn('Fixture::with_named_activation_runtime(', body)
        self.assertNotIn('TenantId("tenant-a"', body)
        self.assertIn('let service = ServiceId(capsule.metadata.name);', body)
        self.assertIn('caller: service.clone()', body)
        self.assertIn('callee: service', body)
        self.assertNotIn('..Default::default()', body)
        from tools import dotnet_root_return as replay
        from tools.phase2_operator_process import WorkflowError
        import hashlib
        translated = replay.JOIN_REPLAY_FIXTURE_TRANSLATION
        self.assertEqual(translated['path'], 'crates/latent-wasmtime/tests/local_service/fixture.rs')
        fixture = (ROOT/translated['path']).read_bytes()
        actual_blob = hashlib.sha1(b'blob '+str(len(fixture)).encode()+b'\0'+fixture).hexdigest()
        self.assertEqual(actual_blob, translated['currentGitBlob'])
        self.assertNotEqual(translated['currentGitBlob'], translated['producerGitBlob'])
        self.assertEqual(replay.JOIN_REPLAY['artifact'], 12759125468)
        self.assertEqual(replay.JOIN_REPLAY['bytes'], 15120874)
        self.assertEqual(len(replay.JOIN_REPLAY_COMPONENTS), 2)
        self.assertEqual(len(replay.JOIN_REPLAY_WIT), 4)
        # Reject an untrusted carrier before reading its central metadata.
        with tempfile.TemporaryDirectory() as temporary:
            bad = Path(temporary)/'untrusted.zip'; bad.write_bytes(b'not the admitted artifact')
            with self.assertRaisesRegex(WorkflowError, 'join-replay-official-archive'):
                replay.join_replay_extract(bad, Path(temporary)/'never-staged', 0)
            self.assertFalse((Path(temporary)/'never-staged').exists())
        for name, text in [("other.cs", ""), (a.JOIN_CAUSE_FILE, ""),
                           (a.JOIN_CAUSE_FILE, a.JOIN_CAUSE_NORMAL)]:
            with self.assertRaisesRegex(ValueError, 'unreviewed-normal-helper'):
                a.diagnostic_join_cause(name, text)

    def test_task_return_stage_parser_never_qualifies_the_failed_old_oracle(self):
        import copy
        import json
        from tools import dotnet_root_return as selected
        from tools.phase2_operator_process import WorkflowError
        rows = []
        for auxiliary in (False, True):
            for mode, cause in ((8, 'quiescence'), (9, 'originalFault'), (10, 'unexpected')):
                rows.append({'component': selected.JOIN_REPLAY_COMPONENTS[int(auxiliary)],
                    'mode': mode, 'auxiliary': auxiliary, 'stage': 'canonicalTaskReturnBeforeScopeExit',
                    'taskReturnWitness': {'claims': 1, 'invalid': False, 'cause': cause} if auxiliary else None,
                    'postCallObservation': {'claims': 1, 'invalid': True, 'cause': None} if auxiliary else None,
                    'rejection': 'callFailed' if auxiliary else None,
                    'terminalOutcome': 'guest-trap', 'outerInvocationSucceeded': False,
                    'canonicalTaskReturnCauseEvidence': auxiliary and mode != 10,
                    'oldPostCallProgrammeQualified': False, 'originalTrapQualified': False,
                    'physicalRetirementQualified': False})
        def encoded(items):
            return ''.join('DOTNET_JOIN_TASK_RETURN '+json.dumps(r)+'\n' for r in items).encode()
        self.assertEqual(selected.join_task_return_observations(encoded(rows), selected.JOIN_REPLAY_COMPONENTS), rows)
        # Parser fixtures are not guest executions or evidence. Every mutation
        # below must refuse, including laundering a failed old post-call model.
        for field, value in [('oldPostCallProgrammeQualified', True),
                             ('outerInvocationSucceeded', True), ('rejection', ['callFailed'])]:
            bad = copy.deepcopy(rows); bad[4][field] = value
            with self.assertRaises(WorkflowError):
                selected.join_task_return_observations(encoded(bad), selected.JOIN_REPLAY_COMPONENTS)
        for change in ({'invalid': True}, {'claims': 2}, {'cause': 'unknown'}):
            bad = copy.deepcopy(rows); bad[4]['taskReturnWitness'].update(change)
            with self.assertRaises(WorkflowError):
                selected.join_task_return_observations(encoded(bad), selected.JOIN_REPLAY_COMPONENTS)
        bad = copy.deepcopy(rows); bad[5]['canonicalTaskReturnCauseEvidence'] = True
        with self.assertRaises(WorkflowError):
            selected.join_task_return_observations(encoded(bad), selected.JOIN_REPLAY_COMPONENTS)


class TaskStageDiagnosticControls(unittest.TestCase):
    def test_private_mode_refuses_default_cache_and_unpaired_generator_before_tools(self):
        from tools.dotnet_guest.compiler import Compiler
        from tools import dotnet_guest_bindings as bindings
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);(directory/'MANAGED-STAGE-INSTALL.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'private-managed-stage-tools-rejected-by-default-compiler'):
                Compiler(directory,Mock(),directory)
            with self.assertRaisesRegex(bindings.BindingError,'managed-stage-requires-auxiliary-profile'):
                bindings.generate(directory/'missing.wit',directory/'missing-output','service','never-bindgen','never-wasm',
                    development_managed_stage=True)
            self.assertFalse((directory/'missing-output').exists())

    def test_selected_actual_task_source_has_whole_original_inverse(self):
        from tools.dotnet_guest import managed_work as selected
        from tools.rust_capsule_project import ROOT
        original=(ROOT/'sdk/dotnet-guest/tests/fixtures/root-return/Library.cs').read_text()
        output,receipt=selected.stage_library(original)
        self.assertEqual(receipt['originalSHA256'],selected.STAGE_LIBRARY_SHA)
        self.assertTrue(receipt['originalSourceInverseExact'])
        self.assertFalse(receipt['readsTaskException'])
        self.assertFalse(receipt['applicationRootJoinAdded'])
        # A source drift outside the selected insertions must refuse, not inherit the reviewed identity.
        with self.assertRaisesRegex(ValueError,'managed-stage-library-preimage'):
            selected.stage_library(original+'\n')
        self.assertNotEqual(output,original)
        # Complete raw bodies survive a refusal BEFORE bindings.json exists;
        # a drift check must refuse without replacing the first raw evidence.
        from tools.dotnet_root_return import retain_managed_stage_failure
        with tempfile.TemporaryDirectory() as temporary:
            compiled=Path(temporary)/'compiled';generated=compiled/'generated';generated.mkdir(parents=True)
            (generated/'ActualExtra.cs').write_bytes(b'// actual raw source\n')
            raw=selected.stage_raw_generation(generated,generated,check=False)
            self.assertEqual(raw['actualNames'],['ActualExtra.cs'])
            self.assertEqual(selected.stage_raw_generation(generated,generated,check=True),raw)
            (generated/'ActualExtra.cs').write_bytes(b'// changed raw source\n')
            with self.assertRaisesRegex(ValueError,'managed-stage-raw-drift'):
                selected.stage_raw_generation(generated,generated,check=True)
            evidence=Path(temporary)/'evidence';evidence.mkdir()
            retain_managed_stage_failure(compiled,evidence)
            self.assertEqual((evidence/'probe-raw-inputs/ActualExtra.cs').read_bytes(),b'// actual raw source\n')
            self.assertFalse((evidence/'probe-inputs.json').exists())

    def test_event_parser_rejects_gap_duplicate_summary_overflow_and_cause_credit(self):
        import json
        from tools.dotnet_root_return import managed_stage_observations
        from tools.phase2_operator_process import WorkflowError
        component='sha256:'+'a'*64
        rows=[{'profile':'dotnet-managed-stage-diagnostic-v1','component':component,'mode':mode,
            'terminalOutcome':outcome,'claims':1,'originalCauseQualified':False,'originalSixCallsQualified':False,
            'fullAc7Qualified':False,'physicalRetirementQualified':False,'nativeAccountingQualified':False}
            for mode,outcome in ((3,'succeeded'),(9,'guest-trap'))]
        stdout=''.join('DOTNET_MANAGED_STAGE_CALL '+json.dumps(row)+'\n' for row in rows).encode()
        events=[]
        for slot in (0,1):
            events += [('DOTNET_MANAGED_STAGE ',{'slot':slot,'sequence':1,'stage':1,'guard':0}),
                ('DOTNET_MANAGED_STAGE_SUMMARY ',{'slot':slot,'attempts':1,'overflow':False,
                    'transportFailed':False,'inconclusive':False})]
        def encode(records):return ''.join(prefix+json.dumps(row)+'\n' for prefix,row in records).encode()
        actual=managed_stage_observations(stdout,encode(events),component)
        self.assertFalse(actual['originalCauseQualified'])
        for changed in (events[:-1],events+[events[-1]],
                [(prefix,dict(row,sequence=2) if prefix=='DOTNET_MANAGED_STAGE ' else row) for prefix,row in events],
                [(prefix,dict(row,overflow=True,attempts=17,inconclusive=True) if prefix.endswith('SUMMARY ') else row) for prefix,row in events]):
            with self.assertRaises(WorkflowError):managed_stage_observations(stdout,encode(changed),component)
        rows[1]['originalCauseQualified']=True
        bad=''.join('DOTNET_MANAGED_STAGE_CALL '+json.dumps(row)+'\n' for row in rows).encode()
        with self.assertRaises(WorkflowError):managed_stage_observations(bad,encode(events),component)


if __name__ == '__main__':
    unittest.main()
