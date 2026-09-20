"""Guide sequencing and real process ownership with explicitly synthetic peers.

These tests do not run latent, latentd or a Wasm component. Native guide evidence
must come from run_first_node_guide.py with independently built product binaries.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import first_node_guide as guide
from tools import run_first_node_guide as runner
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Client, WorkflowError, read_json
from tools.tests.first_node_fixtures import CLI, NODE, echo, executable


class Inputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.documents = echo(self.source)
        self.destination = self.root / 'destination'
        self.destination.mkdir()

    def test_exact_five_public_inputs_not_extra_credential_files(self):
        (self.source / 'credentials.json').write_text('NEVER-COPY-THIS')
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        result = guide.stage_echo(self.source, self.destination)
        self.assertEqual(set(result), set(guide.ECHO_FILES))
        self.assertEqual(set(p.name for p in self.destination.iterdir()), set(guide.ECHO_FILES))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})
        if os.name == 'posix':
            for path in self.destination.iterdir(): self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_changed_component_is_not_a_placeholder_publication(self):
        (self.source / 'echo-capsule.wasm').write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError, 'component-identity'):
            guide.stage_echo(self.source, self.destination)

    def test_changed_deployment_digest_or_tenant_is_rejected(self):
        for key, value in [('tenant', 'foreign'), ('name', 'other')]:
            with self.subTest(key=key):
                document = self.documents['deployment.json'].copy()
                document['metadata'] = dict(document['metadata'], **{key:value})
                (self.source / 'deployment.json').write_text(json.dumps(document))
                target = self.root / key; target.mkdir()
                with self.assertRaisesRegex(WorkflowError, 'deployment-identity'):
                    guide.stage_echo(self.source, target)

    def test_missing_empty_oversized_and_nonregular_inputs_rejected(self):
        for case in ['missing', 'empty', 'oversized', 'directory']:
            with self.subTest(case=case):
                source = self.root / case; echo(source)
                path = source / 'input.json'; path.unlink()
                if case == 'empty': path.write_bytes(b'')
                elif case == 'oversized': path.write_bytes(b'x' * 65537)
                elif case == 'directory': path.mkdir()
                target = self.root / (case + '-out'); target.mkdir()
                with self.assertRaises(WorkflowError): guide.stage_echo(source, target)

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink fixture')
    def test_symlinked_root_and_file_rejected(self):
        linked = self.root / 'linked'; linked.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(WorkflowError, 'echo-root'): guide.stage_echo(linked, self.destination)
        path = self.source / 'input.json'; path.unlink(); path.symlink_to(self.source / 'contracts.json')
        with self.assertRaisesRegex(WorkflowError, 'echo-input-file'): guide.stage_echo(self.source, self.destination)

    def test_existing_outputs_never_overwritten(self):
        (self.destination / 'echo-capsule.wasm').write_bytes(b'keep')
        with self.assertRaises(FileExistsError): guide.stage_echo(self.source, self.destination)
        self.assertEqual((self.destination / 'echo-capsule.wasm').read_bytes(), b'keep')

    def test_config_explicit_profile_and_independent_random_credentials(self):
        first = self.root / 'first'; first.mkdir(); second = self.root / 'second'; second.mkdir()
        config, token = guide.configure(first)
        _, other = guide.configure(second)
        value = read_json(config)
        self.assertNotEqual(token, other)
        self.assertEqual(value['securityProfile'], 'local-experimental-v1')
        self.assertEqual(value['supplyChain'], {'mode':'trusted-local'})
        self.assertEqual(value['bind'], '127.0.0.1:0')
        self.assertGreaterEqual(len(token), 32)
        self.assertFalse((first / 'data').exists())
        with self.assertRaises(FileExistsError): guide.configure(first)


class Payloads(unittest.TestCase):
    def result(self):
        raw = b'[{"ok":"hello"}]'
        return {'category':'success', 'outcomeKnown':True, 'data':{'activationId':'wanted',
                'payload':{'encoding':'base64', 'mediaType':guide.MEDIA,
                           'data':base64.b64encode(raw).decode(), 'byteLength':str(len(raw))}}}

    def invoke(self, value):
        class ClientDouble:
            def call(self, *args, **kwargs): return value
        return guide.invoke(ClientDouble(), Path('/unused'), 'wanted')

    def test_exact_success(self): self.assertEqual(self.invoke(self.result())['category'], 'success')

    def test_uncertain_and_wrong_activation_never_pass(self):
        for mutation in [lambda v: v.update(outcomeKnown=False),
                         lambda v: v.update(category='transport-failure'),
                         lambda v: v['data'].update(activationId='other')]:
            value = self.result(); mutation(value)
            with self.assertRaisesRegex(WorkflowError, 'invocation-result'): self.invoke(value)

    def test_invalid_payload_formats_sizes_and_values(self):
        for patch_value in [{'encoding':'raw'}, {'mediaType':'text/plain'}, {'data':'!'},
                            {'byteLength':999}, {'byteLength':'1'},
                            {'data':base64.b64encode(b'[]').decode(), 'byteLength':'2'}]:
            with self.subTest(patch_value=patch_value):
                value = self.result(); value['data']['payload'].update(patch_value)
                with self.assertRaises((WorkflowError, ValueError)): self.invoke(value)

    def test_exact_source_required(self):
        self.assertEqual(runner.source_commit('a' * 40), 'a' * 40)
        for value in ['development', 'a' * 39, 'A' * 40, 'a' * 40 + ';id']:
            with self.assertRaises(argparse.ArgumentTypeError): runner.source_commit(value)

    def test_failed_run_redacts_exception_and_never_emits_pass(self):
        output = io.StringIO()
        with patch.object(runner, 'run', side_effect=RuntimeError('PRIVATE-TOKEN-CANARY')), redirect_stdout(output):
            executable = str(Path(sys.executable).resolve(strict=True))
            status = runner.main(['--cli', executable, '--node', executable,
                                  '--echo-root', '/unused', '--source-commit', 'a' * 40])
        self.assertEqual(status, 1)
        self.assertNotIn('PRIVATE-TOKEN-CANARY', output.getvalue())
        self.assertIs(json.loads(output.getvalue())['passed'], False)


@unittest.skipUnless(sys.platform == 'linux', 'uses the existing Linux process owner')
class Sequencing(unittest.TestCase):
    def run_scenario(self, case=''):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / 'source'; echo(source)
        package = root / 'package'; package.mkdir(); guide.stage_echo(source, package)
        node_directory = root / 'node'; node_directory.mkdir(mode=0o700)
        client_directory = root / 'client'; client_directory.mkdir(mode=0o700)
        binary = executable(root, 'node-double', NODE)
        cli = executable(root, 'cli-double', CLI)
        (root / 'case').write_text(case)
        with owned_cancellation() as cancellation:
            client = Client(cli, client_directory, cancellation, time.monotonic() + 20)
            result = guide.exercise(client, binary, node_directory, package)
        calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
        return result, calls

    def test_complete_synthetic_sequence_reuses_owners_and_does_not_republish(self):
        result, calls = self.run_scenario()
        self.assertEqual(result['successfulInvocations'], 2)
        self.assertEqual(result['declaredErrors'], 1)
        self.assertEqual(sum(row[:2] == ['release','publish'] for row in calls), 1)
        self.assertEqual(sum(row[:2] == ['deployment','apply'] for row in calls), 1)
        self.assertEqual(sum(row[0] == 'invoke' for row in calls), 3)
        self.assertEqual(len(result['shutdowns']), 2)
        for stop in result['shutdowns']:
            self.assertTrue(stop['clean'] and stop['reaped'])
            with self.assertRaises(ProcessLookupError): os.kill(stop['processId'], 0)
        self.assertNotIn('token', json.dumps(result).lower())

    def test_failure_is_not_retried_or_reported_as_success(self):
        for case in ['invoke-failed', 'wrong-identity', 'unclean']:
            with self.subTest(case=case), self.assertRaises(WorkflowError):
                self.run_scenario(case)


if __name__ == '__main__':
    unittest.main()
