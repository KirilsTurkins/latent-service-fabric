"""Public CA inputs are explicit native locks; credentials and ambient trust stay excluded."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import npm_registry_tls as tls, typescript_application_dependencies as native
from tools import typescript_dependency_authoring as authoring
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import digest
from tools.tests import test_typescript_dependency_authoring as fixture

# Public X.509 root from pinned Node24.19 builtin roots, containing no private key.
CERTIFICATE = b"""-----BEGIN CERTIFICATE-----
MIIEkTCCA3mgAwIBAgIERWtQVDANBgkqhkiG9w0BAQUFADCBsDELMAkGA1UEBhMCVVMxFjAU
BgNVBAoTDUVudHJ1c3QsIEluYy4xOTA3BgNVBAsTMHd3dy5lbnRydXN0Lm5ldC9DUFMgaXMg
aW5jb3Jwb3JhdGVkIGJ5IHJlZmVyZW5jZTEfMB0GA1UECxMWKGMpIDIwMDYgRW50cnVzdCwg
SW5jLjEtMCsGA1UEAxMkRW50cnVzdCBSb290IENlcnRpZmljYXRpb24gQXV0aG9yaXR5MB4X
DTA2MTEyNzIwMjM0MloXDTI2MTEyNzIwNTM0MlowgbAxCzAJBgNVBAYTAlVTMRYwFAYDVQQK
Ew1FbnRydXN0LCBJbmMuMTkwNwYDVQQLEzB3d3cuZW50cnVzdC5uZXQvQ1BTIGlzIGluY29y
cG9yYXRlZCBieSByZWZlcmVuY2UxHzAdBgNVBAsTFihjKSAyMDA2IEVudHJ1c3QsIEluYy4x
LTArBgNVBAMTJEVudHJ1c3QgUm9vdCBDZXJ0aWZpY2F0aW9uIEF1dGhvcml0eTCCASIwDQYJ
KoZIhvcNAQEBBQADggEPADCCAQoCggEBALaVtkNC+sZtKm9I35RMOVcF7sN5EUFoNu3s/poB
j6E4KPz3EEZmLk0eGrEaTsbRwJWIsMn/MYszA9u3g3s+IIRe7bJWKKf44LlAcTfFy0cOlypo
wCKVYhXbR9n10Cv/gkvJrT7eTNuQgFA/CYqEAOwwCj0Yzfv9KlmaI5UXLEWeH25DeW0MXJj+
SKfFI0dcXv1u5x609mhF0YaDW6KKjbHjKYD+JXGIrb68j6xSlkuqUY3kEzEZ6E5Nn9uss2rV
vDlUccp6en+Q3X0dgNmBu1kmwhH+5pPi94DkZfs0Nw4pgHBNrziGLp5/V6+eF67rHMsoIV+2
HNjnogQi+dPa2MsCAwEAAaOBsDCBrTAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0TAQH/BAUwAwEB
/zArBgNVHRAEJDAigA8yMDA2MTEyNzIwMjM0MlqBDzIwMjYxMTI3MjA1MzQyWjAfBgNVHSME
GDAWgBRokORnpKZTgMeGZqTx90tD+4S9bTAdBgNVHQ4EFgQUaJDkZ6SmU4DHhmak8fdLQ/uE
vW0wHQYJKoZIhvZ9B0EABBAwDhsIVjcuMTo0LjADAgSQMA0GCSqGSIb3DQEBBQUAA4IBAQCT
1DCw1wMgKtD5Y+iRDAUgqV8ZyntyTtSx29CW+1RaGSwMCPeyvIWonX9tO1KzKtvn1ISMY/YP
yyYBkVBs9F8U4pN0wBOeMDpQ47RgxRzwIkSNcUesyBrJ6ZuaAGAT/3B+XxFNSRuzFVJ7yVTa
v52Vr2ua2J7p8eRDjeIRRDq/r72DQnNSi6q7pynP9WQcCk3RvKqsnyrQ/39/2n3qse0wJcGE
2jTSW3iDVuycNsMm4hH2Z0kdkquM++v/eu6FSqdQgPCnXEqULl8FmTxSQeDNtGPPAUO6nIPc
j2A781q0tHuu2guQOHXvgR1m0vdXcDazv/wor3ElhVsT/h5/WrQ8
-----END CERTIFICATE-----
"""


class NpmRegistryTrust(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app, self.work = self.root / 'app', self.root / 'work'
        self.app.mkdir(); self.work.mkdir()
        (self.app / 'registry').mkdir()
        (self.app / 'registry/public-ca.pem').write_bytes(CERTIFICATE)
        self.policy = {'registries': [{'scope': '@team', 'url': 'https://packages.example.test/',
            'tlsTrust': {'caFile': 'registry/public-ca.pem'}}]}

    def test_explicit_public_ca_augments_pinned_node_roots_with_verified_owned_bundle(self):
        with patch.dict(os.environ, {'NODE_EXTRA_CA_CERTS': '/unobserved/ambient.pem', 'NODE_OPTIONS': '--inspect'}):
            trust = tls.Trust(self.app, self.policy, self.work)
            environment = native.fetch_environment(self.work, self.policy, trust=trust)
        self.assertEqual(Path(environment['NODE_EXTRA_CA_CERTS']).read_bytes(), CERTIFICATE)
        self.assertNotIn('NODE_OPTIONS', environment)
        self.assertEqual(trust.identity['certificates'], [{'path': 'registry/public-ca.pem',
            'digest': digest(CERTIFICATE), 'size': len(CERTIFICATE)}])
        self.assertEqual(trust.identity['defaultRoots'], 'pinned-native-node-builtin')
        self.assertIn('strict-ssl=true', (self.work / 'registry.npmrc').read_text())
        self.assertNotIn('strict-ssl=false', (self.work / 'registry.npmrc').read_text())
        trust.check_unchanged()

    def test_no_declared_ca_never_inherits_ambient_extra_roots(self):
        policy = {'registries': []}
        with patch.dict(os.environ, {'NODE_EXTRA_CA_CERTS': '/unobserved/ambient.pem'}):
            trust = tls.Trust(self.app, policy, self.work)
            environment = native.fetch_environment(self.work, policy, trust=trust)
        self.assertNotIn('NODE_EXTRA_CA_CERTS', environment)
        self.assertIsNone(trust.identity)
        self.assertEqual(trust.sources, {})

    def test_private_keys_multiple_certificates_malformed_x509_and_overflow_fail(self):
        for raw in (b'-----BEGIN PRIVATE KEY-----\nAQID\n-----END PRIVATE KEY-----',
                CERTIFICATE + CERTIFICATE, b'-----BEGIN CERTIFICATE-----\nAQID\n-----END CERTIFICATE-----',
                CERTIFICATE + b'x' * tls.MAX_CERTIFICATE):
            (self.app / 'registry/public-ca.pem').write_bytes(raw)
            with self.subTest(bytes=len(raw)), self.assertRaises(DependencyError):
                tls.Trust(self.app, self.policy, self.work)
        self.assertFalse((self.work / 'selected-public-registry-roots.pem').exists())

    def test_ca_paths_and_undeclared_trust_shapes_are_rejected(self):
        for value in ({'caFile': '../secret'}, {'caFile': '/secret'}, {'caFile': 'vendor/lsf/sdk-lock.json'},
                {'caFile': 'package.json'}, {'caFile': 'target/public.pem'}, {'caFile': 5},
                {'caFile': 'registry/public-ca.pem', 'verify': False}):
            policy = copy.deepcopy(self.policy); policy['registries'][0]['tlsTrust'] = value
            with self.subTest(value=value), self.assertRaises(DependencyError): tls.names(policy)

    def test_certificate_or_derived_bundle_mutation_is_detected(self):
        trust = tls.Trust(self.app, self.policy, self.work)
        for path in (self.app / 'registry/public-ca.pem', trust.bundle):
            original = path.read_bytes(); path.write_bytes(original + b'\n')
            with self.subTest(path=path.name), self.assertRaisesRegex(DependencyError, 'trust-input-mutated'):
                trust.check_unchanged()
            path.write_bytes(original)
            trust.check_unchanged()

    def test_tls_config_injection_and_unprepared_roots_fail_before_native_tools(self):
        for url in ('https://example.test/\nstrict-ssl=false', 'https://example.test/\rregistry=http://unsafe', 'https://example.test/ a'):
            policy = {'registries': [{'url': url}]}
            with self.subTest(url=url), self.assertRaisesRegex(DependencyError, 'endpoint-invalid'):
                native.fetch_environment(self.work, policy)
        with self.assertRaisesRegex(DependencyError, 'explicit-trust-preparation-required'):
            native.fetch_environment(self.work, self.policy)

    def test_public_trust_helper_is_shipped_and_bound_by_normal_recipe(self):
        from tools.typescript_guest.build import RECIPE
        self.assertIn('tools/npm_registry_tls.py', RECIPE)


class NpmCapturedTrust(unittest.TestCase):
    copy_application = fixture.NpmDependencyAuthoring.copy_application
    select = fixture.NpmDependencyAuthoring.select
    resolver_command = fixture.NpmDependencyAuthoring.resolver_command

    @classmethod
    def setUpClass(cls):
        fixture.NpmDependencyAuthoring.setUpClass.__func__(cls)

    def setUp(self):
        fixture.NpmDependencyAuthoring.setUp(self)
        (self.app / 'registry').mkdir()
        (self.app / 'registry/public-ca.pem').write_bytes(CERTIFICATE)
        self.policy = self.root / 'private-policy.json'
        self.policy.write_text(json.dumps({'registries': [{'url': 'https://packages.example.test/',
            'tlsTrust': {'caFile': 'registry/public-ca.pem'}}]}), encoding='utf-8')

    def test_exact_public_ca_is_native_lock_and_changed_bytes_deny_offline_status(self):
        candidate = self.root / 'tls-candidate.json'
        with patch.object(native, 'run_bounded', side_effect=self.resolver_command):
            locked = native.resolve(self.owner, candidate, node=self.node, npm=self.npm, registry_config=self.policy)
        self.assertIn('registry/public-ca.pem', [row['path'] for row in locked['nativeLocks']])
        authoring.review(self.owner, candidate, digest(candidate.read_bytes()))
        accepted = (self.owner / 'latent.dependencies.lock.json').read_bytes()
        original = (self.app / 'registry/public-ca.pem').read_bytes()
        (self.app / 'registry/public-ca.pem').write_bytes(original + b'\n')
        with self.assertRaisesRegex(DependencyError, 'native-lock-drift'): authoring.status(self.owner)
        self.assertEqual((self.owner / 'latent.dependencies.lock.json').read_bytes(), accepted)
        (self.app / 'registry/public-ca.pem').write_bytes(original)
        self.assertEqual(authoring.status(self.owner)['status'], 'verified')
        self.assertTrue(all('NODE_EXTRA_CA_CERTS' in row[2] for row in self.calls))
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_native_command_mutating_certificate_cannot_publish_candidate(self):
        candidate = self.root / 'changed-tls-candidate.json'
        def execute(*args):
            result = self.resolver_command(*args)
            if args[0][1:] == ['--version']:
                (self.app / 'registry/public-ca.pem').write_bytes(CERTIFICATE + b'\n')
            return result
        with patch.object(native, 'run_bounded', side_effect=execute):
            with self.assertRaisesRegex(DependencyError, 'trust-input-mutated'):
                native.resolve(self.owner, candidate, node=self.node, npm=self.npm, registry_config=self.policy)
        self.assertFalse(candidate.exists())
        self.assertFalse((self.owner / 'latent.dependencies.lock.json').exists())
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk)
