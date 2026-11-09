"""Source-only synthetic controls; no host build or historical checkout is required."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parents[1] / 'rust_http_current_controls.py'
spec = importlib.util.spec_from_file_location('rust_http_current_controls_draft', FILE)
owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner)
REPOSITORY = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'],
    text=True, timeout=10).strip())
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))


class HistoricalInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep the ordinary CI tests independent of a shallow checkout's Git
        # history. The owner authenticates and reads the actual pinned commit.
        rows = []
        for stage in owner.STAGES:
            if stage == 'rust-version':
                args = ('rustc', '--version')
            elif stage == 'release-preparation-protocol-reader-controls':
                args = ('python3', '-B', '-c', 'synthetic-python-control')
            elif stage == 'normal-host-build':
                args = ('cargo', '--config', 'ROOT/.cargo/managed-guest.toml', 'build', '--locked')
            else:
                args = ('cargo', '--config', 'ROOT/.cargo/managed-guest.toml', 'test', '--locked',
                    '-p', 'synthetic', '--lib', stage.replace('-', '_'), '--', '--exact', '--test-threads=1')
            rows.append((stage, *args))
        lines = []
        for row in rows:
            args = ["root / '.cargo/managed-guest.toml'" if value == 'ROOT/.cargo/managed-guest.toml'
                else repr(value) for value in row]
            lines.append('          commands.run(' + ', '.join(args) + ')')
        workflow = ("          python3 -B - <<'PY'\n" + '\n'.join(lines) + '\n          PY\n').encode()
        cls.workflow_sha = hashlib.sha256(workflow).hexdigest()
        cls.files = {owner.WORKFLOW: workflow}
        for stage, sources in owner.TEST_SOURCES.items():
            count = owner.TEST_COUNTS[stage]
            for index in range(count):
                path, _, needle = sources[index % len(sources)]
                name = (needle or stage.replace('-', '_') + '_') + str(index)
                cls.files[path] = cls.files.get(path, b'') + f'#[test]\nfn {name}() {{}}\n'.encode()
        for sources in owner.TEST_SOURCES.values():
            for path, _, _ in sources:
                cls.files.setdefault(path, b'')
        with patch.object(owner, 'WORKFLOW_SHA256', cls.workflow_sha):
            cls.plan = owner.historical_plan(workflow)
        cls.tests = owner.historical_tests(cls.files)

    def test_complete_fixture_contains_every_command_and_default_feature_selection(self):
        self.assertEqual(len(self.plan), 34)
        self.assertEqual(tuple(row[0] for row in self.plan), owner.STAGES)
        self.assertEqual(self.plan[0][1:], ('rustc', '--version'))
        self.assertTrue(all('--features' not in row and '--all-features' not in row
            and '--no-default-features' not in row for row in self.plan))
        self.assertEqual(len(self.tests['c-original-and-final-proof-controls']), 60)
        self.assertEqual(len(self.tests['ordinary-async-worker-owner-controls']), 11)
        self.assertFalse(any('::combined::' in name
            for name in self.tests['ordinary-async-worker-owner-controls']))

    def test_historical_workflow_or_inventory_tampering_is_refused(self):
        with patch.object(owner, 'WORKFLOW_SHA256', self.workflow_sha):
            with self.assertRaisesRegex(ValueError, 'historical-workflow'):
                owner.historical_plan(self.files[owner.WORKFLOW] + b'\n')
        changed = dict(self.files)
        selected = owner.TEST_SOURCES['closed-http-refusal-controls'][0][0]
        changed[selected] = changed[selected].replace(b'#[test]', b'#[nope]', 1)
        with self.assertRaisesRegex(ValueError, 'original-test-inventory'):
            owner.historical_tests(changed)

    def test_missing_or_duplicate_current_selector_is_refused(self):
        expected = self.tests['independent-http-dispatch-controls']
        observed = sorted(expected | {'new_current_test'})
        source = ''.join(name + ': test\n' for name in observed).encode()
        self.assertEqual(set(owner.list_tests(source, expected)), set(observed))
        for candidate in (b'', (observed[0] + ': test\n').encode(), source + source):
            with self.subTest(candidate=candidate), self.assertRaisesRegex(ValueError, 'original-test-missing-or-duplicate'):
                owner.list_tests(candidate, expected)

    def test_changed_five_product_bytes_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            files = [Path(directory) / str(index) for index in range(5)]
            for index, path in enumerate(files):
                path.write_bytes(('product-' + str(index)).encode())
            def evidence():
                return tuple((path.name, hashlib.sha256(path.read_bytes()).hexdigest()) for path in files)
            before = evidence()
            owner.same_products(before, evidence())
            files[2].write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'native-evidence-changed'):
                owner.same_products(before, evidence())

    def test_toolchain_and_ambient_cargo_config_drift_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('rustup', 'rustc', 'cargo'):
                (root / name).write_bytes(name.encode())
            (root / 'config.toml').write_bytes(b'[build]\n')
            environment = {'PATH': str(root), 'HOME': str(root), 'CARGO_HOME': str(root),
                'RUSTUP_TOOLCHAIN': '1.97.1'}
            def identify(path, maximum):
                data = path.read_bytes()
                self.assertLessEqual(len(data), maximum)
                return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            def command(argv, **_):
                return types.SimpleNamespace(stdout=(str(root / argv[-1]) + '\n').encode(), stderr=b'', returncode=0)
            with patch.object(owner.shutil, 'which', side_effect=lambda name, **_: str(root / name)):
                before = owner.toolchain_snapshot(environment, root, identify, runner=command)
                self.assertEqual(before, owner.toolchain_snapshot(environment, root, identify, runner=command))
                (root / 'cargo').write_bytes(b'changed cargo')
                with self.assertRaisesRegex(ValueError, 'native-evidence-changed'):
                    owner.same_products(before, owner.toolchain_snapshot(environment, root, identify, runner=command))
                (root / 'cargo').write_bytes(b'cargo')
                (root / 'config.toml').write_bytes(b'[build]\nrustflags = []\n')
                with self.assertRaisesRegex(ValueError, 'native-evidence-changed'):
                    owner.same_products(before, owner.toolchain_snapshot(environment, root, identify, runner=command))

    def test_dedicated_workflow_keeps_original_bounds_and_explicit_contracts(self):
        from tools import ci_lane_inventory as lanes
        root = Path(__file__).resolve().parents[2]
        model = lanes.workflow_model((root / owner.CURRENT_WORKFLOW).read_text(encoding='utf-8'))
        self.assertEqual(model['on']['push']['branches'], ['fix/rust-http-current-native-20261109',
            'fix/rust-http-current-backend-20261109'])
        self.assertIn('workflow_dispatch', model['on'])
        self.assertEqual(model['permissions'], {'contents': 'read'})
        self.assertFalse(model['concurrency']['cancel-in-progress'])
        job = model['jobs']['native-controls']
        self.assertEqual((job['runs-on'], job['timeout-minutes']), ('ubuntu-24.04', 25))
        steps = {step.get('name'): step for step in job['steps'] if step.get('name')}
        fetch = steps['Fetch only the original pinned control histories']['run']
        self.assertIn('b606b1402961593dd918722a66fe293bfab9b319', fetch)
        self.assertIn(owner.HISTORICAL, fetch)
        self.assertIn('git status --porcelain=v1 --untracked-files=all', fetch)
        execute = steps['Execute the current producer and original default-feature controls']
        self.assertEqual(execute['timeout-minutes'], 23)
        self.assertIn('tools/rust_http_current_controls.py', execute['run'])
        self.assertIn('--revision "$GITHUB_SHA"', execute['run'])
        evidence = steps['Retain bounded current-source and control observations']
        products = steps['Retain the five verified and size-bounded native products']
        self.assertEqual(evidence['if'], 'always()')
        self.assertEqual(products['if'], 'success()')
        self.assertEqual(evidence['with']['retention-days'], 7)
        self.assertEqual(products['with']['retention-days'], 7)
        self.assertEqual(products['with']['if-no-files-found'], 'error')
        self.assertIn('native-binaries/**', products['with']['path'])
        self.assertFalse(any('development-rust-http-combined' in str(step) for step in job['steps']))
        structural = lanes.structural_workflow(model)
        contract = root / 'tools/ci/contracts/workflows/rust-http-current-native.yml'
        workflow_contract = json.loads((contract / 'workflow.json').read_bytes())
        job_contract = json.loads((contract / 'jobs/native-controls.json').read_bytes())
        self.assertEqual(workflow_contract['policy'], {key: value for key, value in structural.items() if key != 'jobs'})
        self.assertEqual(workflow_contract['requiredJobs'], ['current-backend', 'native-controls'])
        self.assertEqual(job_contract['definition'], structural['jobs']['native-controls'])
        backend_contract = json.loads((contract / 'jobs/current-backend.json').read_bytes())
        self.assertEqual(backend_contract['definition'], structural['jobs']['current-backend'])
        backend = model['jobs']['current-backend']
        self.assertEqual((backend['needs'], backend['runs-on'], backend['timeout-minutes']),
            ('native-controls', 'ubuntu-24.04', 30))
        origin = steps['Record exact same-run native origin']
        self.assertIn('rust_http_current_backend_handoff.py origin', origin['run'])
        self.assertNotIn('if', origin)
        self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}', evidence['with']['name'])
        self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}', products['with']['name'])
        following = {step.get('name'): step for step in backend['steps'] if step.get('name')}
        self.assertEqual(following["Restore this run's current-source evidence"]['with']['name'],
            evidence['with']['name'])
        self.assertEqual(following["Restore this run's five bounded native products"]['with']['name'],
            products['with']['name'])
        self.assertIn('rust_http_current_backend_handoff.py build',
            following['Verify same-run source and compile the ordinary backend']['run'])
        self.assertEqual(following['Retain bounded backend result and build evidence']['if'], 'always()')
        self.assertFalse(any('development-rust-http-combined' in str(step) for step in backend['steps']))

    def test_removed_original_command_is_rejected_even_with_a_matching_test_plan(self):
        source = self.files[owner.WORKFLOW].replace(b"commands.run('c-profile-9'", b"commands.skip('c-profile-9'", 1)
        self.assertNotEqual(source, self.files[owner.WORKFLOW])
        # Simulate a separately authenticated workflow payload to exercise the
        # stage-inventory check, independently of the content hash check.
        with patch.object(owner, 'WORKFLOW_SHA256', hashlib.sha256(source).hexdigest()):
            with self.assertRaisesRegex(ValueError, 'historical-all-stages'):
                owner.historical_plan(source)

    def test_orchestrator_rechecks_real_product_bytes_after_original_controls(self):
        head = 'a' * 40
        names = ('latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring')
        original = {row[0]: row for row in self.plan}
        expected = dict(self.tests)
        for row in self.plan[2:]:
            if row[0] not in expected and row[0] != 'release-preparation-protocol-reader-controls':
                split = row.index('--')
                expected[row[0]] = frozenset((row[split - 1],))
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            prepared, output = base / 'native', base / 'result'
            products = {name: prepared / name for name in names}
            written = []

            def produce(path, revision):
                self.assertEqual(revision, head)
                path.mkdir()
                for name, product in products.items():
                    product.write_bytes(name.encode())

            def evidence(path):
                self.assertEqual(path, prepared)
                checksums = {name: hashlib.sha256(product.read_bytes()).hexdigest()
                    for name, product in products.items()}
                return ({'compiledSource': head, 'products': checksums},
                    {'compiledSourceByteExact': True}, products)

            def argv(row):
                return [str(REPOSITORY / '.cargo/managed-guest.toml')
                    if value == 'ROOT/.cargo/managed-guest.toml' else value for value in row[1:]]

            native_record = {'commands': [{'argv': ['git']},
                {'argv': argv(original['rust-version'])}, {'argv': argv(original['normal-host-build'])}],
                'controlCount': 254}
            current = types.SimpleNamespace(current_source=lambda: (head, {}),
                committed_materials=lambda *_: None, native_evidence=evidence,
                read_json=lambda *_: native_record)

            class Stages:
                def __init__(self, *_): self.records = []
                def run(self, stage, *args):
                    self.records.append({'stage': stage})
                    if stage == 'release-preparation-protocol-reader-controls':
                        return b'Ran 12 tests in 0.1s\n\nOK\n'
                    label = stage.removesuffix('-list').removesuffix('-run')
                    rows = sorted(expected[label])
                    if stage.endswith('-list'):
                        return ''.join(name + ': test\n' for name in rows).encode()
                    if label == 'ordinary-async-worker-owner-controls':
                        products['package'].write_bytes(b'tampered after admission')
                    return (''.join('test ' + name + ' ... ok\n' for name in rows)
                        + f'test result: ok. {len(rows)} passed; 0 failed; 0 ignored;\n').encode()

            def exact_result(raw, selected):
                actual = {line[5:-7] for line in raw.decode().splitlines() if line.startswith('test ') and line.endswith(' ... ok')}
                self.assertEqual(actual, set(selected))

            producer = types.SimpleNamespace(materials=lambda _: {}, qualify=produce,
                Stages=Stages, exact_result=exact_result)
            package = types.ModuleType('tools')
            package.c_timed_current_products, package.qualify_host_codec_native = current, producer
            build = types.ModuleType('tools.build_observation')
            build.build_environment = lambda _: {'PATH': 'fixture'}
            identity = types.ModuleType('tools.phase3_resource_identity')
            identity.file_identity = lambda _: {'bytes': 1, 'sha256': 'sha256:' + 'b' * 64}
            compiler = types.ModuleType('tools.rust_capsule_build')
            compiler.Commands = lambda *_args, **_kwargs: object()
            project = types.ModuleType('tools.rust_capsule_project')
            project.ROOT = REPOSITORY
            project.checked_path = lambda path: Path(path).absolute()
            project.fresh = lambda path: (path.mkdir() or path)
            project.write_json = lambda path, value: written.append((path.name, dict(value)))
            modules = {'tools': package, 'tools.build_observation': build,
                'tools.phase3_resource_identity': identity, 'tools.rust_capsule_build': compiler,
                'tools.rust_capsule_project': project}
            with patch.dict(sys.modules, modules), patch.object(owner.sys, 'platform', 'linux'), \
                    patch.object(owner.sys, 'version_info', (3, 13, 5)), \
                    patch.object(owner.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(owner.shutil, 'which', return_value=sys.executable), \
                    patch.object(owner, 'WORKFLOW_SHA256', self.workflow_sha), \
                    patch.object(owner, 'historical_files', return_value=self.files), \
                    patch.object(owner, 'loaded_sources', return_value=set()), \
                    patch.object(owner, 'toolchain_snapshot', return_value={'fixture': 'same-tools'}), \
                    self.assertRaisesRegex(ValueError, 'native-evidence-changed'):
                owner.qualify(prepared, output, head)
            self.assertEqual(written[-1][0], 'FAILED.json')
            self.assertEqual(written[-1][1]['status'], 'failed')
            self.assertFalse(written[-1][1]['signedQualification'])


if __name__ == '__main__':
    unittest.main()
