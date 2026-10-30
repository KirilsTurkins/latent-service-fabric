"""Pure retained-input and strict twelve-call observation controls."""
import copy
import json
import os
from pathlib import Path
import unittest

from tools.java_guest import retained_fiber_inputs as inputs
from tools import qualify_java_retained_fibers as owner


class RetainedJavaFibersTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('LSF_JAVA_RETAINED_ARCHIVE'), 'requires the one authenticated public archive')
    def test_exact_public_archive_and_corruption_refusal(self):
        raw = inputs.read_file(Path(os.environ['LSF_JAVA_RETAINED_ARCHIVE']), inputs.ARCHIVE['bytes'])
        files = inputs.decode(raw)
        self.assertEqual({name: inputs.identity(value) for name, value in files.items()}, inputs.FILES)
        with self.assertRaisesRegex(ValueError, 'whole-archive'):
            inputs.decode(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, 'whole-archive'):
            inputs.decode(raw + b'append')

    def test_origin_allows_unselected_skips_but_requires_the_actual_backend(self):
        run = {'id': inputs.RUN, 'head_sha': inputs.HEAD, 'head_commit': {'tree_id': inputs.TREE},
            'head_branch': 'feat/java-llvm-ssa-consumer-20261025', 'run_attempt': 1,
            'event': 'workflow_dispatch', 'path': '.github/workflows/java-guest-feasibility.yml',
            'status': 'completed', 'conclusion': 'success'}
        names = ('Install the same prerequisites for the separately admitted private-scalar backend',
            'Compile the unchanged public C with the independently qualified backend',
            'Retain only fixed public assembly evidence and original failure')
        job = {'id': inputs.JOB, 'run_id': inputs.RUN, 'head_sha': inputs.HEAD,
            'name': 'Fixed public Java fiber assembly inputs only', 'status': 'completed',
            'conclusion': 'success', 'steps': [{'name': name, 'status': 'completed',
                'conclusion': 'success'} for name in names] + [
                    {'name': 'unselected old branch', 'status': 'completed', 'conclusion': 'skipped'}]}
        artifact = {'id': inputs.ARTIFACT, 'expired': False, 'workflow_run': {'id': inputs.RUN,
            'head_sha': inputs.HEAD}, 'name': 'java-public-fiber-assembly-' + inputs.HEAD,
            'size_in_bytes': inputs.ARCHIVE['bytes'], 'digest': 'sha256:' + inputs.ARCHIVE['sha256']}
        inputs.metadata(run, job, artifact)
        for key, value in (('expired', True), ('digest', 'sha256:' + '0' * 64)):
            bad = {**artifact, key: value}
            with self.assertRaisesRegex(ValueError, 'artifact'):
                inputs.metadata(run, job, bad)
        bad = copy.deepcopy(job)
        bad['steps'][1]['conclusion'] = 'skipped'
        with self.assertRaisesRegex(ValueError, 'selected-steps'):
            inputs.metadata(run, bad, artifact)

    def test_twelve_real_rows_bind_ids_fresh_stores_budgets_and_retirement(self):
        rows = []
        for index in range(12):
            iteration, mode = divmod(index, 4)
            rows.append({**dict.fromkeys(owner.ZERO_FIELDS, 0),
                'activationId': f'java-fibers-{iteration}-{mode}', 'iteration': iteration,
                'mode': mode, 'value': 42, 'cpuFuel': 123, 'reportedPeakMemoryBytes': 4096,
                'storesBefore': index, 'storesCreated': index + 1})

        def output(values, summary='1 passed; 0 failed; 0 ignored; 0 measured; 51 filtered out;'):
            lines = ['test ' + owner.CASE + ' ... ok',
                'teavm-activation-fibers-v1 signed-preparation-setup-micros=1 stores-created=0 guest-activations=0',
                *['LSF_JAVA_RETAINED=' + json.dumps(row) for row in values],
                'test result: ok. ' + summary]
            return ('\n'.join(lines) + '\n').encode()

        self.assertEqual(owner.observations(output(rows))['calls'], rows)
        for index, field, value in ((11, 'activationId', rows[0]['activationId']),
                (3, 'liveStores', 1), (2, 'storesBefore', 0), (4, 'storesCreated', 4),
                (0, 'cpuFuel', 10_000_000_001), (0, 'reportedPeakMemoryBytes', 64 * 1024**2 + 1),
                (0, 'cpuFuel', True), (0, 'value', 41)):
            bad = copy.deepcopy(rows)
            bad[index][field] = value
            with self.assertRaises(ValueError):
                owner.observations(output(bad))
        with self.assertRaisesRegex(ValueError, 'twelve-calls'):
            owner.observations(output(rows[:-1]))
        with self.assertRaisesRegex(ValueError, 'one-executed-no-skip'):
            owner.observations(output(rows, '0 passed; 0 failed; 1 ignored; 0 measured; 51 filtered out;'))


if __name__ == '__main__':
    unittest.main()
