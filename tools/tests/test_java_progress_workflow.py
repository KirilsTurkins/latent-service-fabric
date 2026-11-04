"""Keep fresh signed progress qualification separate from JVM-only controls."""
from copy import deepcopy
import json
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = '.github/workflows/java-checkpoint-context.yml'
CONTRACT = ROOT/'tools/ci/contracts/workflows/java-checkpoint-context.yml'
BRANCH = 'feat/java-nonsuspendable-progress-20261031'


def workflow():
    document = yaml.safe_load((ROOT/WORKFLOW).read_text(encoding='utf-8'))
    # PyYAML's YAML 1.1 resolver treats the Actions key "on" as a boolean.
    if True in document:
        document['on'] = document.pop(True)
    return document


def normalized_job(job):
    result = deepcopy(job)
    for step in result['steps']:
        if 'uses' in step:
            step['uses'] = step['uses'].split('@', 1)[0]
    return result


class JavaProgressWorkflow(unittest.TestCase):
    def test_policy_and_both_job_contracts_match_executable_workflow(self):
        document = workflow()
        policy = json.loads((CONTRACT/'workflow.json').read_text(encoding='utf-8'))
        self.assertEqual(policy['policy'], {k: v for k, v in document.items() if k != 'jobs'})
        self.assertEqual(policy['requiredJobs'], ['compiler-context', 'signed-progress'])
        self.assertEqual(set(document['jobs']), set(policy['requiredJobs']))
        for name, job in document['jobs'].items():
            with self.subTest(job=name):
                contract = json.loads((CONTRACT/'jobs'/f'{name}.json').read_text(encoding='utf-8'))
                self.assertEqual(contract['jobId'], name)
                self.assertEqual(contract['workflow'], WORKFLOW)
                self.assertEqual(contract['definition'], normalized_job(job))

    def test_signed_job_is_branch_scoped_and_requires_successful_jvm_control(self):
        document = workflow()
        self.assertEqual(document['on'], {
            'push': {'branches': ['feat/java-checkpoint-context-20261023', BRANCH]},
            'workflow_dispatch': None})
        job = document['jobs']['signed-progress']
        self.assertEqual(job['if'], f"github.ref == 'refs/heads/{BRANCH}'")
        self.assertEqual(job['needs'], 'compiler-context')
        self.assertEqual(job['timeout-minutes'], 40)
        self.assertEqual(job['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertNotIn('continue-on-error', job)
        self.assertEqual(document['permissions'], {'contents': 'read'})
        self.assertFalse(document['concurrency']['cancel-in-progress'])
        compiler = document['jobs']['compiler-context']
        self.assertNotIn('needs', compiler)
        self.assertNotIn('if', compiler)
        self.assertEqual(compiler['timeout-minutes'], 10)

    def test_fresh_compilation_uses_only_authenticated_native_products(self):
        job = workflow()['jobs']['signed-progress']
        commands = [s['run'] for s in job['steps'] if 'run' in s]
        self.assertEqual(commands[0],
            'git fetch --no-tags --depth=1 origin b422af24d86344ac7abb8b8fa56c3782aab63915')
        acquire = 'python3 -B tools/rust_thread_native_products.py --output "$RUNNER_TEMP/java-progress-native"'
        self.assertIn(acquire, commands)
        build = [c for c in commands if 'tools/qualify_java_checkpoint_gc.py' in c]
        self.assertEqual(len(build), 1)
        self.assertEqual(build[0], 'python3 -B tools/qualify_java_checkpoint_gc.py \\\n'
            '  --native "$RUNNER_TEMP/java-progress-native" \\\n'
            '  --wasi-sdk "$RUNNER_TEMP/wasi-sdk-29.0-x86_64-linux" \\\n'
            '  --output "$RUNNER_TEMP/java-progress-gc"\n')
        self.assertLess(commands.index(acquire), commands.index(build[0]))
        combined = '\n'.join(commands)
        for forbidden in ('cargo ', '--read-only-cache', '--diagnostic-node', '--diagnostic-client',
                'qualify_java_checkpoint_gc_retained', '|| true'):
            self.assertNotIn(forbidden, combined)
        self.assertEqual(sum('test_java_progress_workflow' in c for c in commands), 1)

    def test_tools_are_pinned_and_credentials_do_not_reach_the_guest_build(self):
        job = workflow()['jobs']['signed-progress']
        self.assertEqual(job['env'], {'PYTHONDONTWRITEBYTECODE': '1'})
        for step in job['steps']:
            self.assertNotIn('continue-on-error', step)
            if 'uses' in step:
                self.assertRegex(step['uses'], r'^[^@]+@[0-9a-f]{40}$')
            if 'env' in step:
                self.assertIn('tools/rust_thread_native_products.py', step.get('run', ''))
                self.assertEqual(step['env'], {'GH_TOKEN': '${{ github.token }}'})
        checkout = job['steps'][0]
        self.assertFalse(checkout['with']['persist-credentials'])
        scripts = '\n'.join(s.get('run', '') for s in job['steps'])
        self.assertEqual(len(re.findall(r'[0-9a-f]{64}  \$RUNNER_TEMP/.*sha256sum --check --strict', scripts)), 2)

    def test_evidence_is_retained_on_failure_without_uploading_workspaces_or_keys(self):
        upload = workflow()['jobs']['signed-progress']['steps'][-1]
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['name'], 'java-nonsuspendable-progress-${{ github.sha }}')
        self.assertEqual(upload['with']['retention-days'], 3)
        paths = upload['with']['path'].splitlines()
        self.assertIn('${{ runner.temp }}/java-progress-gc/*.json', paths)
        self.assertIn('${{ runner.temp }}/java-progress-gc/build/component.wasm', paths)
        self.assertIn('${{ runner.temp }}/java-progress-gc/build/compiler-logs/*-java-to-c.log', paths)
        self.assertIn('${{ runner.temp }}/java-progress-gc/node/*.json', paths)
        self.assertTrue(all(p.startswith('${{ runner.temp }}/java-progress-') for p in paths))
        self.assertNotIn('${{ runner.temp }}/java-progress-gc/**', paths)
        self.assertNotIn('${{ runner.temp }}/java-progress-gc/node/**', paths)
        self.assertFalse(any('key' in p.lower() or 'credential' in p.lower() for p in paths))


if __name__ == '__main__':
    unittest.main()
