"""Fixed original guest capture boundaries; no guest/native compiler invocation."""
import copy
from pathlib import Path
import tempfile
import unittest

from tools import audit_c36_component as owner
from tools.phase2_operator_process import WorkflowError


def origin():
    value = owner.pins()
    run = {'id': value['run'], 'head_sha': value['source'], 'head_branch': value['branch'],
        'path': value['workflow'], 'event': 'push', 'status': 'completed', 'conclusion': 'success'}
    job = {'id': value['job'], 'run_id': value['run'], 'head_sha': value['source'],
        'name': value['jobName'], 'status': 'completed', 'conclusion': 'success'}
    artifact = dict(value['artifact'], expired=False,
                    workflow_run={'id': value['run'], 'head_sha': value['source']})
    return run, job, artifact


class AuditC36ComponentTests(unittest.TestCase):
    def test_exact_original_capture_contains_one_component_and_complete_packaged_source(self):
        value = owner.pins()
        self.assertEqual((value['source'], value['run'], value['job']),
            ('02478e6e4354323d9a30f7fa1b46240b96a8bcff', 39863159247, 120118674763))
        self.assertEqual(len(value['files']), 80)
        self.assertEqual(value['files']['component.wasm'], {
            'sha256': 'sha256:067ae9badc5c74b7b841d2271bcf1f34489cc6a1bed4994303670016ca5d7ab4',
            'bytes': 2078955})
        self.assertTrue({'capsule.json', 'package-inputs.json', 'package-source.json',
            'source-inputs.json', 'recipe-inputs.json', 'BUILD-COMPLETE.json',
            'build-observation.json'} <= value['files'].keys())

    def test_changed_origin_or_failed_original_job_cannot_authorize_guest_reuse(self):
        owner.validate_origin(*origin())
        for index, field, replacement in ((0, 'event', 'workflow_dispatch'),
                (0, 'head_sha', '0' * 40), (1, 'conclusion', 'failure'),
                (1, 'run_id', 1), (2, 'digest', 'sha256:' + '0' * 64), (2, 'expired', True)):
            values = list(copy.deepcopy(origin()))
            values[index][field] = replacement
            with self.subTest(field=field), self.assertRaises(WorkflowError):
                owner.validate_origin(*values)

    def test_foreign_archive_is_rejected_before_creating_any_build_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.assertRaisesRegex(WorkflowError, 'original-whole-archive'):
                owner.extract(b'PK-not-the-original-captured-component', output)
            self.assertEqual(list(output.iterdir()), [])

    def test_missing_original_source_or_replaced_component_refuses_before_build_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            build = output / 'build'
            build.mkdir()
            (build / 'component.wasm').write_bytes(b'foreign')
            with self.assertRaisesRegex(WorkflowError, 'retained-original-build-drift'):
                owner.verify_prepared(output)


if __name__ == '__main__':
    unittest.main()
