"""Closed report routing controls; compiler execution is a separate owner."""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools import run_java_early_http_qualification as runner
from tools.phase2_operator_process import read_json


ROOT = Path(__file__).resolve().parents[2]
NEW_PACKET = 'docs/testing/evidence/java-early-http-reconstructed-capture-2026-10-15.json'
REBUILT_PACKET = 'docs/testing/evidence/java-early-http-rebuilt-capture-2026-10-13.json'
HISTORICAL_PACKET = 'docs/development/phase4-handoffs/2026-10-12/pr970-early-http-compiler-evidence.json'
NEW_MODE = 'fixture-sign-reconstructed-early-http-input'
NEW_REPORT = 'sha256:bd40833f7f527f42d5f4a088cbcc093bdcd023060e91fb948f2505f8aaf5d2b7'


class ReconstructedEarlyControls(unittest.TestCase):
    def setUp(self):
        self.packet = read_json(ROOT / NEW_PACKET)
        self.rebuilt = read_json(ROOT / REBUILT_PACKET)
        self.item = SimpleNamespace(directory=Path('/closed-capture'),
            name='forbidden-http-before-stage', compiler_source=self.packet['sourceCommit'],
            component_digest=self.packet['materials']['component']['sha256'])
        self.item.observation = lambda: {'variant': self.item.name,
            'compilerSource': self.item.compiler_source, 'componentDigest': self.item.component_digest}

    @contextmanager
    def report_identity(self, report, packet=None):
        original = runner.read_json

        def public_packet(path):
            if Path(path) == ROOT / NEW_PACKET:
                return copy.deepcopy(self.packet if packet is None else packet)
            return original(path)

        # These controls mock only report identities. The full authentic material
        # loader and native signing fixture have their own retained executions.
        with patch.object(runner, 'read_file', return_value=b'ROUTING-ONLY-MOCK-REPORT'), \
             patch.object(runner.inputs, 'digest', return_value=report), \
             patch.object(runner, 'read_json', side_effect=public_packet):
            yield

    def test_public_packet_changes_only_the_actual_report_and_preserves_material_and_limits(self):
        self.assertEqual(hashlib.sha256((ROOT / NEW_PACKET).read_bytes()).hexdigest(),
                         'a2d37eb966f631a8614650839fcd95b3588855a71cc8243d42b04ab977eb1798')
        self.assertEqual(self.packet['sourceCommit'], '47e4e60778d7fdd033d5f1d6c05595752713c971')
        self.assertEqual(self.packet['materials']['report'], {'sha256': NEW_REPORT, 'bytes': 20952})
        self.assertEqual(set(self.packet['materials']), set(self.rebuilt['materials']))
        for name, value in self.rebuilt['materials'].items():
            if name != 'report':
                self.assertEqual(self.packet['materials'][name], value, name)
        for name in ('sourceTree', 'variant', 'actualImports', 'limits'):
            self.assertEqual(self.packet[name], self.rebuilt[name], name)
        self.assertIs(self.packet['reportIsNew'], True)
        self.assertIs(self.packet['compilerClosureByteExactHistorical'], True)
        self.assertIs(self.packet['reportAndCompilerClosureAreNew'], False)
        for name in ('signedNodeExecutionQualified', 'immediateHttpDenialQualified',
                     'postStageRollbackQualified', 'productionApproval', 'issueClosure'):
            self.assertIs(self.packet[name], False, name)

    def test_exact_new_report_uses_only_the_fixed_reconstructed_signer(self):
        with self.report_identity(NEW_REPORT):
            self.assertEqual(runner.signing_mode(self.item), NEW_MODE)

    def test_original_d7_report_keeps_its_rebuilt_signer(self):
        with self.report_identity(self.rebuilt['materials']['report']['sha256']):
            self.assertEqual(runner.signing_mode(self.item), 'fixture-sign-rebuilt-early-http-input')

    def test_historical_report_keeps_its_original_signer(self):
        historical = read_json(ROOT / HISTORICAL_PACKET)
        with self.report_identity(historical['materials']['report']['sha256']):
            self.assertEqual(runner.signing_mode(self.item), 'fixture-sign-early-http-input')

    def test_new_report_refuses_a_different_compiler_source(self):
        self.item.compiler_source = 'f' * 40
        with self.report_identity(NEW_REPORT), self.assertRaisesRegex(
                ValueError, 'reconstructed-early-captured-component-and-source'):
            runner.signing_mode(self.item)

    def test_new_report_refuses_a_different_component(self):
        self.item.component_digest = 'sha256:' + 'f' * 64
        with self.report_identity(NEW_REPORT), self.assertRaisesRegex(
                ValueError, 'reconstructed-early-captured-component-and-source'):
            runner.signing_mode(self.item)

    def test_mixed_new_report_and_old_public_packet_are_rejected(self):
        with self.report_identity(NEW_REPORT, self.rebuilt), self.assertRaisesRegex(
                ValueError, 'reconstructed-early-captured-component-and-source'):
            runner.signing_mode(self.item)

    def test_missing_new_packet_never_falls_back_to_an_old_signer(self):
        original = runner.read_json

        def missing(path):
            if Path(path) == ROOT / NEW_PACKET:
                raise FileNotFoundError('closed-new-packet-absent')
            return original(path)

        with self.report_identity(NEW_REPORT), patch.object(runner, 'read_json', side_effect=missing), \
             self.assertRaisesRegex(FileNotFoundError, 'closed-new-packet-absent'):
            runner.signing_mode(self.item)

    def test_incomplete_new_packet_cannot_authorize_the_new_report(self):
        for name in ('sourceCommit', 'report', 'component'):
            with self.subTest(field=name):
                packet = copy.deepcopy(self.packet)
                if name == 'sourceCommit':
                    del packet[name]
                else:
                    del packet['materials'][name]
                with self.report_identity(NEW_REPORT, packet), self.assertRaises(KeyError):
                    runner.signing_mode(self.item)

    def test_identical_component_with_an_unmatched_report_cannot_select_new_mode(self):
        unknown = 'sha256:' + hashlib.sha256(b'UNREVIEWED-REPORT').hexdigest()
        with self.report_identity(unknown):
            self.assertEqual(runner.signing_mode(self.item), 'fixture-sign-early-http-input')

    def test_collector_identity_adds_the_exact_packet_and_preserves_old_prefix(self):
        self.assertEqual(runner.EXTRA_COLLECTORS[:-1], (
            'tools/run_java_early_http_qualification.py',
            'tools/java_transaction_qualification/early_http_inputs.py',
            'tools/java_transaction_qualification/early_http_campaign.py', REBUILT_PACKET))
        self.assertEqual(runner.EXTRA_COLLECTORS[-1], NEW_PACKET)
        identity = runner.collector_identity()
        self.assertEqual(identity[NEW_PACKET], 'sha256:' +
                         hashlib.sha256((ROOT / NEW_PACKET).read_bytes()).hexdigest())
        self.assertIn(REBUILT_PACKET, identity)

    def test_real_package_path_forwards_new_mode_once_and_never_signs_refused_identity(self):
        args = SimpleNamespace(contracts_tool=Path('/not-executed/contracts'),
                               signer=Path('/not-executed/signer'))
        calls = []
        item = self.item

        class Commands:
            def __init__(self, output, *_args, **_kwargs):
                self.output, self.records = output, []

            def run(self, stage, *argv):
                calls.append((stage, argv))
                signed = self.output / 'signed'
                signed.mkdir()
                (signed / 'release-set.json').write_text(json.dumps({
                    'schemaVersion': 'latent.component.signing-fixture.v1',
                    'trust': 'ephemeral-native-package-test-only',
                    'releases': [{'componentDigest': item.component_digest,
                                  'name': 'java718-' + item.name}]}), encoding='utf-8')

        with tempfile.TemporaryDirectory() as temporary, self.report_identity(NEW_REPORT), \
             patch.object(runner, 'Commands', Commands), \
             patch.object(runner, 'build_environment', return_value={}), \
             patch.object(runner.packaging, 'prepare') as prepare:
            output = Path(temporary) / 'accepted'
            self.assertEqual(runner.package(args, item, output, 600), output / 'signed')
            self.assertEqual(calls, [('early-http-signing', (args.signer, NEW_MODE,
                output / 'signed', item.compiler_source, output / item.name))])
            self.assertEqual(prepare.call_count, 1)
            calls.clear()
            item.compiler_source = 'f' * 40
            with self.assertRaisesRegex(ValueError, 'reconstructed-early-captured-component-and-source'):
                runner.package(args, item, Path(temporary) / 'refused', 600)
            self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
