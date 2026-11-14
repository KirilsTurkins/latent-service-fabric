"""Closed finite protocol outcomes, explicit verification and original owners."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import qualify_go_smtp_tls_runtime as runtime
from tools import go_network_read_barrier as network_runtime
from tools import qualify_go_published_smtp as published

ROOT = Path(__file__).resolve().parents[2]


class GoSmtpTlsRuntimeTests(unittest.TestCase):
    def rows(self, program='standard'):
        result = []
        cases = {'standard': runtime.EXPECTED, 'published': runtime.PUBLISHED_EXPECTED,
                 'published-lost-reply': runtime.LOST_REPLY_EXPECTED}[program]
        for label, mode, outcome, contacts in cases:
            result.append(('GO_SMTP_OWNER', {'case': label, 'stores': 0, 'instances': 0,
                'streamOwners': 0, 'ioOwners': 0, 'kernelRetirementQualified': False}))
            result.append(('GO_SMTP_CASE', {'case': label, 'mode': mode, 'result': outcome, 'contacts': contacts}))
        complete = {'cases': 6, 'contacts': 6, 'cleanLogicalProviderStop': True,
            'normalProviderInstalled': False, 'kernelRetirementQualified': False, 'hostTlsQualified': False}
        if program == 'published-lost-reply':
            complete = {'cases': 2, 'contacts': 2, 'peerMutations': 1, 'postCompletionReplayWindowMillis': 250,
                'cleanLogicalProviderStop': True, 'normalProviderInstalled': False,
                'kernelRetirementQualified': False, 'hostTlsQualified': False}
        result.append(('GO_SMTP_COMPLETE', complete))
        return result

    def output(self, rows=None, program='standard'):
        rows = self.rows(program) if rows is None else rows
        case = {'standard': runtime.CASE, 'published': runtime.PUBLISHED_CASE,
                'published-lost-reply': runtime.LOST_REPLY_CASE}[program]
        return '\n'.join(name + ' ' + json.dumps(row) for name, row in rows).encode() + (
            '\ntest ' + case + ' ... ok\n'
            'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.0s\n').encode()

    def test_exact_smtp_and_guest_tls_paths_do_not_promote_host_tls_or_kernel_accounting(self):
        value = runtime.outcomes(self.output())
        expanded = self.output().replace(b"0 filtered out", b"2 filtered out")
        self.assertEqual(runtime.outcomes(expanded, filtered=2), value)
        with self.assertRaises(ValueError):
            runtime.outcomes(expanded, filtered=1)
        self.assertEqual(len(value['cases']), 6)
        self.assertEqual(value['completion']['contacts'], 6)
        self.assertEqual(len(value['userSpaceOwners']), 6)
        self.assertIs(value['completion']['hostTlsQualified'], False)
        self.assertIs(value['completion']['kernelRetirementQualified'], False)

    def test_v7_limits_bind_the_new_receipt_and_fail_closed(self):
        marker = b'GO_V7_NETWORK_LIMITS ' + json.dumps(network_runtime.V7_LIMITS).encode() + b'\n'
        self.assertIsNone(runtime.profile_witness(self.output(), runtime.MANAGED_PROFILE))
        self.assertEqual(runtime.profile_witness(self.output() + marker, runtime.STACK_PROFILE), network_runtime.V7_LIMITS)
        self.assertEqual(runtime.outcomes(self.output() + marker), runtime.outcomes(self.output()))
        for raw, profile in ((self.output(), runtime.STACK_PROFILE),
                             (self.output() + marker + marker, runtime.STACK_PROFILE),
                             (self.output() + marker, runtime.MANAGED_PROFILE),
                             (self.output() + marker, 'go-component-activation-v6'),
                             (self.output() + marker.replace(b'"queuedWork": 16', b'"queuedWork": 2'), runtime.STACK_PROFILE),
                             (self.output() + marker.replace(b'"tasks": 16', b'"tasks": true'), runtime.STACK_PROFILE)):
            with self.subTest(profile=profile, tail=raw[-150:]), self.assertRaises(ValueError):
                runtime.profile_witness(raw, profile)

    def test_workflow_selection_keeps_v5_and_requires_an_explicit_v7_route(self):
        self.assertEqual(runtime.workflow_profile('push', runtime.V5_PUSH_BRANCH, ''), runtime.MANAGED_PROFILE)
        self.assertEqual(runtime.workflow_profile('push', runtime.V7_PUSH_BRANCH, ''), runtime.STACK_PROFILE)
        self.assertEqual(runtime.workflow_profile('push', runtime.PUBLISHED_PUSH_BRANCH, ''), runtime.STACK_PROFILE)
        self.assertEqual(runtime.workflow_profile('push', runtime.REFERENCE_PIN_PUSH_BRANCH, ''), runtime.STACK_PROFILE)
        self.assertEqual(runtime.workflow_program('push', runtime.PUBLISHED_PUSH_BRANCH, ''), 'published')
        self.assertEqual(runtime.workflow_program('push', runtime.REFERENCE_PIN_PUSH_BRANCH, ''), 'published')
        self.assertEqual(runtime.workflow_profile('push', runtime.LOST_REPLY_PUSH_BRANCH, ''), runtime.STACK_PROFILE)
        self.assertEqual(runtime.workflow_program('push', runtime.LOST_REPLY_PUSH_BRANCH, ''), 'published-lost-reply')
        self.assertEqual(runtime.workflow_program('push', runtime.V7_PUSH_BRANCH, ''), 'standard')
        self.assertEqual(runtime.workflow_program('workflow_dispatch', 'development', ''), 'standard')
        self.assertEqual(runtime.workflow_program('workflow_dispatch', 'development', 'published'), 'published')
        self.assertEqual(runtime.workflow_program('workflow_dispatch', 'development', 'published-lost-reply'),
                         'published-lost-reply')
        for program in ('published', 'published-lost-reply'):
            with self.assertRaisesRegex(ValueError, 'program-not-selected'):
                runtime.qualify(ROOT, ROOT / 'must-not-exist', 'revision', Path('go'), runtime.MANAGED_PROFILE, program)
        for event, branch, choice in (('push', runtime.PUBLISHED_PUSH_BRANCH, 'standard'),
                                      ('push', 'development', ''),
                                      ('workflow_dispatch', 'development', 'unknown')):
            with self.assertRaisesRegex(ValueError, 'workflow-program'):
                runtime.workflow_program(event, branch, choice)
        for choice in ('', 'v5'):
            self.assertEqual(runtime.workflow_profile('workflow_dispatch', 'development', choice), runtime.MANAGED_PROFILE)
        self.assertEqual(runtime.workflow_profile('workflow_dispatch', 'development', 'v7'), runtime.STACK_PROFILE)
        for event, branch, choice in (('push', 'development', ''), ('push', runtime.V5_PUSH_BRANCH, 'v7'),
                ('workflow_dispatch', 'development', 'v6'), ('workflow_dispatch', 'development', 'V7'),
                ('pull_request', runtime.V7_PUSH_BRANCH, ''), ('', '', '')):
            with self.subTest(event=event, branch=branch, choice=choice):
                with self.assertRaisesRegex(ValueError, 'workflow-selection'):
                    runtime.workflow_profile(event, branch, choice)
        workflow = (ROOT / '.github/workflows/go-smtp-tls-runtime.yml').read_text()
        for branch in (runtime.V5_PUSH_BRANCH, runtime.V7_PUSH_BRANCH, runtime.PUBLISHED_PUSH_BRANCH, runtime.REFERENCE_PIN_PUSH_BRANCH):
            self.assertIn("'" + branch + "'", workflow)
        self.assertIn("github.ref_name == '" + runtime.REFERENCE_PIN_PUSH_BRANCH + "'", workflow)
        for expected in ('default: v5', 'options: [v5, v7]',
                         'LSF_GO_SMTP_TLS_DISPATCH_PROFILE: ${{ inputs.profile }}', '--workflow-selection'):
            self.assertIn(expected, workflow)

    def test_published_contracts_product_requires_exact_successful_cargo_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / 'crates/latent-packaging/Cargo.toml'
            source = manifest.parent / 'examples/capsule_contracts.rs'
            executable = root / 'target/debug/examples/capsule_contracts'
            for item in (manifest, source, executable):
                item.parent.mkdir(parents=True, exist_ok=True)
                item.write_bytes(b'x')
            artifact = {'reason': 'compiler-artifact', 'manifest_path': str(manifest),
                        'target': {'kind': ['example'], 'name': 'capsule_contracts', 'src_path': str(source)},
                        'profile': {'test': False}, 'executable': str(executable)}
            finish = {'reason': 'build-finished', 'success': True}
            encode = lambda rows: b'\n'.join(json.dumps(row).encode() for row in rows) + b'\n'
            self.assertEqual(runtime.contracts_artifact(encode([artifact, finish]), root), executable)
            for rows in ([finish], [artifact], [artifact, artifact, finish],
                         [dict(artifact, profile={'test': True}), finish],
                         [dict(artifact, executable=str(manifest)), finish],
                         [artifact, {'reason': 'build-finished', 'success': False}],
                         [artifact, finish, artifact]):
                with self.subTest(rows=rows), self.assertRaises(ValueError):
                    runtime.contracts_artifact(encode(rows), root)

    def test_published_transcript_has_separate_case_and_closed_observations(self):
        raw = self.output(program='published')
        record = runtime.outcomes(raw, program='published')
        self.assertEqual([row['case'] for row in record['cases']],
                         [row[0] for row in runtime.PUBLISHED_EXPECTED])
        self.assertEqual(len(record['userSpaceOwners']), 6)
        with self.assertRaises(ValueError):
            runtime.outcomes(raw)
        with self.assertRaises(ValueError):
            runtime.outcomes(self.output(), program='published')
        with self.assertRaises(ValueError):
            runtime.outcomes(raw + b'GO_SMTP_UNKNOWN {}\n', program='published')
        with self.assertRaises(ValueError):
            runtime.outcomes(raw, program='unknown')

    def test_lost_reply_requires_one_peer_mutation_no_extra_contact_and_fresh_invocation(self):
        program = 'published-lost-reply'
        raw = self.output(program=program)
        result = runtime.outcomes(raw, program=program)
        self.assertEqual(result['completion']['peerMutations'], 1)
        self.assertEqual(result['completion']['postCompletionReplayWindowMillis'], 250)
        self.assertEqual([row['case'] for row in result['cases']], [row[0] for row in runtime.LOST_REPLY_EXPECTED])
        for key, value in (('peerMutations', 0), ('peerMutations', 2), ('contacts', 3),
                           ('postCompletionReplayWindowMillis', 0), ('kernelRetirementQualified', True)):
            rows = self.rows(program)
            rows[-1][1][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                runtime.outcomes(self.output(rows, program), program=program)
        with self.assertRaises(ValueError):
            runtime.outcomes(self.output(self.rows(program)[:-3] + self.rows(program)[-1:], program), program=program)
        with self.assertRaises(ValueError):
            runtime.outcomes(raw, program='published')
        with self.assertRaises(ValueError):
            runtime.outcomes(self.output(program='published'), program=program)

    def test_published_graph_binds_original_client_and_separate_worker_edges(self):
        versions = {name: value[0] for name, value in published.LIBRARIES.items()}
        versions[published.SASL] = published.SASL_VERSION
        ids = {name: 'fixture-' + str(index) for index, name in enumerate(versions)}
        names = {'github.com/emersion/go-smtp': 'client.go', published.SASL: 'sasl.go',
                 'github.com/reactivex/rxgo/v2': 'observable_operator.go',
                 'github.com/cenkalti/backoff/v4': 'timer.go'}
        declaration = {'Module': {'Path': 'wit_component'},
                       'Require': [{'Path': name, 'Version': version}
                                   for name, version in versions.items() if name != published.SASL]}
        nodes = [{'id': 'root', 'path': 'wit_component', 'main': True}]
        nodes += [{'id': ids[name], 'path': name, 'version': version, 'main': False,
                   'indirect': name == published.SASL, 'replacement': None}
                  for name, version in versions.items()]
        edges = [{'owner': 'wit_component', 'selected': ids[name]}
                 for name in versions if name != published.SASL]
        edges += [{'owner': 'github.com/emersion/go-smtp@v0.25.0',
                   'dependency': published.SASL + '@' + published.SASL_VERSION,
                   'selected': ids[published.SASL]},
                  {'owner': 'github.com/reactivex/rxgo/v2@v2.5.0',
                   'dependency': 'github.com/cenkalti/backoff/v4@v4.0.0',
                   'selected': ids['github.com/cenkalti/backoff/v4']}]
        native = {'module': 'wit_component', 'nodes': nodes, 'edges': edges}
        assets = [{'id': ids[name], 'role': 'application',
                   'metadata': {'module': name, 'version': version, 'assetType': 'selected-module-source',
                                'effectiveModule': name, 'effectiveVersion': version},
                   'files': [{'path': names[name], 'digest': 'sha256:' + '0' * 64, 'size': 1}]}
                  for name, version in versions.items()]
        result = published.graph_evidence(declaration, native, assets)
        self.assertEqual(len(result['transitiveEdges']), 2)
        self.assertEqual(result['smtpRetryPolicy'], 'none')
        lost = published.graph_evidence(declaration, native, assets, lost_reply=True)
        self.assertEqual(lost['workerTimer'], 'not exercised by the separate lost-reply fixture')
        self.assertEqual([row['ordinaryApi'] for row in lost['applicationLibraries']][1:],
                         ['captured but not exercised by the lost-reply fixture'] * 2)
        with self.assertRaises(ValueError):
            published.graph_evidence(declaration, native, assets, lost_reply=1)
        for mutation in ('edge', 'replacement', 'source'):
            changed_native = json.loads(json.dumps(native))
            changed_assets = json.loads(json.dumps(assets))
            if mutation == 'edge':
                changed_native['edges'].pop()
            elif mutation == 'replacement':
                changed_native['nodes'][-1]['replacement'] = {'path': 'other'}
            else:
                changed_assets[0]['files'] = []
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                published.graph_evidence(declaration, changed_native, changed_assets)

    def test_published_client_uses_original_factories_and_separate_pre_network_timer(self):
        root = ROOT / 'sdk/go-guest/runtime/published-smtp-conformance'
        source = (root / 'main.go').read_text()
        for expected in ('smtp.Dial(config.Address)', 'smtp.DialStartTLS(config.Address',
                         'client.Noop()', 'client.Quit()', 'rxgo.Defer(', 'source.BackOffRetry(policy)',
                         'backoff.NewConstantBackOff(5*time.Millisecond)', 'attempts.Load() == 2'):
            self.assertIn(expected, source)
        self.assertLess(source.index('if !workerTimerStage()'), source.index('smtp.Dial(config.Address)'))
        for forbidden in ('smtp.NewClient(', 'net.Conn', 'net.Pipe', 'InsecureSkipVerify', 'lsf/'):
            self.assertNotIn(forbidden, source)
        module = (root / 'go.mod').read_text()
        for expected in ('github.com/emersion/go-smtp v0.25.0',
                         'github.com/reactivex/rxgo/v2 v2.5.0',
                         'github.com/cenkalti/backoff/v4 v4.0.0',
                         'github.com/emersion/go-sasl v0.0.0-20241020182733-b788ff22d5a6'):
            self.assertIn(expected, module)

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

    def test_hidden_or_reordered_reserved_events_and_extra_test_cannot_pass(self):
        rows = self.rows()
        rows[1], rows[2] = rows[2], rows[1]  # Each per-kind sequence stays unchanged.
        for raw in (self.output(rows),
                    self.output() + b'GO_SMTP_UNKNOWN {}\n',
                    self.output() + b'GO_SMTP_CASE\t{}\n',
                    self.output() + b' GO_SMTP_OWNER {}\n',
                    self.output() + b'test unexpected ... FAILED\n',
                    self.output() + b'GO_SMTP_OWNER ' + b'x' * 4097 + b'\n'):
            with self.subTest(tail=raw[-100:]), self.assertRaises(ValueError):
                runtime.outcomes(raw)

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
        for bound in ('tasks: 16', 'executors: 2', 'PROFILE => 2', 'V7_PROFILE => 16', 'queued_work,', 'waits: 4',
                      'timers: 2', 'results: 2', 'native_owners: 2', 'GO_V7_NETWORK_LIMITS'):
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


    def test_tls_cache_overlay_authenticates_exact_upstream_and_keeps_generic_cleanup_refused(self):
        import hashlib
        from tools.go_guest import network, activation
        source = (ROOT / 'tools/tests/fixtures/go_network/crypto/tls/cache.go').read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), network.PREIMAGES['crypto/tls/cache.go'])
        self.assertEqual(source.count(b'runtime.AddCleanup('), 2)
        guard = (ROOT / 'tools/go_guest/activation.py').read_text()
        self.assertIn('LSF Go cleanup callbacks are not qualified', guard)
        self.assertNotIn('crypto/tls/cache.go', activation.PREIMAGES)
        compiler = (ROOT / 'tools/go_guest/compiler.py').read_text()
        selection = compiler.index('            if network_context:\n                from tools.go_guest.network import prepare')
        self.assertLess(selection, compiler.index('replacements.update(prepare_network'))
        # Other certificate, handshake, authentication and hostname source is
        # never selected by this private-cache-only derivation.
        self.assertEqual([p for p in network.PREIMAGES if p.startswith('crypto/')], ['crypto/tls/cache.go'])

    def test_cache_admission_precedes_allocating_parse_and_key_copy_with_no_cleanup_or_eviction(self):
        source = (ROOT / runtime.CACHE_TEMPLATE).read_text()
        admission = source.index('if len(der) > lsfCertCacheMaximumDER')
        self.assertLess(admission, source.index('x509.ParseCertificate(der)'))
        self.assertLess(admission, source.index('der: string(der)'))
        for bound in ('lsfCertCacheMaximumEntries = 8', 'lsfCertCacheMaximumDER = 16 * 1024',
                      'lsfCertCacheMaximumTotalDER = 64 * 1024'):
            self.assertIn(bound, source)
        self.assertIn('entries [lsfCertCacheMaximumEntries]lsfCertCacheEntry', source)
        self.assertIn('len(der) > lsfCertCacheMaximumTotalDER-wcc.derSize', source)
        self.assertLess(source.index('wcc.mu.Lock()'), source.index('x509.ParseCertificate(der)'))
        self.assertIn('defer wcc.mu.Unlock()', source)
        self.assertIn('return nil, err', source)
        self.assertIn('wcc.used++', source)
        self.assertIn('wcc.derSize += len(der)', source)
        for absent in ('runtime.AddCleanup(', 'weak.Make(', 'go func', 'append(', 'delete(', 'wcc.used--', 'wcc.derSize -='):
            self.assertNotIn(absent, source)

    def test_reference_go_pin_is_archive_derived_and_rejects_changed_bytes(self):
        from tools import qualify_go_captured_checkpoints as captured
        from tools.tests import go_checkpoint_goto_reference as goto
        self.assertEqual(runtime.REFERENCE_GO_SHA, goto.GO_SHA256)
        self.assertEqual(captured.GO_IDENTITY['digest'], 'sha256:' + runtime.REFERENCE_GO_SHA)
        fixture = b'one fixed compiler preimage'
        with mock.patch.object(runtime, 'REFERENCE_GO_SHA', hashlib.sha256(fixture).hexdigest()):
            runtime.require_reference_go(fixture)
            for altered in (fixture + b'!', fixture[:-1], b'', 'not bytes'):
                with self.subTest(altered=altered), self.assertRaisesRegex(ValueError, 'compiler-preimage'):
                    runtime.require_reference_go(altered)

    def test_reference_projects_only_package_declaration_and_requires_all_eight_actual_passes(self):
        source = (ROOT / runtime.CACHE_TEMPLATE).read_bytes()
        projected = runtime.cache_reference_source(source)
        self.assertEqual(projected.replace(b'\npackage tlscache\n', b'\npackage tls\n'), source)
        for bad in (source.replace(b'\n', b'\r\n'), source + b'\npackage tls\n', b'x' * 16385):
            with self.assertRaises(ValueError): runtime.cache_reference_source(bad)
        rows = [{'Package': 'example.invalid/tlscache', 'Action': 'pass', 'Test': case} for case in runtime.CACHE_CASES]
        rows.append({'Package': 'example.invalid/tlscache', 'Action': 'pass'})
        encode = lambda values: b'\n'.join(json.dumps(row).encode() for row in values)
        self.assertEqual(runtime.cache_reference_outcomes(encode(rows)), list(runtime.CACHE_CASES))
        for values in (rows[:-2] + rows[-1:], rows + rows[:1], [dict(rows[0], Action='skip')] + rows[1:],
                       [dict(rows[0], Package='private')] + rows[1:], [dict(rows[0], Action='fail')] + rows[1:]):
            with self.assertRaises(ValueError): runtime.cache_reference_outcomes(encode(values))
        with self.assertRaises(ValueError): runtime.cache_reference_outcomes(b'{"Package":"example.invalid/tlscache","Action":"pass","Action":"skip"}')

    def test_reference_covers_actual_cache_identity_admission_gc_parse_concurrency_and_fresh_state(self):
        source = (ROOT / runtime.CACHE_TESTS).read_text()
        for case in runtime.CACHE_CASES:
            self.assertEqual(source.count('func ' + case + '('), 1)
        for expression in ('testing.AllocsPerRun(100', 'runtime.GC()', 'x509.ParseCertificate(der)',
                           'cache.used != 8', 'cache.derSize != 65536', 'exactCertificate(t, 2, 16385)',
                           'fresh.used != 0', 'for range 16', 'value != first'):
            self.assertIn(expression, source)
        controller = (ROOT / 'tools/qualify_go_smtp_tls_runtime.py').read_text()
        self.assertIn('CACHE_TESTS}', controller)
        self.assertLess(controller.index('record[\'cacheReference\']'), controller.index('compiler.compile('))
        self.assertIn("GOPROXY='off'", controller)
        self.assertEqual(controller.count('compiler.compile('), 1)
        self.assertIn("'--test', 'go_smtp_tls'", controller)
        self.assertNotIn("'--workspace'", controller)


if __name__ == '__main__':
    unittest.main()
