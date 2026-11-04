"""Authenticate the original retained WAC failure and bounded probe inputs."""
import hashlib
import io
import unittest
import warnings
import zipfile
from unittest.mock import patch

from tools import diagnose_rust_wac_threading as probe
from tools.phase2_operator_process import WorkflowError


class RetainedPreviewIdentity(unittest.TestCase):
    def metadata(self):
        return [
            {'id': probe.RUN, 'head_sha': probe.SOURCE, 'event': 'push',
             'head_branch': 'fix/rust-http-bindgen-20261104',
             'path': '.github/workflows/rust-http-thread-composition-diagnostic.yml',
             'status': 'completed', 'conclusion': 'failure', 'run_attempt': 1},
            {'jobs': [{'id': probe.JOB, 'head_sha': probe.SOURCE,
             'name': 'Capture one unadmitted composed HTTP and ThreadPool graph',
             'status': 'completed', 'conclusion': 'failure'}]},
            {'id': probe.ARTIFACT, 'name': 'rust-http-thread-composition-diagnostic-' + probe.SOURCE,
             'size_in_bytes': probe.ARCHIVE_SIZE, 'digest': 'sha256:' + probe.ARCHIVE_SHA,
             'expired': False, 'workflow_run': {'id': probe.RUN, 'head_sha': probe.SOURCE}},
        ]

    def test_exact_failed_run_job_and_artifact_are_all_required(self):
        values = self.metadata(); result = probe.official_metadata(lambda _path: values.pop(0))
        self.assertEqual((result['run'], result['job'], result['artifact']), (probe.RUN, probe.JOB, probe.ARTIFACT))
        for row, field, bad in ((0, 'head_sha', 'foreign'), (0, 'conclusion', 'success'),
                                (0, 'run_attempt', 2), (2, 'expired', True),
                                (2, 'digest', 'sha256:other')):
            values = self.metadata(); values[row][field] = bad
            with self.subTest(row=row, field=field), self.assertRaises(WorkflowError):
                probe.official_metadata(lambda _path: values.pop(0))
        values = self.metadata(); values[1]['jobs'][0]['id'] += 1
        with self.assertRaises(WorkflowError): probe.official_metadata(lambda _path: values.pop(0))
        values = self.metadata(); values[2]['workflow_run']['id'] += 1
        with self.assertRaises(WorkflowError): probe.official_metadata(lambda _path: values.pop(0))

    def test_exact_members_and_duplicate_or_tampered_archives_refuse(self):
        def archive(rows):
            data = io.BytesIO()
            with warnings.catch_warnings(), zipfile.ZipFile(data, 'w') as output:
                warnings.simplefilter('ignore', UserWarning)
                for name, body in rows: output.writestr(name, body)
            return data.getvalue()
        raw = archive([('retained/preview.wasm', b'preview')])
        members = {'retained/preview.wasm': (7, hashlib.sha256(b'preview').hexdigest())}
        with patch.multiple(probe, ARCHIVE_SIZE=len(raw), ARCHIVE_SHA=hashlib.sha256(raw).hexdigest(), MEMBERS=members):
            self.assertEqual(probe.selected_members(raw), {'retained/preview.wasm': b'preview'})
            with self.assertRaises(WorkflowError): probe.selected_members(raw[:-1])
            with patch.dict(members, {'retained/preview.wasm': (7, '0' * 64)}):
                with self.assertRaises(WorkflowError): probe.selected_members(raw)
        repeated = archive([('retained/preview.wasm', b'preview'), ('retained/preview.wasm', b'preview')])
        with patch.multiple(probe, ARCHIVE_SIZE=len(repeated), ARCHIVE_SHA=hashlib.sha256(repeated).hexdigest(), MEMBERS=members):
            with self.assertRaisesRegex(WorkflowError, 'archive-entries'): probe.selected_members(repeated)


if __name__ == '__main__':
    unittest.main()
