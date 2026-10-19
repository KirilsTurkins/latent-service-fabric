"""Explicit NuGet trust source controls; no compiler or restore is executed."""
import json
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from tools import dotnet_application_dependencies as native
from tools import dotnet_registry_tls as tls
from tools import dotnet_dependency_authoring as authoring
from tools import application_dependencies as dependencies
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical, digest
from tools.dotnet_guest.project import create
from tools.rust_capsule_project import snapshot


class PrivateFeedPolicy(unittest.TestCase):
    def test_explicit_public_ca_selection_preserves_sources_and_redacts_private_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = {'sources': [{'name': 'team', 'url': 'https://127.0.0.1:9443/index.json',
                                  'patterns': ['Outside.*'], 'authorizationEnv': 'LSF_NUGET_TEAM_PASSWORD'}],
                      'tlsTrust': {'caFile': 'feed-trust/public-roots.pem'}}
            baseline = b'<configuration><packageSources><add key="sdk" value="https://api.nuget.org/v3/index.json" /></packageSources><packageSourceMapping><packageSource key="sdk"><package pattern="Maintained.*" /></packageSource></packageSourceMapping></configuration>'
            with patch.dict(os.environ, {'LSF_NUGET_TEAM_PASSWORD': 'opaque-test-value'}):
                raw, identity = native.feed_config(policy, Path(directory), baseline)
            parsed = ET.fromstring(raw)
            self.assertEqual([row.attrib['key'] for row in parsed.find('packageSources') if row.tag == 'add'], ['sdk', 'team'])
            self.assertIn(b'opaque-test-value', raw)
            self.assertNotIn('opaque-test-value', json.dumps(identity))
            self.assertNotIn('https://127.0.0.1', json.dumps(identity))
            self.assertEqual(identity['sources'][1]['kind'], 'https')

    def test_malformed_trust_shape_or_escaping_path_refuses_without_reading_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ({'caFile': '../outside.pem'}, {'caFile': '/outside.pem'}, {'caFile': 'vendor/roots.pem'},
                          {'caFile': 'target/roots.pem'}, {'caFile': 'feeds/root.pem', 'skipVerification': True},
                          {'caFile': True}, 'ambient'):
                with self.subTest(value=value), self.assertRaises(DependencyError):
                    native.feed_config({'sources': [], 'tlsTrust': value}, Path(directory),
                        b'<configuration><packageSources /><packageSourceMapping /></configuration>')


