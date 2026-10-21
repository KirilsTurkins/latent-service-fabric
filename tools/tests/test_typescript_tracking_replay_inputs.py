"""Reject mixed provenance and unsuccessful engine products before reuse."""
import copy
from pathlib import Path
import tempfile
import unittest

from tools import typescript_tracking_replay_inputs as tracking
from tools.phase2_operator_process import WorkflowError


def metadata(kind):
    identity, size, sha, job, name = tracking.SPECS[kind]
    run = {'id': tracking.RUN, 'head_sha': tracking.HEAD, 'event': 'pull_request',
        'head_branch': 'feat/typescript-runtime-accounting-20261021',
        'path': '.github/workflows/typescript-guest.yml', 'status': 'completed', 'conclusion': 'cancelled'}
    owning = {'id': job, 'run_id': tracking.RUN, 'head_sha': tracking.HEAD, 'name': name,
        'status': 'completed', 'conclusion': 'success', 'steps': [{'conclusion': 'success'}]}
    artifact = {'id': identity, 'size_in_bytes': size, 'digest': 'sha256:'+sha, 'expired': False,
        'workflow_run': {'id': tracking.RUN, 'head_sha': tracking.HEAD},
        'name': 'typescript-'+('fetch-engine-input' if kind == 'engine' else 'source-splicer-input')+'-'+tracking.SOURCE}
    return run, owning, artifact


class TrackingInputs(unittest.TestCase):
    def test_cancelled_boundary_is_not_qualification_but_successful_owning_jobs_can_be_reused(self):
        for kind in tracking.SPECS:
            tracking.owning(*metadata(kind), kind)
            for conclusion in ('cancelled', 'failure', 'timed_out', 'action_required', None):
                run, job, artifact = metadata(kind)
                job['conclusion'] = conclusion
                with self.subTest(kind=kind, conclusion=conclusion), self.assertRaises(WorkflowError):
                    tracking.owning(run, job, artifact, kind)
            run, job, artifact = metadata(kind)
            job['steps'][0]['conclusion'] = 'failure'
            with self.assertRaises(WorkflowError):
                tracking.owning(run, job, artifact, kind)

    def test_head_job_name_branch_and_tested_merge_artifact_cannot_be_interchanged(self):
        for kind in tracking.SPECS:
            original = metadata(kind)
            for index, key, value in ((0, 'head_sha', tracking.SOURCE), (0, 'event', 'push'),
                    (0, 'head_branch', 'development'), (0, 'path', 'other.yml'),
                    (1, 'id', 1), (1, 'head_sha', tracking.SOURCE), (1, 'name', 'TypeScript guest value and ownership boundary'),
                    (2, 'id', 1), (2, 'expired', True), (2, 'digest', 'sha256:'+'0'*64),
                    (2, 'size_in_bytes', 1), (2, 'name', 'typescript-fetch-engine-input-'+tracking.HEAD)):
                changed = copy.deepcopy(original)
                changed[index][key] = value
                with self.subTest(kind=kind, index=index, key=key), self.assertRaises(WorkflowError):
                    tracking.owning(*changed, kind)
            changed = copy.deepcopy(original)
            changed[2]['workflow_run']['head_sha'] = tracking.SOURCE
            with self.assertRaises(WorkflowError):
                tracking.owning(*changed, kind)

    def test_changed_archive_is_rejected_before_any_directory_or_member_is_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/'selected'
            for kind in tracking.SPECS:
                with self.assertRaises(WorkflowError):
                    tracking.unpack(b'not-the-original-archive', kind, destination)
                self.assertFalse(destination.exists())

    def test_forged_prepared_receipt_is_rejected_before_engine_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory/'engine').mkdir()
            (directory/'engine/engine-input.json').write_bytes(b'{}')
            with self.assertRaisesRegex(WorkflowError, 'tracking-frozen-receipt'):
                tracking.compiler_inputs(directory)


if __name__ == '__main__':
    unittest.main()
