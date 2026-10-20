"""Owning Java packet wiring; source controls do not qualify filesystem errors."""
import hashlib
import json
import unittest

from tools.ci_lane_inventory import workflow_model
from tools.rust_capsule_project import ROOT


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def model():
    return workflow_model((ROOT/'.github/workflows/java-guest-feasibility.yml').read_bytes().decode('utf-8'))


class JavaScratchWiring(unittest.TestCase):
    def test_original_normal_parent_and_dependency_programmes_remain_exact(self):
        jobs = model()['jobs']
        parent = dict(jobs['compiler-component'])
        self.assertEqual(parent['timeout-minutes'], 55)
        self.assertNotIn('if', parent)
        self.assertEqual(len(parent['steps']), 45)
        parent['steps'] = parent['steps'][:-2]
        self.assertEqual(signature(parent), '675efc9337b2541aa3e3ded18bc473fb3109c5653794d80c347a45a539c12fb6')
        dependency = dict(jobs['dependency-ingestion'])
        self.assertEqual(dependency.pop('if'),
            "${{ github.event_name != 'workflow_dispatch' || !inputs.qualify-scratch-refusals }}")
        self.assertEqual(signature(dependency), '610ba34e0cd9c37dacdc2f5c1575272cc609d62f261656ff145e4bdc22f4694e')
        selector = model()['on']['workflow_dispatch']['inputs']['qualify-scratch-refusals']
        self.assertEqual(selector['type'], 'boolean')
        self.assertIs(selector['default'], False)

    def test_public_bundle_is_from_this_same_normal_run_and_original_native_directory(self):
        jobs = model()['jobs']
        export, upload = jobs['compiler-component']['steps'][-2:]
        self.assertIn('--export-bundle --language java', export['run'])
        self.assertIn('--native-qualification "$RUNNER_TEMP/java-capsule-authoring"', export['run'])
        self.assertIn('--native-directory "$GITHUB_WORKSPACE/target/debug"', export['run'])
        self.assertEqual(upload['with']['name'], 'java-scratch-prepared-${{ github.sha }}')
        child = jobs['scratch-refusals']
        download = next(s for s in child['steps'] if 'download-artifact@' in s.get('uses', ''))
        self.assertEqual(download['with']['name'], upload['with']['name'])
        self.assertNotIn('run-id', download['with'])
        self.assertEqual(download['with']['path'], '${{ runner.temp }}/java-scratch-prepared')

    def test_separate_twenty_minute_child_does_not_build_a_host_or_install_rust(self):
        child = model()['jobs']['scratch-refusals']
        self.assertEqual(child['needs'], 'compiler-component')
        self.assertEqual(child['timeout-minutes'], 20)
        self.assertFalse(any('rust' in s.get('uses', '') for s in child['steps']))
        commands = '\n'.join(s.get('run', '') for s in child['steps'])
        self.assertNotIn('cargo ', commands)
        self.assertIn('tools/qualify_sdk_scratch.py --language java', commands)
        self.assertIn('--wasi-sdk "$RUNNER_TEMP/wasi-sdk-29.0-x86_64-linux"', commands)
        self.assertIn('--native-qualification "$RUNNER_TEMP/java-scratch-prepared"', commands)
        self.assertNotIn('--runtime-profile', commands)
        retained = child['steps'][-1]
        self.assertEqual(retained['if'], 'always()')
        for name in ('FAILED.json', 'compatibility-execution-report.json', 'node/workflow.json', 'node/controls/*.json'):
            self.assertIn('/java-scratch-refusals/'+name, retained['with']['path'])

    def test_child_compiler_and_jdk_are_the_same_pinned_tools_as_original_parent(self):
        jobs = model()['jobs'];parent = jobs['compiler-component']['steps'];child = jobs['scratch-refusals']['steps']
        original = next(s['run'] for s in parent if s.get('name') == 'Install pinned compiler tools')
        selected = next(s['run'] for s in child if s.get('name') == 'Install only the pinned ordinary Java component compiler')
        self.assertEqual(selected.replace('          ', ''),
            original.replace('set -euo pipefail\n', 'set -euo pipefail\npython3 -m pip install --requirement tools/requirements.lock\n', 1).replace('          ', ''))
        for action in ('actions/setup-java@', 'bytecodealliance/actions/wasm-tools/setup@'):
            self.assertEqual(next(s for s in child if action in s.get('uses', '')),
                             next(s for s in parent if action in s.get('uses', '')))


if __name__ == '__main__': unittest.main()
