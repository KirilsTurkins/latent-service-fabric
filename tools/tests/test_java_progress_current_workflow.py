"""Keep the current-host route separate from the historical signed programme."""
from copy import deepcopy
import json
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = '.github/workflows/java-checkpoint-current.yml'
CONTRACT = ROOT/'tools/ci/contracts/workflows/java-checkpoint-current.yml'
BRANCH = 'feat/java-current-checkpoint-20261104'


def workflow(path):
    document = yaml.safe_load((ROOT/path).read_text(encoding='utf-8'))
    if True in document:
        document['on'] = document.pop(True)
    return document


def normalized_job(job):
    result = deepcopy(job)
    for step in result['steps']:
        if 'uses' in step:
            step['uses'] = step['uses'].split('@', 1)[0]
    return result


class CurrentJavaProgressWorkflow(unittest.TestCase):
    def test_policy_and_job_contracts_match_executable_workflow(self):
        document = workflow(WORKFLOW)
        policy = json.loads((CONTRACT/'workflow.json').read_text(encoding='utf-8'))
        self.assertEqual(policy['policy'], {k:v for k,v in document.items() if k != 'jobs'})
        self.assertEqual(policy['requiredJobs'], ['compiler-context', 'signed-current'])
        self.assertEqual(set(document['jobs']), set(policy['requiredJobs']))
        for name, job in document['jobs'].items():
            with self.subTest(job=name):
                record = json.loads((CONTRACT/'jobs'/f'{name}.json').read_text(encoding='utf-8'))
                self.assertEqual(record['workflow'], WORKFLOW)
                self.assertEqual(record['jobId'], name)
                self.assertEqual(record['definition'], normalized_job(job))

    def test_current_route_preserves_historical_program_and_limits(self):
        document = workflow(WORKFLOW)
        historical = workflow('.github/workflows/java-checkpoint-context.yml')
        self.assertEqual(document['on'], {'push': {'branches': [BRANCH]}})
        self.assertEqual(document['permissions'], {'contents': 'read'})
        self.assertFalse(document['concurrency']['cancel-in-progress'])
        self.assertEqual(document['jobs']['compiler-context'], historical['jobs']['compiler-context'])
        expected = deepcopy(historical['jobs']['signed-progress'])
        expected['name'] = 'Fresh Java progress and parked GC regression on current authenticated native products'
        expected['if'] = f"github.ref == 'refs/heads/{BRANCH}'"
        steps = expected['steps']
        checks = next(s for s in steps if s.get('name') ==
            'Check the branch route and existing compiler and GC boundaries')
        slash_line = 'python3 -B -m unittest tools.tests.test_java_progress_workflow ' + chr(92) + '\n'
        self.assertIn(slash_line, checks['run'])
        checks['run'] = checks['run'].replace(slash_line, slash_line +
            '  tools.tests.test_java_progress_current_workflow ' + chr(92) + '\n', 1)
        slash_line = '  tools.tests.test_java_checkpoint_gc ' + chr(92) + '\n'
        self.assertIn(slash_line, checks['run'])
        checks['run'] = checks['run'].replace(slash_line, slash_line +
            '  tools.tests.test_java_checkpoint_gc_current ' + chr(92) + '\n', 1)
        producer = next(i for i,s in enumerate(steps) if s.get('name') ==
            'Fetch the immutable native producer source without rebuilding')
        steps.insert(producer + 1, {
            'name': 'Fetch the current immutable native producer source without rebuilding',
            'run': 'git fetch --no-tags --depth=1 origin 678b19d42b26a12ac35f3d6de525029b82e169f7'})
        tests = next(i for i,s in enumerate(steps) if s.get('name') ==
            'Check the branch route and existing compiler and GC boundaries')
        steps.insert(tests + 1, {
            'name': 'Refuse stale current native source before compiler downloads',
            'run': 'python3 -B tools/qualify_java_checkpoint_gc_current.py --check-source-only'})
        acquire = next(s for s in steps if s.get('name') ==
            'Authenticate the five existing 193-control native products')
        acquire['name'] = 'Authenticate the five current-source native products'
        acquire['run'] = 'python3 -B tools/wasmtime_48_0_8_678b_native_products.py --output "$RUNNER_TEMP/java-progress-native"'
        build = next(s for s in steps if s.get('name') ==
            'Build a fresh component and execute the unchanged signed two-tenant GC programme')
        build['run'] = build['run'].replace('tools/qualify_java_checkpoint_gc.py',
                                             'tools/qualify_java_checkpoint_gc_current.py')
        self.assertEqual(document['jobs']['signed-current'], expected)
        reader = (ROOT/'tools/wasmtime_48_0_8_678b_native_products.py').read_text(encoding='utf-8')
        self.assertEqual(re.findall(r"^SOURCE = '([0-9a-f]{40})'$", reader, re.MULTILINE),
                         ['678b19d42b26a12ac35f3d6de525029b82e169f7'])
        old_reader = (ROOT/'tools/rust_thread_native_products.py').read_text(encoding='utf-8')
        self.assertEqual(re.findall(r"^SOURCE = '([0-9a-f]{40})'$", old_reader, re.MULTILINE),
                         ['b422af24d86344ac7abb8b8fa56c3782aab63915'])
