from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import qualify_java_published_http as campaign
from tools.application_dependency_store import DependencyError, Store
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import read_json, write_json


class PublishedJavaHttp(unittest.TestCase):
    def test_exact_transitive_jar_selection_rejects_changed_coordinates_edges_and_duplicates(self):
        def row(name, edges):
            return {'id': name, 'role': 'application', 'format': 'file',
                    'mount': 'dependencies/java/0000.jar', 'dependencies': edges,
                    'metadata': {'scope': 'selected-runtime', 'coordinates': name}}
        original = {'artifacts': [row(campaign.PRIMARY, [campaign.CHILD]), row(campaign.CHILD, [])]}
        self.assertEqual(set(campaign.selected_jars(original)), {campaign.PRIMARY, campaign.CHILD})
        changed = []
        for coordinate in ('other.owner:client:1.0', campaign.PRIMARY + '-changed'):
            value = deepcopy(original)
            value['artifacts'][0]['id'] = coordinate
            changed.append(value)
        for edges in ([], [campaign.CHILD, campaign.CHILD], ['other.owner:child:1.0']):
            value = deepcopy(original)
            value['artifacts'][0]['dependencies'] = edges
            changed.append(value)
        value = deepcopy(original)
        value['artifacts'].append(deepcopy(value['artifacts'][0]))
        changed.append(value)
        value = deepcopy(original)
        value['artifacts'][1]['dependencies'] = [campaign.PRIMARY]
        changed.append(value)
        for value in changed:
            with self.subTest(value=value), self.assertRaisesRegex(WorkflowError, 'reviewed-closure-changed'):
                campaign.selected_jars(value)

    def test_selected_native_tool_or_metadata_cannot_substitute_for_application_jar(self):
        original = {'artifacts': [
            {'id': name, 'role': 'application', 'format': 'file', 'dependencies': edges,
             'mount': 'dependencies/java/0000.jar',
             'metadata': {'scope': 'selected-runtime', 'coordinates': name}}
            for name, edges in ((campaign.PRIMARY, [campaign.CHILD]), (campaign.CHILD, []))]}
        for key, value in (('role', 'build-tool'), ('format', 'tar'), ('mount', 'metadata/client.pom')):
            changed = deepcopy(original)
            changed['artifacts'][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(WorkflowError, 'reviewed-jar-kind'):
                campaign.selected_jars(changed)
        changed = deepcopy(original)
        changed['artifacts'][0]['metadata']['coordinates'] = campaign.CHILD
        with self.assertRaisesRegex(WorkflowError, 'reviewed-jar-kind'):
            campaign.selected_jars(changed)

    def test_real_project_installs_normal_maven_declaration_and_unmodified_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = campaign.project(root / 'application')
            declared = read_json(app / 'java-dependencies.json')
            self.assertEqual(declared['localJars'], [])
            self.assertEqual([(r['group'], r['name'], r['version']) for r in declared['dependencies']],
                             [('com.goebl', 'david-webb', '1.3.0')])
            self.assertEqual((app / 'src/dev/latent/app/Capsule.java').read_bytes(),
                             (campaign.ROOT / campaign.SOURCE).read_bytes())
            lock = read_json(app / 'sdk-lock.json')
            self.assertEqual(lock['template']['name'], 'java-david-webb')
            self.assertEqual(lock['template']['sourceDigest'],
                             campaign.digest((campaign.ROOT / campaign.SOURCE).read_bytes()))

    def test_changed_published_original_refuses_before_review_and_preserves_accepted_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'application'
            app.mkdir()
            (app / 'sdk-lock.json').write_bytes(b'unchanged sdk input')
            accepted = app / campaign.inputs.LOCK
            accepted.write_bytes(b'unchanged accepted closure')
            store = Store(app / 'dependency-inputs/objects')
            identity = store.put(b'changed published primary jar')
            selected = {'artifacts': [
                {'id': name, 'role': 'application', 'format': 'file', 'dependencies': edges,
                 'mount': 'dependencies/java/0000.jar', 'original': identity,
                 'metadata': {'scope': 'selected-runtime', 'coordinates': name}}
                for name, edges in ((campaign.PRIMARY, [campaign.CHILD]), (campaign.CHILD, []))]}
            candidate = root / 'candidate.json'
            write_json(candidate, selected)
            commands = mock.Mock()
            with mock.patch.object(campaign, 'review') as review:
                with self.assertRaisesRegex(WorkflowError, 'published-original-changed-review-required'):
                    campaign.resolve_review(commands, app, candidate)
                review.assert_not_called()
            self.assertEqual(accepted.read_bytes(), b'unchanged accepted closure')
            self.assertEqual((app / 'sdk-lock.json').read_bytes(), b'unchanged sdk input')
            self.assertEqual(commands.run.call_count, 1)

    def test_sha256_cas_refusal_precedes_published_checksum_or_lock_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'application'
            app.mkdir()
            (app / 'sdk-lock.json').write_bytes(b'unchanged sdk input')
            accepted = app / campaign.inputs.LOCK
            accepted.write_bytes(b'unchanged accepted closure')
            store = Store(app / 'dependency-inputs/objects')
            identity = store.put(b'original object')
            store.path(identity['digest']).write_bytes(b'tampered object')
            selected = {'artifacts': [
                {'id': name, 'role': 'application', 'format': 'file', 'dependencies': edges,
                 'mount': 'dependencies/java/0000.jar', 'original': identity,
                 'metadata': {'scope': 'selected-runtime', 'coordinates': name}}
                for name, edges in ((campaign.PRIMARY, [campaign.CHILD]), (campaign.CHILD, []))]}
            candidate = root / 'candidate.json'
            write_json(candidate, selected)
            with mock.patch.object(campaign, 'review') as review:
                with self.assertRaises(DependencyError):
                    campaign.resolve_review(mock.Mock(), app, candidate)
                review.assert_not_called()
            self.assertEqual(accepted.read_bytes(), b'unchanged accepted closure')

    def test_nonlinux_refuses_before_output_native_or_command_effects(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'not-created'
            with mock.patch.object(campaign.sys, 'platform', 'win32'), \
                    mock.patch.object(campaign, 'Commands') as commands, \
                    mock.patch.object(campaign, 'ordinary_tuple') as native:
                with self.assertRaisesRegex(WorkflowError, 'linux-required'):
                    campaign.qualify(output, Path('absent'), Path('absent'), Path('absent'), Path('absent'))
                commands.assert_not_called()
                native.assert_not_called()
            self.assertFalse(output.exists())

    def test_failed_receipt_observer_preserves_original_execution_exception_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'output'
            original = RuntimeError('original controlled failure')
            with mock.patch.object(campaign.sys, 'platform', 'linux'), \
                    mock.patch.object(campaign, 'Commands'), \
                    mock.patch.object(campaign, 'ordinary_tuple'), \
                    mock.patch.object(campaign, 'file_identity', return_value={'sha256': 'sha256:' + 'a' * 64, 'bytes': 1}), \
                    mock.patch.object(campaign, 'execute', side_effect=original), \
                    mock.patch.object(campaign, 'write_json', side_effect=RecursionError('observer failed')):
                with self.assertRaises(RuntimeError) as raised:
                    campaign.qualify(output, Path('absent'), Path('absent'), Path('absent'), Path('absent'))
            self.assertIs(raised.exception, original)


class PublishedJarResourceGraph(unittest.TestCase):
    @staticmethod
    def captured(resources):
        import io
        import zipfile
        from tools.application_dependencies import capture, MANIFEST
        from tools.java_resource_artifacts import capture_resources
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root / 'dependency-inputs/objects')
            rows = []
            for ordinal, (name, edges) in enumerate(((campaign.PRIMARY, [campaign.CHILD]), (campaign.CHILD, []))):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
                    archive.writestr('example/Library' + str(ordinal) + '.class', b'\xca\xfe\xba\xbe\x00\x00\x00\x34')
                    if resources:
                        archive.writestr('META-INF/maven/fixture' + str(ordinal) + '/pom.xml', b'<project>captured metadata</project>')
                original = store.put(stream.getvalue())
                rows.append({'id': name, 'role': 'application', 'format': 'file',
                    'mount': 'dependencies/java/' + str(ordinal) + '.jar',
                    'source': {'path': store.path(original['digest']).relative_to(root).as_posix()},
                    'dependencies': edges, 'metadata': {'scope': 'selected-runtime', 'coordinates': name}})
            produced = capture_resources(root, store, rows)
            write_json(root / MANIFEST, {'formatVersion': 1, 'language': 'java', 'selection': {},
                'nativeLocks': [], 'artifacts': produced, 'transformations': []})
            return capture(root)

    def test_actual_resource_capture_retains_two_runtime_jars_and_their_owned_children(self):
        for resources in (False, True):
            with self.subTest(resources=resources):
                candidate = self.captured(resources)
                selected = campaign.selected_jars(candidate)
                self.assertEqual(set(selected), {campaign.PRIMARY, campaign.CHILD})
                children = [row for row in candidate['artifacts'] if row['role'] == 'resource']
                self.assertEqual(len(children), 2 if resources else 0)
                runtime_edges = [edge for edge in selected[campaign.PRIMARY]['dependencies'] if edge in selected]
                self.assertEqual(runtime_edges, [campaign.CHILD])
                self.assertEqual([edge for edge in selected[campaign.CHILD]['dependencies'] if edge in selected], [])

    def test_resource_exception_rejects_missing_forged_duplicate_and_foreign_children(self):
        original = self.captured(True)
        changes = []
        missing = deepcopy(original)
        missing['artifacts'] = [row for row in missing['artifacts'] if row['role'] != 'resource']
        changes.append(missing)
        for field, value in (('jar', campaign.CHILD), ('originalJarDigest', 'sha256:' + '0' * 64)):
            changed = deepcopy(original)
            next(row for row in changed['artifacts'] if row['role'] == 'resource')['metadata'][field] = value
            changes.append(changed)
        changed = deepcopy(original)
        changed['artifacts'].append(deepcopy(next(row for row in changed['artifacts'] if row['role'] == 'resource')))
        changes.append(changed)
        changed = deepcopy(original)
        selected = next(row for row in changed['artifacts'] if row['id'] == campaign.PRIMARY)
        selected['dependencies'].append(campaign.PRIMARY)
        changes.append(changed)
        changed = deepcopy(original)
        next(row for row in changed['artifacts'] if row['role'] == 'resource')['original']['digest'] = 'sha256:' + '0' * 64
        changes.append(changed)
        for candidate in changes:
            with self.subTest(candidate=candidate), self.assertRaises(WorkflowError):
                campaign.selected_jars(candidate)


if __name__ == '__main__':
    unittest.main()
