"""Pure controls for the separately authenticated security-current SDK tuple."""
from __future__ import annotations
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import sdk_native_products_reader as reader
from tools import wait_runtime_native_products as previous
from tools import wasmtime_48_0_7_native_products as native
from tools.phase2_operator_process import WorkflowError


class WasmtimeSecurityNativeProducts(unittest.TestCase):
    def test_direct_cli_requires_no_repository_cwd_pythonpath_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run([sys.executable, '-B', str(Path(native.__file__)), '--help'],
                cwd=temporary, env={**os.environ, 'PYTHONPATH': ''},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            self.assertIn(b'--output', completed.stdout)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_current_tuple_keeps_all_twelve_original_controls_and_historical_tuple(self):
        self.assertEqual(native.STAGES, previous.STAGES)
        self.assertEqual(len(native.STAGES), 12)
        self.assertEqual(native.READER.event, 'workflow_dispatch')
        self.assertEqual(previous.READER.event, 'push')
        self.assertNotEqual(native.SOURCE, previous.SOURCE)
        self.assertNotEqual(native.ARTIFACT, previous.ARTIFACT)
        self.assertNotEqual(native.RECEIPTS, previous.RECEIPTS)
        self.assertEqual(native.native_products(Path('prepared')), previous.native_products(Path('prepared')))

    def test_actual_security_current_git_materials_bind_all_auxiliary_trees(self):
        materials = native.READER._git_materials()
        self.assertEqual(len(materials), 114)
        self.assertEqual(sum(row['bytes'] for row in materials.values()), 496980)
        for prefix in ('wit/', 'schemas/', 'examples/echo-contract/wit/'):
            self.assertTrue(any(name.startswith(prefix) for name in materials))
        self.assertNotEqual(materials['wit/host-abi-phase3-v7.json'],
                            previous.READER._git_materials()['wit/host-abi-phase3-v7.json'])
        self.assertEqual(materials, native.READER._git_materials())

    def test_official_manual_origin_refuses_push_old_native_and_every_foreign_identity(self):
        run = {'id': native.RUN, 'head_sha': native.SOURCE, 'path': reader.WORKFLOW,
            'event': native.EVENT, 'head_branch': native.BRANCH,
            'status': 'completed', 'conclusion': 'success'}
        job = {'id': native.JOB, 'run_id': native.RUN, 'head_sha': native.SOURCE,
            'name': 'Build and retain five source-bound native products',
            'status': 'completed', 'conclusion': 'success'}
        artifact = {**native.ARTIFACT, 'name': 'sdk-native-products-'+native.SOURCE,
            'expired': False, 'workflow_run': {'id': native.RUN, 'head_sha': native.SOURCE}}
        headers = [run, job, {'total_count': 1, 'artifacts': [artifact]}]
        with patch.object(reader, 'api', side_effect=copy.deepcopy(headers)):
            self.assertEqual(native.READER._official_artifact(), artifact)
        changes = ((0, 'event', 'push'), (0, 'event', 'pull_request'),
            (0, 'head_sha', previous.SOURCE), (0, 'id', previous.RUN),
            (0, 'head_branch', 'development'), (0, 'path', '.github/workflows/native-runtime.yml'),
            (1, 'id', previous.JOB), (1, 'run_id', previous.RUN),
            (1, 'head_sha', previous.SOURCE), (1, 'conclusion', 'failure'))
        for index, key, value in changes:
            changed = copy.deepcopy(headers);changed[index][key] = value
            with self.subTest(index=index, field=key), patch.object(reader, 'api', side_effect=changed):
                with self.assertRaises(WorkflowError): native.READER._official_artifact()
        changed = copy.deepcopy(headers)
        changed[2]['artifacts'][0]['id'] = previous.ARTIFACT['id']
        with patch.object(reader, 'api', side_effect=changed), self.assertRaises(WorkflowError):
            native.READER._official_artifact()


if __name__ == '__main__':
    unittest.main()
