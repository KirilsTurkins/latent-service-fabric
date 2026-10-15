"""Real GNU Make orchestration with controlled owners; not LSF execution evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
RECORDER = r'''
import json, os, pathlib, sys, time
args = sys.argv[1:]
if args[:2] == ['tools/ci_cargo.py', 'run']:
    stage = 'cargo.' + args[2]
elif args[0] == 'tools/aot_test_inputs.py':
    stage = 'aot.' + args[1]
elif args[0] == 'tools/ci_suite_discovery.py':
    stage = 'discovery.' + ('inventory' if '--inventory' in args else args[args.index('--recipe')+1] if '--recipe' in args else 'custom')
elif args[0] == 'contract-script':
    stage = 'contracts.' + args[1]
else:
    stage = args[0]
def record(event):
    with open(os.environ['MAKE_TEST_LOG'], 'a') as output:
        output.write(json.dumps({'event': event, 'stage': stage, 'args': args,
            'selectors': {key: os.environ.get(key) for key in ('LSF_AOT_TEST_INPUTS', 'LSF_AOT_TEST_INPUTS_SHA256', 'LSF_AOT_TEST_EXECUTION_ONLY', 'LSF_AOT_REQUIRE_LINUX', 'CARGO_MANIFEST_DIR', 'LD_LIBRARY_PATH')},
            'time': time.monotonic_ns()}) + '\n')
record('start')
time.sleep(0.003)
if os.environ.get('MAKE_TEST_FAIL') == stage:
    print('controlled failure: ' + stage, file=sys.stderr)
    record('end')
    raise SystemExit(9)
if stage == 'aot.environment':
    print('CARGO_MANIFEST_DIR=must-not-be-exported')
    print('LD_LIBRARY_PATH=must-not-be-exported')
    print('LSF_AOT_TEST_INPUTS=/owned/input with spaces; untouched')
    print('LSF_AOT_TEST_INPUTS_SHA256=' + 'a'*64)
    print('LSF_AOT_TEST_EXECUTION_ONLY=1')
    print('LSF_AOT_REQUIRE_LINUX=1')
elif stage == 'cargo.prepare':
    path = pathlib.Path(args[args.index('--inventory')+1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('controlled producer, not a Cargo inventory')
elif stage == 'aot.prepare':
    path = pathlib.Path(args[args.index('--output')+1])
    path.mkdir(parents=True)
    (path/'manifest.json').write_text('{}')
elif stage == 'discovery.inventory':
    path = pathlib.Path(args[args.index('--receipt')+1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"qualification":false}')
else:
    print('controlled owner: ' + stage)
record('end')
'''


class MakefileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.make = shutil.which('make')
        if os.name != 'posix' or not cls.make or not shutil.which('bash'):
            if os.environ.get('LSF_REQUIRE_NATIVE_PROCESS_TESTS') == '1':
                raise AssertionError('Required Make orchestration tests need GNU Make and Bash on Linux')
            raise unittest.SkipTest('GNU Make/Bash orchestration requires the POSIX tool environment')
        result = subprocess.run([cls.make, '--version'], text=True, capture_output=True, timeout=5, check=True)
        if not result.stdout.startswith('GNU Make '):
            raise AssertionError('These recipes require GNU Make')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lsf-make-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'working tree'
        self.root.mkdir()
        shutil.copyfile(ROOT / 'Makefile', self.root / 'Makefile')
        self.log = self.root / 'events.jsonl'
        self.recorder = self.root / 'record owner.py'
        self.recorder.write_text(RECORDER)
        tools, binaries = self.root / 'tools', self.root / 'bin'
        tools.mkdir()
        binaries.mkdir()
        for name, owner in (('validate_contracts.sh', 'contract-script'), ('validate_sdks.sh', 'sdk-script')):
            (tools / name).write_text('exec "$MAKE_TEST_PYTHON" "$MAKE_TEST_RECORDER" ' + owner + ' "$@"\n')
        (binaries / 'cargo').write_text('#!/usr/bin/env bash\nexec "$MAKE_TEST_PYTHON" "$MAKE_TEST_RECORDER" cargo-cli "$@"\n')
        (binaries / 'git').write_text('#!/usr/bin/env bash\nset -eu\nif [[ -n "${MAKE_TEST_GIT_FAILURE:-}" ]]; then exit 33; fi\nif [[ "$1" == status ]]; then printf "%s" "${MAKE_TEST_DIRTY:-}"; else printf "%s\\n" aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; fi\n')
        for path in binaries.iterdir():
            path.chmod(0o755)
        self.environment = {key: value for key, value in os.environ.items()
                            if key not in {'MAKEFLAGS', 'MFLAGS', 'GNUMAKEFLAGS'}}
        self.environment.update(PATH=str(binaries) + os.pathsep + os.environ['PATH'],
            MAKE_TEST_LOG=str(self.log), MAKE_TEST_PYTHON=sys.executable, MAKE_TEST_RECORDER=str(self.recorder),
            CARGO_MANIFEST_DIR='original-cargo-directory', LD_LIBRARY_PATH='original-library-path')
        frontend = shlex.join([sys.executable, str(self.recorder)])
        self.variables = ['PYTHON=' + frontend, 'NODE=' + frontend,
                          'BOOTSTRAP_NPM=' + frontend + ' bootstrap-npm']

    def run_make(self, *arguments, fail=None, dirty=None):
        environment = dict(self.environment)
        if fail:
            environment['MAKE_TEST_FAIL'] = fail
        if dirty:
            environment['MAKE_TEST_DIRTY'] = dirty
        return subprocess.run([self.make, '--no-print-directory', *self.variables, *arguments],
            cwd=self.root, env=environment, text=True, capture_output=True, timeout=20)

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def calls(self):
        return [event for event in self.events() if event['event'] == 'start']

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_default_is_help_without_build_install_or_test_side_effects(self):
        before = set(self.root.iterdir())
        result = self.run_make()
        self.assert_success(result)
        self.assertIn('test-plan', result.stdout)
        self.assertIn('website-validate', result.stdout)
        self.assertNotIn('phase1-foundation', result.stdout)
        self.assertEqual(self.calls(), [])
        self.assertEqual(set(self.root.iterdir()), before)

    def test_exact_selectors_and_paths_are_single_arguments_without_shell_execution(self):
        case = "module::has 'quotes'; touch injected"
        inventory = "target/local tests/one'case.jsonl"
        for target in ('test-plan', 'test-prepare', 'test-check', 'test-run'):
            self.assert_success(self.run_make(target, 'SUITE=latent-core.lib.latent-core',
                'CASE=' + case, 'INVENTORY=' + inventory, 'FORMAT=json'))
            args = self.calls()[-1]['args']
            self.assertEqual(args[0:2], ['tools/test.py', target.removeprefix('test-')])
            self.assertEqual(args[args.index('--case')+1], case)
            self.assertEqual(args[args.index('--inventory')+1], inventory)
        self.assertFalse((self.root / 'injected').exists())
        self.assertEqual(len(self.calls()), 4)

    def test_missing_selection_inputs_fail_before_an_owner_is_started(self):
        for arguments in (('test-plan',), ('test-run', 'SUITE=selected'),
                          ('test-prepare', 'INVENTORY=target/owned.jsonl'), ('test-reproduce',)):
            with self.subTest(arguments=arguments):
                self.assertNotEqual(self.run_make(*arguments).returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_execution_and_reproduction_never_prepare_or_allow_changed_replay(self):
        self.assert_success(self.run_make('test-run', 'SUITE=selected', 'INVENTORY=target/owned.jsonl'))
        self.assert_success(self.run_make('test-reproduce', 'REPORT=failed report.json', 'INVENTORY=target/owned.jsonl'))
        self.assertEqual([call['args'][1] for call in self.calls()], ['run', 'reproduce'])
        self.assertEqual(self.calls()[1]['args'][2], 'failed report.json')
        self.assertNotIn('--allow-changed-checkout', self.calls()[1]['args'])

    def test_aot_preparation_validates_existing_inputs_without_rebuilding(self):
        self.assert_success(self.run_make('workspace-prepare', 'aot-prepare'))
        self.assertEqual([call['stage'] for call in self.calls()], ['cargo.prepare', 'aot.prepare'])
        self.assert_success(self.run_make('aot-prepare'))
        self.assertEqual(self.calls()[-1]['stage'], 'aot.validate')

    def test_workspace_execution_preserves_all_recipes_checks_and_cargo_environment(self):
        self.assert_success(self.run_make('test'))
        self.assertEqual([call['stage'] for call in self.calls()], [
            'aot.environment', 'discovery.inventory', 'cargo.workspace-tests', 'discovery.custom',
            'cargo.doctests', 'discovery.explicit-doctests', 'cargo.signing-compatibility', 'discovery.signing-compatibility'])
        for call in self.calls()[2:]:
            self.assertEqual(call['selectors']['LSF_AOT_TEST_INPUTS'], '/owned/input with spaces; untouched')
            self.assertEqual(call['selectors']['LSF_AOT_TEST_EXECUTION_ONLY'], '1')
            self.assertEqual(call['selectors']['CARGO_MANIFEST_DIR'], 'original-cargo-directory')
            self.assertEqual(call['selectors']['LD_LIBRARY_PATH'], 'original-library-path')
        self.assertEqual({path.name for path in (self.root / 'target/make/test-results').iterdir()},
            {'discovery.json', 'workspace-tests.log', 'doctests.log', 'signing-compatibility.log'})

    def test_failed_preparation_discovery_or_test_cannot_be_hidden_by_tee(self):
        for stage in ('aot.environment', 'discovery.inventory', 'cargo.workspace-tests',
                      'discovery.custom', 'cargo.doctests', 'discovery.explicit-doctests',
                      'cargo.signing-compatibility', 'discovery.signing-compatibility'):
            with self.subTest(stage=stage):
                root = 'target/' + stage
                before = len(self.calls())
                result = self.run_make('test', 'WORKSPACE_ROOT=' + root, fail=stage)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.calls()[before:][-1]['stage'], stage)

    def test_existing_execution_logs_are_not_overwritten(self):
        self.assert_success(self.run_make('test'))
        reports = self.root / 'target/make/test-results'
        before = {path.name: path.read_bytes() for path in reports.iterdir()}
        count = len(self.calls())
        self.assertNotEqual(self.run_make('test').returncode, 0)
        self.assertEqual([call['stage'] for call in self.calls()[count:]], ['aot.environment'])
        self.assertEqual({path.name: path.read_bytes() for path in reports.iterdir()}, before)

    def test_missing_git_identity_blocks_discovery_and_workspace_execution(self):
        self.environment['MAKE_TEST_GIT_FAILURE'] = '1'
        self.assertNotEqual(self.run_make('workspace-discover').returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertNotEqual(self.run_make('test').returncode, 0)
        self.assertEqual([call['stage'] for call in self.calls()], ['aot.environment'])

    def test_broad_validation_preflight_refuses_dirty_source_before_building(self):
        result = self.run_make('validate', dirty=' M changed-source.rs')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('clean tracked checkout', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_parallel_make_keeps_fixture_writers_and_full_validation_order_serial(self):
        self.assert_success(self.run_make('-j8', 'validate'))
        events = self.events()
        self.assertEqual([event['event'] for event in events], ['start', 'end'] * (len(events)//2))
        stages = [call['stage'] for call in self.calls()]
        self.assertLess(stages.index('contracts.all'), stages.index('cargo.prepare'))
        self.assertLess(stages.index('sdk-script'), stages.index('cargo.prepare'))
        self.assertLess(stages.index('cargo.prepare'), stages.index('aot.prepare'))
        self.assertLess(stages.index('aot.prepare'), stages.index('cargo.workspace-tests'))
        self.assertEqual({stage for stage in stages if stage.startswith('cargo.')}, {
            'cargo.format', 'cargo.workspace-check', 'cargo.bindings', 'cargo.production', 'cargo.clippy',
            'cargo.deterministic', 'cargo.prepare', 'cargo.workspace-tests', 'cargo.doctests', 'cargo.signing-compatibility'})

    def test_named_contract_lane_is_exact_and_phony_checks_cannot_be_skipped_by_files(self):
        (self.root / 'docs').write_text('not an up-to-date validation receipt')
        self.assert_success(self.run_make('docs', 'contracts-bindings'))
        self.assertEqual([call['stage'] for call in self.calls()], ['tools/validate_docs.py', 'contracts.bindings'])

    def test_website_validation_uses_prepared_npm_without_installing(self):
        self.assert_success(self.run_make('website-validate'))
        calls = self.calls()
        self.assertEqual(calls[0]['args'], ['website/scripts/check-package-manager.mjs'])
        self.assertEqual([call['args'] for call in calls[1:]], [
            ['website/toolchain/node_modules/npm/bin/npm-cli.js', '--prefix', 'website', *args]
            for args in (['run', 'check'], ['test'], ['run', 'build'], ['run', 'build:root'], ['run', 'test:build'])])
        self.assertNotIn('bootstrap-npm', [call['stage'] for call in calls])


if __name__ == '__main__':
    unittest.main()
