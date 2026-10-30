"""Real capture/retention controls; these do not execute a guest or compiler."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import typescript_buffer_fixture as fixture
from tools.rust_capsule_project import ROOT, digest, read_file, read_json, snapshot
from tools.typescript_guest import buffer_profile
from tools.typescript_guest.project import validate


class BufferQualificationControls(unittest.TestCase):
    def test_normal_project_keeps_original_limits_and_exact_fixture_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = fixture.project(Path(temporary)/'application')
            files = snapshot(app)
            project, lock, _pins = validate(files)
            self.assertEqual(project['world'], fixture.WORLD)
            self.assertEqual(project['limits'], {'cpuFuel': 1000000000, 'memoryBytes': 134217728,
                'wallTimeLimitMillis': 120000, 'logBytes': 0, 'outboundRequests': 0,
                'childCalls': 0, 'effectCount': 0, 'blobReadBytes': 0, 'blobWriteBytes': 0,
                'stateReadBytes': 0, 'stateWriteBytes': 0})
            for name in ('main.ts', 'relative-fixture.ts'):
                self.assertEqual(files['src/'+name], read_file(ROOT/fixture.FIXTURE/name))
            self.assertEqual(lock['template']['sourceDigest'], digest(files['src/main.ts']))
            self.assertEqual(len(fixture.CASES), 8)
            self.assertEqual(fixture.CASES[-1], 'relative-fixture-only')

    def test_selected_receipt_survives_compiler_directory_and_binds_exact_material(self):
        backend = digest(read_file(ROOT/buffer_profile.BACKEND))
        selected = buffer_profile.check_selection({'standardBufferModules': ['node:buffer'],
            'standardBufferProfile': buffer_profile.PROFILE,
            'standardBufferBackendDigest': backend}, backend)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled, output = root/'compiled', root/'output'
            compiled.mkdir(); output.mkdir()
            path = compiled/'typescript-buffer-selection.json'
            raw = (json.dumps(selected, sort_keys=True)+'\n').encode()
            path.write_bytes(raw)
            assets, materials = buffer_profile.retain_selection(compiled, output, backend)
            path.unlink()
            self.assertEqual(read_file(output/path.name), raw)
            self.assertEqual(assets, ((path.name, 'asset',
                'application/vnd.latent.typescript.buffer-selection.v1+json'),))
            self.assertEqual(materials, [{'name': 'typescript-standard-buffer',
                'digest': digest(raw), 'size': len(raw)}])
            self.assertEqual(read_json(output/path.name)['qualification'], 'unknown')

    def test_unselected_has_no_asset_and_mismatched_receipt_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled, output = root/'compiled', root/'output'
            compiled.mkdir(); output.mkdir()
            backend = digest(read_file(ROOT/buffer_profile.BACKEND))
            self.assertEqual(buffer_profile.retain_selection(compiled, output, backend), ((), []))
            selected = buffer_profile.check_selection({'standardBufferModules': ['node:buffer'],
                'standardBufferProfile': buffer_profile.PROFILE,
                'standardBufferBackendDigest': backend}, backend)
            for field, value in (('backendDigest', 'sha256:'+'0'*64), ('qualification', 'passed'),
                                 ('globalBufferInstalled', 0), ('nativeStorage', 0),
                                 ('globalBufferInstalled', 0.0), ('nativeStorage', 0.0),
                                 ('maximumBufferBytes', 1048576.0)):
                with self.subTest(field=field, value=value):
                    changed = dict(selected, **{field: value})
                    (compiled/'typescript-buffer-selection.json').write_text(json.dumps(changed))
                    with self.assertRaisesRegex(ValueError, 'retained-selection-drift'):
                        buffer_profile.retain_selection(compiled, output, backend)
                    with self.assertRaisesRegex(ValueError, 'retained-selection-drift'):
                        buffer_profile.validate_selection(changed, backend)
                    self.assertEqual(list(output.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
