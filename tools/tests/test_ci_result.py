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

    def test_real_sparse_checkouts_preserve_the_complete_effective_inventory(self):
        import hashlib
        from pathlib import Path
        import subprocess
        import sys
        import tempfile
        from tools.ci_lane_inventory import workflow_model

        root = Path(__file__).resolve().parents[2]
        workflow = workflow_model((root / '.github/workflows/ci.yml').read_text())
        complete = registry.load(root / 'tools/ci/suites.json')
        expected_digest = hashlib.sha256(json.dumps(complete, sort_keys=True).encode()).hexdigest()
        outputs = ci_profile.Decision('full', 'sparse-checkout-control', 1).outputs()
        required = json.loads(outputs['expected_jobs'])
        results = {name: {'result': 'success' if name in required else 'skipped'}
                   for name in registry.ALL_JOBS}
        results['profile']['outputs'] = outputs
        files = ['tools/ci_profile.py', 'tools/ci_result.py', 'tools/ci_suite_inventory.py',
                 'tools/ci/suites.json']
        for directory in ('suites.d',):
            fragments = sorted((root / 'tools/ci' / directory).glob('*.json'))
            self.assertTrue(fragments, f'production {directory} controls must not be vacuous')
            files.extend(path.relative_to(root).as_posix() for path in fragments)
        # A fresh interpreter cannot borrow already-imported modules or the
        # outer checkout through PYTHONPATH. Both consumers load their real data.
        probe = '''
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from tools import ci_suite_inventory as registry
assert registry.ROOT == Path.cwd()
data = registry.load()
observed = {'inventory': hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()}
if sys.argv[1] == 'profile':
    from tools import ci_profile
    observed['outputs'] = ci_profile.Decision('full', 'sparse-checkout-control', 1).outputs()
else:
    from tools import ci_result
    observed['required'] = sorted(ci_result.validate(json.load(sys.stdin)))
print(json.dumps(observed))
'''
        for job in ('profile', 'result'):
            checkout = workflow['jobs'][job]['steps'][0]['with']
            self.assertIs(checkout['sparse-checkout-cone-mode'], False)
            patterns = checkout['sparse-checkout']
            with self.subTest(job=job), tempfile.TemporaryDirectory() as temporary:
                sparse = Path(temporary)
                for name in files:
                    target = sparse / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((root / name).read_bytes())
                (sparse / 'unselected-control.txt').write_text('not a classifier input\n')

                def git(*args, input=None):
                    return subprocess.run(['git', '-c', 'core.autocrlf=false', *args],
                        cwd=sparse, input=input, capture_output=True, text=True,
                        check=True, timeout=15)

                git('init', '--quiet')
                git('add', '.')
                git('-c', 'user.name=Sparse CI control', '-c',
                    'user.email=sparse-ci@example.invalid', 'commit', '--quiet', '-m', 'fixture')
                for omitted in (None, '/tools/ci_suite_inventory.py', '/tools/ci/suites.d/'):
                    selected = patterns if omitted is None else patterns + '\n!' + omitted + '\n'
                    git('sparse-checkout', 'set', '--no-cone', '--stdin', input=selected)
                    self.assertFalse((sparse / 'unselected-control.txt').exists())
                    run = subprocess.run([sys.executable, '-I', '-B', '-c', probe, job],
                        cwd=sparse, input=json.dumps(results), capture_output=True,
                        text=True, timeout=15)
                    with self.subTest(job=job, omitted=omitted):
                        if omitted == '/tools/ci_suite_inventory.py':
                            self.assertNotEqual(run.returncode, 0)
                            self.assertIn('ImportError', run.stderr)
                            self.assertIn('ci_suite_inventory', run.stderr)
                            continue
                        if omitted is not None:
                            # A missing suite fragment may fail closed immediately
                            # or yield a different inventory; it cannot appear complete.
                            if run.returncode == 0:
                                self.assertNotEqual(json.loads(run.stdout)['inventory'], expected_digest)
                            continue
                        self.assertEqual(run.returncode, 0, run.stderr)
                        observed = json.loads(run.stdout)
                        self.assertEqual(observed['inventory'], expected_digest)
                        if job == 'profile':
                            self.assertEqual(observed['outputs'], outputs)
                        else:
                            self.assertEqual(observed['required'], required)
