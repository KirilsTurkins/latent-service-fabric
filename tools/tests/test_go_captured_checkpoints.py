"""Focused fail-closed controls for the captured Go goto owner."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import qualify_go_captured_checkpoints as subject
from tools.rust_capsule_project import digest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'sdk/go-guest/runtime/checkpoints-captured-conformance'


class CapturedGoto(unittest.TestCase):
    def test_fixture_retains_original_modes_and_signals_inside_dependency(self):
        original = (ROOT / 'sdk/go-guest/runtime/checkpoints-conformance/main.go').read_text()
        captured = (FIXTURE / 'main.go').read_text()
        start = '\tif which == 7 || which == 8 {\n'
        end = '\tif which == 5 || which == 6 {\n'
        self.assertEqual(captured.count(start), 1)
        before, rest = captured.split(start, 1)
        _, after = rest.split(end, 1)
        restored = (before + end + after).replace('\t"example.invalid/worker"\n', '', 1)
        self.assertEqual(restored, original)
        worker = (FIXTURE / 'module/worker.go').read_text()
        self.assertEqual(worker.count('close(started)'), 1)
        self.assertLess(worker.index('close(started)'), worker.index('goto again'))
        self.assertNotIn('Gosched', worker)
        self.assertEqual((FIXTURE / 'module/go.mod').read_text(),
                         'module example.invalid/worker\n\ngo 1.27.4\n')

    def test_exact_v2_transformation_and_v1_negative_fail_closed(self):
        source = (FIXTURE / 'module/worker.go').read_bytes()
        site = subject.goto_site(source)
        row = {'name': subject.TRANSFORM, 'upstreamDigest': digest(source),
               'adaptedDigest': 'sha256:' + 'a' * 64, 'sites': [site]}
        def check(profile, rows):
            return subject.validate_transformation(json.dumps(
                {'profile': profile, 'automaticTransformations': rows}).encode(), source, profile)
        self.assertEqual(check('go-component-activation-v2', [row])['sourceSite'], site)
        self.assertEqual(check('go-component-activation-v1', [])['sourceSite'], site)
        bad = copy.deepcopy(row); bad['upstreamDigest'] = 'sha256:' + '0' * 64
        wrong = copy.deepcopy(row); wrong['sites'][0]['column'] += 1
        missing = copy.deepcopy(row); missing.pop('adaptedDigest')
        for profile, rows in [('go-component-activation-v2', []),
                              ('go-component-activation-v2', [row, row]),
                              ('go-component-activation-v2', [bad]),
                              ('go-component-activation-v2', [wrong]),
                              ('go-component-activation-v2', [missing]),
                              ('go-component-activation-v1', [row])]:
            with self.subTest(profile=profile, rows=rows), self.assertRaises(ValueError):
                check(profile, rows)
        with self.assertRaises(ValueError):
            subject.goto_site(source + b'\ngoto again\n')

    def test_transform_json_rejects_duplicate_fields_before_interpretation(self):
        source = (FIXTURE / 'module/worker.go').read_bytes()
        for raw in (b'{"profile":"go-component-activation-v1","profile":"go-component-activation-v2","automaticTransformations":[]}',
                    b'{"profile":"go-component-activation-v1","automaticTransformations":[],"automaticTransformations":[]}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'duplicate-transformation-field'):
                subject.validate_transformation(raw, source, 'go-component-activation-v1')

    def test_go_executable_identity_requires_exact_digest_and_size(self):
        identity = dict(subject.GO_IDENTITY)
        with patch.object(subject, 'file_identity', return_value=identity):
            self.assertEqual(subject.authenticate_go(Path('unused')), identity)
        for field, bad in (('digest', 'sha256:' + '0' * 64), ('size', identity['size'] - 1)):
            changed = dict(identity, **{field: bad})
            with self.subTest(field=field), patch.object(subject, 'file_identity', return_value=changed), \
                    self.assertRaisesRegex(ValueError, 'reference-compiler-drift'):
                subject.authenticate_go(Path('unused'))

    def test_module_lock_and_materialized_bytes_are_required(self):
        files = {name: (FIXTURE / 'module' / name).read_bytes() for name in ('go.mod', 'worker.go')}
        with TemporaryDirectory() as temp:
            work = Path(temp)
            destination = work / 'dependencies/test-module'
            destination.mkdir(parents=True)
            for name, raw in files.items():
                (destination / name).write_bytes(raw)
            artifact = {'id': 'go/test-module', 'role': 'application', 'mount': 'dependencies/test-module',
                        'metadata': {'module': subject.MODULE, 'version': subject.VERSION, 'assetType': 'local-module'},
                        'files': [{'path': name, 'digest': digest(raw), 'size': len(raw)}
                                  for name, raw in files.items()]}
            closure = SimpleNamespace(work=work, lock={'artifacts': [artifact]}, identity='identity', lock_bytes=b'lock')
            native = {'module': 'wit_component',
                      'nodes': [{'id': artifact['id'], 'path': subject.MODULE, 'version': subject.VERSION,
                                 'main': False, 'indirect': False, 'replacement': {'path': None}}],
                      'edges': [{'owner': 'wit_component', 'selected': artifact['id']}]}
            self.assertEqual(subject.selected_dependency(closure, native, files)['sourceDigest'], digest(files['worker.go']))
            for mutation in ('indirect', 'edge', 'digest', 'duplicate'):
                c, n = copy.deepcopy(closure), copy.deepcopy(native)
                if mutation == 'indirect': n['nodes'][0]['indirect'] = True
                if mutation == 'edge': n['edges'] = []
                if mutation == 'digest': c.lock['artifacts'][0]['files'][0]['digest'] = 'sha256:' + '0' * 64
                if mutation == 'duplicate': c.lock['artifacts'].append(copy.deepcopy(c.lock['artifacts'][0]))
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    subject.selected_dependency(c, n, files)
            (destination / 'worker.go').write_bytes(files['worker.go'] + b' ')
            with self.assertRaisesRegex(ValueError, 'materialization-changed'):
                subject.selected_dependency(closure, native, files)


if __name__ == '__main__':
    unittest.main()