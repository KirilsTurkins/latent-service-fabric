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
