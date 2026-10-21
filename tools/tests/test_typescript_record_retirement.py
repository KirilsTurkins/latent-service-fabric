"""Compile the actual owner classes; JS doubles establish no engine semantics."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RecordRetirementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++')
        if compiler is None:
            if os.name == 'nt':
                raise unittest.SkipTest('Set LSF_TYPESCRIPT_RECORD_CXX for the finite C++ reference')
            raise RuntimeError('C++ compiler is required for record lifetime controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        msvc = Path(compiler).stem.lower() == 'cl'
        cls.binary = output / ('records.exe' if os.name == 'nt' else 'records')
        args = [compiler]
        args += ['-std=c++17', '-O0', '-Wall', '-Wextra', '-Werror',
                 '-I', str(ROOT/'tools/tests/fixtures/typescript_record_retirement'),
                 str(ROOT/'sdk/typescript-guest/activation/tests/record_retirement.cpp')]
        args += ['-o', str(cls.binary)]
        if msvc:
            args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                    '/I' + str(ROOT/'tools/tests/fixtures/typescript_record_retirement'),
                    str(ROOT/'sdk/typescript-guest/activation/tests/record_retirement.cpp'),
                    '/Fe:' + str(cls.binary), '/Fo:' + str(output/'records.obj')]
        result = subprocess.run(args, capture_output=True, timeout=60)
        if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
            raise AssertionError(result.stderr[:65536].decode(errors='replace'))
        if not cls.binary.is_file() or cls.binary.stat().st_size > 4*1024**2:
            raise AssertionError('finite record reference output required')

    def control(self, case):
        command = [str(self.binary), case]
        result = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 65536)
        self.assertEqual(json.loads(result.stdout),
                         {'case': case, 'passed': True, 'engineQualified': False})

    def test_promise_tracking_allocation_dies_before_refund(self):
        self.control('promise-ack-after-delete')

    def test_promise_refused_ack_retains_exact_owner_without_allocation(self):
        self.control('promise-refused-ack-retains-owner')

    def test_reaction_tracking_allocation_dies_before_refund(self):
        self.control('reaction-ack-after-delete')

    def test_reaction_partial_ack_cannot_double_refund_job_owners(self):
        self.control('reaction-partial-ack-retains-owner')

    def test_completed_job_destroys_callable_root_before_refund(self):
        self.control('job-ack-after-delete')

    def test_failed_job_destroys_callable_root_before_refund(self):
        self.control('job-error-ack-after-delete')

    def test_cancelled_job_destroys_callable_root_before_refund(self):
        self.control('job-cancel-ack-after-delete')

    def test_completed_job_retains_partial_ack_without_replaying_frame(self):
        self.control('job-partial-ack-retains-owner')

    def test_cancelled_job_retains_partial_ack_without_replaying_callback(self):
        self.control('job-cancel-partial-ack-retains-owner')


if __name__ == '__main__':
    unittest.main()
