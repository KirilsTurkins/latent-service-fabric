"""The unconditional merge gate distinguishes intentional skips from missing work."""
import copy
import json
import unittest

from tools import ci_result, ci_profile, ci_suite_inventory as registry


def successful(profile):
    decision = ci_profile.classify_paths({'docs': ['README.md'], 'website': ['website/src/css/custom.css'], 'fast': ['crates/latent-state/src/lib.rs'],
                                         'full': ['Cargo.lock']}[profile])
    outputs = decision.outputs()
    required = set(json.loads(outputs['expected_jobs']))
    results = {name: {'result': 'success' if name in required else 'skipped', 'outputs': {}}
               for name in registry.ALL_JOBS}
    results['profile']['outputs'] = outputs
    return results


class ResultTests(unittest.TestCase):
    def test_all_profiles_require_their_exact_jobs(self):
        for profile in ('docs', 'website', 'fast', 'full'):
            self.assertEqual(ci_result.validate(successful(profile)),
                             set(json.loads(successful(profile)['profile']['outputs']['expected_jobs'])))

    def test_every_failure_cancellation_and_unexpected_skip_is_fatal(self):
        for profile in ('docs', 'website', 'fast', 'full'):
            valid = successful(profile)
            for job in registry.ALL_JOBS:
                for status in ('success', 'failure', 'cancelled', 'skipped', None):
                    if status == valid[job]['result']:
                        continue
                    changed = copy.deepcopy(valid); changed[job]['result'] = status
                    with self.subTest(profile=profile, job=job, status=status), self.assertRaises(ValueError):
                        ci_result.validate(changed)

    def test_missing_jobs_and_outputs_cannot_be_success(self):
        for profile in ('docs', 'website', 'fast', 'full'):
            valid = successful(profile)
            for job in registry.ALL_JOBS:
                changed = copy.deepcopy(valid); del changed[job]
                with self.subTest(profile=profile, missing=job), self.assertRaises(ValueError):
                    ci_result.validate(changed)
            for key in valid['profile']['outputs']:
                changed = copy.deepcopy(valid); del changed['profile']['outputs'][key]
                with self.subTest(profile=profile, missing=key), self.assertRaises(ValueError):
                    ci_result.validate(changed)

    def test_declared_expected_set_is_not_trusted(self):
        for key, value in [('profile', 'almost-full'), ('expected_jobs', '["profile","docs"]'),
                           ('renderer', ''), ('fast_packages', '[]'), ('fast_packages', '["wasmtime"]'),
                           ('changed_files', '-1'), ('reason', '')]:
            changed = successful('full'); changed['profile']['outputs'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                ci_result.validate(changed)

    def test_unexpected_job_is_not_silently_dropped(self):
        changed = successful('full'); changed['missing-from-needs-contract'] = {'result': 'success'}
        with self.assertRaises(ValueError): ci_result.validate(changed)
