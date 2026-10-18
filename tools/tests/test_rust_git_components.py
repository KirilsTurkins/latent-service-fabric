"""Git component campaign source controls; all native operations here are modelled."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from tools import application_dependencies as dependencies
from tools import qualify_rust_git_components as campaign
from tools import rust_git_component_fixture as fixture
from tools.build_snapshot import canonical, digest
from tools.phase3_resource_identity import file_identity
from tools.native_runtime.common import InstallError
from tools.rust_capsule_project import create


class GitComponentCapture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='git-component-source-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = create(self.root / 'app', 'greeting')
        self.original_sdk = (self.project / 'sdk-lock.json').read_bytes()
        self.cargo = self.root / 'cargo-never-executed'
        self.outside = self.root / 'outside'
        version, revision = fixture.REVISIONS[-1]
        self.source = f'git+{fixture.REPOSITORY}?rev={revision}#{revision}'
        self.git_id, self.local_id = 'git-package-id', 'outside-path-package-id'
        self.lock = {'artifacts': [], 'executableInputs': []}
        for name, version, identity, source in ((fixture.PACKAGE, version, self.git_id, self.source),
                (fixture.LOCAL_PACKAGE, fixture.LOCAL_VERSION, self.local_id, 'captured-path')):
            self.lock['artifacts'].append({'id': name + '/' + version, 'role': 'application',
                'treeDigest': digest(name.encode()), 'metadata': {'package': name, 'version': version,
                'nativeIdDigest': digest(identity.encode()), 'nativeSourceDigest': digest(source.encode())}})
        edges = [{'pkg': self.git_id}, {'pkg': self.local_id}]
        self.graph = {'root': 'root', 'nodes': [{'id': 'root', 'dependencies': edges}]
            + [{'id': identity, 'artifact': row['id'], 'source': source} for identity, row, source in
               zip((self.git_id, self.local_id), self.lock['artifacts'], (self.source, 'captured-path'))],
            'selectedResolve': {'root': 'root', 'nodes': [{'id': 'root', 'deps': edges}]}}
        self.calls = []
        self.author = self.enterContext(patch.object(fixture.authoring, 'author',
            side_effect=lambda *args, **kwargs: self.calls.append((args, kwargs)) or {'status': 'modelled'}))
        self.resolve = self.enterContext(patch.object(fixture.native, 'resolve', side_effect=self.capture))
        self.review = self.enterContext(patch.object(fixture.review, 'review', side_effect=self.accept))
        self.enterContext(patch.object(fixture.review, 'status', return_value={'status': 'verified'}))

    def capture(self, project, candidate, *, cargo):
        self.assertEqual(project, self.project)
        self.assertEqual(cargo, self.cargo)
        self.assertTrue((self.outside / fixture.LOCAL_PACKAGE / 'src/lib.rs').is_file())
        candidate.write_bytes(canonical(self.lock))
        (project / 'cargo-resolved.lock.json').write_bytes(canonical(self.graph))
        return self.lock

    def accept(self, project, candidate, identity):
        self.assertEqual(identity, digest(candidate.read_bytes()))
        (project / dependencies.LOCK).write_bytes(candidate.read_bytes())

    def test_normal_exact_git_authoring_and_unchanged_api_precede_review_and_original_removal(self):
        result = fixture.install(self.project, self.outside, self.cargo)
        self.assertEqual(self.calls[0][0], (self.project, 'add'))
        self.assertEqual(self.calls[0][1], {'identity': fixture.PACKAGE, 'version': fixture.REVISIONS[-1][0],
            'git': fixture.REPOSITORY, 'revision': fixture.REVISIONS[-1][1], 'cargo': self.cargo})
        self.assertEqual(self.calls[1][1]['local'], self.outside / fixture.LOCAL_PACKAGE)
        self.assertEqual(result['executableInputs'], [])
        self.assertFalse(result['catalogueRegistration'])
        self.assertEqual(result['catalogueRemoval'], 'not-tested')
        self.assertEqual(len(result['applicationLibraries']), 2)
        self.assertEqual(result['resourceDigests']['binary.dat'], digest(bytes((0, 255, 65, 128))))
        self.assertIn('UnicodeXID::is_xid_start', fixture.LIBRARY)
        self.assertIn('UnicodeXID::is_xid_continue', fixture.LIBRARY)
        self.assertIn('include_str!("greeting.txt")', fixture.LIBRARY)
        self.assertIn(b'outside_git_component_library::prefix()', (self.project / 'src/lib.rs').read_bytes())
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.original_sdk)
        self.assertFalse((self.outside / fixture.LOCAL_PACKAGE).exists())
        self.review.assert_called_once()

    def test_foreign_revision_or_executable_input_cannot_reach_review_or_cleanup(self):
        for change in ('source', 'executable'):
            lock, graph = copy.deepcopy(self.lock), copy.deepcopy(self.graph)
            if change == 'source':
                graph['nodes'][1]['source'] = self.source.replace(fixture.REVISIONS[-1][1], '0' * 40)
            else:
                lock['executableInputs'] = [{'id': 'not-approved'}]
            with self.subTest(change=change), self.assertRaises(ValueError):
                fixture.selected(lock, graph)
        self.lock['executableInputs'] = [{'id': 'not-approved'}]
        with self.assertRaisesRegex(ValueError, 'Git-component-unexpected-executable-input'):
            fixture.install(self.project, self.outside, self.cargo)
        self.review.assert_not_called()
        self.assertTrue((self.outside / fixture.LOCAL_PACKAGE / 'src/lib.rs').is_file())

    def test_selected_git_must_be_a_real_application_root_edge(self):
        self.graph['nodes'][0]['dependencies'] = [{'pkg': self.local_id}]
        with self.assertRaisesRegex(ValueError, 'not independently selected'):
            fixture.install(self.project, self.outside, self.cargo)
        self.review.assert_not_called()
        self.assertTrue((self.outside / fixture.LOCAL_PACKAGE).is_dir())

    def test_changed_greeting_hook_is_refused_before_native_authoring(self):
        source = self.project / 'src/lib.rs'
        source.write_bytes(source.read_bytes().replace(b'Hello, {name}!', b'Changed, {name}!'))
        with self.assertRaisesRegex(ValueError, 'Git-component-greeting-source-hook-changed'):
            fixture.install(self.project, self.outside, self.cargo)
        self.author.assert_not_called()
        self.resolve.assert_not_called()


class PreparedGitComponentInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='git-component-bundle-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prepared = self.root / 'prepared'
        self.prepared.mkdir()
        self.source = {'fixture': 'source-inputs-not-native-proof'}
        self.enterContext(patch.object(campaign, 'inputs', return_value=self.source))
        raw = canonical(self.source)
        for name in ('source-inputs.json', 'source-inputs-after.json'):
            (self.prepared / name).write_bytes(raw)
        self.qualified = {'status': 'passed', 'applicationDependencies': {}, 'sourceIdentityDigest': digest(raw),
                          'binaries': {}, 'builds': {}}
        for name in campaign.PRODUCTS:
            path = self.prepared / 'native-binaries' / name.replace('/', '-')
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'synthetic-not-an-executable')
            self.qualified['binaries'][name] = file_identity(path)
        for name in campaign.COMPANIONS:
            path = self.prepared / 'builds' / name
            path.mkdir(parents=True)
            for filename in campaign.SIGNER_FILES:
                (path / filename).write_bytes(canonical({'fixture': name}))
            (path / 'component.wasm').write_bytes(b'synthetic-not-wasm')
            (path / 'package-source.json').write_bytes(canonical({'layers': [{'source': 'component.wasm'}]}))
            self.qualified['builds'][name] = {'fixture': name}
        self.save()

    def save(self):
        (self.prepared / 'qualification.json').write_bytes(canonical(self.qualified))

    def test_bundle_exports_only_closed_public_signer_inputs_and_exact_native_files(self):
        (self.prepared / 'not-exported-private-fixture.txt').write_bytes(b'synthetic-not-a-credential')
        (self.prepared / 'builds/word-count/compiler-source.rs').write_bytes(b'not a signer input')
        result = campaign.bundle(self.prepared, self.root / 'bundle')
        output = self.root / 'bundle'
        self.assertEqual(result['files'], 32)
        self.assertFalse((output / 'not-exported-private-fixture.txt').exists())
        self.assertFalse((output / 'builds/word-count/compiler-source.rs').exists())
        self.assertEqual(campaign.prepared_inputs(output)[:2], (self.source, self.qualified))

    def test_changed_source_native_or_companion_is_refused_before_bundle_creation(self):
        mutations = [('source-inputs-after.json', b'{}'), ('native-binaries/latent', b'changed'),
                     ('builds/word-count/BUILD-COMPLETE.json', b'{}')]
        for name, changed in mutations:
            path = self.prepared / name
            original = path.read_bytes()
            path.write_bytes(changed)
            with self.subTest(name=name), self.assertRaises(ValueError):
                campaign.bundle(self.prepared, self.root / 'bundle')
            path.write_bytes(original)
            self.assertFalse((self.root / 'bundle').exists())

    def test_unexpected_native_product_cannot_be_executed_or_exported(self):
        self.qualified['binaries']['outside-unreviewed-tool'] = {'sha256': '0' * 64, 'bytes': 0}
        self.save()
        with self.assertRaisesRegex(ValueError, 'Git-component-exact-five-native-products-required'):
            campaign.bundle(self.prepared, self.root / 'bundle')

    def test_signer_layer_paths_cannot_escape_the_prepared_build(self):
        path = self.prepared / 'builds/word-count/package-source.json'
        for index, name in enumerate(('../not-exported-private-fixture.txt', '/etc/passwd', 'keys\\secret')):
            path.write_bytes(canonical({'layers': [{'source': name}]}))
            with self.subTest(name=name), self.assertRaises(InstallError):
                campaign.bundle(self.prepared, self.root / ('bundle-' + str(index)))

    def exercise_campaign(self, *, mutate=False):
        output = self.root / 'campaign'
        self.qualified['tools'] = [{'name': 'cargo', 'fixture': 'exact-tool'}]
        self.save()
        order = []
        commands = Mock(environment={}, records=[], deadline=time.monotonic() + 1100)
        commands.run.side_effect = lambda *args: order.append(('sign', args))

        def build(app, destination, *args, **kwargs):
            order.append(('build', kwargs))
            destination.mkdir()
            (destination / 'cargo-inputs.json').write_bytes(canonical({'networkResolution': False}))
            (destination / 'BUILD-COMPLETE.json').write_bytes(canonical({'fixture': 'modelled-build'}))
            if mutate:
                (app / 'src/lib.rs').write_bytes(b'mutated source')
            return destination

        def offline(*args):
            order.append(('offline', args))
            return {'status': 'modelled'}

        def node(*args, **kwargs):
            order.append(('node', kwargs))
            destination = output / 'node'
            destination.mkdir()
            (destination / 'workflow.json').write_bytes(canonical({'status': 'modelled'}))
            return {'status': 'passed'}

        self.enterContext(patch.object(campaign, 'Commands', return_value=commands))
        self.enterContext(patch.object(campaign, 'resolve_tools', return_value=(
            {'cargo': self.root / 'never-executed-cargo'}, self.qualified['tools'])))
        self.enterContext(patch.object(campaign, 'install', return_value={'status': 'modelled'}))
        self.enterContext(patch.object(campaign, 'offline', side_effect=offline))
        self.enterContext(patch.object(campaign, 'build', side_effect=build))
        self.enterContext(patch.object(campaign, 'node_workflow', side_effect=node))
        return output, order

    def test_offline_identity_then_two_isolated_builds_precede_strict_signer_and_node(self):
        output, order = self.exercise_campaign()
        result = campaign.qualify(self.prepared, output)
        self.assertEqual([row[0] for row in order], ['offline', 'build', 'build', 'sign', 'node'])
        self.assertTrue(all(row[1] == {'offline': True} for row in order if row[0] == 'build'))
        sign = next(row[1] for row in order if row[0] == 'sign')
        self.assertEqual(sign[1], self.prepared / 'native-binaries/examples-capsule_authoring')
        self.assertEqual(sign[2:4], ('demo-sign', output / 'signed'))
        self.assertEqual(sign[4], output / 'first')
        self.assertEqual(sign[5:], tuple(self.prepared / 'builds' / name for name in campaign.COMPANIONS))
        self.assertEqual(next(row[1] for row in order if row[0] == 'node'), {'language': 'rust'})
        self.assertFalse(result['hermetic'])
        self.assertEqual(result['releasePublication'], 'not-performed')

    def test_mutated_original_during_build_cannot_reach_signer_or_node(self):
        output, order = self.exercise_campaign(mutate=True)
        with self.assertRaisesRegex(ValueError, 'Git-component-build-mutated-source'):
            campaign.qualify(self.prepared, output)
        self.assertEqual([row[0] for row in order], ['offline', 'build'])
        self.assertEqual(json.loads((output / 'FAILED.json').read_bytes())['stage'],
                         'isolated-offline-component-builds')
        self.assertFalse((output / 'qualification.json').exists())
