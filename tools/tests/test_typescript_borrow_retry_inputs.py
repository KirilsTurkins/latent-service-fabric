"""Focused refusal and shared deadline controls; no native build."""
import copy
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from tools import typescript_borrow_retry_inputs as retry
from tools.typescript_guest.borrow_controls import diagnostic_phase
from tools.phase2_operator_process import WorkflowError


class BorrowRetryTests(unittest.TestCase):
    def records(self):
        run = {'id': retry.RUN, 'head_sha': retry.HEAD, 'event': 'push',
               'path': '.github/workflows/typescript-borrow-release.yml',
               'head_branch': 'feat/typescript-borrow-release-source-20261024',
               'status': 'completed', 'conclusion': 'failure'}
        job = {'id': retry.JOB, 'run_id': retry.RUN, 'head_sha': retry.HEAD,
               'name': 'One source-built library and engine with native borrow controls',
               'status': 'completed', 'conclusion': 'failure',
               'steps': [{'number': 13, 'conclusion': 'failure'}]}
        artifact = {'id': retry.ARTIFACT, 'size_in_bytes': retry.ARCHIVE_BYTES,
                    'digest': 'sha256:' + retry.ARCHIVE_SHA, 'expired': False,
                    'workflow_run': {'id': retry.RUN, 'head_sha': retry.HEAD},
                    'name': 'typescript-borrow-controls-' + retry.HEAD}
        return run, job, artifact

    def test_failed_producer_is_preserved_and_foreign_or_success_metadata_refuses(self):
        records = self.records()
        retry.metadata(*records)
        for index, key, value in [(0, 'conclusion', 'success'), (1, 'head_sha', '0' * 40),
                                  (1, 'conclusion', 'success'), (2, 'expired', True),
                                  (2, 'digest', 'sha256:' + '0' * 64)]:
            changed = copy.deepcopy(records)
            changed[index][key] = value
            with self.assertRaises(WorkflowError): retry.metadata(*changed)

    def test_changed_archive_or_receipts_refuse_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); archive = root / 'changed.zip'; destination = root / 'products'
            archive.write_bytes(b'wrong producer')
            with self.assertRaisesRegex(WorkflowError, 'whole-archive'):
                retry.extract(archive, destination)
            self.assertFalse(destination.exists())
        with self.assertRaisesRegex(WorkflowError, 'frozen-receipt'):
            retry.frozen_receipts(lambda name: b'{}')

    def test_unsafe_carrier_member_refuses_before_receipt_parse(self):
        class Carrier:
            def __init__(self, row): self.row = row
            def infolist(self): return [self.row]
            def read(self, row): raise AssertionError('must refuse before parsing')
        for name, mode in [('../escape', stat.S_IFREG), ('safe', stat.S_IFLNK),
                           ('safe', stat.S_IFCHR), ('C:escape', stat.S_IFREG)]:
            row = zipfile.ZipInfo(name); row.file_size = 1; row.external_attr = mode << 16
            with self.assertRaisesRegex(WorkflowError, 'member-type-or-path'):
                retry.selected_members(Carrier(row))

    def test_compile_and_link_share_one_deadline_and_failed_phase_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary); phases = []; clock = [0.0]; limits = []
            def run(label, *arguments, seconds):
                limits.append((label, seconds)); clock[0] += 70 if label == 'compile' else 51
            with patch('tools.typescript_guest.borrow_controls.time.monotonic', side_effect=lambda: clock[0]):
                diagnostic_phase('compile', (), run=run, deadline=120, output=output, phases=phases)
                with self.assertRaisesRegex(ValueError, 'aggregate-deadline'):
                    diagnostic_phase('link', (), run=run, deadline=120, output=output, phases=phases)
                with self.assertRaisesRegex(ValueError, 'aggregate-deadline'):
                    diagnostic_phase('extra', (), run=run, deadline=120, output=output, phases=phases)
            self.assertEqual(limits, [('compile', 120), ('link', 50)])
            self.assertEqual([p['status'] for p in phases], ['passed', 'failed'])
            self.assertTrue((output / 'link.phase-result.json').is_file())
