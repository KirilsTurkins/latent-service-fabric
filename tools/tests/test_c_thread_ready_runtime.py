"""Fixed product routing, with the original seventeen-case body retained."""
import ast
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_c_thread_runtime as qualification
from tools import host_codec_owned_reply_native_products as native

ORIGINAL = '173ccd9c096e4db643aa9627bd4550cef27fb922'


class CThreadReadyRuntime(unittest.TestCase):
    def test_fixed_v4_admission_runs_before_any_compiler_or_node_work(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'refused'
            with patch.object(qualification.sys, 'platform', 'linux'), \
                    patch.object(qualification.sys, 'version_info', (3, 13)), \
                    patch.object(qualification.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(qualification, 'native_evidence', side_effect=RuntimeError('fixed-v7-refusal')) as admission, \
                    patch.object(qualification.compiler, 'build') as compiler, \
                    patch.object(qualification.node, 'run') as node, \
                    self.assertRaisesRegex(RuntimeError, '^fixed-v7-refusal$'):
                qualification.qualify(Path(directory) / 'prepared', output)
            admission.assert_called_once_with(native, Path(directory) / 'prepared')
            compiler.assert_not_called()
            node.assert_not_called()

    def test_pre_call_audit_idle_requires_real_zero_samples_and_bounds_nonquiescent_work(self):
        from tools import c_thread_runtime_node as node
        from tools.phase2_operator_process import WorkflowError
        names = ('audit_queued_operations', 'audit_queued_bytes', 'audit_reserved_records',
                 'audit_reserved_bytes', 'audit_pending_attempts', 'audit_query_owners',
                 'audit_query_bytes', 'audit_recovery_pending', 'audit_closed')
        zero = {'nodeUsage': {'counters': dict.fromkeys(names, 0)}}
        busy = {'nodeUsage': {'counters': {**zero['nodeUsage']['counters'], 'audit_query_owners': 1}}}
        output = Path('/unused-private-output')
        with patch.object(node, 'usage', side_effect=[busy, zero]) as sample, \
                patch.object(node, 'write_json') as write, patch.object(node.time, 'sleep') as sleep:
            self.assertIs(node.wait_audit_idle(object(), 'target', output, 'activation'), zero)
            self.assertEqual(sample.call_count, 2)
            self.assertEqual(write.call_count, 3)
            self.assertIs(write.call_args.args[1], zero)
            self.assertEqual(write.call_args.args[0].name, 'audit-before-activation.json')
            sleep.assert_called_once_with(0.01)
        with patch.object(node, 'usage', return_value=busy) as sample, \
                patch.object(node, 'write_json') as write, patch.object(node.time, 'sleep') as sleep:
            with self.assertRaisesRegex(ValueError, 'precall-audit-idle-premise'):
                node.wait_audit_idle(object(), 'target', output, 'activation')
            self.assertEqual((sample.call_count, write.call_count, sleep.call_count), (16, 16, 15))
            self.assertTrue(all(call.args[0].name != 'audit-before-activation.json'
                                for call in write.call_args_list))
        for field in ('audit_closed', 'audit_recovery_pending'):
            bad = {'nodeUsage': {'counters': {**zero['nodeUsage']['counters'], field: 1}}}
            with self.subTest(field=field), patch.object(node, 'usage', return_value=bad) as sample, \
                    patch.object(node, 'write_json'), patch.object(node.time, 'sleep') as sleep:
                with self.assertRaisesRegex(WorkflowError, 'precall-audit-live'):
                    node.wait_audit_idle(object(), 'target', output, 'activation')
                sample.assert_called_once()
                sleep.assert_not_called()

    def test_seventeen_outcomes_oracles_caps_and_default_assert_current_are_unchanged(self):
        original = subprocess.check_output(['git', 'show', ORIGINAL + ':tools/qualify_c_thread_runtime.py'],
                                           cwd=qualification.ROOT).decode()
        current = (qualification.ROOT / 'tools/qualify_c_thread_runtime.py').read_text()
        # Remove only the exact appended synchronization extension before the
        # unchanged whole-original-body comparison below. Every new fragment
        # must occur exactly once; changed old guards cannot be projected away.
        def project_once(text, added, previous):
            self.assertEqual(text.count(added), 1, added)
            return text.replace(added, previous)
        for added, previous in (
            ("'signed-original-seventeen-and-three-synchronization-programme'",
             "'signed-seventeen-case-c-thread-programme'"),
            ("                and record['node']['programme']['originalSeventeenOutcomePrefix'] == 17\n"
             "                and len(record['node']['programme']['outcomes']) == 20,\n"
             "                'c-thread-all-seventeen-original-and-three-synchronization-outcomes')",
             "                and len(record['node']['programme']['outcomes']) == 17,\n"
             "                'c-thread-all-seventeen-original-outcomes')"),
            ('record.update(status=\'passed\', observedCases=20)',
             'record.update(status=\'passed\', observedCases=17)'),
        ):
            current = project_once(current, added, previous)
        old, new = ast.parse(original), ast.parse(current)
        old_functions = {item.name: item for item in old.body if isinstance(item, ast.FunctionDef)}
        new_functions = {item.name: item for item in new.body if isinstance(item, ast.FunctionDef)}
        selected = new_functions['qualify']
        imports = [item for item in ast.walk(selected) if isinstance(item, ast.ImportFrom)
                   and item.module == 'tools']
        self.assertEqual([(item.names[0].name, item.names[0].asname) for item in imports],
                         [('host_codec_owned_reply_native_products', 'products')])
        imports[0].names[0].name = 'host_codec_native_products'
        projection = new_functions['assert_current'].body.pop(0)
        self.assertEqual(ast.dump(projection), ast.dump(ast.parse('''
if products is not None and products.SOURCE == 'f5351a9331ed954c49ae83f2f4004e0f96d25d0e':
    from tools.c_thread_linear_memory_native_source import assert_current as selected_source
    return selected_source(root)
''').body[0]))
        self.assertEqual(set(old_functions), set(new_functions))
        for name in old_functions:
            self.assertEqual(ast.dump(old_functions[name]), ast.dump(new_functions[name]), name)
        node = 'tools/c_thread_runtime_node.py'
        original_node = subprocess.check_output(['git', 'show', ORIGINAL + ':' + node], cwd=qualification.ROOT)
        retained = original_node.replace(b'            pages.append(page)\n',
            b'            pages.append(page)\n'
            b"            write_json(output / f'child-audit-{process.authoring_activation}-{attempt}-{len(pages)}.json', page)\n")
        retained = retained.replace(
            b"        inventory = client.call('node', 'get', 'operator-workflow-test')['data']['inventory']\n",
            b"        inventory = client.call('node', 'get', 'operator-workflow-test')['data']['inventory']\n"
            b"        write_json(output / f'child-inventory-{process.authoring_activation}-{attempt}.json', inventory)\n")
        self.assertNotEqual(retained, original_node)
        current_node = (qualification.ROOT / node).read_text()
        # Invert only the authenticated paired-client addendum before old node proofs.
        self.assertEqual(hashlib.sha256(current_node.encode()).hexdigest(),
                         '336345171062a1d9bcde8c0b93bdafcbcfcb3c68cc10bd5feae57c8a5a726e13')
        self.assertEqual(current_node.count('from tools.c_guest.standard_facilities import FETCH_PROFILE, FETCH_STANDARD_PROFILE\n'), 1)
        current_node = current_node.replace('from tools.c_guest.standard_facilities import FETCH_PROFILE, FETCH_STANDARD_PROFILE\n', '', 1)
        self.assertEqual(current_node.count('\n\ndef configure_libucl('), 1)
        current_node = current_node.split('\n\ndef configure_libucl(', 1)[0]
        actual_run = next(item for item in ast.parse(current_node).body
                          if isinstance(item, ast.FunctionDef) and item.name == 'run_http')
        actual_run = ''.join(current_node.splitlines(keepends=True)[actual_run.lineno - 1:actual_run.end_lineno])
        self.assertEqual(hashlib.sha256(actual_run.encode()).hexdigest(),
                         '7aac17ccef3bc6b6363c6da08e226b84aa45fdb00739c1e174ebb882b40b0925')
        current_node = current_node.replace(actual_run, "def run_http(artifact: Path, native: dict, output: Path, *, deadline):\n    import secrets\n    from tools.standard_http.peer import Peer\n    from tools.standard_http.observations import validate\n    output = fresh(output)\n    component = file_identity(artifact / 'component.wasm', 8 * 1024**2)\n    before = {name: file_identity(path) for name, path in native.items()}\n    require(deadline > time.monotonic(), 'c-libfetch-original-parent-deadline')\n    commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),\n                        deadline_seconds=300, command_seconds=60)\n    commands.deadline = min(commands.deadline, deadline)\n    record = {'schemaVersion': 'latent.c.libfetch.node.v1', 'status': 'incomplete',\n              'component': component, 'native': before, 'full690Qualified': False,\n              'fullCCostModelQualified': False, 'independentClientCount': 1}\n    stage, failed = 'sign', False\n    try:\n        signed = output / 'signed'\n        commands.run('libfetch-sign', native['capsule_authoring'], 'demo-sign', signed, artifact)\n        releases = read_json(signed / 'release-set.json')['releases']\n        require(len(releases) == 1 and releases[0]['componentDigest'] == component['sha256'],\n                'c-libfetch-one-signed-component')\n        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-c-libfetch-') as temporary, \\\n                owned_cleanup(record) as cleanup:\n            work = Path(temporary)\n            for name in ('client', 'node', 'credentials'):\n                (work / name).mkdir(mode=0o700)\n            secret = b'Bearer ' + secrets.token_hex(32).encode('ascii')\n            credential = work / 'credentials/peer'\n            credential.write_bytes(secret); credential.chmod(0o600)\n            peer = Peer(secret, maximum_seconds=max(1, min(300, int(commands.deadline - time.monotonic()))))\n            cleanup.callback(peer.close)\n            client = RecordingClient(native['latent'], work / 'client', cancellation,\n                min(commands.deadline, time.monotonic() + 240), evidence=output / 'controls')\n            config, settings = configure_base(work / 'node', signed, peer.origin()['port'], language='c')\n            configure_http(settings, read_json(artifact / 'capsule.json'), peer, credential)\n            config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\\n').encode())\n            # Private credentials and node configuration are intentionally not public artifacts.\n            stage = 'node'\n            node = connect(client, native['latentd'], work / 'node', config, 'examples', 0)\n            cleanup.callback(node.close)\n            record['startup'] = node.startup_record\n            probe = Probe(node, before['latentd'])\n            source = signed / SERVICE\n            published = client.call('release', 'publish-package', source / 'package',\n                '--evidence', source / 'evidence/index.json', '--operation-id', 'c-libfetch-publish',\n                '--expected-generation', '0')\n            require(published['outcomeKnown'] is True and published['data']['release']['digest'] == component['sha256'],\n                    'c-libfetch-signed-admission')\n            publication = published['data']['operation']['publication']['id']\n            target = deploy(client, source / 'deployment.json', publication)\n            require(target['grants'] == [], 'c-libfetch-no-ambient-grants')\n            grants = install_http(client, node, target, peer.origin())\n            target = deploy(client, source / 'deployment.json', publication,\n                            generation=str(target['generation']), grants=grants)\n            stage = 'five-ordinary-cells'\n            record['cases'] = []\n            for case in fixture.HTTP_CASES:\n                record['cases'].append(http_cell(client, node, probe, target, peer, output, case))\n            require([row['case'] for row in record['cases']] == list(fixture.HTTP_CASES)\n                    and peer.observation()['startedRequests'] == 6, 'c-libfetch-five-cells-six-contacts')\n            delete_all(client, [target['name']])\n            record['afterDeletes'] = sample(client, probe, 'c-libfetch-after-deletes', 0)\n            stop(client, node); record['nodeShutdown'] = stopped_record(node)\n            record['peerShutdown'] = peer.close(); validate(record['peerShutdown'])\n            require(record['peerShutdown']['openConnections'] == record['peerShutdown']['listeningOrigins'] == 0,\n                    'c-libfetch-stopped-peer')\n            cancellation.check()\n        require(component == file_identity(artifact / 'component.wasm', 8 * 1024**2)\n                and before == {name: file_identity(path) for name, path in native.items()}\n                and time.monotonic() < commands.deadline and client.calls <= 384,\n                'c-libfetch-final-original-inputs-and-deadline')\n        record.update(status='passed', cliCalls=client.calls, commands=commands.records)\n        write_json(output / 'qualified.json', record)\n        return record\n    except BaseException:\n        failed = True\n        record.update(status='failed', stage=stage)\n        raise\n    finally:\n        if failed:\n            write_json(output / 'FAILED.json', record)\n", 1)
        http_marker = "\n\nHTTP = 'latent:http/streaming@0.3.0'\n"
        self.assertEqual(current_node.count(http_marker), 1)
        original_prefix, http_tail = current_node.split(http_marker, 1)
        self.assertEqual(hashlib.sha256((http_marker + http_tail).encode()).hexdigest(),
                         'de3b789dd49822e530b15217823e61677ccc1f4b570762d60e6b8790fe1d7870')
        current_node = original_prefix
        current_node = project_once(current_node,
            "            children = {'mixed': 2, 'pressure': 3, 'sync-pthread': 2, 'sync-mixed': 2}.get(mode, 1)\n"
            "            witness = fixture.observation(row['decoded'][0]['ok'], children,\n"
            "                synchronized=mode in ('sync-pthread', 'sync-mixed'))\n",
            "            children = {'mixed': 2, 'pressure': 3}.get(mode, 1)\n"
            "            witness = fixture.observation(row['decoded'][0]['ok'], children)\n")
        current_node = project_once(current_node,
            "    for label, mode in (('sync-pthread', 'sync-pthread'), ('sync-mixed', 'sync-mixed'),\n"
            "                        ('fresh-sync', 'pthread')):\n"
            "        outcomes.append(invoke(client, probe, target, output, mode, 'c-thread-' + label))\n"
            "    require(len(outcomes) == 20, 'c-thread-original-seventeen-and-three-synchronization-controls')\n", '')
        current_node = project_once(current_node,
            "        'originalSeventeenOutcomePrefix': 17,\n"
            "        'pthreadAndMixedBasicSynchronizationQualified': True,\n", '')
        def function(text, name):
            item = next(value for value in ast.parse(text).body if isinstance(value, ast.FunctionDef) and value.name == name)
            return '\n'.join(text.splitlines()[item.lineno - 1:item.end_lineno]) + '\n'
        helper = function(current_node, 'positive_audit_coverage')
        child = function(current_node, 'child_entry')
        self.assertEqual(hashlib.sha256(helper.encode()).hexdigest(), '994d4f544302a7f5d8b7025df68bbdab32cf0d6070dabcb0be1e94dbf35ef8c5')
        self.assertEqual(hashlib.sha256(child.encode()).hexdigest(), '44db0ed2e9927c641646b898e684edbe247c7a79f991a818371cf77a77afcc8c')
        idle = function(current_node, 'wait_audit_idle')
        self.assertEqual(hashlib.sha256(idle.encode()).hexdigest(),
                         '7666d1a10c9f560446ad6cf52b9c712f8636683921194646feba2a2606658bc7')
        projected = project_once(current_node, idle + '\n\n', '')
        projected = projected.replace(helper + '\n\n', '').replace(child, function(original_node.decode(), 'child_entry'))
        projected = projected.replace(
            '        witness = child_entry(inventory, pages, process.authoring_activation,\n'
            '            expected_revision=revision, positive_only=True)\n',
            '        witness = child_entry(inventory, pages, process.authoring_activation, expected_revision=revision)\n')
        projected = projected.replace("    require(settings['audit'] == {'mode': 'durable', 'records': 1024, 'diskBytes': 16 * 1024 * 1024,\n            'queuedOperations': 8, 'queryOwners': 2}, 'c-thread-original-diagnostic-audit-envelope')\n    # Nine original pre-hold provider calls can offer 18 optional observations.\n    # Each holds 16 KiB through journal completion; one serialized query needs 4 KiB.\n    # This is a finite test-environment envelope, not a durable/lossless guarantee.\n    settings['audit']['queuedOperations'] = (9 * 2 * 16384 + 4096) // 4096\n", '')
        projected = project_once(projected, "    if mode in ('cancel', 'deadline'):\n"
            "        wait_audit_idle(client, target, output, activation)\n", '')
        self.assertEqual(retained, projected.encode())
        self.assertIn('tools/host_codec_linear_memory_native_products.py', qualification.MATERIALS)
        self.assertIn('tools/host_codec_linear_memory_native_products_reader.py', qualification.MATERIALS)
        self.assertIn('tools/c_thread_linear_memory_native_source.py', qualification.MATERIALS)
        self.assertIn('tools/host_codec_owned_reply_native_products.py', qualification.MATERIALS)
        self.assertIn('tools/host_codec_owned_reply_native_products_reader.py', qualification.MATERIALS)
        self.assertIn('.github/workflows/c-thread-runtime.yml', qualification.MATERIALS)


if __name__ == '__main__':
    unittest.main()
