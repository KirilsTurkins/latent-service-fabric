"""Ownership and exact-selection controls for the signed native CORS campaign."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from tools.phase2_operator_process import WorkflowError

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('native_cors_qualification', ROOT / 'tools/cross-origin/native_qualify.py')
CAMPAIGN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAMPAIGN)


class NativeCrossOriginWorkflow(unittest.TestCase):
    def test_native_lint_uses_the_maintained_strict_owner_recipe(self):
        from tools import ci_cargo, ci_lane_inventory
        workflow = ci_lane_inventory.workflow_model((ROOT / '.github/workflows/cross-origin-assets.yml').read_text())
        steps = workflow['jobs']['native']['steps']
        lint = next(step for step in steps if step.get('name') ==
                    'Check maintained formatting and strict native lint')
        self.assertEqual(lint['run'].splitlines(), [
            'python3 tools/ci_cargo.py run format',
            'python3 tools/ci_cargo.py run clippy'])
        self.assertNotIn('continue-on-error', lint)
        commands = [invocation.command() for invocation in ci_cargo.RECIPES['clippy']]
        self.assertEqual(commands[0], ['cargo', 'clippy', '--workspace',
            '--all-targets', '--all-features', '--locked'])
        strict = commands[1]
        self.assertIn('latentd', strict)
        self.assertIn('--all-targets', strict)
        self.assertIn('--all-features', strict)
        self.assertIn('--no-deps', strict)
        self.assertEqual(strict[-3:], ['--', '-D', 'warnings'])

    def test_retained_green_run_binds_complete_native_receipts_and_cleanup(self):
        import gzip
        import hashlib
        directory = ROOT / 'docs/testing/evidence'
        name = 'cross-origin-native-2026-10-30.1817de8.json'
        manifest = json.loads((directory / name).read_bytes())
        self.assertEqual((manifest['runId'], manifest['jobId'], manifest['artifactId']),
                         (41058876134, 124073873211, 12978249187))
        self.assertEqual(manifest['headCommit'], '1817de81d59cfdd1811dab3b9ce0741de8f01b5b')
        self.assertEqual(manifest['testedCommit'], '0e6fc761b8f6751a30e4d8a6301f75495db66315')
        self.assertIs(manifest['workflowPassed'], True)
        self.assertIs(manifest['qualificationPassed'], True)
        receipts = {}
        for source, record in manifest['receipts'].items():
            packed = (directory / record['file']).read_bytes()
            self.assertEqual(hashlib.sha256(packed).hexdigest(), record['gzipSha256'])
            raw = gzip.decompress(packed)
            self.assertEqual(len(raw), record['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record['sha256'])
            receipts[source] = json.loads(raw)
        qualification, browser = receipts['qualification.json'], receipts['browser-network.json']
        for receipt in (qualification, browser):
            self.assertIs(receipt['passed'], True)
            self.assertIs(receipt['nativeRuntimeQualified'], True)
            self.assertIs(receipt['productionTlsQualified'], False)
            self.assertIs(receipt['testIdentityOnly'], True)
        self.assertEqual(tuple(phase['stage'] for phase in qualification['phases']), CAMPAIGN.STAGES)
        self.assertTrue(all(phase['passed'] for phase in qualification['phases']))
        self.assertEqual(qualification['networkReceiptSha256'],
                         manifest['receipts']['browser-network.json']['sha256'])
        self.assertEqual(qualification['browserCases'], len(browser['cases']))
        self.assertEqual(len(browser['cases']), 19)
        self.assertEqual((len(browser['observations']), len(browser['wireObservations'])), (73, 13))
        self.assertEqual(len(qualification['shutdown']), 6)
        for stop in qualification['shutdown']:
            self.assertIs(stop['reaped'], True)
            self.assertIs(stop['record']['clean'], True)
            report = stop['record']['report']
            self.assertEqual((report['activeActivations'], report['activeLeases']), (0, 0))
            self.assertEqual(report['http']['assets']['activeReads'], 0)
        self.assertEqual(browser['cleanup'], 'browser-and-caller-listener-closed')
        self.assertEqual(qualification['cleanup'], 'owned-processes-closed-and-fixture-removed')
        guide = (ROOT / 'docs/testing/cross-origin-static-assets.md').read_text()
        self.assertIn(name, guide)
        for record in manifest['receipts'].values():
            self.assertIn(record['file'], guide)

    def test_complete_lifecycle_has_no_optional_or_skipped_stage(self):
        self.assertEqual(CAMPAIGN.STAGES, ('default', 'allowed', 'removed', 'restored',
            'new-ungranted', 'new-opted-in', 'expiring', 'expired', 'renewed', 'revoked', 'restart-revoked'))

    def test_http_exchanges_fit_the_unchanged_node_reservation_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, node = root / 'fixture', root / 'node'
            fixture.mkdir(); node.mkdir()
            (fixture / 'policy.json').write_text('{}')
            config = json.loads(CAMPAIGN.configure_node(node, fixture, 'tests').read_bytes())
            limits = CAMPAIGN.ingress_configuration(fixture, 'assets.lsf.localhost:8443',
                'foreign.lsf.localhost:8443', 8443)['limits']
            reservations = sum(cell['capacity'] + cell['queueCapacity'] for cell in config['cells'])
            self.assertEqual(reservations, 3)
            self.assertEqual(limits['maximumExchanges'], 2)
            self.assertLessEqual(limits['maximumExchanges'], reservations)
            self.assertEqual(limits['maximumConnections'], 16)

    def test_messages_are_complete_private_and_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'request.json'
            CAMPAIGN.publish_message(target, {'stage': 'removed'})
            self.assertEqual(json.loads(target.read_bytes()), {'stage': 'removed'})
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                CAMPAIGN.publish_message(target, {'stage': 'allowed'})
            self.assertEqual(json.loads(target.read_bytes()), {'stage': 'removed'})
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_message_bound_does_not_publish_a_partial_request(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'request.json'
            with self.assertRaises(WorkflowError):
                CAMPAIGN.publish_message(target, {'stage': 'x' * 262144})
            self.assertFalse(target.exists())

    def test_browser_exit_before_receipt_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            client = SimpleNamespace(deadline=float('inf'), cancellation=Mock(), node=None)
            browser = SimpleNamespace(drain=Mock(), owner=SimpleNamespace(exited=lambda: True))
            with self.assertRaisesRegex(WorkflowError, 'browser-exited'):
                CAMPAIGN.wait_file(client, browser, Path(directory) / 'absent.json')

    def test_existing_receipt_is_bounded_without_polling(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'response.json'
            CAMPAIGN.publish_message(target, {'stage': 'revoked', 'passed': True})
            self.assertEqual(CAMPAIGN.wait_file(SimpleNamespace(deadline=float('inf')), None, target), {'stage': 'revoked', 'passed': True})

    def test_route_apply_uses_exact_publication_method_and_both_cas_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            publication = 'publication:sha256:' + 'ab' * 32
            receipt = {'target': {'kind': 'static-web', 'publication': {'id': publication, 'tenant': 'tests'}}}
            client = SimpleNamespace(directory=Path(directory), calls=12, call=Mock(side_effect=[
                {'data': {'trigger': {'generation': '7'}, 'stateVersion': '11'}},
                {'outcomeKnown': True, 'data': {'receipt': receipt}}]))
            self.assertEqual(CAMPAIGN.apply(client, publication, 'assets.lsf.localhost:8443', 'HEAD'), receipt)
            applied = client.call.call_args_list[1].args
            self.assertEqual(applied[-4:], ('--expected-generation', '7', '--expected-state-version', '11'))
            spec = json.loads(applied[2].read_bytes())['spec']
            self.assertEqual(spec['target'], {'kind': 'static-web', 'publication': publication})
            self.assertEqual(spec['configuration']['method'], 'HEAD')
            self.assertEqual(spec['configuration']['scheme'], 'https')

    def test_foreign_or_uncertain_mutation_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as directory:
            publication = 'publication:sha256:' + 'ab' * 32
            client = SimpleNamespace(directory=Path(directory), calls=12, call=Mock(side_effect=[
                {'data': {'trigger': None, 'stateVersion': '1'}},
                {'outcomeKnown': False, 'data': {'receipt': {'target': {'kind': 'static-web',
                 'publication': {'id': publication, 'tenant': 'foreign'}}}}}]))
            with self.assertRaisesRegex(WorkflowError, 'exact-static-route'):
                CAMPAIGN.apply(client, publication, 'assets.lsf.localhost:8443', 'GET')


if __name__ == '__main__':
    unittest.main()
