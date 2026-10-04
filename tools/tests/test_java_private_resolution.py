"""Private repository input/credential boundaries before actual resolver execution."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.application_dependency_store import DependencyError
from tools.build_snapshot import digest
from tools import java_registry_tls as tls
from tools.java_dependency_resolution import declarations


class JavaPrivateResolution(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)
        self.project, self.work, self.jdk = (self.root / name for name in ('project', 'work', 'jdk'))
        for directory in (self.project, self.work, self.jdk / 'bin', self.jdk / 'lib/security'):
            directory.mkdir(parents=True)
        self.java = self.jdk / 'bin/java'
        self.keytool = self.jdk / 'bin/keytool'
        self.store = self.jdk / 'lib/security/cacerts'
        self.java.write_bytes(b'reviewed-jdk-java')
        self.keytool.write_bytes(b'reviewed-jdk-keytool')
        self.store.write_bytes(b'immutable-public-system-store')
        self.config = {'formatVersion': 1, 'dependencies': [], 'localJars': [], 'selection': {},
            'repositories': [{'id': 'private-feed', 'url': 'https://packages.example.test/maven',
                              'tlsTrust': {'caFile': 'registry/public-ca.pem'}}]}
        self.ca = self.project / 'registry/public-ca.pem'
        self.ca.parent.mkdir()
        self.ca.write_bytes(b'-----BEGIN CERTIFICATE-----\nAQID\n-----END CERTIFICATE-----\n')

    def execute_import(self, argv, work, environment, timeout, maximum):
        self.assertEqual(Path(argv[0]), self.keytool)
        self.assertEqual(work, self.work)
        self.assertEqual(maximum, 16384)
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, tls.TRUST_PREPARATION_SECONDS)
        self.assertFalse(any(name.startswith('LSF_REGISTRY_') for name in environment))
        certificate = Path(argv[argv.index('-file') + 1])
        target = Path(argv[argv.index('-keystore') + 1])
        self.assertTrue(certificate.is_relative_to(self.work))
        self.assertTrue(target.is_relative_to(self.work))
        target.write_bytes(target.read_bytes() + certificate.read_bytes())
        return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')

    def test_public_repository_has_no_new_tls_execution_or_inputs(self):
        self.config['repositories'][0].pop('tlsTrust')
        with patch.object(tls, 'run_bounded_result') as execute:
            self.assertEqual(tls.prepare(self.project, declarations(self.config), self.work, self.java, {}),
                             ((), {}, {}, None))
        execute.assert_not_called()
        self.assertEqual(list(self.work.iterdir()), [])

    def test_only_declared_complete_credentials_enter_resolver_environment(self):
        environment = {'PATH': 'closed-path'}
        with patch.dict(os.environ, {'LSF_REGISTRY_PRIVATE_FEED_USERNAME': 'private-user',
            'LSF_REGISTRY_PRIVATE_FEED_PASSWORD': 'private-password', 'LSF_REGISTRY_UNDECLARED_PASSWORD': 'outside-secret'}, clear=True):
            tls.credentials(self.config, environment)
        self.assertEqual(environment, {'PATH': 'closed-path', 'LSF_REGISTRY_PRIVATE_FEED_USERNAME': 'private-user',
                                     'LSF_REGISTRY_PRIVATE_FEED_PASSWORD': 'private-password'})

    def test_partial_empty_oversized_and_control_credentials_fail_without_export(self):
        pairs = [('user', None), (None, 'password'), ('', 'password'), ('user', ''),
                 ('u' * 1025, 'password'), ('user', 'p' * 16385), ('user\n', 'password'), ('user', 'password\r')]
        for username, password in pairs:
            with self.subTest(usernameBytes=len(username or ''), passwordBytes=len(password or '')):
                selected = {key: value for key, value in [('LSF_REGISTRY_PRIVATE_FEED_USERNAME', username),
                    ('LSF_REGISTRY_PRIVATE_FEED_PASSWORD', password)] if value is not None}
                target = {'PATH': 'closed-path'}
                with patch.dict(os.environ, selected, clear=True), self.assertRaisesRegex(DependencyError, 'credential-pair-invalid'):
                    tls.credentials(self.config, target)
                self.assertEqual(target, {'PATH': 'closed-path'})

    def test_project_owned_public_certificate_derives_private_store_and_bound_material(self):
        before = {path: path.read_bytes() for path in (self.ca, self.java, self.keytool, self.store)}
        environment = {'JAVA_HOME': str(self.jdk), 'LSF_REGISTRY_PRIVATE_FEED_PASSWORD': 'private-password'}
        with patch.object(tls, 'run_bounded_result', side_effect=self.execute_import) as execute:
            arguments, certificates, inputs, identity = tls.prepare(self.project, declarations(self.config), self.work,
                                                                   self.java, environment)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(certificates, {'registry/public-ca.pem': before[self.ca]})
        self.assertIn('-Djavax.net.ssl.trustStore=' + str(self.work / 'private-registry-cacerts'), arguments)
        self.assertEqual(inputs[str(self.store)], digest(before[self.store]))
        self.assertEqual(inputs[str(self.keytool)], digest(before[self.keytool]))
        self.assertEqual(identity['certificates'], [{'path': 'registry/public-ca.pem', 'digest': digest(before[self.ca]),
                                                    'size': len(before[self.ca])}])
        self.assertEqual(identity['derivedTrustStoreDigest'], digest((self.work / 'private-registry-cacerts').read_bytes()))
        self.assertNotIn('private-password', repr((arguments, certificates, inputs, identity)))
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_private_key_unknown_trust_fields_and_escaping_paths_fail_before_keytool(self):
        for name in ('../outside.pem', '/absolute.pem', 'target/transient.pem', 'application-dependencies.json', 'registry/link\\ca.pem'):
            value = copy.deepcopy(self.config)
            value['repositories'][0]['tlsTrust']['caFile'] = name
            with self.subTest(path=name), self.assertRaises(DependencyError):
                declarations(value)
        value = copy.deepcopy(self.config)
        value['repositories'][0]['tlsTrust']['password'] = 'not-an-input'
        with self.assertRaisesRegex(DependencyError, 'trust-declaration-invalid'):
            declarations(value)
        for raw in (b'-----BEGIN PRIVATE KEY-----\nnot-public\n-----END PRIVATE KEY-----',
                    self.ca.read_bytes() * 2, b'empty'):
            self.ca.write_bytes(raw)
            with patch.object(tls, 'run_bounded_result') as execute, self.assertRaisesRegex(DependencyError, 'public-certificate-required'):
                tls.prepare(self.project, self.config, self.work, self.java, {})
            execute.assert_not_called()

    def test_duplicate_certificate_paths_share_one_import_and_retain_count_bound(self):
        value = copy.deepcopy(self.config)
        value['repositories'].append({'id': 'second', 'url': 'https://other.example.test',
                                     'tlsTrust': {'caFile': 'registry/public-ca.pem'}})
        self.assertEqual(tls.certificates(declarations(value)), ('registry/public-ca.pem',))
        value['repositories'] = [{'id': 'r' + str(i), 'url': 'https://example.test/' + str(i),
            'tlsTrust': {'caFile': f'registry/{i}.pem'}} for i in range(63)]
        with self.assertRaisesRegex(DependencyError, 'certificate-count-limit'):
            declarations(value)

    def test_keytool_failure_remains_static_and_original_trust_is_unchanged(self):
        original = self.store.read_bytes()
        with patch.object(tls, 'run_bounded_result', return_value=SimpleNamespace(returncode=1,
            stdout=b'private-password', stderr=b'private-password')):
            with self.assertRaisesRegex(DependencyError, '^java-registry-trust-preparation-failed-private-diagnostics-discarded$') as caught:
                tls.prepare(self.project, self.config, self.work, self.java, {})
        self.assertNotIn('private-password', str(caught.exception))
        self.assertEqual(self.store.read_bytes(), original)

    def test_certificate_mutation_and_mismatched_jdk_fail_without_ambient_change(self):
        def mutated(*args):
            result = self.execute_import(*args)
            Path(args[0][args[0].index('-file') + 1]).write_bytes(b'changed')
            return result
        with patch.object(tls, 'run_bounded_result', side_effect=mutated), self.assertRaisesRegex(DependencyError, 'certificate-mutated'):
            tls.prepare(self.project, self.config, self.work, self.java, {})
        other = self.root / 'other/bin'; other.mkdir(parents=True); (other / 'java').write_bytes(b'different-jdk')
        with patch.object(tls, 'run_bounded_result') as execute, self.assertRaisesRegex(DependencyError, 'jdk-home-mismatch'):
            tls.prepare(self.project, self.config, self.root / 'unused', self.java, {'JAVA_HOME': str(other.parent)})
        execute.assert_not_called()


if __name__ == '__main__': unittest.main()
