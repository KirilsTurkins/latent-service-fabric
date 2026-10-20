"""Source/controller controls; no signed SPI or cross-tenant pass is inferred."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import java_http_spi_fixture as fixture, java_http_spi_node as node
from tools import qualify_java_http_spi as campaign
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT, read_json, digest


def response(mode, selected):
    return {'processReaped': True, 'exitCode': 0, 'decoded': [node.expected(mode)],
        'response': {'outcomeKnown': True, 'data': {'resolvedRevision': selected,
            'consumption': {'cpuFuel': '17', 'outboundRequests': '1'}}}}


class JavaHttpPublicSpi(unittest.TestCase):
    def test_normal_project_captures_same_public_closure_without_changing_default_programme(self):
        before = {name: (ROOT/name).read_bytes() for name in (
            'tools/fixtures/java-http-phases/Capsule.java', 'tools/java_http_phase_node.py',
            'sdk/java-guest/client/dev/latent/guest/client/Connection.java')}
        with tempfile.TemporaryDirectory() as temporary:
            app = fixture.project(Path(temporary)/'source')
            self.assertEqual((app/'src/dev/latent/app/Capsule.java').read_bytes(), (ROOT/fixture.SOURCE).read_bytes())
            self.assertEqual((app/'wit/world.wit').read_bytes(), (ROOT/fixture.WORLD).read_bytes())
            lock = read_json(app/'sdk-lock.json')
            self.assertEqual(lock['template'], {'name': 'java-http-optional-public-spi',
                'sourceDigest': digest((ROOT/fixture.SOURCE).read_bytes()),
                'witDigest': digest((ROOT/fixture.WORLD).read_bytes())})
            for name, identity in lock['sdk'].items():
                self.assertEqual(digest((app/'vendor/lsf'/name).read_bytes()), identity['digest'])
            dependencies = read_json(app/'java-dependencies.json')['dependencies']
            self.assertEqual([(row['group'], row['name'], row['version']) for row in dependencies],
                [('com.goebl', 'david-webb', '1.3.0'), ('com.github.kevinsawicki', 'http-request', '6.0')])
        self.assertEqual(before, {name: (ROOT/name).read_bytes() for name in before})

    def test_public_factory_delegates_only_to_ordinary_url_connection_and_fresh_default_is_separate(self):
        source = (ROOT/fixture.SOURCE).read_text()
        for required in ('implements HttpRequest.ConnectionFactory',
                'create(URL target)', 'create(URL target, Proxy proxy)', 'target.openConnection()',
                'HttpRequest.setConnectionFactory(null)', 'request.disconnect()',
                'if (which != 1) HttpRequest.setConnectionFactory', '++invocations', 'factoryCalls++'):
            self.assertIn(required, source)
        for forbidden in ('LatentHttp', 'new Thread(', 'Thread.sleep(', 'registerProvider', 'Bindings.Latent'):
            self.assertNotIn(forbidden, source)
        self.assertEqual(len(fixture.CASES), 6)
        self.assertEqual([mode for mode, _ in fixture.CASES], [0, 1, 2, 3, 4, 1])
        self.assertIs(node.configuration, __import__('tools.java_http_phase_node', fromlist=['configuration']).configuration)

    def test_every_result_requires_real_guest_work_exact_factory_static_state_and_revision(self):
        selected = {'revisionId': 'signed:test'}
        for mode in range(5):
            good = response(mode, selected);node.validate_result(good, mode, selected)
            for field, invalid in (('processReaped', False), ('decoded', ['2:spi:200:7:1'])):
                changed = response(mode, selected);changed[field] = invalid
                with self.subTest(mode=mode, field=field), self.assertRaises(WorkflowError):
                    node.validate_result(changed, mode, selected)
            for key, invalid in (('cpuFuel', '0'), ('outboundRequests', '2')):
                changed = response(mode, selected);changed['response']['data']['consumption'][key] = invalid
                with self.subTest(mode=mode, key=key), self.assertRaises(WorkflowError):
                    node.validate_result(changed, mode, selected)
            changed = response(mode, selected);changed['response']['data']['resolvedRevision'] = {}
            with self.assertRaises(WorkflowError): node.validate_result(changed, mode, selected)
        for mode in (True, None, -1, 5, '0'):
            with self.subTest(mode=mode), self.assertRaises((WorkflowError, ValueError)): node.expected(mode)

    def test_failed_invocation_preserves_original_exception_while_attempting_process_close(self):
        original = RuntimeError('original-public-fixture-failure')
        process = Mock();process.owner.exited.return_value = True;process.close.side_effect = RuntimeError('cleanup')
        peer = Mock();peer.origin.return_value = {'host': '127.0.0.1', 'port': 80}
        peer.observation.return_value = {'requests': []}
        client = SimpleNamespace(deadline=1000)
        with patch.object(node, 'selected_revision', return_value={}), \
                patch.object(node, 'start_call', return_value=process), \
                patch.object(node, 'finish_call', side_effect=original):
            with self.assertRaises(RuntimeError) as error: node.invoke(client, Mock(), {}, peer, Mock(), 0, 'failed')
        self.assertIs(error.exception, original);process.close.assert_called_once()

    def test_unknown_or_boolean_numeric_consumption_cannot_be_qualification(self):
        selected = {'revisionId': 'signed:test'}
        for key in ('cpuFuel', 'outboundRequests'):
            for invalid in (True, 1, '', '-1', '1.0', '9'*21):
                changed = response(0, selected);changed['response']['data']['consumption'][key] = invalid
                with self.subTest(key=key, invalid=invalid), self.assertRaises(WorkflowError):
                    node.validate_result(changed, 0, selected)

    def test_absent_new_native_authenticator_refuses_before_any_product_or_build(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(campaign, 'ROOT', Path(temporary)), \
                patch.object(campaign, 'execute') as execute:
            with self.assertRaisesRegex(WorkflowError, 'authenticated-nominal-products-helper-required'):
                campaign.run(Path(temporary)/'output', Path(temporary)/'prepared', Path(temporary)/'wasi')
            execute.assert_not_called()

    def test_failed_build_keeps_closed_stage_and_original_exception_without_raw_message(self):
        original = RuntimeError('private-detail-must-not-be-copied')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);product = root/'product';product.write_bytes(b'public fixture')
            commands = SimpleNamespace(deadline=1000)
            with patch.object(campaign, 'MATERIALS', (fixture.SOURCE,)), \
                    patch.object(campaign, 'project', side_effect=original):
                with self.assertRaises(RuntimeError) as error:
                    campaign.execute(commands, {'latent': product}, root/'wasi', root/'output')
            self.assertIs(error.exception, original)
            failed = read_json(root/'output/FAILED.json')
            self.assertEqual(failed, {'status': 'failed', 'stage': 'project',
                'defaultClientQualification': False, 'sameNodeCrossTenantHttpQualified': False})
            self.assertNotIn(str(original), (root/'output/FAILED.json').read_text())


class JavaSpiComponentIdentityFence(unittest.TestCase):
    def test_shared_producer_bound_identity_guard_runs_before_signed_spi_execution(self):
        import time
        from tools.rust_capsule_project import write_json
        original = RuntimeError('preserved-shared-component-refusal')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);artifact = root/'artifact';artifact.mkdir()
            product = root/'product';product.write_bytes(b'public fixture')
            write_json(artifact/'java-classpath.json', {'artifacts': [
                {'id': 'fixture', 'originalDigest': 'sha256:'+'1'*64}]})
            binaries = {name: product for name in ('latent', 'latentd', 'capsule_authoring',
                'capsule_contracts', 'package')}
            commands = SimpleNamespace(deadline=time.monotonic()+30)
            with patch.object(campaign, 'MATERIALS', ()), \
                    patch.object(campaign, 'project', return_value=root/'app'), \
                    patch.object(campaign, 'resolve_review', return_value={'originalJars': {
                        'fixture': {'digest': 'sha256:'+'1'*64}}}), \
                    patch.object(campaign, 'compiler_cache', return_value=root/'cache'), \
                    patch.object(campaign, 'build', return_value=artifact), \
                    patch.object(campaign, 'component_profile', side_effect=original) as identity, \
                    patch.object(campaign, 'node_controls') as node:
                with self.assertRaises(RuntimeError) as caught:
                    campaign.execute(commands, binaries, root/'wasi', root/'output')
            self.assertIs(caught.exception, original)
            identity.assert_called_once_with(artifact, 'java-spi-selected-profile-drift')
            node.assert_not_called()
            failed = read_json(root/'output/FAILED.json')
            self.assertEqual(failed['stage'], 'offline-optional-spi-component')
            self.assertFalse(failed['defaultClientQualification'])


class JavaSpiManualWorkflow(unittest.TestCase):
    def test_explicit_false_selector_restores_entire_baseline_and_duplicates_only_same_spi_job(self):
        import subprocess
        import yaml
        name = '.github/workflows/java-guest-feasibility.yml'
        old = yaml.safe_load(subprocess.check_output(['git', 'show',
            'aa56bdebad8c12f20acce4ec4ecfeca73cf554be:'+name], cwd=ROOT, text=True))
        selected = yaml.safe_load((ROOT/name).read_text())
        flag = selected[True]['workflow_dispatch']['inputs'].pop('java_http_spi')
        self.assertEqual(flag['type'], 'boolean');self.assertIs(flag['default'], False)
        job = selected['jobs'].pop('http-public-spi')
        focused = yaml.safe_load((ROOT/'.github/workflows/java-http-fiber-lifecycle.yml').read_text())
        self.assertEqual(job, focused['jobs']['http-public-spi'])
        fetch=next(i for i,step in enumerate(job['steps']) if step.get('name')=='Fetch exact original workflow baseline before SPI preservation controls')
        controls=next(i for i,step in enumerate(job['steps']) if step.get('name')=='Check optional SPI authority, original exception and native receipt controls')
        self.assertLess(fetch,controls)
        self.assertEqual(job['steps'][fetch]['run'],'git fetch --no-tags --depth=1 origin aa56bdebad8c12f20acce4ec4ecfeca73cf554be')
        self.assertEqual(selected['jobs']['compiler-component'].pop('if'),
            "${{ github.event_name != 'workflow_dispatch' || !inputs.java_http_spi }}")
        self.assertEqual(selected['jobs']['dependency-ingestion']['if'],
            "${{ (github.event_name != 'workflow_dispatch' || !inputs.qualify-scratch-refusals) && (github.event_name != 'workflow_dispatch' || !inputs.java_http_spi) }}")
        selected['jobs']['dependency-ingestion']['if'] = old['jobs']['dependency-ingestion']['if']
        self.assertEqual(selected, old)
