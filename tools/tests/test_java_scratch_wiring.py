"""Owning Java packet wiring; source controls do not qualify filesystem errors."""
import copy
import hashlib
import json
import unittest

from tools.ci_lane_inventory import workflow_model
from tools.rust_capsule_project import ROOT


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def model():
    return workflow_model(historical_checkout((ROOT/'.github/workflows/java-guest-feasibility.yml').read_bytes()).decode('utf-8'))


def historical_cache_selection(steps):
    """Invert only the reviewed current restore/save revisions for the old guard."""
    result = copy.deepcopy(steps)
    for action in ('restore', 'save'):
        prefix = 'KirilsTurkins/lsf-cache/' + action + '@'
        matches = [step for step in result if step.get('uses', '').startswith(prefix)]
        if len(matches) != 1 or matches[0]['uses'] != prefix + 'ec176dce9471270c8a9be1289040c0a8fd6aa708':
            raise AssertionError('historical-cache-selection-exact-current-required')
        matches[0]['uses'] = prefix + '2ff27e45011b8bcf31ef566ae84c1c923c8aea69'
    return result


def original_compiler_parent(test, parent, *, historical_security=True):
    """Invert only reviewed current changes before historical comparisons."""
    parent = copy.deepcopy(parent)
    # Keep the old workflow fingerprints while requiring the reviewed current
    # finite timeout exactly; no command or other deadline is normalized.
    test.assertEqual(parent['timeout-minutes'], 75)
    parent['timeout-minutes'] = 55
    test.assertEqual(parent.pop('permissions'), {'contents': 'read', 'actions': 'read'})
    steps = parent['steps']
    # Project the reviewed bounded replacement back to the historical action
    # only after authenticating its complete current command and authority.
    wasm = [step for step in steps if step.get('name') == 'Install the verified wasm-tools release asset']
    test.assertEqual(len(wasm), 1)
    test.assertEqual(signature(wasm[0]), 'cb32fca7dcd5a442c8253a3f5afc18d71fc1d3131c78d91bfbecebee9259e2a7')
    wasm_pin = ('9244ec9f4725400c84054e3e6ec97514cadddf53' if historical_security
                else '1ce6e3461b7d83b4b5a5a6557870b4fdfd4386ce')
    steps[steps.index(wasm[0])] = {'uses': 'KirilsTurkins/lsf-bytecodealliance-actions/wasm-tools/setup@' + wasm_pin,
                                  'with': {'version': '1.254.0'}}
    # The independently qualified final-import pair was added after the old
    # baseline. Preserve an exact guard on both complete steps before removal.
    for name, expected in (
        ('Prepare the Java final-import admission control', 'c39b46b29451e8cd7d9a5c5947387c063ee448e521fd8a696ac43236da2aedb5'),
        ('Refuse a test-signed unknown import and run the fresh valid tenant', '096e91c38c25e3dcd124802f5bb454bd56be723dbadfb50b51f3868b5d96a789')):
        matches = [step for step in steps if step.get('name') == name]
        test.assertEqual(len(matches), 1)
        test.assertEqual(signature(matches[0]), expected)
        steps.remove(matches[0])
    retained = next(step for step in steps if step.get('name') ==
                    'Retain diagnostics, generated source and component candidates')
    final_import = '${{ runner.temp }}/java-standard-timers/final-import/**'
    test.assertEqual(retained['with']['path'].splitlines().count(final_import), 1)
    retained['with']['path'] = retained['with']['path'].replace(final_import + '\n', '', 1)
    index = next(i for i, step in enumerate(steps) if step.get('name') == 'Install pinned compiler tools')
    selected = steps[index - 2:index + 2]
    test.assertEqual([step.get('name') for step in selected], [
        'Select the runner-owned compiler archive cache',
        'Restore untrusted source-pinned Java prepared inputs',
        'Install pinned compiler tools',
        'Save only reverified Java prepared input bytes'])
    # Covers every command, action SHA, cache key/path, token scope and condition.
    test.assertEqual(signature(historical_cache_selection(selected)),
        'f145f3a3fbb98a7473f7c35bb07b1b3fd82b3f82a5e54003fc04f72755bad476')
    legacy = next(step['run'] for step in model()['jobs']['scratch-refusals']['steps']
        if step.get('name') == 'Install only the pinned ordinary Java component compiler')
    test.assertEqual(hashlib.sha256(legacy.encode()).hexdigest(),
        'a4e2763d338b1b6d304092eb90a6051c155dcdbb0f7afb07fb4a5d32204cf0e5')
    prerequisite = 'python3 -m pip install --requirement tools/requirements.lock\n'
    test.assertEqual(legacy.count(prerequisite), 1)
    install = copy.deepcopy(selected[2])
    test.assertEqual(install.pop('env'), {'GH_TOKEN': '${{ github.token }}'})
    install['run'] = legacy.replace(prerequisite, '', 1)
    steps[index - 2:index + 2] = [install]
    routed = [(i, step) for i, step in enumerate(steps)
        if '$LSF_JAVA_WASI_SDK' in step.get('run', '')]
    test.assertEqual([i for i, _ in routed],
        [13, 15, 16, 18, 22, 24, 26, 28, 30, 33, 35, 36, 37, 38, 39, 41, 43])
    test.assertEqual(signature(routed),
        '9a2e5bc2032e49606bf83c8d370a4ce68db128582e1d704fc9ca2fabc9bb3609')
    for _, step in routed:
        selected = '--wasi-sdk "$LSF_JAVA_WASI_SDK"'
        test.assertEqual(step['run'].count(selected), 1)
        step['run'] = step['run'].replace(selected,
            '--wasi-sdk "$RUNNER_TEMP/wasi-sdk-29.0-x86_64-linux"', 1)
    return parent


