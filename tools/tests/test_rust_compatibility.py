"""Qualification controls model commands; signed outcomes require the hosted programme."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import application_dependencies as dependencies
from tools import guest_compatibility as compatibility
from tools import qualify_rust_compatibility as campaign
from tools import rust_compatibility_probe as fixture
from tools.build_snapshot import canonical, digest
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import create


class CapturedCompatibility(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='rust-compatibility-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = create(self.root / 'application', 'greeting')
        self.sdk = (self.project / 'sdk-lock.json').read_bytes()
        self.outside = self.root / 'outside'
        self.cargo = self.root / 'cargo-not-executed'
        self.lock = {'executableInputs': [], 'artifacts': []}
        ids = {name: name + '-native-id' for name in (fixture.PACKAGE, fixture.CALLBACK)}
        for name in ids:
            self.lock['artifacts'].append({'id': name + '/' + fixture.VERSION, 'role': 'application',
                'treeDigest': digest(name.encode()),
                'dependencies': [fixture.CALLBACK + '/' + fixture.VERSION] if name == fixture.PACKAGE else [],
                'metadata': {'package': name, 'version': fixture.VERSION, 'nativeIdDigest': digest(ids[name].encode())}})
        edge = {'pkg': ids[fixture.PACKAGE]}
        self.graph = {'root': 'root', 'nodes': [{'id': 'root', 'dependencies': [edge]}],
            'selectedResolve': {'root': 'root', 'nodes': [{'id': 'root', 'deps': [edge]}]}}
        self.graph['nodes'].extend({'id': ids[name], 'artifact': name + '/' + fixture.VERSION} for name in ids)
        self.author = self.enterContext(patch.object(fixture.authoring, 'author', return_value={'status': 'modelled'}))
        self.enterContext(patch.object(fixture.native, 'resolve', side_effect=self.capture))
        self.review = self.enterContext(patch.object(fixture.review, 'review', side_effect=self.accept))
        self.enterContext(patch.object(fixture.review, 'status', return_value={'status': 'verified'}))

    def capture(self, project, candidate, *, cargo):
        self.assertEqual((project, cargo), (self.project, self.cargo))
        for name in (fixture.PACKAGE, fixture.CALLBACK):
            self.assertTrue((self.outside / name / 'src/lib.rs').is_file())
        candidate.write_bytes(canonical(self.lock))
        (project / 'cargo-resolved.lock.json').write_bytes(canonical(self.graph))
        return self.lock

    def accept(self, project, candidate, identity):
        self.assertEqual(identity, digest(candidate.read_bytes()))
        (project / dependencies.LOCK).write_bytes(candidate.read_bytes())

    def test_normal_authoring_and_review_capture_real_transitive_sources_before_removal(self):
        value = fixture.install(self.project, self.outside, self.cargo)
        self.author.assert_called_once_with(self.project, 'add', identity=fixture.PACKAGE,
            version=fixture.VERSION, local=self.outside / fixture.PACKAGE, cargo=self.cargo)
        self.assertEqual(set(value['libraries']), {fixture.PACKAGE, fixture.CALLBACK})
        self.assertFalse(value['catalogueRegistration'])
        self.assertEqual(value['executableInputs'], [])
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.sdk)
        self.assertIn(b'outside_compatibility_library::describe(mode)', (self.project / 'src/lib.rs').read_bytes())
        self.assertFalse((self.outside / fixture.PACKAGE).exists())
        self.assertFalse((self.outside / fixture.CALLBACK).exists())
        self.review.assert_called_once()

    def test_uncaptured_transitive_callback_or_unapproved_executable_cannot_reach_review(self):
        self.lock['artifacts'][0]['dependencies'] = []
        with self.assertRaisesRegex(WorkflowError, 'transitive-callback-required'):
            fixture.install(self.project, self.outside, self.cargo)
        self.review.assert_not_called()
        self.assertTrue((self.outside / fixture.PACKAGE).is_dir())

    def test_library_that_is_not_an_application_root_edge_cannot_borrow_unrelated_presence(self):
        self.graph['nodes'][0]['dependencies'] = []
        with self.assertRaisesRegex(ValueError, 'not independently selected'):
            fixture.install(self.project, self.outside, self.cargo)
        self.review.assert_not_called()

    def test_executable_input_refuses_before_review_or_source_removal(self):
        self.lock['executableInputs'] = [{'id': 'unreviewed'}]
        with self.assertRaisesRegex(WorkflowError, 'unexpected-executable-input'):
            fixture.install(self.project, self.outside, self.cargo)
        self.review.assert_not_called()


class ActualOutcomeRequirements(unittest.TestCase):
    def setUp(self):
        self.client, self.target, self.probe = Mock(), {
            'budget': {'memoryBytes': 65536}, 'publication': 'publication:owned', 'generation': '1'}, Mock()
        self.result = {'invocations': [], 'samples': [], 'providerIdle': []}
        self.rows = []
        for index, (_mode, expected) in enumerate(fixture.CASES):
            self.rows.append({'activation': 'case-' + str(index), 'exitCode': 4 if expected is None else 0,
                'decoded': None if expected is None else [{'ok': expected}], 'processReaped': True,
                'response': {'outcomeKnown': True, 'category': 'platform-failure' if expected is None else 'success',
                    'error': {'code': 'guest-trap'} if expected is None else None,
                    'data': {'terminalState': 'guest_trap' if expected is None else 'success',
                             'resolvedRevision': {'publicationId': 'publication:owned', 'routeGeneration': '1'},
                             'consumption': {'peakMemoryBytes': '4096', 'outboundRequests': 0}}}})
        self.enterContext(patch.object(fixture, 'sample', return_value={'idle': 'modelled'}))
        self.enterContext(patch.object(fixture, 'provider_idle', return_value={'idle': 'modelled'}))

    def run_probes(self):
        with patch.object(fixture, 'call', side_effect=self.rows):
            fixture.probe(self.client, self.target, self.probe, self.result, 2)

    def test_terminal_trap_is_followed_by_a_distinct_successful_reaped_fresh_invocation(self):
        self.run_probes()
        observed = self.result['rustCompatibility']
        self.assertEqual([row['outcome'] for row in observed['cases']],
                         ['unsupported-thread', 'eliminated', 'terminal-trap', 'unsupported-thread'])
        self.assertEqual(len(self.result['samples']), 4)
        self.assertEqual(len(self.result['providerIdle']), 4)
        self.assertEqual(observed['trapCause'], 'not-inferred-from-generic-node-error')
        self.assertEqual(observed['retrySafety'], 'unknown')

    def test_wrong_thread_result_cannot_be_called_success_or_catchable_denial(self):
        self.rows[0]['decoded'] = [{'ok': 'spawned:7'}]
        with patch('tools.capsule_invocation_diagnostics.capture'), self.assertRaisesRegex(WorkflowError, 'application-result'):
            self.run_probes()
        self.assertNotIn('rustCompatibility', self.result)

    def test_a_failure_after_trap_cannot_satisfy_fresh_state(self):
        self.rows[3]['processReaped'] = False
        with self.assertRaisesRegex(WorkflowError, 'client-not-reaped'):
            self.run_probes()
        self.assertNotIn('rustCompatibility', self.result)

    def test_unexpected_outbound_activity_refuses_before_success_receipt(self):
        self.rows[0]['response']['data']['consumption']['outboundRequests'] = 1
        with self.assertRaisesRegex(WorkflowError, 'unexpected-outbound'):
            self.run_probes()

    def test_foreign_publication_or_route_generation_cannot_borrow_successful_values(self):
        self.rows[0]['response']['data']['resolvedRevision']['publicationId'] = 'publication:foreign'
        with self.assertRaisesRegex(WorkflowError, 'selected-revision-mismatch'):
            self.run_probes()

    def test_a_declared_error_or_timeout_cannot_substitute_for_the_terminal_trap(self):
        self.rows[2]['response']['error']['code'] = 'deadline-exceeded'
        with self.assertRaisesRegex(WorkflowError, 'failure-result'):
            self.run_probes()

    def test_source_bound_execution_report_does_not_infer_generic_trap_cause_or_elimination(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name)
        original = compatibility.report('rust', digest(b'source'), digest(b'component'), 'lsf-host-abi-phase3-v4', [],
            [compatibility.finding('lifecycle-unproven', 'retirement', 'not-evaluated', owner_issue=736)])
        (path / 'compatibility-report.json').write_bytes(canonical(original))
        captured = {'package': fixture.PACKAGE, 'librarySourceDigest': digest(fixture.LIBRARY.encode()),
                    'libraries': {fixture.PACKAGE: {'treeDigest': digest(b'captured-library')}}}
        self.run_probes()
        self.result['releaseSet'] = {'releases': [{'name': 'my-greeting', 'componentDigest': original['componentDigest']}]}
        value = campaign.execution_report(path, captured, self.result)
        self.assertEqual(value['componentDigest'], original['componentDigest'])
        self.assertEqual(value['status'], 'blocked')
        self.assertEqual([row['classification'] for row in value['findings']],
                         ['lifecycle-unproven', 'unsupported-reached', 'unresolved-behavior'])
        self.assertEqual(value['findings'][1]['evidence'], 'actual-component')
        self.assertNotIn('unsupported-eliminated', json.dumps(value))
        changed = copy.deepcopy(self.result)
        changed['rustCompatibility']['cases'][-1]['outcome'] = 'terminal-trap'
        with self.assertRaisesRegex(WorkflowError, 'signed-probe-outcomes-required'):
            campaign.execution_report(path, captured, changed)
        changed = copy.deepcopy(self.result)
        changed['releaseSet']['releases'][0]['componentDigest'] = digest(b'foreign-component')
        with self.assertRaisesRegex(WorkflowError, 'signed-component-mismatch'):
            campaign.execution_report(path, captured, changed)

    def test_native_reference_needs_each_exact_result_without_converting_errors(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        rustc = root / 'rustc'
        rustc.write_bytes(b'controlled compiler bytes')
        commands = Mock()
        commands.run.side_effect = [b'', b'spawned:7\n', b'native-thread:7\n', b'spawned:7\n']
        value = campaign.reference(root / 'reference', commands, rustc)
        self.assertEqual(value['profile'], 'native-reference')
        self.assertEqual(len(value['results']), 3)
        commands.run.side_effect = [b'', b'unsupported-thread\n']
        with self.assertRaisesRegex(WorkflowError, 'native-reference-result'):
            campaign.reference(root / 'wrong-reference', commands, rustc)


if __name__ == '__main__':
    unittest.main()
