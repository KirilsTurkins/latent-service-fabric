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
    def test_normal_lock_target_reparse_is_denied_before_capture_or_review(self):
        from types import SimpleNamespace
        from tools import go_http_library_fixture as fixture
        from tools.application_dependency_store import DependencyError
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            identity = 'outside.example.test/http-library/linked'
            app, library = capture_source(root/'application',root/'outside',identity)
            def lock(project, *, go):
                (project/'target/go-dependency-authoring').mkdir(parents=True)
                return {'status':'locked'}
            with patch.object(fixture,'run_bounded',return_value=SimpleNamespace(stdout=b'{}')), \
                    patch.object(fixture,'create_lock',side_effect=lock), \
                    patch('tools.application_dependency_store.is_reparse',side_effect=lambda path: path == app/'target'), \
                    patch.object(fixture,'resolve') as capture, patch.object(fixture,'review') as review:
                with self.assertRaisesRegex(DependencyError,'dependency-link-denied'):
                    fixture.install(app,library,identity,root/'pinned-go')
                capture.assert_not_called(); review.assert_not_called()
            self.assertFalse((app/'target/http-libraries.candidate.json').exists())
            self.assertTrue(library.exists())

    def test_ordinary_clients_use_normal_reviewable_native_lock_without_wit_source_imports(self):
        from types import SimpleNamespace
        from tools import go_http_library_fixture as fixture
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            identity = 'outside.example.test/http-library/ordinary'
            app, library = capture_source(root/'application',root/'outside',identity)
            source = read_file(app/'src/main.go')
            self.assertNotIn(b'go.bytecodealliance.org',source)
            order = []
            def native_command(arguments, _work, _environment, _seconds, _maximum):
                self.assertEqual(arguments[1:3],['mod','edit'])
                return SimpleNamespace(stdout=b'{}' if arguments[-1] == '-json' else b'')
            def lock(project, *, go):
                self.assertEqual(project,app); order.append('lock')
                self.assertEqual(read_file(project/'src/main.go'),source)
                (project/'target/go-dependency-authoring').mkdir(parents=True)
                (project/'target/normal-authoring-state.txt').write_bytes(b'retained normal lock state')
                return {'status':'locked','captureRequired':True,'reviewRequired':True}
            def capture(project, _candidate, *, go):
                self.assertEqual(order,['lock']); order.append('capture')
                (project/'go-resolved.lock.json').write_text('{}')
                _candidate.write_text('{}')
                return {'selection':{},'artifacts':[]}
            with patch.object(fixture,'run_bounded',side_effect=native_command), \
                    patch.object(fixture,'create_lock',side_effect=lock) as normal_lock, \
                    patch.object(fixture,'resolve',side_effect=capture), \
                    patch.object(fixture,'review') as review, \
                    patch.object(fixture,'direct_libraries',return_value=[]):
                record = fixture.install(app,library,identity,root/'pinned-go')
            normal_lock.assert_called_once_with(app,go=root/'pinned-go')
            review.assert_called_once()
            self.assertEqual(order,['lock','capture'])
            self.assertTrue(record['nativeLock']['captureRequired'])
            self.assertTrue(record['nativeLock']['reviewRequired'])
            self.assertEqual(read_file(app/'src/main.go'),source)
            self.assertEqual(read_file(app/'target/normal-authoring-state.txt'),b'retained normal lock state')

    def test_client_ci_gate_requires_normal_native_and_own_boundaries_without_waiving_shared_failure(self):
        from tools import ci_lane_inventory
        from tools.rust_capsule_project import ROOT
        workflow = ci_lane_inventory.structural_workflow(ci_lane_inventory.workflow_model(
            read_file(ROOT/'.github/workflows/go-guest.yml').decode()))
        job = workflow['jobs']['upstream-probe']
        steps = job['steps']
        normal = next(step for step in steps if step.get('id') == 'normal_go_qualification')
        boundaries = next(step for step in steps if step.get('id') == 'http_library_boundaries')
        clients = next(step for step in steps if step.get('name') ==
            'Qualify two captured default clients and renamed private transitive workers')
        shared = next(step for step in steps if step.get('name') ==
            'Qualify ordinary net/http contexts and disposal on the signed node')
        self.assertEqual(normal['run'],
            'python3 tools/qualify_go_capsules.py --output "$RUNNER_TEMP/go-capsule-authoring"\n')
        self.assertNotIn('if',normal)
        self.assertEqual(boundaries['run'],'python3 -m unittest tools.tests.test_go_http_libraries -v')
        self.assertEqual(boundaries['if'],
            "${{ !cancelled() && steps.normal_go_qualification.outcome == 'success' }}")
        self.assertEqual(clients['if'],
            "${{ !cancelled() && steps.normal_go_qualification.outcome == 'success' && steps.http_library_boundaries.outcome == 'success' }}")
        self.assertLess(steps.index(normal),steps.index(shared))
        self.assertLess(steps.index(shared),steps.index(boundaries))
        self.assertLess(steps.index(boundaries),steps.index(clients))
        self.assertNotIn('if',shared)
        for value in (job,normal,shared,boundaries,clients):
            self.assertFalse(value.get('continue-on-error',False))
        self.assertEqual(job['timeout-minutes'],45)

    def test_private_coordinates_change_application_inputs_without_changing_captured_sdk(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); snapshots = []
            for variant in ('first','renamed'):
                app, library = capture_source(root/('app-'+variant),root/('outside-'+variant),
                    'outside.example.test/http-library/'+variant)
                document, _lock, _pins = validate(snapshot(app))
                self.assertEqual(document['runtimeProfile'],'go-component-activation-v4')
                self.assertEqual(document['tenant'],'examples')
                self.assertEqual(document['world'],'examples:go-standard-http/service@1.0.0')
                self.assertTrue(read_file(app/'wit/world.wit').startswith(b'package examples:go-standard-http@1.0.0;\n'))
                self.assertTrue(read_file(app/'src/main.go').startswith(b'package export_examples_go_standard_http_api\n'))
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
