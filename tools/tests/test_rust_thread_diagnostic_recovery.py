"""Fail-closed selection and member checks for separately attributed e3 storage."""
import copy
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
import zipfile

from tools.phase2_operator_process import WorkflowError
from tools import rust_thread_diagnostic_compiler_materials as materials


class RustThreadDiagnosticRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.recovery = copy.deepcopy(materials.RECOVERY)
        self.run = {'id': self.recovery['run'], 'path': materials.RECOVERY_WORKFLOW,
            'event': 'push', 'head_sha': self.recovery['source'], 'head_branch': materials.RECOVERY_BRANCH,
            'repository': {'full_name': materials.REPOSITORY},
            'head_repository': {'full_name': materials.REPOSITORY}, 'status': 'completed', 'conclusion': 'success'}
        self.job = {'id': self.recovery['job'], 'run_id': self.recovery['run'],
            'head_sha': self.recovery['source'], 'name': materials.RECOVERY_JOB_NAME,
            'status': 'completed', 'conclusion': 'success'}
        self.item = {**self.recovery['artifact'], 'name': materials.RECOVERY_NAME, 'expired': False,
            'workflow_run': {'id': self.recovery['run'], 'head_sha': self.recovery['source']}}
        self.items = [self.item]
        self.original_run = {'id': materials.RUN, 'path': '.github/workflows/rust-owned-thread-inputs.yml',
            'event': 'workflow_dispatch', 'head_sha': materials.SOURCE,
            'head_branch': 'feat/rust-thread-runtime-20261023', 'status': 'completed', 'conclusion': 'success'}
        self.original_job = {'id': materials.JOB, 'run_id': materials.RUN, 'head_sha': materials.SOURCE,
            'name': 'Compile exact Rust context utility and owned thread sysroot',
            'status': 'completed', 'conclusion': 'success'}
        self.empty = {'total_count': 0, 'artifacts': []}

    def api(self, path):
        values = {f'actions/runs/{materials.RUN}': self.original_run,
            f'actions/jobs/{materials.JOB}': self.original_job,
            f'actions/runs/{materials.RUN}/artifacts?per_page=100': self.empty,
            f"actions/runs/{self.recovery['run']}": self.run,
            f"actions/jobs/{self.recovery['job']}": self.job,
            f"actions/runs/{self.recovery['run']}/artifacts?per_page=100":
                {'total_count': len(self.items), 'artifacts': self.items}}
        return copy.deepcopy(values[path])

    def test_fixed_storage_pins_are_distinct_from_original_compiler(self):
        self.assertEqual(self.recovery, {'run': 41886594203, 'job': 126772593516,
            'source': '83f1bbd2fad747471c37a777a50965dfd81351c0',
            'artifact': {'id': 13357657805, 'size_in_bytes': 20919269,
                'digest': 'sha256:59628870883ca8870072332004efb1325e76ecb7d3aa1700ce39c430eb6c3a0f'}})
        self.assertNotEqual((self.recovery['run'], self.recovery['job']), (materials.RUN, materials.JOB))
        with patch.object(materials, 'api', self.api):
            selected = materials.storage_for(self.empty)
        self.assertEqual(selected[3]['kind'], 'separately-attributed-recovery-artifact')
        self.assertEqual((selected[3]['run'], selected[3]['job']), (self.recovery['run'], self.recovery['job']))

    def test_original_exact_artifact_remains_preferred_and_missing_fallback_fails_closed(self):
        row = {**materials.ARTIFACT, 'expired': False,
            'workflow_run': {'id': materials.RUN, 'head_sha': materials.SOURCE}}
        self.assertEqual(materials.storage_for({'total_count': 1, 'artifacts': [row]})[3]['kind'],
            'original-compiler-artifact')
        row['id'] += 1
        with self.assertRaises(WorkflowError):
            materials.storage_for({'total_count': 1, 'artifacts': [row]})
        with patch.object(materials, 'RECOVERY', None), self.assertRaises(WorkflowError):
            materials.storage_for(self.empty)
        with self.assertRaises(WorkflowError):
            materials.storage_for({'total_count': 2, 'artifacts': [{}, {}]})

    def test_wrong_recovery_origin_job_digest_or_duplicate_refuses(self):
        with patch.object(materials, 'api', self.api):
            self.run['head_sha'] = '0' * 40
            with self.assertRaises(WorkflowError): materials.storage_for(self.empty)
            self.run['head_sha'] = self.recovery['source']; self.job['conclusion'] = 'failure'
            with self.assertRaises(WorkflowError): materials.storage_for(self.empty)
            self.job['conclusion'] = 'success'; self.item['digest'] = 'sha256:' + '0' * 64
            with self.assertRaises(WorkflowError): materials.storage_for(self.empty)
            self.item['digest'] = self.recovery['artifact']['digest']; self.items.append(copy.deepcopy(self.item))
            with self.assertRaises(WorkflowError): materials.storage_for(self.empty)

    def exercise(self, rows):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as out:
            for name, data in rows: out.writestr(name, data)
        content = archive.getvalue()
        class Ranges(io.BytesIO):
            def __init__(self, url, size):
                super().__init__(content); self.transferred = len(content); self.requests = 1
        class Redirect:
            def open(self, request, timeout):
                raise urllib.error.HTTPError('https://api.github.com/', 302, 'redirect',
                    {'Location': 'https://storage.example.com/artifact'}, None)
        payload = {'application-source-and-capture.tar.gz': b'capture', 'source-inputs.json': b'{}',
                   'raw-core.wasm': b'wasm', 'observation.json': b'observation'}
        pins = {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in payload.items()}
        with tempfile.TemporaryDirectory() as temp, patch.object(materials, 'api', self.api), \
                patch.object(materials, 'PINS', pins), patch.object(materials, 'Ranges', Ranges), \
                patch.object(materials.urllib.request, 'build_opener', lambda *_: Redirect()), \
                patch.dict(os.environ, {'GH_TOKEN': 'unit-test-only'}):
            return materials.prepare(Path(temp) / 'out')

    def test_exact_members_preserve_both_compiler_and_storage_origins(self):
        payload = [('application-source-and-capture.tar.gz', b'capture'), ('source-inputs.json', b'{}'),
                   ('raw-core.wasm', b'wasm'), ('observation.json', b'observation')]
        record = self.exercise(payload)
        self.assertEqual((record['source'], record['run'], record['job']),
                         (materials.SOURCE, materials.RUN, materials.JOB))
        self.assertEqual(record['storage']['run'], self.recovery['run'])
        self.assertFalse(record['originalCompilerReceiptRewritten'])
        self.assertFalse(record['applicationRecompiled'])
        self.assertFalse(record['actualGuestExecuted'])

    def test_changed_extra_or_missing_member_refuses(self):
        payload = [('application-source-and-capture.tar.gz', b'capture'), ('source-inputs.json', b'{}'),
                   ('raw-core.wasm', b'wasm'), ('observation.json', b'observation')]
        for bad in ([('application-source-and-capture.tar.gz', b'CAPTURE'), *payload[1:]],
                    payload + [('extra', b'x')], payload[:-1]):
            with self.subTest(members=len(bad)), self.assertRaises(WorkflowError): self.exercise(bad)


if __name__ == '__main__':
    unittest.main()
