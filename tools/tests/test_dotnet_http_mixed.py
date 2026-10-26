"""Finite controller refusals and real managed source semantics; guest execution is separate."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import dotnet_http_mixed_fixture as fixture, dotnet_http_mixed_node as node
from tools import dotnet_standard_http_node as base
from tools import dotnet_http_tenant_node as tenants
from tools.dotnet_guest.project import validate
from tools.dotnet_standard_http_project import project as original
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT, read_json, snapshot
from tools.standard_http.peer import Peer


class DotnetHttpMixed(unittest.TestCase):
    def test_tenant_configuration_preserves_limits_and_uses_independent_http_not_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);releases = root/'releases';releases.mkdir()
            (releases/'policy.json').write_text('{}');(root/'node').mkdir()
            peers, credentials = {}, {}
            try:
                for tenant, digit in (('examples', b'3'), ('foreign', b'4')):
                    directory = root/tenant;directory.mkdir()
                    peers[tenant] = {name: Peer(b'Bearer '+digit*64, maximum_seconds=10) for name in ('main', 'helper')}
                    credentials[tenant] = {name: directory/name for name in ('main', 'helper')}
                config = read_json(tenants.configuration(root/'node', releases, peers, credentials))
                providers = config['providers'];first = providers['httpStreaming'];second, = providers['additionalHttpStreaming']
                self.assertEqual(first['configuration']['limits'], second['configuration']['limits'])
                self.assertEqual(first['limits'], second['limits'])
                self.assertEqual(first['identity']['tenant'], 'examples');self.assertEqual(second['identity']['tenant'], 'foreign')
                self.assertNotEqual(first['credentialDirectory'], second['credentialDirectory'])
                self.assertEqual(second['configuration']['destinations'][0]['origin'], peers['foreign']['main'].origin())
                self.assertEqual({row['source'] for row in providers['scalarAliases']},
                    {'clockMonotonic', 'clockWall', 'noncrypto-random', 'activation'})
                self.assertTrue(all(row['consumerService'] == 'dotnet-standard-http' for row in providers['bindings']))
                self.assertEqual(len(providers['bindings']), 10)
                self.assertEqual(config['cells'][0]['capacity'], 1)
                self.assertEqual(config['execution']['maximumWallTimeMillis'], 120000)
                self.assertEqual(providers['activationRuntime']['limits']['queuedWork'], 8)
            finally:
                for group in peers.values():
                    for peer in group.values():peer.close()

    def test_neutral_tenant_scope_refuses_inherited_grants_or_foreign_service(self):
        original = {'metadata': {'name': 'neutral', 'tenant': None},
            'spec': {'service': 'dotnet-standard-http', 'grants': []}}
        for tenant in ('examples', 'foreign'):
            scoped = tenants.scoped(original, tenant)
            self.assertEqual(scoped['metadata']['tenant'], tenant)
            self.assertEqual(scoped['spec'], original['spec'])
            self.assertIsNone(original['metadata']['tenant'])
        for mutation in ('tenant', 'service', 'grants'):
            changed = copy.deepcopy(original)
            if mutation == 'tenant':changed['metadata']['tenant'] = 'examples'
            elif mutation == 'service':changed['spec']['service'] = 'foreign-service'
            else:changed['spec']['grants'] = [{'capability': 'invented'}]
            with self.subTest(mutation=mutation), self.assertRaises(WorkflowError):tenants.scoped(changed, 'foreign')

    def test_actual_retained_node_usage_is_old_red_new_green_and_refuses_hostile_shapes(self):
        raw = (ROOT/'tools/tests/fixtures/dotnet-http-node-usage-actual.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '531dc4097f29c6ad4d5c2739333d3427307a3d7eafa1ebc057ad90fb9ff1abe3')
        # Authenticated actual Rust8f controls/006.json: artifact12315739891,
        # run39532447535/job119001285605. The failed outer is not qualification.
        original = json.loads(raw)
        actual = original['data']['nodeUsage']
        self.assertFalse(actual['unavailable'] is False)  # Old consumer's exact failed predicate.
        client = Mock();client.call.return_value = original
        self.assertEqual(node.usage(client, {'name': 'owned'}), actual)
        self.assertTrue(all(node.natural(actual['counters'][key]) == 0 for key in node.ACTIVE_COUNTERS))
        for mutation in ('false', 'none', 'dict', 'nonempty', 'scope', 'missing', 'negative', 'bool', 'counters'):
            changed = copy.deepcopy(original);value = changed['data']['nodeUsage']
            if mutation in ('false', 'none', 'dict', 'nonempty'):
                value['unavailable'] = {'false': False, 'none': None, 'dict': {}, 'nonempty': ['io_calls']}[mutation]
            elif mutation == 'scope':value['scope'] = 'tenant'
            elif mutation == 'missing':value['counters'].pop(node.ACTIVE_COUNTERS[0])
            elif mutation == 'negative':value['counters'][node.ACTIVE_COUNTERS[0]] = '-1'
            elif mutation == 'bool':value['counters'][node.ACTIVE_COUNTERS[0]] = False
            else:value['counters'] = []
            client.call.return_value = changed
            with self.subTest(mutation=mutation), self.assertRaises(WorkflowError):node.usage(client, {'name': 'owned'})

    def test_manual_only_selector_restores_entire_previous_workflow_without_any_step_changes(self):
        from tools.ci_lane_inventory import workflow_model
        value = workflow_model((ROOT/'.github/workflows/dotnet-published-http.yml').read_text())
        diagnostic = value['on']['workflow_dispatch']['inputs'].pop('periodic_diagnostic')
        self.assertEqual(diagnostic['type'], 'boolean');self.assertIs(diagnostic['default'], False)
        diagnostic_job = value['jobs'].pop('periodic-diagnostic')
        self.assertEqual(diagnostic_job['if'], "github.event_name == 'workflow_dispatch' && inputs.periodic_diagnostic && !inputs.owner_capacity && !inputs.mixed_content && !inputs.fresh_component")
        for old_job in ('owner-capacity', 'mixed-content', 'published-http', 'exact-component'):
            self.assertTrue(value['jobs'][old_job]['if'].endswith(' && !inputs.periodic_diagnostic'))
            value['jobs'][old_job]['if'] = value['jobs'][old_job]['if'].removesuffix(' && !inputs.periodic_diagnostic')
        capacity = value['on']['workflow_dispatch']['inputs'].pop('owner_capacity')
        self.assertEqual(capacity['type'], 'boolean');self.assertIs(capacity['default'], False)
        capacity_job = value['jobs'].pop('owner-capacity')
        self.assertEqual(capacity_job['if'], "github.event_name == 'workflow_dispatch' && inputs.owner_capacity")
        for old_job in ('mixed-content', 'published-http', 'exact-component'):
            self.assertTrue(value['jobs'][old_job]['if'].endswith(' && !inputs.owner_capacity'))
            value['jobs'][old_job]['if'] = value['jobs'][old_job]['if'].removesuffix(' && !inputs.owner_capacity')
        selection = value['on']['workflow_dispatch']['inputs'].pop('mixed_content')
        self.assertEqual(selection['type'], 'boolean');self.assertIs(selection['default'], False)
        job = value['jobs'].pop('mixed-content')
        self.assertEqual(job['if'], "github.event_name == 'workflow_dispatch' && inputs.mixed_content")
        self.assertEqual(value['jobs']['published-http']['if'],
            "github.event_name == 'workflow_dispatch' && inputs.fresh_component && !inputs.mixed_content")
        self.assertEqual(value['jobs']['exact-component']['if'],
            "(github.event_name != 'workflow_dispatch' || !inputs.fresh_component) && !inputs.mixed_content")
        value['jobs']['published-http']['if'] = "github.event_name == 'workflow_dispatch' && inputs.fresh_component"
        value['jobs']['exact-component']['if'] = "github.event_name != 'workflow_dispatch' || !inputs.fresh_component"
        self.assertEqual(hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'be7b04874a1e666ffe5816c7908b9e0af681a03bc3057c585c62f9cfccad8441')

    def test_project_keeps_normal_sdk_authoritative_wit_and_all_original_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, after = original(root/'before'), fixture.project(root/'after')
            old, new = snapshot(before), snapshot(after)
            validate(new)
            self.assertEqual(old['capsule-project.json'], new['capsule-project.json'])
            self.assertEqual(old['wit/world.wit'], new['wit/world.wit'])
            self.assertEqual({name: data for name, data in old.items() if name.startswith('vendor/')},
                {name: data for name, data in new.items() if name.startswith('vendor/')})
            old_lock, new_lock = (json.loads(value['sdk-lock.json']) for value in (old, new))
            old_lock.pop('template');new_lock.pop('template');self.assertEqual(old_lock, new_lock)
            self.assertEqual(new['src/Main.cs'], (ROOT/fixture.SOURCE).read_bytes())
            self.assertEqual(len(fixture.CASES), 20)
            self.assertEqual(sum(node.CONTACTS[:len(fixture.CASES)]), 26)

    def test_every_result_requires_signed_owner_original_budget_and_exact_contact_count(self):
        revision = {'revisionId': 'owned', 'releaseDigest': 'sha256:'+64*'1'}
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 67108864}
        for mode in range(len(node.EXPECTED)):
            terminal = mode in node.TERMINAL
            row = {'processReaped': True, 'exitCode': 4 if terminal else 0,
                'decoded': None if terminal else ['1:'+(node.EXPECTED[mode] if mode != 20 else 'fresh-tenant:tenant-examples:200:0')
                    +(':thread-local:1:1:1:1' if mode in (3, 4) else '')],
                'response': {'outcomeKnown': True, 'category': 'platform-failure' if terminal else 'success',
                    'error': {'code': node.TERMINAL.get(mode)}, 'data': {'resolvedRevision': revision,
                        'consumption': {'cpuFuel': '1', 'peakMemoryBytes': '1',
                            'outboundRequests': node.CONTACTS[mode]}}}}
            node.checked(row, mode, revision, budget, nonce='tenant-examples' if mode == 20 else None)
            for mutation in ('owner', 'unknown', 'unreaped', 'replay', 'cpu', 'memory', 'result'):
                changed = copy.deepcopy(row)
                if mutation == 'owner':changed['response']['data']['resolvedRevision'] = {}
                elif mutation == 'unknown':changed['response']['outcomeKnown'] = False
                elif mutation == 'unreaped':changed['processReaped'] = False
                elif mutation == 'replay':changed['response']['data']['consumption']['outboundRequests'] += 1
                elif mutation == 'cpu':changed['response']['data']['consumption']['cpuFuel'] = '1000000001'
                elif mutation == 'memory':changed['response']['data']['consumption']['peakMemoryBytes'] = '67108865'
                else:changed.update(exitCode=0, decoded=['invented-success'])
                with self.subTest(mode=mode, mutation=mutation), self.assertRaises(WorkflowError):
                    node.checked(changed, mode, revision, budget, nonce='tenant-examples' if mode == 20 else None)
        for value in (True, False, '', '01', '-1', '1.0', '+1', '１', 2**64, str(2**64)):
            with self.subTest(value=value), self.assertRaises(WorkflowError):node.natural(value)

    def test_second_origin_changes_only_explicit_destinations_and_scoped_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);releases = root/'releases';releases.mkdir()
            (releases/'policy.json').write_text('{}')
            original_dir = root/'original';selected_dir = root/'selected'
            original_dir.mkdir();selected_dir.mkdir()
            credential_dir = root/'credentials';credential_dir.mkdir()
            credentials = {name: credential_dir/name for name in ('main', 'helper')}
            peers = {name: Peer(b'Bearer '+digit*64, maximum_seconds=10)
                for name, digit in (('main', b'1'), ('helper', b'2'))}
            try:
                startup = {'origins': peers['main'].observation()['origins'],
                    'destinations': peers['main'].provider_destinations()+peers['helper'].provider_destinations()[:1]}
                first = read_json(base.configuration(original_dir, releases, startup, credentials['main']))
                second = read_json(node.configuration(selected_dir, releases, peers, credentials))
                selected = second['providers']['httpStreaming']['credentials']
                self.assertEqual(selected[-1], {'reference': 'sibling-peer', 'file': 'helper',
                    'destination': 2, 'header': 'authorization'})
                selected.pop()
                self.assertEqual(first, second)
                self.assertEqual(second['providers']['httpStreaming']['configuration']['limits']['maximumRequestBodyBytes'], 4096)
                self.assertEqual(second['providers']['activationRuntime']['limits'], {
                    'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16, 'timers': 8, 'results': 8, 'nativeOwners': 8})
            finally:
                for peer in peers.values():peer.close()

    def test_late_release_requires_exact_completed_marker_after_actual_pending_gate(self):
        marker = b'managed-task-cancelled'
        gate = SimpleNamespace(request=1)
        value = {'events': [{'sequence': 0, 'kind': 'gate-pending', 'request': 1, 'phase': 'body'},
            {'sequence': 1, 'kind': 'response-write-complete', 'request': 2}],
            'requests': [{}, {'request': 2, 'vector': 'method-bytes', 'method': 'POST',
                'bodyBytes': len(marker), 'bodySha256': 'sha256:'+hashlib.sha256(marker).hexdigest(),
                'closeReason': 'response-write-complete'}]}
        self.assertTrue(node.late_marker(value, 0, gate))
        for field in ('bodyBytes', 'bodySha256', 'method', 'closeReason'):
            changed = copy.deepcopy(value);changed['requests'][1][field] = None
            self.assertFalse(node.late_marker(changed, 0, gate))
        changed = copy.deepcopy(value);changed['events'][1]['sequence'] = 0
        self.assertFalse(node.late_marker(changed, 0, gate))

    def test_sibling_release_requires_guest_marker_after_completed_domain_result(self):
        for mode, suffix in ((3, b'headers'), (4, b'content')):
            marker = b'managed-sibling-'+suffix
            value = {'requests': [{'vector': 'domain-json', 'closeReason': 'response-write-complete'},
                {'vector': 'method-bytes', 'method': 'POST', 'bodyBytes': len(marker),
                 'bodySha256': 'sha256:'+hashlib.sha256(marker).hexdigest(), 'closeReason': 'response-write-complete'}]}
            self.assertTrue(node.sibling_marker(value, 0, mode))
            for mutation in ('only-json', 'wrong-mode', 'incomplete-marker', 'wrong-bytes'):
                changed = copy.deepcopy(value)
                if mutation == 'only-json':changed['requests'].pop()
                elif mutation == 'wrong-mode':changed['requests'][1]['bodySha256'] = 'sha256:'+64*'0'
                elif mutation == 'incomplete-marker':changed['requests'][1]['closeReason'] = 'pending'
                else:changed['requests'][1]['bodyBytes'] += 1
                with self.subTest(mode=mode, mutation=mutation):self.assertFalse(node.sibling_marker(changed, 0, mode))

    def test_closing_child_and_finally_require_actual_pending_release_completion_order(self):
        def marker(request, payload):
            return {'request': request, 'vector': 'method-bytes', 'method': 'POST',
                'bodyBytes': len(payload), 'bodySha256': 'sha256:'+hashlib.sha256(payload).hexdigest(),
                'closeReason': 'response-write-complete'}
        gate = SimpleNamespace(request=1)
        value = {'requests': [{}, marker(2, b'managed-closing:accepted-child'),
                marker(3, b'managed-closing:finally')],
            'events': [{'sequence': 0, 'kind': 'gate-pending', 'request': 1},
                {'sequence': 1, 'kind': 'response-write-complete', 'request': 2},
                {'sequence': 2, 'kind': 'gate-released', 'request': 1},
                {'sequence': 3, 'kind': 'response-write-complete', 'request': 1},
                {'sequence': 4, 'kind': 'response-write-complete', 'request': 3}]}
        self.assertTrue(node.closing_marker(value, 0, gate))
        self.assertTrue(node.closing_marker(value, 0, gate, complete=True))
        for mutation in ('pre-pending-child', 'pre-release-finally', 'before-body-finally',
                'missing-release', 'missing-body', 'wrong-child', 'wrong-finally', 'duplicate-child', 'incomplete'):
            changed = copy.deepcopy(value)
            if mutation == 'pre-pending-child':changed['events'][1]['sequence'] = 0
            elif mutation == 'pre-release-finally':changed['events'][4]['sequence'] = 1
            elif mutation == 'before-body-finally':changed['events'][4]['sequence'] = 3
            elif mutation == 'missing-release':changed['events'].pop(2)
            elif mutation == 'missing-body':changed['events'].pop(3)
            elif mutation == 'wrong-child':changed['requests'][1]['bodySha256'] = 'sha256:'+64*'0'
            elif mutation == 'wrong-finally':changed['requests'][2]['bodyBytes'] += 1
            elif mutation == 'duplicate-child':changed['requests'].append(copy.deepcopy(changed['requests'][1]))
            else:changed['requests'][2]['closeReason'] = 'pending'
            with self.subTest(mutation=mutation):
                self.assertFalse(node.closing_marker(changed, 0, gate, complete=True))

    def test_observer_failure_retains_both_public_peers_and_original_exception(self):
        process = Mock();process.owner.exited.return_value = False;process.owner.finished = False
        process.buffers = [bytearray(b'public-out'), bytearray(b'public-error')]
        process.close.side_effect = RuntimeError('secondary-cleanup')
        peer = Mock();peer.origin.return_value = {'host': '127.0.0.1', 'port': 12345}
        peer.observation.return_value = {'failure': None, 'requests': [], 'events': []}
        gate = SimpleNamespace(request=1, phase='body');peer.gates.return_value = [gate]
        original_error = ValueError('original-observer-refusal')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);client = SimpleNamespace(deadline=1e20, evidence=root)
            with patch.object(node, 'selected_revision', return_value={}), \
                    patch.object(node, 'start_call', return_value=process), \
                    patch.object(node, 'sample', side_effect=original_error), \
                    patch.object(node, 'finish_call') as finish:
                with self.assertRaises(ValueError) as raised:
                    node.invoke(client, Mock(), {'budget': {}}, {'main': peer, 'helper': peer}, Mock(), 3, 'owned')
            self.assertIs(raised.exception, original_error);finish.assert_not_called()
            self.assertEqual((root/'owned-partial.stdout').read_bytes(), b'public-out')
            self.assertEqual((root/'owned-partial.stderr').read_bytes(), b'public-error')
            self.assertFalse(read_json(root/'owned-partial-failure.json')['qualification'])
            self.assertEqual(read_json(root/'owned-helper-partial.json'), peer.observation())
            self.assertFalse(read_json(root/'owned-cleanup-refusal.json')['processCleanupConfirmed'])

    def test_exact_fixture_runs_real_incomplete_content_and_cancelled_result_on_clr(self):
        dotnet = shutil.which('dotnet')
        if dotnet is None:self.skipTest('local .NET SDK unavailable; hosted owning reference is mandatory')
        discovered = subprocess.run([dotnet, '--list-sdks'], capture_output=True, text=True, timeout=15, check=True)
        versions = [line.split()[0] for line in discovered.stdout.splitlines() if line.startswith('10.0.')]
        if not versions:self.skipTest('local .NET10 unavailable; hosted owning reference is mandatory')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('Main.cs', 'Reference.cs'):
                (root/name).write_bytes((ROOT/'tools/fixtures/dotnet-http-mixed'/name).read_bytes())
            (root/'global.json').write_text(json.dumps({'sdk': {'version': versions[-1], 'rollForward': 'disable'}}))
            (root/'nuget.config').write_text('<configuration><packageSources><clear/></packageSources></configuration>')
            (root/'Reference.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                '<OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>'
                '<Nullable>enable</Nullable><NuGetAudit>false</NuGetAudit><UseSharedCompilation>false</UseSharedCompilation>'
                '</PropertyGroup></Project>')
            compiled = subprocess.run([dotnet, 'build', root/'Reference.csproj', '--output', root/'bin'], cwd=root,
                capture_output=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout+compiled.stderr)
            result = subprocess.run([dotnet, root/'bin/Reference.dll'], cwd=root, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(result.stdout.strip(),
                b'managed-reference:incomplete-producer:4096:borrowed-output:owned-dispose:late-cancel-preserved')


if __name__ == '__main__':unittest.main()
