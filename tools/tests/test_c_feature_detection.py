"""Captured C feature-kit selection and fail-closed identity checks."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import c_capsule_project
from tools.build_observation import file_identity
from tools.c_guest import feature_detection, standard_facilities, threading
from tools.rust_capsule_project import digest, inventory, snapshot


class CFeatureDetection(unittest.TestCase):
    def test_old_capture_produces_no_probe_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = c_capsule_project.create(root / 'old project', 'greeting',
                threading_profile=threading.PROFILE, runtime_profile=standard_facilities.STREAM_STDIO_PROFILE)
            (project / standard_facilities.SDK_SOURCE_PREFIX / standard_facilities.RESOLVER_SOURCE).unlink()
            files = snapshot(project)
            lock = json.loads(files['sdk-lock.json'])
            vendor = {name.removeprefix('vendor/lsf/'): raw for name, raw in files.items()
                      if name.startswith('vendor/lsf/')}
            lock['sdk'] = json.loads(inventory(vendor))
            (project / 'sdk-lock.json').write_text(json.dumps(lock) + '\n')
            before = snapshot(project)
            zig = root / 'zig'
            zig.write_bytes(b'fixed-compiler')
            identity = file_identity(zig, 'zig')
            fake = SimpleNamespace(materials={'zig': identity},
                isolation=SimpleNamespace(receipt={'tools': {'zig': identity},
                    'distributions': {'zig-compiler-and-sysroot': []}}),
                enable_captured_isolation=lambda _workspace: None, check_unchanged=lambda: None)
            with patch.object(feature_detection, 'Compiler', return_value=fake):
                kit = feature_detection.prepare(project, root / 'old kit')
            expected = digest((kit / 'feature-probes.json').read_bytes())
            with patch.object(feature_detection.Isolation, 'observe_distribution', return_value=[]):
                self.assertEqual(feature_detection.verify(project, kit, expected, zig), 'not-selected')
            self.assertEqual(snapshot(project), before)
            with patch.object(feature_detection, 'recipe_identity', return_value='sha256:' + '0' * 64):
                with self.assertRaisesRegex(ValueError, 'captured-input-changed'):
                    feature_detection.verify(project, kit, expected, zig)
            (kit / 'untrusted.cmake').write_text('message(FATAL_ERROR "must not run")\n')
            with self.assertRaisesRegex(ValueError, 'unexpected-input'):
                feature_detection.verify(project, kit, expected, zig)
            with self.assertRaisesRegex(ValueError, 'receipt-changed'):
                feature_detection.verify(project, kit, 'sha256:' + '0' * 64, zig)

    def test_unsafe_paths_are_refused_before_filesystem_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for value in ('bad;path', 'bad\npath', 'bad\rpath', 'bad"path', "bad'path", 'bad$path', 'bad`path'):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'c-feature-probe-path'):
                    feature_detection.safe_path(root / value)
            self.assertEqual(feature_detection.safe_path(root / 'path with spaces'), root / 'path with spaces')


if __name__ == '__main__':
    unittest.main()
