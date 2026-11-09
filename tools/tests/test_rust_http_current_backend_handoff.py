"""Source-only controls of the same-run handoff; no build or signed guest."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parents[1] / 'rust_http_current_backend_handoff.py'
spec = importlib.util.spec_from_file_location('http_handoff_candidate', FILE)
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)

REPOSITORY = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip())
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from tools import qualify_host_codec_native as producer
from tools import rust_wasi_http_inputs as runtime
from tools.rust_capsule_project import ROOT, read_file
from tools.phase2_operator_process import WorkflowError


def example_context(job):
    revision = 'a' * 40
    ref = 'refs/heads/fix/rust-http-current-native-20261109'
    return {'GITHUB_REPOSITORY': handoff.REPOSITORY, 'GITHUB_RUN_ID': '123',
        'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': revision, 'GITHUB_REF': ref,
        'GITHUB_WORKFLOW_REF': handoff.REPOSITORY + '/' + handoff.WORKFLOW + '@' + ref,
        'GITHUB_WORKFLOW_SHA': revision, 'GITHUB_EVENT_NAME': 'push', 'GITHUB_JOB': job,
        'GITHUB_WORKSPACE': str(ROOT)}


class SameRun(unittest.TestCase):
    def test_producer_and_consumer_match_only_same_run_and_checkout(self):
        producer_ctx = handoff.context(example_context('native-controls'), ROOT, 'native-controls')
        consumer_ctx = handoff.context(example_context('current-backend'), ROOT, 'current-backend')
        self.assertEqual(producer_ctx, consumer_ctx)
        origin = {'schemaVersion': handoff.ORIGIN_SCHEMA, 'producerJob': 'native-controls',
            'context': producer_ctx, 'evidence': {'fixture': True}, 'signedQualification': False}
        handoff.check_origin(origin, consumer_ctx)
        for key, value in [('GITHUB_RUN_ID', '124'), ('GITHUB_RUN_ATTEMPT', '2'),
                ('GITHUB_SHA', 'b' * 40), ('GITHUB_WORKSPACE', str(ROOT.parent)),
                ('GITHUB_REPOSITORY', 'other/repo'), ('GITHUB_WORKFLOW_REF', 'other/workflow'),
                ('GITHUB_JOB', 'native-controls')]:
            candidate = example_context('current-backend')
            candidate[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                handoff.check_origin(origin, handoff.context(candidate, ROOT, 'current-backend'))
        altered = copy.deepcopy(origin)
        altered['signedQualification'] = True
        with self.assertRaisesRegex(ValueError, 'same-run-origin'):
            handoff.check_origin(altered, consumer_ctx)

    def test_real_native_reader_refuses_changed_or_missing_product_bytes(self):
        path = FILE.parent / 'c_timed_current_products.py'
        spec = importlib.util.spec_from_file_location('current_native_reader', path)
        reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader)
        from tools.phase3_resource_identity import file_identity
        with tempfile.TemporaryDirectory() as temporary:
            prepared = Path(temporary)
            binary = prepared / 'native-binaries'
            binary.mkdir()
            for original in reader.PRODUCTS:
                (binary / original.replace('/', '-')).write_bytes(original.encode())
            recorded = {original: file_identity(binary / original.replace('/', '-'))
                for original in reader.PRODUCTS}
            self.assertEqual(len(reader._products(prepared, recorded)), 5)
            selected = binary / next(iter(reader.PRODUCTS)).replace('/', '-')
            selected.write_bytes(b'changed')
            with self.assertRaises((ValueError, WorkflowError)):
                reader._products(prepared, recorded)
            selected.unlink()
            with self.assertRaises((OSError, ValueError, WorkflowError)):
                reader._products(prepared, recorded)

    def test_failed_origin_refuses_before_build_and_postbuild_drift_never_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            prepared, controls = base / 'prepared', base / 'controls'
            prepared.mkdir(); controls.mkdir()
            ctx = handoff.context(example_context('native-controls'), ROOT, 'native-controls')
            proof = {'sourceRevision': ctx['revision'], 'fixture': 1}
            origin = {'schemaVersion': handoff.ORIGIN_SCHEMA, 'producerJob': 'native-controls',
                'context': {**ctx, 'runId': '999'}, 'evidence': proof, 'signedQualification': False}
            origin_path = controls / 'same-run-origin.json'
            origin_path.write_text(json.dumps(origin))
            with patch.dict(os.environ, example_context('current-backend')), \
                    patch.object(runtime, 'install') as install, \
                    patch.object(handoff, 'verify') as verify:
                with self.assertRaisesRegex(ValueError, 'same-run-origin'):
                    handoff.build(prepared, controls, base / 'bad-origin')
                verify.assert_not_called(); install.assert_not_called()
            origin['context'] = ctx
            origin_path.write_text(json.dumps(origin))
            def install_backend(path):
                path.mkdir(); (path / runtime.RECEIPT).write_bytes(b'fixture backend receipt'); return path
            with patch.dict(os.environ, example_context('current-backend')), \
                    patch.object(runtime, 'install', side_effect=install_backend), \
                    patch.object(handoff, 'verify', side_effect=[proof, {**proof, 'fixture': 2}]):
                with self.assertRaisesRegex(ValueError, 'post-build-input-change'):
                    handoff.build(prepared, controls, base / 'drift')
            self.assertFalse((base / 'drift/qualification.json').exists())
            self.assertFalse(json.loads((base / 'drift/FAILED.json').read_text())['signedQualification'])
            with patch.dict(os.environ, example_context('current-backend')), \
                    patch.object(runtime, 'install', side_effect=install_backend), \
                    patch.object(handoff, 'verify', return_value=proof):
                result = handoff.build(prepared, controls, base / 'accepted')
            self.assertEqual(result['qualification'], 'compiled-adapter-only')
            self.assertFalse(result['signedQualification'])
            self.assertEqual(result['guestComponentsBuilt'], 0)


class HistoricalStreams(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Inspect the exact pinned historical source without building anything.
        owner_path = FILE.parent / 'rust_http_current_controls.py'
        owner_spec = importlib.util.spec_from_file_location('historical_http_owner', owner_path)
        cls.owner = importlib.util.module_from_spec(owner_spec)
        owner_spec.loader.exec_module(cls.owner)
        names = {cls.owner.WORKFLOW, *(path for sources in cls.owner.TEST_SOURCES.values() for path, _, _ in sources)}
        request = ''.join(cls.owner.HISTORICAL + ':' + name + '\n' for name in sorted(names)).encode()
        env = dict(os.environ, GIT_NO_LAZY_FETCH='1')
        proc = subprocess.run(['git', 'cat-file', '--batch'], cwd=ROOT, input=request,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, env=env, timeout=60)
        raw, offset, files = proc.stdout, 0, {}
        for name in sorted(names):
            end = raw.index(b'\n', offset)
            oid, kind, size = raw[offset:end].decode('ascii').split()
            assert kind == 'blob'
            size = int(size); body = raw[end + 1:end + 1 + size]
            assert hashlib.sha1(b'blob ' + str(size).encode() + b'\0' + body).hexdigest() == oid
            assert raw[end + 1 + size:end + 2 + size] == b'\n'
            files[name] = body; offset = end + 2 + size
        assert offset == len(raw)
        cls.plan = cls.owner.historical_plan(files[cls.owner.WORKFLOW])
        cls.tests = cls.owner.historical_tests(files)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        (self.directory / 'logs').mkdir()
        self.rows = []
        original = lambda item: [str(ROOT / '.cargo/managed-guest.toml') if x == 'ROOT/.cargo/managed-guest.toml'
            else x for x in item[1:]]
        self.native = {'commands': [{'argv': ['git']}, {'argv': original(self.plan[0])},
            {'argv': original(self.plan[1])}]}
        def put(stage, argv, stdout):
            i = len(self.rows); logs = {}
            for stream, body in [('stdout', stdout), ('stderr', b'')]:
                relative = f'logs/{i:02d}-{stage}.{stream}.txt'
                (self.directory / relative).write_bytes(body)
                logs[stream] = {'path': relative, 'bytes': len(body),
                    'sha256': 'sha256:' + hashlib.sha256(body).hexdigest()}
            self.rows.append({'stage': stage, 'exitCode': 0, 'seconds': 0.001, 'argv': argv, 'logs': logs})
        for item in self.plan[2:]:
            stage, argv = item[0], original(item)
            if stage == 'release-preparation-protocol-reader-controls':
                put(stage, argv, b'Ran 12 tests in 0.001s\n\nOK\n'); continue
            split = argv.index('--')
            listing = argv[:split + 1] + (['--exact'] if '--exact' in argv[split + 1:] else []) + ['--list']
            expected = self.tests.get(stage)
            if expected is None: expected = {argv[split - 1]}
            selected = sorted(expected)
            put(stage + '-list', listing, ''.join(n + ': test\n' for n in selected).encode())
            put(stage + '-run', argv, (''.join('test ' + n + ' ... ok\n' for n in selected)
                + f'test result: ok. {len(selected)} passed; 0 failed; 0 ignored;\n').encode())

    def check(self, rows=None):
        return handoff.check_rows(self.rows if rows is None else rows, self.plan, self.tests,
            self.native, ROOT, self.directory, self.owner, producer, read_file)

    def rewrite(self, index, stream, raw):
        row = self.rows[index]['logs'][stream]
        (self.directory / row['path']).write_bytes(raw)
        row['bytes'], row['sha256'] = len(raw), 'sha256:' + hashlib.sha256(raw).hexdigest()

    def test_all_real_historical_selectors_pass_synthetic_streams(self):
        self.assertEqual(len(self.plan), 34)
        self.assertEqual(len(self.rows), 63)
        self.assertGreater(self.check(), 0)

    def test_missing_duplicate_wrong_argv_or_missing_log_refused(self):
        for rows in (self.rows[:-1], [self.rows[0], *self.rows[:-1]]):
            with self.subTest(length=len(rows)), self.assertRaises(ValueError): self.check(rows)
        changed = copy.deepcopy(self.rows); changed[0]['argv'].append('--all-features')
        with self.assertRaisesRegex(ValueError, 'command-record'): self.check(changed)
        (self.directory / self.rows[0]['logs']['stdout']['path']).unlink()
        with self.assertRaises((ValueError, FileNotFoundError)): self.check()

    def test_changed_log_and_self_consistent_missing_test_are_refused(self):
        row = self.rows[0]
        (self.directory / row['logs']['stdout']['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'log-identity'): self.check()
        self.setUp()
        index = next(i for i, row in enumerate(self.rows) if row['stage'].endswith('-list'))
        original = (self.directory / self.rows[index]['logs']['stdout']['path']).read_bytes()
        self.rewrite(index, 'stdout', b'\n'.join(original.splitlines()[1:]) + b'\n')
        with self.assertRaises(ValueError): self.check()

    def test_self_consistent_ignored_or_failed_result_is_refused(self):
        index = next(i for i, row in enumerate(self.rows) if row['stage'].endswith('-run'))
        original = (self.directory / self.rows[index]['logs']['stdout']['path']).read_bytes()
        self.rewrite(index, 'stdout', original.replace(b' ... ok', b' ... ignored', 1))
        with self.assertRaises((ValueError, WorkflowError)): self.check()


if __name__ == '__main__':
    unittest.main()