from tools.tests.test_sdk_scratch_qualification import historical_security_actions


def historical_checkout(value):
    """Authenticate the current action before the exact historical pin inverse."""
    value = historical_security_actions(value)
    prefix = 'KirilsTurkins/lsf-checkout@'
    current = prefix + '4d310727149d3abacc52b5dcb0a1c4d18b345d13'
    previous = prefix + 'c3024dfac542bb46ebccc7829ddf1f95e0be8da9'
    if type(value) is bytes:
        prefix, current, previous = (item.encode('ascii') for item in (prefix, current, previous))
    if type(value) not in (str, bytes) or not value.count(current) or value.count(prefix) != value.count(current):
        raise AssertionError('historical-workflow-exact-current-checkout-required')
    return value.replace(current, previous)


class JavaScratchWiring(unittest.TestCase):
    def test_current_wasm_and_final_import_projection_rejects_changed_inputs(self):
        parent = model()['jobs']['compiler-component']
        for name in ('Install the verified wasm-tools release asset',
                     'Prepare the Java final-import admission control',
                     'Refuse a test-signed unknown import and run the fresh valid tenant'):
            with self.subTest(name=name):
                changed = copy.deepcopy(parent)
                step = next(step for step in changed['steps'] if step.get('name') == name)
                step['run'] += '\nchanged\n'
                with self.assertRaises(AssertionError):
                    original_compiler_parent(self, changed)
        changed = copy.deepcopy(parent)
        retained = next(step for step in changed['steps'] if step.get('name') ==
                        'Retain diagnostics, generated source and component candidates')
        retained['with']['path'] += '${{ runner.temp }}/java-standard-timers/final-import/**\n'
        with self.assertRaises(AssertionError):
            original_compiler_parent(self, changed)

    def test_cache_projection_requires_both_exact_current_refs_and_preserves_other_fields(self):
        steps = model()['jobs']['compiler-component']['steps']
        index = next(i for i, step in enumerate(steps) if step.get('name') == 'Install pinned compiler tools')
        selected = steps[index - 2:index + 2]
        expected = 'f145f3a3fbb98a7473f7c35bb07b1b3fd82b3f82a5e54003fc04f72755bad476'
        self.assertEqual(signature(historical_cache_selection(selected)), expected)
        for action in ('restore', 'save'):
            for suffix in ('2ff27e45011b8bcf31ef566ae84c1c923c8aea69', '0' * 40):
                altered = copy.deepcopy(selected)
                row = next(step for step in altered if step.get('uses', '').startswith('KirilsTurkins/lsf-cache/' + action + '@'))
                row['uses'] = 'KirilsTurkins/lsf-cache/' + action + '@' + suffix
                with self.assertRaisesRegex(AssertionError, 'historical-cache-selection-exact-current-required'):
                    historical_cache_selection(altered)
        altered = copy.deepcopy(selected)
        restore = next(step for step in altered if step.get('uses', '').startswith('KirilsTurkins/lsf-cache/restore@'))
        duplicate = altered + [copy.deepcopy(restore)]
        with self.assertRaisesRegex(AssertionError, 'historical-cache-selection-exact-current-required'):
            historical_cache_selection(duplicate)
        with self.assertRaisesRegex(AssertionError, 'historical-cache-selection-exact-current-required'):
            historical_cache_selection([step for step in altered if step is not restore])
        restore['with']['path'] += '-changed'
        self.assertNotEqual(signature(historical_cache_selection(altered)), expected)

    def test_original_normal_parent_and_dependency_programmes_remain_exact(self):
        workflow = model()
        from tools.tests.qualification_selection import restore_java_pre_tooling_view
        restore_java_pre_tooling_view(self, workflow)
        private = workflow['on']['workflow_dispatch']['inputs'].pop('public_fiber_private_scalar_llvm')
        self.assertEqual(private['type'], 'boolean');self.assertIs(private['default'], False)
        clause = " && (github.event_name != 'workflow_dispatch' || !inputs.public_fiber_private_scalar_llvm)"
        for name in ('compiler-component', 'dependency-ingestion', 'http-public-spi'):
            self.assertEqual(workflow['jobs'][name]['if'].count(clause), 1)
            workflow['jobs'][name]['if'] = workflow['jobs'][name]['if'].replace(clause, '', 1)
        self.assertEqual(workflow['jobs']['public-fiber-assembly']['if'],
            "${{ github.event_name == 'workflow_dispatch' && (inputs.public_fiber_assembly || inputs.public_fiber_derived_llvm || inputs.public_fiber_private_scalar_llvm) }}")
        workflow['jobs']['public-fiber-assembly']['if'] = "${{ github.event_name == 'workflow_dispatch' && (inputs.public_fiber_assembly || inputs.public_fiber_derived_llvm) }}"
        derived = workflow['on']['workflow_dispatch']['inputs'].pop('public_fiber_derived_llvm')
        self.assertEqual(derived['type'], 'boolean');self.assertIs(derived['default'], False)
        for name, clause in (
                ('compiler-component', " && (github.event_name != 'workflow_dispatch' || !inputs.public_fiber_derived_llvm)"),
                ('dependency-ingestion', " && (github.event_name != 'workflow_dispatch' || !inputs.public_fiber_derived_llvm)"),
                ('http-public-spi', ' && !inputs.public_fiber_derived_llvm')):
            self.assertEqual(workflow['jobs'][name]['if'].count(clause), 1)
            workflow['jobs'][name]['if'] = workflow['jobs'][name]['if'].replace(clause, '', 1)
        self.assertEqual(workflow['jobs']['public-fiber-assembly']['if'],
            "${{ github.event_name == 'workflow_dispatch' && (inputs.public_fiber_assembly || inputs.public_fiber_derived_llvm) }}")
        workflow['jobs']['public-fiber-assembly']['if'] = "${{ github.event_name == 'workflow_dispatch' && inputs.public_fiber_assembly }}"
        public = workflow['on']['workflow_dispatch']['inputs'].pop('public_fiber_assembly')
        self.assertEqual(public['type'], 'boolean');self.assertIs(public['default'], False)
        assembly = workflow['jobs'].pop('public-fiber-assembly')
        self.assertEqual(assembly['if'],
            "${{ github.event_name == 'workflow_dispatch' && inputs.public_fiber_assembly }}")
        self.assertEqual(workflow['jobs']['compiler-component']['if'],
            "${{ (github.event_name != 'workflow_dispatch' || !inputs.java_http_spi) && (github.event_name != 'workflow_dispatch' || !inputs.public_fiber_assembly) }}")
        workflow['jobs']['compiler-component']['if'] = "${{ github.event_name != 'workflow_dispatch' || !inputs.java_http_spi }}"
        for name, clause in (
                ('dependency-ingestion', " && (github.event_name != 'workflow_dispatch' || !inputs.public_fiber_assembly)"),
                ('http-public-spi', ' && !inputs.public_fiber_assembly')):
            self.assertEqual(workflow['jobs'][name]['if'].count(clause), 1)
            workflow['jobs'][name]['if'] = workflow['jobs'][name]['if'].replace(clause, '', 1)
        jobs = workflow['jobs']
        parent = original_compiler_parent(self, jobs['compiler-component'])
        self.assertEqual(parent['timeout-minutes'], 55)
        self.assertEqual(parent.pop('if'),
            "${{ github.event_name != 'workflow_dispatch' || !inputs.java_http_spi }}")
        self.assertEqual(len(parent['steps']), 45)
        retained = next(step for step in parent['steps'] if step.get('name') ==
            'Retain diagnostics, generated source and component candidates')
        added = '${{ runner.temp }}/java-activation-fibers/build/component-inputs/**'
        self.assertEqual(retained['with']['path'].splitlines().count(added), 1)
        retained['with']['path'] = retained['with']['path'].replace(added + '\n', '', 1)
        parent['steps'] = [step for step in parent['steps'] if step.get('name') not in {
            'Export only exact normal public prerequisites for the separate Java scratch packet',
            'Retain verified normal Java products without keys or compiler caches'}]
        self.assertEqual(len(parent['steps']), 43)
        self.assertEqual(signature(parent), 'd7166e281fd131f0e43f0412e680c79f89c14f0a614fc2acfea0ff84b70563ed')
        dependency = dict(jobs['dependency-ingestion'])
        self.assertEqual(dependency.pop('if'),
            "${{ (github.event_name != 'workflow_dispatch' || !inputs.qualify-scratch-refusals) && (github.event_name != 'workflow_dispatch' || !inputs.java_http_spi) }}")
        self.assertEqual(signature(dependency), 'd79386c6ceabb835c556a46db3b480f43e87f3f35bd9189f4e424c4281eca44f')
        selector = model()['on']['workflow_dispatch']['inputs']['qualify-scratch-refusals']
        self.assertEqual(selector['type'], 'boolean')
        self.assertIs(selector['default'], False)

    def test_public_bundle_is_from_this_same_normal_run_and_original_native_directory(self):
        jobs = model()['jobs']
        steps = jobs['compiler-component']['steps']
        qualified = next(index for index, step in enumerate(steps) if step.get('name') ==
            'Qualify standalone Java projects, nine SDK components, signed node and printed guide')
        index = next(index for index, step in enumerate(steps) if step.get('name') ==
            'Export only exact normal public prerequisites for the separate Java scratch packet')
        self.assertEqual(index, qualified + 1,
            'freeze the observed binaries before later Cargo work can overwrite target/debug')
        export, upload = steps[index:index+2]
        self.assertEqual(upload.get('name'), 'Retain verified normal Java products without keys or compiler caches')
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
        self.assertIn('sudo apt-get install --yes bubblewrap', commands)
        self.assertIn('sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0', commands)
        retained = child['steps'][-1]
        self.assertEqual(retained['if'], 'always()')
        for name in ('FAILED.json', 'compatibility-execution-report.json', 'node/workflow.json', 'node/controls/*.json'):
            self.assertIn('/java-scratch-refusals/'+name, retained['with']['path'])

    def test_child_compiler_and_jdk_are_the_same_pinned_tools_as_original_parent(self):
        jobs = model()['jobs'];parent = original_compiler_parent(self, jobs['compiler-component'])['steps'];child = jobs['scratch-refusals']['steps']
        original = next(s['run'] for s in parent if s.get('name') == 'Install pinned compiler tools')
        selected = next(s['run'] for s in child if s.get('name') == 'Install only the pinned ordinary Java component compiler')
        self.assertEqual(selected.replace('          ', ''),
            original.replace('set -euo pipefail\n', 'set -euo pipefail\npython3 -m pip install --requirement tools/requirements.lock\n', 1).replace('          ', ''))
        for action in ('KirilsTurkins/lsf-setup-java@', 'KirilsTurkins/lsf-bytecodealliance-actions/wasm-tools/setup@'):
            self.assertEqual(next(s for s in child if action in s.get('uses', '')),
                             next(s for s in parent if action in s.get('uses', '')))


if __name__ == '__main__': unittest.main()
