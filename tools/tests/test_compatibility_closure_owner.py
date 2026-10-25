"""Source/filesystem/controller boundaries only; no compiler or guest runs."""
from pathlib import Path
import copy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import application_dependencies as dependencies
from tools import compatibility_api_fixture as fixture
from tools import compatibility_closure_node as node
from tools import guest_compatibility as compatibility, guest_compatibility_context as context
from tools import guest_compatibility_outcomes as outcomes
from tools import qualify_compatibility_closure as owner
from tools.dev_workflow.common import digest
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import snapshot


class CompatibilityClosureOwner(unittest.TestCase):
    def test_fixed_public_go_body_is_bounded_and_observer_is_private_default_none(self):
        from tools import guest_compiler_capture, go_capsule_build
        source = fixture.SOURCES['go']
        files = {source: fixture.application_source('go', reached=False)}
        value = {'language': 'go', 'reached': False, 'rootFunction': fixture.ROOTS['go'],
            'rootSource': source, 'sourceTargetSpelling': fixture.CALLEES['go'],
            'targetFunction': fixture.PRIMARY['go'] + '.Probe'}
        captured = guest_compiler_capture.Capture(files, 'go')
        query = next(row for row in captured.queries if row['root'] == value['rootFunction'])
        raw = b'compatibilityRoot func() int32\nb1:\n(?) v1 = I64Const <int32> [0]\nRet v1\n'
        captured.retain(query['id'], raw)
        with tempfile.TemporaryDirectory() as temporary, patch.object(subprocess, 'Popen', side_effect=AssertionError('no-process')):
            root = Path(temporary)
            result = owner.selected_go_body(captured, value, files, root)
            self.assertEqual((root / 'go-selected-body.ssa').read_bytes(), raw)
            self.assertEqual(result['raw'], {'bytes': len(raw), 'sha256': digest(raw)})
            self.assertFalse(result['qualificationClaimed'])
            self.assertEqual(result['runtimeExecution'], 'not-observed')
            from tools import compatibility_closure_matrix as matrix
            (root / 'unselected.ssa').write_bytes(b'not selected')
            admitted = matrix.retain(root, root.parent / (root.name + '-public'))
            self.assertEqual(set(admitted['files']), {'go-selected-body.ssa'})
            import shutil
            shutil.rmtree(root.parent / (root.name + '-public'))
            for invalid in (b'x' * 4097, b'x' * 257, b'\0', b'x\n' * 65):
                captured.raw[query['id']] = invalid
                with self.subTest(invalid=len(invalid)), self.assertRaises(ValueError):
                    owner.selected_go_body(captured, value, files, root)
            with self.assertRaisesRegex(ValueError, 'private-compiler-observer'):
                go_capsule_build.build(root / 'absent', root / 'uncreated', root / 'contracts', None,
                    'https://github.com/example/test', _compiler_observer=1)
            self.assertFalse((root / 'uncreated').exists())
        from inspect import signature
        self.assertIsNone(signature(go_capsule_build.build).parameters['_compiler_observer'].default)
        with patch.object(go_capsule_build, 'build', return_value=Path('original')) as build:
            owner.normal_build('go', Path('app'), Path('out'), {'capsule_contracts': Path('contracts'),
                'package': Path('packager')}, Path('tools'), owner.time.monotonic() + 60)
            self.assertNotIn('_compiler_observer', build.call_args.kwargs)

    def test_native_client_data_migration_is_exact_and_never_relabels_original_materials(self):
        products = owner.products
        paths = tuple(products.NON_COMPILED_DATA)
        payloads = {name: {'before': b'original-' + str(index).encode(),
            'after': b'original-' + str(index).encode() + b'-ten-fixed-constants'} for index, name in enumerate(paths)}
        identities = {name: {version: {'bytes': len(raw), 'sha256': digest(raw)}
            for version, raw in values.items()} for name, values in payloads.items()}
        inputs = {'native': dict(products.ORIGINAL_SOURCE), 'materials': {
            paths[1]: identities[paths[1]]['before']}}
        unchanged = copy.deepcopy(inputs)
        with tempfile.TemporaryDirectory() as directory, patch.object(products, 'NON_COMPILED_DATA', identities):
            root = Path(directory)
            for version, source in (('before', products.ORIGINAL_SOURCE), ('after', products.CLIENT_DATA_SOURCE)):
                for name in paths:
                    path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payloads[name][version])
                with patch.object(products, 'source_identity', return_value=source):
                    result = products.current_source(inputs, root=root)
                    self.assertEqual(result['currentSource'], source)
                    self.assertEqual(result['originalProducerSource'], products.ORIGINAL_SOURCE)
                    self.assertFalse(result['sourceRelabeled'])
                    (root / paths[1]).write_bytes(b'unknown descriptor')
                    with self.assertRaisesRegex(WorkflowError, 'unreviewed-client-data'):
                        products.current_source(inputs, root=root)
                (root / paths[1]).write_bytes(payloads[paths[1]][version])
            with patch.object(products, 'source_identity', return_value={**products.CLIENT_DATA_SOURCE, 'bytes': 1}):
                with self.assertRaisesRegex(WorkflowError, 'unreviewed-current-source'):
                    products.current_source(inputs, root=root)
            with patch.object(products, 'source_identity', return_value=products.CLIENT_DATA_SOURCE):
                changed = copy.deepcopy(inputs)
                changed['materials'][paths[1]] = identities[paths[1]]['after']
                with self.assertRaisesRegex(WorkflowError, 'original-material-not-rebound'):
                    products.current_source(changed, root=root)
            self.assertEqual(inputs, unchanged)

    def test_actual_normal_C_capture_is_in_process_and_counterfactual_keeps_accepted_library_identity(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
                subprocess, 'Popen', side_effect=AssertionError('no-native-tool-or-outer-Python')):
            value = fixture.prepare(Path(temporary) / 'fixture', 'c')
            captured = owner.capture('c', value)
            self.assertEqual([row['operation'] for row in captured['normalMainCalls']],
                             ['add', 'resolve', 'review-lock', 'dependencies'])
            app = Path(value['projectPath']); before = snapshot(app)
            accepted = dependencies.verify_inputs(app, 'c')
            self.assertIsNotNone(accepted)
            changed = fixture.counterfactual(value)
            after = snapshot(app)
            self.assertEqual([name for name in before if before[name] != after[name]], [value['rootSource']])
            self.assertEqual(dependencies.verify_inputs(app, 'c').identity, accepted.identity)
            self.assertEqual(changed['acceptedInputIdentity'], accepted.identity)

    def test_unqualified_native_tuple_refuses_before_output_or_acquisition(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(owner.sys, 'platform', 'linux'), \
                patch.object(owner.products, 'QUALIFIED', None), \
                patch.object(subprocess, 'Popen', side_effect=AssertionError('no-process')):
            root = Path(temporary)
            with self.assertRaisesRegex(WorkflowError, 'native-prerequisite-unqualified'):
                owner.qualify('c', root / 'native', root / 'tools', root / 'output')
            self.assertEqual(list(root.iterdir()), [])

    def test_completed_capture_after_allowance_cannot_start_the_compiler_phase(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (patch.object(owner.fixtures, 'prepare', return_value={'projectPath': str(root)}),
                    patch.object(owner, 'capture', return_value={'sourceOnlyTest': True}),
                    patch.object(owner.time, 'monotonic', side_effect=(100.0, 701.0)),
                    patch.object(owner.application_dependencies, 'verify_inputs') as verified,
                    patch.object(owner, 'normal_build') as compiler,
                    self.assertRaisesRegex(ValueError, 'capture-allowance-consumed-no-compiler-start')):
                owner.capture_phase('c', root, root)
            verified.assert_not_called(); compiler.assert_not_called()

    def test_original_queue_operation_fact_never_replaces_unrelated_terminal_cause(self):
        component = digest(b'component'); revision = {'releaseDigest': component}
        report = compatibility.report('go', digest(b'original-source'), component, 'lsf-host-abi-phase3-v5', [], [])
        captured = outcomes.Capture(digest(b'frontend'), component, context.create(report, [], {'state': 'absent'}))
        response = {'category': 'platform-failure', 'outcomeKnown': True,
            'error': {'code': 'guest-trap', 'details': []}, 'data': {'resolvedRevision': revision}}
        row = {'exitCode': 4, 'response': response, 'activation': 'same-original-case'}
        captured.observe(row['activation'], response, True, expected_revision=revision)
        tree = {'category': 'success', 'outcomeKnown': True, 'data': {'schemaVersion': 1,
            'historyAvailable': True, 'nodes': [{'activationId': 'original-id', 'targetService': 'my-greeting',
                'diagnosticIsTerminal': False, 'diagnostic': {'schemaVersion': 1, 'stage': 5, 'reason': 18,
                    'configuredBound': '8', 'calculatedRequirement': '9'}}]}}
        captured.observe_node(row['activation'], tree, 'original-id', 'my-greeting')
        observed = node.operation_refusal(row, 'queue-8', captured.snapshot())
        self.assertEqual(observed['observedOperationResource'], 'queues')
        self.assertEqual(observed['terminalCause'], 'unknown')
        self.assertEqual(observed['implementationBinding'], 'unavailable')
        self.assertFalse(observed['apiAttributionFromManagementFact'])
        changed = copy.deepcopy(tree); changed['data']['nodes'][0]['diagnostic']['calculatedRequirement'] = '10'
        captured.observe_node(row['activation'], changed, 'original-id', 'my-greeting')
        with self.assertRaisesRegex(ValueError, 'actual-original-resource-operation'):
            node.operation_refusal(row, 'queue-8', captured.snapshot())


if __name__ == '__main__': unittest.main()
