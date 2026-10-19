"""Public CA selection controls; actual native authentication runs in CI."""
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from tools import go_proxy_tls as tls, go_application_dependencies as native
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical

ROOT = Path(__file__).resolve().parents[2]
CERTIFICATE = (ROOT / 'tools/tests/fixtures/cargo-registry-public-ca.txt').read_bytes()


class PublicProxyTrust(unittest.TestCase):
    def test_installed_go_recipe_contains_the_actual_trust_consumer(self):
        from tools.dev_tool_distribution import recipe
        from tools.go_native_authoring import recipe_identity
        with tempfile.TemporaryDirectory() as temporary:
            payload = Path(temporary)
            recipe(payload, 'go')
            self.assertEqual((payload / 'recipe/tools/go_proxy_tls.py').read_bytes(),
                             (ROOT / 'tools/go_proxy_tls.py').read_bytes())
            self.assertIn('proxy-trust-owner', recipe_identity())

    def prepare(self, directory):
        root = Path(directory)
        project, owned = root / 'application', root / 'owned'
        project.mkdir()
        owned.mkdir()
        (project / 'trust').mkdir()
        (project / 'trust/roots.pem').write_bytes(CERTIFICATE)
        policy = {'tlsTrust': {'caFile': 'trust/roots.pem'}}
        return project, owned, policy

    def test_default_selection_leaves_environment_and_owned_directory_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {'SSL_CERT_FILE': 'controlled-existing-value'}
            self.assertIsNone(tls.prepare(root, root, {}, environment))
            self.assertEqual(environment, {'SSL_CERT_FILE': 'controlled-existing-value'})
            self.assertEqual(list(root.iterdir()), [])

    def test_explicit_public_bundle_is_bounded_owned_and_bound_to_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, owned, policy = self.prepare(temporary)
            environment = {}
            with patch.object(tls.sys, 'platform', 'linux'):
                identity = tls.prepare(project, owned, policy, environment)
            self.assertEqual(identity, tls.identity('trust/roots.pem', CERTIFICATE))
            self.assertEqual(Path(environment['SSL_CERT_FILE']).read_bytes(), CERTIFICATE)
            self.assertEqual(list(Path(environment['SSL_CERT_DIR']).iterdir()), [])
            self.assertEqual(tls.check(project, owned, policy, environment), identity)
            tls.validate(project, identity)
            self.assertEqual((project / 'trust/roots.pem').read_bytes(), CERTIFICATE)

    def test_non_linux_explicit_selection_refuses_before_creating_trust(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, owned, policy = self.prepare(temporary)
            with patch.object(tls.sys, 'platform', 'win32'), self.assertRaisesRegex(DependencyError, 'requires-linux'):
                tls.prepare(project, owned, policy, {})
            self.assertEqual(list(owned.iterdir()), [])

    def test_private_key_malformed_and_oversized_data_are_rejected(self):
        for data in (b'', b'not a certificate', CERTIFICATE + b'\n-----BEGIN PRIVATE KEY-----\nsecret',
                     CERTIFICATE * (tls.MAX_CERTIFICATES + 1), b'x' * (tls.MAX_BYTES + 1)):
            with self.subTest(size=len(data)), self.assertRaises(DependencyError):
                tls.public_bundle(data)

    def test_alias_escape_and_infrastructure_paths_are_rejected(self):
        for name in ('../roots.pem', '/roots.pem', 'vendor/roots.pem', 'target/roots.pem', 'trust\\roots.pem'):
            with self.subTest(name=name), self.assertRaises(DependencyError):
                tls.selection({'tlsTrust': {'caFile': name}})
        for value in (None, [], {'caFile': 'trust/roots.pem', 'verify': False}, {'caFile': False}):
            with self.subTest(value=value), self.assertRaises(DependencyError):
                tls.selection({'tlsTrust': value})

    def test_source_copy_directory_or_environment_mutation_refuses(self):
        for fault in ('source', 'copy', 'directory', 'environment'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                project, owned, policy = self.prepare(temporary)
                environment = {}
                with patch.object(tls.sys, 'platform', 'linux'):
                    tls.prepare(project, owned, policy, environment)
                if fault == 'source':
                    (project / 'trust/roots.pem').write_bytes(CERTIFICATE + b'\n')
                elif fault == 'copy':
                    Path(environment['SSL_CERT_FILE']).write_bytes(CERTIFICATE + b'\n')
                elif fault == 'directory':
                    (Path(environment['SSL_CERT_DIR']) / 'foreign.pem').write_bytes(CERTIFICATE)
                else:
                    environment['SSL_CERT_FILE'] = str(project / 'trust/roots.pem')
                with self.assertRaisesRegex(DependencyError, 'trust-mutated'):
                    tls.check(project, owned, policy, environment)

    def test_offline_public_identity_detects_changed_bytes_and_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, _owned, _policy = self.prepare(temporary)
            value = tls.identity('trust/roots.pem', CERTIFICATE)
            tls.validate(project, value)
            (project / 'trust/roots.pem').write_bytes(CERTIFICATE + b'\n')
            with self.assertRaisesRegex(DependencyError, 'input-drift'):
                tls.validate(project, value)
            for selected in ({**value, 'profile': 'unknown'}, {**value, 'privateKey': 'forbidden'}):
                with self.assertRaisesRegex(DependencyError, 'identity-invalid'):
                    tls.validate(project, selected)

    def test_native_environment_selects_trust_and_netrc_without_inheriting_control_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, owned, trust = self.prepare(temporary)
            policy = {'proxy': 'https://127.0.0.1:34567', 'sumdb': 'off', 'private': ['private.example.test/*'],
                      'username': 'fixture', 'authorizationEnv': 'LSF_PRIVATE_PROXY_FIXTURE', **trust}
            configuration = Path(temporary) / 'outside-policy.json'
            configuration.write_bytes(canonical(policy))
            token = 'owned-fixture-private-token'
            with patch.object(tls.sys, 'platform', 'linux'), patch.dict(os.environ,
                    {'LSF_PRIVATE_PROXY_FIXTURE': token, 'SSL_CERT_FILE': '/foreign/ca',
                     'NETRC': '/foreign/credentials', 'GODEBUG': 'x509usefallbackroots=1'}):
                environment, selected, raw = native.fetch_environment(project, owned, configuration, project=project)
            self.assertEqual(selected, policy)
            self.assertEqual(raw, canonical(policy))
            self.assertNotIn('LSF_PRIVATE_PROXY_FIXTURE', environment)
            self.assertNotIn('GODEBUG', environment)
            self.assertEqual(environment['GOAUTH'], 'netrc')
            self.assertEqual(environment['GONOPROXY'], 'none')
            self.assertEqual(environment['GOTOOLCHAIN'], 'local')
            self.assertIn(token, Path(environment['NETRC']).read_text())
            self.assertTrue(Path(environment['SSL_CERT_FILE']).is_relative_to(owned))
            self.assertNotIn(token, canonical(selected).decode())

    def test_normal_capture_and_exact_review_bind_ca_as_native_input(self):
        from tools.tests.test_go_dependency_authoring import GoDependencyAuthoring
        from tools.go_capsule_project import create, snapshot
        from tools import application_dependencies as inputs, go_dependency_authoring as authoring
        from tools.build_snapshot import digest
        with tempfile.TemporaryDirectory() as temporary:
            model = GoDependencyAuthoring()
            model.original = snapshot(create(Path(temporary) / 'source', 'greeting'))
            model.setUp()
            self.addCleanup(model.doCleanups)
            (model.app / 'trust').mkdir()
            (model.app / 'trust/roots.pem').write_bytes(CERTIFICATE)
            configuration = model.root / 'outside-policy.json'
            configuration.write_bytes(canonical({'proxy': 'https://proxy.example.test', 'sumdb': 'off',
                'tlsTrust': {'caFile': 'trust/roots.pem'}}))
            with patch.object(tls.sys, 'platform', 'linux'):
                candidate, lock = model.capture(proxy_config=configuration)
            graph = json.loads((model.app / 'go-resolved.lock.json').read_bytes())
            self.assertEqual(graph['fetchTrust'], tls.identity('trust/roots.pem', CERTIFICATE))
            captured = [row for row in lock['nativeLocks'] if row['path'] == 'trust/roots.pem']
            self.assertEqual(captured, [{'path': 'trust/roots.pem', 'digest': digest(CERTIFICATE), 'size': len(CERTIFICATE)}])
            authoring.review(model.owner, candidate, digest(candidate.read_bytes()))
            self.assertEqual(authoring.status(model.owner)['status'], 'verified')
            previous = (model.owner / inputs.LOCK).read_bytes()
            (model.app / 'trust/roots.pem').write_bytes(CERTIFICATE + b'\n')
            with self.assertRaises(DependencyError):
                inputs.verify_inputs(model.owner, 'go')
            self.assertEqual((model.owner / inputs.LOCK).read_bytes(), previous)


if __name__ == '__main__':
    unittest.main()
