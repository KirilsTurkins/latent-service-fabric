"""Reject false runtime/credential evidence; these are not guest execution."""
import copy
import unittest
from unittest.mock import patch

from tools import go_http_adversarial as subject
from tools.phase2_operator_process import WorkflowError


class AdversarialHttpEvidence(unittest.TestCase):
    def test_unchanged_custom_transport_keeps_exact_utf8_domain_payload(self):
        import json
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        original = (root / 'sdk/go-guest/runtime/standard-http-conformance/main.go').read_bytes()
        selected = (root / 'tools/fixtures/go-http-adversarial/main.go').read_bytes()
        def payload(raw):
            marker = b'Body:io.NopCloser(bytes.NewBufferString(`'
            return raw.split(marker, 1)[1].split(b'`)', 1)[0]
        self.assertEqual(payload(selected), payload(original))
        decoded = json.loads(payload(selected))
        self.assertEqual(decoded['name'], 'caf\u00e9')
        self.assertEqual(decoded['items'], ['\u03bb', ''])
        self.assertEqual(re.findall(rb'[\x80-\xff]+', selected), re.findall(rb'[\x80-\xff]+', original))

    def test_secondary_grant_authorizes_only_the_exact_get_target(self):
        primary = {'scheme': 'http', 'host': '127.0.0.1', 'port': 19001}
        secondary = {**primary, 'port': 19002}
        with patch.object(subject, 'policy') as apply:
            grant = subject.authorize_redirect('client', 'publication', primary, secondary)
        self.assertEqual(grant, {'capability': subject.CAPABILITY, 'policy': 'http-redirect-allow'})
        value = apply.call_args.args[3]
        self.assertEqual(value['tenant'], 'examples')
        first, second = value['rules']
        self.assertEqual(first['resources']['origins'], [primary])
        self.assertEqual(second['resources'], {'kind': 'http', 'origins': [secondary],
            'methods': ['GET'], 'paths': ['/conformance/redirect-target'], 'pathPrefixes': []})
        self.assertEqual(second['publications'], ['publication'])
        self.assertEqual(second['services'], ['examples/go-standard-http'])
        self.assertEqual(first['ceiling'], second['ceiling'])
        self.assertEqual(second['ceiling']['operations'], 64)

    def test_referer_selection_does_not_change_original_configuration_or_credentials(self):
        headers = ['accept', 'user-agent', 'x-conformance']
        original = {'providers': {'httpStreaming': {'credentials': [{'destination': 0}],
            'configuration': {'destinations': [{'allowedRequestHeaders': list(headers)} for _ in range(2)],
                              'limits': {'maximumRedirects': 0}}}}}
        before = copy.deepcopy(original)
        selected = subject.configure(original)
        self.assertEqual(original, before)
        self.assertEqual(selected['providers']['httpStreaming']['credentials'], [{'destination': 0}])
        self.assertEqual(selected['providers']['httpStreaming']['configuration']['limits'], {'maximumRedirects': 0})
        for row in selected['providers']['httpStreaming']['configuration']['destinations']:
            self.assertEqual(row['allowedRequestHeaders'], headers + ['referer'])
        for malformed in ([], [{'allowedRequestHeaders': headers}],
                          [{'allowedRequestHeaders': ['authorization']}] * 2):
            changed = copy.deepcopy(original)
            changed['providers']['httpStreaming']['configuration']['destinations'] = malformed
            with self.subTest(malformed=malformed), self.assertRaises(WorkflowError):
                subject.configure(changed)

    def test_uncertainty_wrong_revision_unreaped_or_excess_consumption_cannot_pass(self):
        revision = {'publicationId': 'publication', 'routeGeneration': '19',
                    'revisionId': 'revision', 'releaseDigest': 'digest'}
        budget = {'cpuFuel': 1000, 'memoryBytes': 4096}
        row = {'processReaped': True, 'exitCode': 0, 'decoded': ['200:twice'], 'response': {
            'outcomeKnown': True, 'requestDispatched': True, 'data': {'resolvedRevision': revision,
            'consumption': {'outboundRequests': 2, 'effectCount': 0, 'cpuFuel': '999', 'peakMemoryBytes': '4096'}}}}
        subject.outcome(row, '200:twice', 2, revision, budget)
        mutations = (
            lambda r: r.update(processReaped=False),
            lambda r: r['response'].update(outcomeKnown=False),
            lambda r: r['response'].update(requestDispatched=False),
            lambda r: r['response']['data']['resolvedRevision'].update(routeGeneration='20'),
            lambda r: r['response']['data']['consumption'].update(outboundRequests=3),
            lambda r: r['response']['data']['consumption'].update(effectCount=1),
            lambda r: r['response']['data']['consumption'].update(cpuFuel='1001'),
            lambda r: r['response']['data']['consumption'].update(peakMemoryBytes='4097'),
        )
        for mutate in mutations:
            changed = copy.deepcopy(row)
            mutate(changed)
            with self.subTest(mutation=mutate), self.assertRaises(WorkflowError):
                subject.outcome(changed, '200:twice', 2, revision, budget)
        trap = copy.deepcopy(row)
        trap.update(exitCode=4, decoded=None)
        trap['response']['error'] = {'code': 'guest-trap'}
        trap['response']['data']['terminalState'] = 'guest_trap'
        subject.outcome(trap, None, 2, revision, budget)
        for code, terminal in [('cancelled', 'cancelled'), ('guest-trap', 'fuel_exhausted'), ('deadline-exceeded', 'deadline_exceeded')]:
            changed = copy.deepcopy(trap)
            changed['response']['error']['code'] = code
            changed['response']['data']['terminalState'] = terminal
            with self.subTest(code=code, terminal=terminal), self.assertRaises(WorkflowError):
                subject.outcome(changed, None, 2, revision, budget)

    def test_missing_duplicate_denied_target_or_forwarded_credentials_fail_peer_oracle(self):
        vectors = ['redirect-denied', 'redirect', 'domain-json', 'domain-json',
                   'partial-body', 'partial-body', 'domain-json', 'redirect', 'redirect-target']
        rows = [{'role': 'primary' if index < 8 else 'secondary', 'vector': name,
                 'authorizationPresent': index < 8, 'cookiePresent': False, 'proxyAuthorizationPresent': False,
                 'closeReason': 'response-write-complete'} for index, name in enumerate(vectors)]
        value = {'acceptedConnections': 9, 'startedRequests': 9, 'rejectedRequests': 0,
                 'committedMutations': 0, 'openConnections': 0, 'requests': rows}
        subject.peer_outcome(value)
        mutations = (
            lambda v: v['requests'].pop(),
            lambda v: v['requests'].append(copy.deepcopy(v['requests'][-1])),
            lambda v: v['requests'][-1].update(vector='denied-target'),
            lambda v: v['requests'][-1].update(authorizationPresent=True),
            lambda v: v['requests'][-1].update(cookiePresent=True),
            lambda v: v['requests'][-1].update(proxyAuthorizationPresent=True),
            lambda v: v.update(openConnections=1),
            lambda v: v.update(startedRequests=10),
        )
        for mutate in mutations:
            changed = copy.deepcopy(value)
            mutate(changed)
            with self.subTest(mutation=mutate), self.assertRaises(WorkflowError):
                subject.peer_outcome(changed)
