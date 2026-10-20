"""Closed finite protocol outcomes, explicit verification and original owners."""
import json
from pathlib import Path
import unittest

from tools import qualify_go_smtp_tls_runtime as runtime

ROOT = Path(__file__).resolve().parents[2]


class GoSmtpTlsRuntimeTests(unittest.TestCase):
    def rows(self):
        result = []
        for label, mode, outcome, contacts in runtime.EXPECTED:
            result.append(('GO_SMTP_OWNER', {'case': label, 'stores': 0, 'instances': 0,
                'streamOwners': 0, 'ioOwners': 0, 'kernelRetirementQualified': False}))
            result.append(('GO_SMTP_CASE', {'case': label, 'mode': mode, 'result': outcome, 'contacts': contacts}))
        result.append(('GO_SMTP_COMPLETE', {'cases': 6, 'contacts': 6, 'cleanLogicalProviderStop': True,
            'normalProviderInstalled': False, 'kernelRetirementQualified': False, 'hostTlsQualified': False}))
        return result

    def output(self, rows=None):
        rows = self.rows() if rows is None else rows
        return '\n'.join(name + ' ' + json.dumps(row) for name, row in rows).encode() + (
            '\ntest ' + runtime.CASE + ' ... ok\n'
            'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.0s\n').encode()

    def test_exact_smtp_and_guest_tls_paths_do_not_promote_host_tls_or_kernel_accounting(self):
        value = runtime.outcomes(self.output())
        self.assertEqual(len(value['cases']), 6)
        self.assertEqual(value['completion']['contacts'], 6)
        self.assertEqual(len(value['userSpaceOwners']), 6)
        self.assertIs(value['completion']['hostTlsQualified'], False)
        self.assertIs(value['completion']['kernelRetirementQualified'], False)

    def test_missing_reordered_duplicate_or_incorrect_verification_results_fail(self):
        variants = []
        rows = self.rows(); rows.pop(1); variants.append(rows)
        rows = self.rows(); rows[1], rows[3] = rows[3], rows[1]; variants.append(rows)
        rows = self.rows(); rows.insert(0, rows[0]); variants.append(rows)
        rows = self.rows(); rows[5][1]['result'] = 'ordinary-smtp-tls13'; variants.append(rows)
        rows = self.rows(); rows[7][1]['contacts'] = 0; variants.append(rows)
        for rows in variants:
            with self.assertRaises(ValueError):
                runtime.outcomes(self.output(rows))

    def test_unknown_private_duplicate_and_numeric_aliases_are_not_evidence(self):
        for key, value in (('private', 'fixture-secret'), ('mode', False), ('contacts', 1.0)):
            rows = self.rows(); rows[1][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                runtime.outcomes(self.output(rows))
        raw = self.output().replace(b'"contacts": 1}', b'"contacts": 0, "contacts": 1}', 1)
        with self.assertRaisesRegex(ValueError, 'duplicate-observation-field'):
            runtime.outcomes(raw)

    def test_retained_resources_ignored_execution_and_any_host_promotion_fail(self):
        for index, key, value in ((0, 'streamOwners', 1), (0, 'stores', False),
                (-1, 'hostTlsQualified', True), (-1, 'normalProviderInstalled', True),
                (-1, 'kernelRetirementQualified', True), (-1, 'cleanLogicalProviderStop', False)):
            rows = self.rows(); rows[index][1][key] = value
            with self.assertRaises(ValueError):
                runtime.outcomes(self.output(rows))
        with self.assertRaises(ValueError):
            runtime.outcomes(self.output().replace(b'0 ignored', b'1 ignored'))

    def test_ordinary_public_smtp_owns_its_connection_and_uses_explicit_verified_trust(self):
        source = (ROOT / 'sdk/go-guest/runtime/smtp-tls-conformance/main.go').read_text()
        for expression in ('smtp.Dial(config.Address)', 'client.StartTLS(&tls.Config{',
                'x509.NewCertPool()', 'roots.AppendCertsFromPEM', 'RootCAs: roots, ServerName: name',
                'MinVersion: version, MaxVersion: version', 'tls.VersionTLS12', 'tls.VersionTLS13',
                'x509.HostnameError', 'x509.UnknownAuthorityError', 'state.VerifiedChains',
                'client.Noop()', 'client.Quit()', 'defer client.Close()'):
            self.assertIn(expression, source)
        for forbidden in ('InsecureSkipVerify', 'smtp.NewClient(', 'net.Conn', 'net.Pipe',
                          'VerifyPeerCertificate', 'err.Error()', 'lsf/'):
            self.assertNotIn(forbidden, source)

    def test_bounded_owned_peer_checks_protocol_and_guest_uses_original_runtime_limits(self):
        peer = (ROOT / 'crates/latent-wasmtime/tests/go_smtp_tls.rs').read_text()
        for expression in ('let mut line = [0; 128]', '"STARTTLS\\r\\n"', 'acceptor.accept(',
                '"EHLO localhost\\r\\n"', 'secure.is_err()', 'stores_created, 6'):
            self.assertIn(expression, peer)
        setup = (ROOT / 'crates/latent-wasmtime/tests/go_smtp_tls/setup.rs').read_text()
        for bound in ('tasks: 16', 'executors: 2', 'queued_work: 2', 'waits: 4',
                      'timers: 2', 'results: 2', 'native_owners: 2'):
            self.assertIn(bound, setup)
        self.assertIn('tls: None', setup)  # Only TCP provider; TLS is inside Go.
        controller = (ROOT / 'tools/qualify_go_smtp_tls_runtime.py').read_text()
        self.assertEqual(controller.count('compiler.compile('), 1)
        self.assertIn("'--test', 'go_smtp_tls'", controller)
        self.assertNotIn("'--workspace'", controller)


    def test_compiled_fixture_environment_and_retained_observation_match_the_actual_consumer(self):
        controller = (ROOT / 'tools/qualify_go_smtp_tls_runtime.py').read_text()
        setup = (ROOT / 'crates/latent-wasmtime/tests/go_smtp_tls/setup.rs').read_text()
        workflow = (ROOT / '.github/workflows/go-smtp-tls-runtime.yml').read_text()
        self.assertIn("environment['LSF_GO_SMTP_TLS_FIXTURE'] = str(prepared)", controller)
        self.assertIn('std::env::var_os("LSF_GO_SMTP_TLS_FIXTURE")', setup)
        for source in (controller, setup, workflow):
            self.assertIn('GO-SMTP-TLS-COMPILE.json', source)
            self.assertNotIn('GO-NETWORK-COMPILE.json', source)


if __name__ == '__main__':
    unittest.main()