class OwnedRestoreTrust(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='nuget-trust-source-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app, self.owned = self.root / 'app', self.root / 'restore'
        self.app.mkdir()
        self.owned.mkdir()
        self.name = 'feed-trust/public-roots.pem'
        self.ca = self.app / self.name
        self.ca.parent.mkdir()
        # ISRG Root X1 is public test data, not an issuer private key.
        # Exact source: https://letsencrypt.org/certs/isrgrootx1.pem
        self.raw = (Path(__file__).parent / 'fixtures/nuget-public-ca.pem').read_bytes()
        self.ca.write_bytes(self.raw)
        self.files = {self.name: self.raw}
        self.policy = {'sources': [], 'tlsTrust': {'caFile': self.name}}

    def prepare(self, environment=None):
        environment = {} if environment is None else environment
        with patch.object(tls.sys, 'platform', 'linux'):
            return tls.prepare(self.app, self.files, self.policy, self.owned, environment)

    def test_selected_public_ca_is_parsed_and_bound_only_to_private_child_environment(self):
        environment = {'PATH': 'unchanged'}
        original = dict(os.environ)
        trust = self.prepare(environment)
        self.assertEqual(dict(os.environ), original)
        self.assertEqual(environment['PATH'], 'unchanged')
        self.assertEqual(environment['SSL_CERT_FILE'], str(trust.bundle))
        self.assertEqual(environment['SSL_CERT_DIR'], str(trust.directory))
        self.assertEqual(trust.bundle.read_bytes(), self.raw)
        self.assertFalse(list(trust.directory.iterdir()))
        self.assertEqual(trust.identity, {'profile': tls.PROFILE, 'caFile': self.name,
                                         'digest': digest(self.raw), 'size': len(self.raw)})
        self.assertNotIn(str(self.root), json.dumps(trust.identity))
        trust.check()
        tls.validate(self.files, trust.identity)

    def test_default_policy_does_not_add_any_environment_or_trust_file(self):
        environment = {'PATH': 'original', 'SSL_CERT_FILE': 'explicit-caller-sentinel'}
        before = dict(environment)
        self.assertIsNone(tls.prepare(self.app, self.files, None, self.owned, environment))
        self.assertEqual(environment, before)
        self.assertFalse(list(self.owned.iterdir()))

    def test_other_platform_refuses_explicit_profile_before_any_trust_installation(self):
        with patch.object(tls.sys, 'platform', 'win32'), self.assertRaisesRegex(DependencyError, 'requires-linux'):
            tls.prepare(self.app, self.files, self.policy, self.owned, {})
        self.assertFalse(list(self.owned.iterdir()))

    def test_private_keys_invalid_certificates_oversize_and_certificate_count_refuse(self):
        for raw in (b'-----BEGIN PRIVATE KEY-----\nAQID\n-----END PRIVATE KEY-----',
                    b'-----BEGIN CERTIFICATE-----\nAQID\n-----END CERTIFICATE-----',
                    self.raw + b'private-data', self.raw * 257, b'x' * (tls.MAX_BUNDLE + 1)):
            with self.subTest(length=len(raw)), self.assertRaisesRegex(DependencyError, 'public-ca-bundle-required'):
                tls.public_bundle(raw)

    def test_missing_changed_or_hardlinked_source_refuses_before_owned_environment_mutation(self):
        environment = {}
        os.link(self.ca, self.root / 'linked-ca.pem')
        with self.assertRaisesRegex(DependencyError, 'certificate-unavailable-or-changed'):
            self.prepare(environment)
        self.assertEqual(environment, {})
        self.assertFalse(list(self.owned.iterdir()))
        (self.root / 'linked-ca.pem').unlink()
        self.ca.write_bytes(self.raw + b'\n')
        with self.assertRaisesRegex(DependencyError, 'certificate-unavailable-or-changed'):
            self.prepare(environment)
        self.ca.unlink()
        with self.assertRaisesRegex(DependencyError, 'certificate-unavailable-or-changed'):
            self.prepare(environment)

    def test_owned_copy_environment_or_selected_source_drift_refuses(self):
        trust = self.prepare()
        trust.bundle.write_bytes(self.raw + b'\n')
        with self.assertRaisesRegex(DependencyError, 'trust-mutated'):
            trust.check()
        trust.bundle.write_bytes(self.raw)
        trust.environment['SSL_CERT_FILE'] = '/unselected/ambient'
        with self.assertRaisesRegex(DependencyError, 'trust-mutated'):
            trust.check()
        trust.environment['SSL_CERT_FILE'] = str(trust.bundle)
        self.ca.write_bytes(self.raw + b'\n')
        with self.assertRaisesRegex(DependencyError, 'trust-mutated'):
            trust.check()

    def test_offline_trust_identity_checks_exact_bytes_types_and_closed_profile(self):
        trust = self.prepare()
        for update in ({'size': True}, {'size': len(self.raw) - 1}, {'digest': digest(b'foreign')},
                       {'profile': 'other'}, {'caFile': 'other.pem'}, {'skipVerification': True}):
            with self.subTest(update=update), self.assertRaises(DependencyError):
                tls.validate(self.files, {**trust.identity, **update})
        with self.assertRaisesRegex(DependencyError, 'trust-input-drift'):
            tls.validate({self.name: self.raw + b'\n'}, trust.identity)


class RealRestoreBoundary(unittest.TestCase):
    def exercise(self, root, *, mutate_during_restore=False):
        project = create(root / 'app', 'greeting')
        ca_name = 'feed-trust/public-roots.pem'
        ca = project / ca_name
        ca.parent.mkdir()
        ca.write_bytes((Path(__file__).parent / 'fixtures/nuget-public-ca.pem').read_bytes())
        files = snapshot(project)
        sdk_before = files['sdk-lock.json']
        tools = root / 'tools'
        (tools / 'package-hash').mkdir(parents=True)
        (tools / 'package-hash/PackageHash.dll').write_bytes(b'not-executed-helper')
        helper_source = project / 'vendor/lsf/sdk/dotnet-guest/tools/package-hash'
        for name, raw in snapshot(helper_source).items():
            target = tools / 'package-hash-source' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        dotnet = root / 'dotnet-not-executed'
        dotnet.write_bytes(b'not-executed-dotnet')
        baseline_raw = files['vendor/lsf/sdk/dotnet-guest/probes/smoke/packages.lock.json']
        baseline = native.native_json(baseline_raw)
        declared = native.declarations(files)
        model = {'formatVersion': 1, **declared, 'packages': [], 'sdkBaselineDigest': digest(canonical(baseline))}
        observed = []
        def process(arguments, owned, environment, *_bounds):
            if arguments[1] == '--version':
                return SimpleNamespace(stdout=b'10.0.100')
            self.assertEqual(arguments[1], 'restore')
            self.assertEqual(environment['SSL_CERT_FILE'], str(owned / 'nuget-feed-trust/public-ca-bundle.pem'))
            self.assertEqual((owned / 'nuget-feed-trust/public-ca-bundle.pem').read_bytes(), files[ca_name])
            self.assertEqual(list((owned / 'nuget-feed-trust/empty-certificates').iterdir()), [])
            self.assertNotIn('SSL_CERT_FILE', os.environ)
            observed.append('restore-model-boundary')
            (owned / native.LOCK).write_bytes(baseline_raw)
            (owned / 'obj').mkdir()
            (owned / 'obj/project.assets.json').write_bytes(canonical({'version': 3, 'targets': {}, 'libraries': {}}))
            if mutate_during_restore:
                ca.write_bytes(files[ca_name] + b'\n')
            return SimpleNamespace(stdout=b'')
        candidate = root / 'candidate.json'
        with patch.object(tls.sys, 'platform', 'linux'), patch.object(native, 'run_bounded', side_effect=process), \
                patch.object(native, 'analyze', side_effect=lambda *_: copy.deepcopy(model)):
            if mutate_during_restore:
                with self.assertRaisesRegex(DependencyError, 'nuget-feed-trust-mutated'):
                    native.resolve(project, candidate, dotnet=dotnet, tools=tools,
                                   policy={'sources': [], 'tlsTrust': {'caFile': ca_name}})
                self.assertFalse(candidate.exists())
                self.assertFalse((project / dependencies.MANIFEST).exists())
            else:
                lock = native.resolve(project, candidate, dotnet=dotnet, tools=tools,
                                      policy={'sources': [], 'tlsTrust': {'caFile': ca_name}})
                self.assertIn(ca_name, [row['path'] for row in lock['nativeLocks']])
                graph = json.loads((project / native.ASSETS).read_bytes())
                self.assertEqual(graph['fetchPolicy']['tlsTrust']['digest'], digest(files[ca_name]))
                authoring.review(project, candidate, digest(candidate.read_bytes()))
                self.assertIsNotNone(dependencies.verify_inputs(project, 'dotnet'))
                ca.write_bytes(files[ca_name] + b'\n')
                with self.assertRaisesRegex(DependencyError, 'dependency-native-lock-drift'):
                    dependencies.verify_inputs(project, 'dotnet')
        self.assertEqual(observed, ['restore-model-boundary'])
        self.assertEqual((project / 'sdk-lock.json').read_bytes(), sdk_before)

    def test_real_resolve_capture_and_exact_review_bind_selected_ca_as_native_input(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SSL_CERT_FILE', None)
            self.exercise(Path(directory))

    def test_actual_restore_boundary_refuses_ca_mutation_before_candidate_publication(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SSL_CERT_FILE', None)
            self.exercise(Path(directory), mutate_during_restore=True)


if __name__ == '__main__':
    unittest.main()
