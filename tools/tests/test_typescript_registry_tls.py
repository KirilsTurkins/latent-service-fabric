"""Explicit npm public trust controls; no native npm/TLS execution credit."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import typescript_registry_tls as tls, typescript_application_dependencies as native
from tools import typescript_dependency_authoring as authoring, npm_lock_authoring as locking
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical, digest
from tools.dev_tool_distribution import recipe
from tools.tests import test_typescript_dependency_authoring as source_fixture
from tools.tests import test_npm_lock_authoring as lock_fixture

ROOT = Path(__file__).resolve().parents[2]
CERTIFICATE = (ROOT/'tools/tests/fixtures/cargo-registry-public-ca.txt').read_bytes()


class RegistryTrust(unittest.TestCase):
    def prepare(self, directory):
        root = Path(directory)
        project, owned = root/'application', root/'owned'
        project.mkdir(); owned.mkdir(); (project/'trust').mkdir()
        (project/'trust/roots.pem').write_bytes(CERTIFICATE)
        return project, owned, {'registries': [], 'tlsTrust': {'caFile': 'trust/roots.pem'}}

    def test_default_has_no_trust_side_effect_and_linux_selection_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            project, owned, policy = self.prepare(directory)
            environment = {'NPM_CONFIG_STRICT_SSL': 'existing'}
            self.assertIsNone(tls.prepare(project, owned, {'registries': []}, environment))
            self.assertEqual(environment, {'NPM_CONFIG_STRICT_SSL': 'existing'})
            self.assertEqual(list(owned.iterdir()), [])
            with patch.object(tls.sys, 'platform', 'win32'), self.assertRaisesRegex(DependencyError, 'requires-linux'):
                tls.prepare(project, owned, policy, environment)
            self.assertEqual(list(owned.iterdir()), [])

    def test_owned_public_bundle_and_identity_are_bound_to_exact_child_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            project, owned, policy = self.prepare(directory)
            environment = {}
            with patch.object(tls.sys, 'platform', 'linux'):
                value = tls.prepare(project, owned, policy, environment)
            self.assertEqual(value, tls.identity('trust/roots.pem', CERTIFICATE))
            self.assertEqual(Path(environment['NPM_CONFIG_CAFILE']).read_bytes(), CERTIFICATE)
            self.assertEqual(environment['NPM_CONFIG_STRICT_SSL'], 'true')
            self.assertNotIn('NODE_EXTRA_CA_CERTS', environment)
            tls.validate(project, value)
            self.assertEqual(tls.check(project, owned, policy, environment), value)

    def test_private_key_malformed_oversized_and_non_certificate_data_refuse(self):
        for raw in (b'', b'not-pem', CERTIFICATE + b'-----BEGIN PRIVATE KEY-----\nsecret',
                    CERTIFICATE*(tls.MAX_CERTIFICATES+1), b'x'*(tls.MAX_BYTES+1)):
            with self.subTest(size=len(raw)), self.assertRaises(DependencyError):
                tls.public_bundle(raw)

    def test_infrastructure_escape_and_open_trust_declarations_refuse(self):
        for value in ({'caFile': '../roots.pem'}, {'caFile': '/roots.pem'}, {'caFile': 'vendor/roots.pem'},
                      {'caFile': 'trust\\roots.pem'}, {'caFile': 'trust/roots.pem', 'verify': False}, None):
            with self.subTest(value=value), self.assertRaises(DependencyError):
                tls.selection({'tlsTrust': value})

    def test_source_owned_copy_and_tls_verification_mutation_refuse(self):
        for fault in ('source', 'copy', 'path', 'verify'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                project, owned, policy = self.prepare(directory); environment = {}
                with patch.object(tls.sys, 'platform', 'linux'):
                    tls.prepare(project, owned, policy, environment)
                if fault == 'source':
                    (project/'trust/roots.pem').write_bytes(CERTIFICATE+b'\n')
                elif fault == 'copy':
                    Path(environment['NPM_CONFIG_CAFILE']).write_bytes(CERTIFICATE+b'\n')
                elif fault == 'path':
                    environment['NPM_CONFIG_CAFILE'] = str(project/'trust/roots.pem')
                else:
                    environment['NPM_CONFIG_STRICT_SSL'] = 'false'
                with self.assertRaises(DependencyError):
                    tls.check(project, owned, policy, environment)

    def test_offline_changed_source_or_profile_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            project, owned, policy = self.prepare(directory)
            value = tls.identity('trust/roots.pem', CERTIFICATE)
            with self.assertRaises(DependencyError):
                tls.validate(project, {**value, 'profile': 'other'})
            (project/'trust/roots.pem').write_bytes(CERTIFICATE+b'\n')
            with self.assertRaisesRegex(DependencyError, 'input-drift'):
                tls.validate(project, value)

    def test_native_environment_keeps_tokens_opaque_and_uses_only_explicit_npm_ca(self):
        with tempfile.TemporaryDirectory() as directory:
            project, owned, policy = self.prepare(directory)
            policy['registries'] = [{'url': 'https://private.example.invalid/', 'authorizationEnv': 'NODE_OPTIONS'}]
            with patch.dict(os.environ, {'NODE_OPTIONS': '--require /forbidden',
                    'NPM_CONFIG_STRICT_SSL': 'false', 'NODE_EXTRA_CA_CERTS': '/ambient-roots'}), \
                 patch.object(tls.sys, 'platform', 'linux'):
                environment = native.fetch_environment(owned, policy, project=project)
            self.assertEqual(environment['LSF_NPM_REGISTRY_TOKEN_0'], '--require /forbidden')
            self.assertEqual(environment['NPM_CONFIG_STRICT_SSL'], 'true')
            self.assertNotIn('NODE_OPTIONS', environment)
            self.assertNotIn('NODE_EXTRA_CA_CERTS', environment)
            self.assertNotIn('--require', (owned/'registry.npmrc').read_text())

    def test_installed_recipe_contains_actual_trust_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            recipe(output, 'typescript')
            self.assertEqual((output/'recipe/tools/typescript_registry_tls.py').read_bytes(),
                             (ROOT/'tools/typescript_registry_tls.py').read_bytes())


class RegistryTrustCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source_fixture.NpmDependencyAuthoring.setUpClass.__func__(cls)

    def fixture(self, kind=source_fixture.NpmDependencyAuthoring):
        fixture = kind('test_exact_capture_review_and_offline_resource_after_originals_are_removed'
                       if kind is source_fixture.NpmDependencyAuthoring else 'test_first_add_creates_only_native_application_declaration')
        fixture.original = self.original
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        (fixture.app/'trust').mkdir()
        (fixture.app/'trust/roots.pem').write_bytes(CERTIFICATE)
        policy = fixture.root/'registries.json'
        policy.write_bytes(canonical({'registries': [], 'tlsTrust': {'caFile': 'trust/roots.pem'}}))
        return fixture, policy

    def test_real_capture_and_exact_review_bind_ca_as_native_input(self):
        fixture, policy = self.fixture()
        with patch.object(tls.sys, 'platform', 'linux'):
            candidate, lock = fixture.capture(registry_config=policy)
        self.assertIn('trust/roots.pem', [row['path'] for row in lock['nativeLocks']])
        graph = json.loads((fixture.app/'npm-resolved.lock.json').read_bytes())
        self.assertEqual(graph['fetchTrust'], tls.identity('trust/roots.pem', CERTIFICATE))
        authoring.review(fixture.owner, candidate, digest(candidate.read_bytes()))
        self.assertEqual(authoring.status(fixture.owner)['status'], 'verified')
        accepted = (fixture.owner/'latent.dependencies.lock.json').read_bytes()
        (fixture.app/'trust/roots.pem').write_bytes(CERTIFICATE+b'\n')
        with self.assertRaises(DependencyError):
            authoring.status(fixture.owner)
        self.assertEqual((fixture.owner/'latent.dependencies.lock.json').read_bytes(), accepted)

    def test_native_lock_checks_owned_trust_and_records_immutable_recipe(self):
        fixture, policy = self.fixture(lock_fixture.NpmLockAuthoring)
        with patch.object(tls.sys, 'platform', 'linux'), patch.object(locking, 'run_bounded', side_effect=fixture.command):
            result = locking.create_lock(fixture.owner, node=fixture.node, npm=fixture.npm, registry_config=policy)
        self.assertEqual(result['fetchTrust'], tls.identity('trust/roots.pem', CERTIFICATE))
        self.assertIn('npm-public-trust-owner', result['recipe'])
        self.assertEqual((fixture.app/'sdk-lock.json').read_bytes(), fixture.sdk)


if __name__ == '__main__':
    unittest.main()
