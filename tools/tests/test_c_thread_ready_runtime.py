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
