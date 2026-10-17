"""Captured-client fixture ownership; native compilation/execution is separate."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.go_capsule_project import validate
from tools.go_http_library_fixture import capture_source
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity
from tools.qualify_go_http_libraries import qualify
from tools.qualify_go_standard_http import NATIVE_NAMES
from tools.rust_capsule_project import read_file, snapshot


class HttpLibraryCapture(unittest.TestCase):
    def test_private_coordinates_change_application_inputs_without_changing_captured_sdk(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); snapshots = []
            for variant in ('first','renamed'):
                app, library = capture_source(root/('app-'+variant),root/('outside-'+variant),
                    'outside.example.test/http-library/'+variant)
                document, _lock, _pins = validate(snapshot(app))
                self.assertEqual(document['runtimeProfile'],'go-component-activation-v4')
                self.assertEqual(document['limits']['memoryBytes'],67108864)
                self.assertEqual(document['limits']['wallTimeLimitMillis'],120000)
                snapshots.append((read_file(app/'src/main.go'),snapshot(app/'vendor/lsf'),library))
                self.assertFalse(library.is_relative_to(app))
                self.assertEqual(read_file(library/'marker.txt'),b'captured-private-worker')
            self.assertNotEqual(snapshots[0][0],snapshots[1][0])
            self.assertEqual(snapshots[0][1],snapshots[1][1])

    def test_nested_private_origins_and_injected_coordinates_fail_before_writes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for origin,identity in ((root/'app/private','outside.example.test/http-library/valid'),
                    (root/'private','outside.example.test/http-library/../escape'),
                    (root/'private','outside.example.test/http-library/quote"')):
                with self.subTest(origin=origin,identity=identity), self.assertRaisesRegex(ValueError,'go-http-private'):
                    capture_source(root/'app',origin,identity)
                self.assertFalse(origin.exists())

    def test_tampered_native_tuple_cannot_start_capture_resolution_compilation_or_node(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); native = root/'native'; (native/'native-binaries').mkdir(parents=True)
            identities = {}
            for key in NATIVE_NAMES.values():
                path = native/'native-binaries'/key.replace('/','-'); path.write_bytes(key.encode())
                identities[key] = file_identity(path)
            (native/'qualification.json').write_text(json.dumps({'schemaVersion':'latent.go-capsule.qualification.v1',
                'status':'passed','binaries':identities}))
            (native/'native-binaries/latentd').write_bytes(b'tampered')
            with patch('tools.qualify_go_http_libraries.capture_source') as source, \
                    patch('tools.qualify_go_http_libraries.run_bounded_result') as compiler, \
                    patch('tools.qualify_go_http_libraries.run') as node:
                with self.assertRaisesRegex(WorkflowError,'frozen-native-product-drift'):
                    qualify(root/'output',native)
                for operation in (source,compiler,node): operation.assert_not_called()


if __name__ == '__main__': unittest.main()
