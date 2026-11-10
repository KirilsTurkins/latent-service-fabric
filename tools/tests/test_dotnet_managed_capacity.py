"""Capacity profile boundaries and failure retention; no simulated guest qualification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import dotnet_managed_capacity_node as node
from tools.phase2_operator_process import WorkflowError


from tools.tests.test_sdk_scratch_qualification import historical_security_actions


def historical_checkout(value):
    """Authenticate the current action before the exact historical pin inverse."""
    value = historical_security_actions(value)
    prefix = 'KirilsTurkins/lsf-checkout@'
    current = prefix + '4d310727149d3abacc52b5dcb0a1c4d18b345d13'
    previous = prefix + 'c3024dfac542bb46ebccc7829ddf1f95e0be8da9'
    if type(value) is bytes:
        prefix, current, previous = (item.encode('ascii') for item in (prefix, current, previous))
    if type(value) not in (str, bytes) or not value.count(current) or value.count(prefix) != value.count(current):
        raise AssertionError('historical-workflow-exact-current-checkout-required')
    return value.replace(current, previous)


class ManagedCapacityTests(unittest.TestCase):
    def test_manual_selector_restores_entire_original_three_job_workflow(self):
        import hashlib
        from tools.ci_lane_inventory import workflow_model
        from tools.rust_capsule_project import ROOT
        value = workflow_model(historical_checkout((ROOT/'.github/workflows/dotnet-published-http.yml').read_text(encoding='utf8')))
        # Temporary diagnostic child: authenticate and invert only its exact
        # branch selector before the existing complete historical comparison.
        branch = "diag/dotnet-ready-reap-20261110"; ref = "refs/heads/" + branch
        self.assertEqual(value['on']['push']['branches'], ['feat/dotnet-published-http-20261020', branch])
        self.assertEqual(value['on']['push']['paths'], ['.github/workflows/dotnet-published-http.yml'])
        value['on']['push']['branches'].remove(branch)
        exact = "(github.event_name != 'workflow_dispatch' || !inputs.fresh_component) && !inputs.mixed_content && !inputs.owner_capacity && !inputs.periodic_diagnostic"
        self.assertEqual(value['jobs']['exact-component']['if'], exact + " && !(github.event_name == 'push' && github.ref == '" + ref + "')")
        value['jobs']['exact-component']['if'] = exact
        owner = "github.event_name == 'workflow_dispatch' && inputs.owner_capacity && !inputs.periodic_diagnostic"
        self.assertEqual(value['jobs']['owner-capacity']['if'], "(" + owner + ") || (github.event_name == 'push' && github.ref == '" + ref + "')")
        value['jobs']['owner-capacity']['if'] = owner
        command = 'python3 -B tools/qualify_dotnet_managed_capacity.py --native "$RUNNER_TEMP/capacity-native" --tools "$RUNNER_TEMP/capacity-tools" --output "$RUNNER_TEMP/managed-capacity"'
        suffix = " ${{ github.event_name == 'push' && github.ref == '" + ref + "' && '--ready-retirement-witness' || '' }}"
        steps = [step for step in value['jobs']['owner-capacity']['steps'] if 'tools/qualify_dotnet_managed_capacity.py' in step.get('run', '')]
        self.assertEqual(len(steps), 1); self.assertEqual(steps[0]['run'], command + suffix)
        steps[0]['run'] = command
        diagnostic = value['on']['workflow_dispatch']['inputs'].pop('periodic_diagnostic')
        self.assertEqual(diagnostic['type'], 'boolean');self.assertIs(diagnostic['default'], False)
        value['jobs'].pop('periodic-diagnostic')
        for original in value['jobs'].values():
            self.assertTrue(original['if'].endswith(' && !inputs.periodic_diagnostic'))
            original['if'] = original['if'].removesuffix(' && !inputs.periodic_diagnostic')
        selector = value['on']['workflow_dispatch']['inputs'].pop('owner_capacity')
        self.assertEqual(selector['type'], 'boolean');self.assertIs(selector['default'], False)
        job = value['jobs'].pop('owner-capacity')
        self.assertEqual(job['if'], "github.event_name == 'workflow_dispatch' && inputs.owner_capacity")
        expected = {'mixed-content': "github.event_name == 'workflow_dispatch' && inputs.mixed_content",
            'published-http': "github.event_name == 'workflow_dispatch' && inputs.fresh_component && !inputs.mixed_content",
            'exact-component': "(github.event_name != 'workflow_dispatch' || !inputs.fresh_component) && !inputs.mixed_content"}
        self.assertEqual(set(value['jobs']), set(expected))
        for name, previous in expected.items():
            self.assertEqual(value['jobs'][name]['if'], previous+' && !inputs.owner_capacity')
            value['jobs'][name]['if'] = previous
        self.assertEqual(hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'f99e0b898d7c2bb8f2b5bc73574fc10ddf8b194b54b42970189dcac61181abf1')
        commands = [step.get('run', '') for step in job['steps']]
        self.assertEqual(sum('tools/qualify_dotnet_managed_capacity.py' in line for line in commands), 1)
        self.assertFalse(any('tools/qualify_dotnet_http_mixed.py' in line for line in commands))
        self.assertEqual(job['timeout-minutes'], 40)

    def test_selected_ceilings_only_narrow_original_queue_and_native_owners(self):
        original = {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
            'timers': 8, 'results': 8, 'nativeOwners': 8}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'node.json'
            source = {'providers': {'activationRuntime': {'limits': original}, 'http': {'unchanged': True}},
                'execution': {'maximumWallTimeMillis': 120000}, 'memory': 134217728}
            for native in (0, 1, 2):
                path.write_text(json.dumps(source), encoding='utf8')
                with patch.object(node.base, 'configuration', return_value=path):
                    selected = node.configuration(path.parent, None,
                        type('Peer', (), {'observation': lambda _: {'origins': []}, 'provider_destinations': lambda _: []})(), None, native)
                actual = json.loads(selected.read_text(encoding='utf8'))
                expected = copy.deepcopy(source)
                expected['providers']['activationRuntime']['limits'] = {**node.LIMITS, 'nativeOwners': native}
                self.assertEqual(actual, expected)
            for bad in (True, -1, 3, '1', None):
                with self.subTest(bad=bad), self.assertRaises((WorkflowError, ValueError)):
                    node.configuration(path.parent, None, None, None, bad)

    def test_timer_birth_and_return_sequences_prove_individual_original_instances(self):
        eight = '1:timers:8:1,2,3,4,5,6,7,8:7,6,5,4,3,2,1,0:refused:reused:fresh'
        seven = '1:timers:7:2,3,4,5,6,7,8:7,6,5,4,3,2,1:refused:reused:fresh'
        self.assertEqual(node.timers(eight)['individualTimers'], 8)
        self.assertEqual(node.timers(seven)['individualTimers'], 7)
        for bad in (eight.replace('1,2,3,4,5,6,7,8', '1,2,3,4,5,6,7,7'),
                    eight.replace('7,6,5,4,3,2,1,0', '7,6,6,4,3,2,1,0'),
                    eight.replace(':8:', ':True:'), eight.replace(':refused:', ':accepted:'),
                    eight.replace(':1,2', ':01,2'), eight+':extra'):
            with self.subTest(bad=bad), self.assertRaises((WorkflowError, ValueError)):
                node.timers(bad)

    def test_rearm_derivation_authenticates_historical_fixture_and_only_adds_the_witness(self):
        from tools import dotnet_managed_capacity_fixture as fixture
        from tools.rust_capsule_project import ROOT, digest, read_file
        original = read_file(ROOT/fixture.SOURCE); snippet = read_file(ROOT/fixture.REARM_SOURCE)
        derived = fixture.rearm_source(original, snippet)
        inserted_case = b'        case 8: return TimerRearmDiagnostic();\n'
        self.assertEqual(derived.count(inserted_case), 1)
        self.assertEqual(derived.count(snippet), 1)
        self.assertEqual(derived.replace(inserted_case, b'', 1).replace(snippet, b'', 1), original)
        for source, extra in ((original+b' ', snippet), (original, snippet+b' ')):
            with self.subTest(mutated=source != original), self.assertRaises(WorkflowError):
                fixture.rearm_source(source, extra)
        def standard(directory):
            directory.mkdir(); (directory/'src').mkdir()
            (directory/'sdk-lock.json').write_text('{"template":{"sourceDigest":"old"}}', encoding='utf8')
            return directory
        with tempfile.TemporaryDirectory() as temporary, patch.object(fixture, 'standard_project', standard):
            root = Path(temporary)
            for selected, expected in ((False, original), (True, derived)):
                app = fixture.project(root/str(selected), rearm_diagnostic=selected)
                self.assertEqual((app/'src/Main.cs').read_bytes(), expected)
                self.assertEqual(json.loads((app/'sdk-lock.json').read_text())['template']['sourceDigest'], digest(expected))
            with self.assertRaises(WorkflowError):fixture.project(root/'invalid', rearm_diagnostic=1)

    def test_optional_rearm_plan_preserves_all_seventeen_original_cases(self):
        original = [
            ('capacity-2-0-0', 0, False), ('capacity-2-0-0-fresh', 7, False),
            ('capacity-2-1-1', 1, False), ('capacity-2-1-1-fresh', 7, False),
            ('capacity-2-2-2', 2, False), ('capacity-2-2-2-fresh', 7, False),
            ('capacity-2-3-3', 3, False), ('capacity-2-3-3-fresh', 7, False),
            ('capacity-2-4-4', 4, False), ('capacity-2-4-4-fresh', 7, False),
            ('capacity-2-5-5', 5, False), ('capacity-2-5-5-fresh', 7, False),
            ('capacity-2-6-6', 6, False), ('capacity-2-6-6-fresh', 7, False)]
        self.assertEqual(node.case_plan(2, False), original)
        self.assertEqual(node.case_plan(2, True), original + [
            ('capacity-2-rearm-8', 8, True), ('capacity-2-rearm-8-fresh', 7, True)])
        self.assertEqual(node.case_plan(0, False), [('capacity-0-0-7', 7, False)])
        self.assertEqual(node.case_plan(1, False), [
            ('capacity-1-0-7', 7, False), ('capacity-1-1-7', 7, False)])
        for native in (0, 1):self.assertEqual(node.case_plan(native, True), node.case_plan(native, False))
        for native, selected in ((True, False), (3, False), (2, 1), (2, 'true')):
            with self.subTest(native=native, selected=selected), self.assertRaises(WorkflowError):
                node.case_plan(native, selected)

    def test_ready_witness_derives_only_from_exact_original_and_is_separately_selected(self):
        from tools import dotnet_managed_capacity_fixture as fixture
        from tools.rust_capsule_project import ROOT, digest, read_file
        original = read_file(ROOT/fixture.SOURCE); snippet = read_file(ROOT/fixture.READY_SOURCE)
        selected = fixture.ready_source(original, snippet)
        case = b'        case 9: return ReadyRetirementWitness();\n'
        self.assertEqual(selected.count(case), 1)
        self.assertEqual(selected.count(snippet), 1)
        self.assertEqual(selected.replace(case, b'', 1).replace(snippet, b'', 1), original)
        for before, witness in ((original+b' ', snippet), (original, snippet+b' ')):
            with self.assertRaises(WorkflowError):fixture.ready_source(before, witness)
        def standard(directory):
            directory.mkdir(); (directory/'src').mkdir()
            (directory/'sdk-lock.json').write_text('{"template":{"sourceDigest":"old"}}', encoding='utf8')
            return directory
        with tempfile.TemporaryDirectory() as temporary, patch.object(fixture, 'standard_project', standard):
            root = Path(temporary)
            for enabled, expected in ((False, original), (True, selected)):
                app = fixture.project(root/str(enabled), ready_witness=enabled)
                self.assertEqual((app/'src/Main.cs').read_bytes(), expected)
                self.assertEqual(json.loads((app/'sdk-lock.json').read_text())['template']['sourceDigest'], digest(expected))
            with self.assertRaises(WorkflowError):fixture.project(root/'both', rearm_diagnostic=True, ready_witness=True)
            with self.assertRaises(WorkflowError):fixture.project(root/'wrong', ready_witness=1)
        for native in (0, 1):
            self.assertEqual(node.case_plan(native, False, True), node.case_plan(native, False))
        self.assertEqual(node.case_plan(2, False, True), node.case_plan(2, False) + [
            ('capacity-2-ready-9', 9, True), ('capacity-2-ready-9-fresh', 7, True)])
        for native, rearm, ready in ((2, True, True), (2, False, 1), (True, False, True)):
            with self.assertRaises(WorkflowError):node.case_plan(native, rearm, ready)

    def test_ready_witness_requires_the_original_wait_transition_and_rejects_a_trap(self):
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 134217728}
        row = self.row(); row['decoded'] = ['1:ready-retirement:0:1:2:2:1:1:0']
        with self.assertRaises(WorkflowError):node.checked(row, 9, {'exact': True}, budget)
        result = node.checked(row, 9, {'exact': True}, budget, ready_witness=True)
        self.assertEqual((result['droppedWaits'], result['reapedWaits'], result['finalWaits']), (2, 1, 0))
        self.assertFalse(result['ordinaryTimerDriverQualified'])
        self.assertFalse(result['postRetirementPhysicalCustodyQualified'])
        for value in ('1:ready-retirement:0:1:2:2:2:2:1',  # prior ready-path behavior
                      '1:ready-retirement:0:1:2:1:1:1:0',  # premature release
                      '1:ready-retirement:0:1:2:2:1:2:0',  # repeated call changed count
                      '1:ready-retirement:0:1:2:2:1:1:1',  # ready owner not retired
                      '1:ready-retirement:0:1:2:2:1:1:0:extra',
                      '1:ready-retirement:00:1:2:2:1:1:0',
                      '1:ready-retirement:15:16:17:17:16:16:15'):
            changed = copy.deepcopy(row); changed['decoded'] = [value]
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                node.checked(changed, 9, {'exact': True}, budget, ready_witness=True)
        trap = copy.deepcopy(row); trap['exitCode'] = 4
        trap['response'].update(category='platform-failure', error={'code': 'guest-trap'})
        with self.assertRaises(WorkflowError):node.checked(trap, 9, {'exact': True}, budget, ready_witness=True)
        with self.assertRaises(WorkflowError):node.checked(row, 8, {'exact': True}, budget, ready_witness=True)

    def test_rearm_observation_is_opt_in_bounded_and_never_qualifies_a_fix(self):
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 134217728}
        row = self.row(); row['decoded'] = ['1:timer-rearm:0:0:1,2,3,3:1,1,1,0:42:0']
        with self.assertRaises(WorkflowError):node.checked(row, 8, {'exact': True}, budget)
        actual = node.checked(row, 8, {'exact': True}, budget, rearm_diagnostic=True)
        self.assertEqual(actual['waitCounts'], [1, 2, 3, 3])
        self.assertEqual(actual['waitDeltaAtLastChange'], 2)
        self.assertIs(actual['diagnosticOnly'], True)
        self.assertIs(actual['timerRearmFixQualified'], False)
        self.assertIs(actual['postRetirementPhysicalCustodyQualified'], False)
        steady = copy.deepcopy(row); steady['decoded'] = ['1:timer-rearm:0:0:1,1,1,0:1,1,1,0:42:0']
        self.assertEqual(node.checked(steady, 8, {'exact': True}, budget,
            rearm_diagnostic=True)['waitDeltaAtLastChange'], 0)
        for bad in ('1:timer-rearm:0:0:1,2,3:1,1,1,0:42:0',
                    '1:timer-rearm:0:0:1,2,17,3:1,1,1,0:42:0',
                    '1:timer-rearm:0:1:1,2,3,3:1,1,1,0:42:0',
                    '1:timer-rearm:0:0:1,2,3,3:1,0,1,0:42:0',
                    '1:timer-rearm:0:0:1,2,3,3:1,1,1,0:42:1',
                    '1:timer-rearm:0:0:01,2,3,3:1,1,1,0:42:0',
                    '1:timer-rearm:0:0:1,2,3,3:1,1,1,0:10000:0'):
            changed = copy.deepcopy(row); changed['decoded'] = [bad]
            with self.subTest(bad=bad), self.assertRaises((WorkflowError, ValueError)):
                node.checked(changed, 8, {'exact': True}, budget, rearm_diagnostic=True)
        trap = copy.deepcopy(row); trap['exitCode'] = 4
        trap['response'].update(category='platform-failure', error={'code': 'guest-trap'})
        with self.assertRaises(WorkflowError):node.checked(trap, 8, {'exact': True}, budget, rearm_diagnostic=True)
        with self.assertRaises(WorkflowError):node.checked(row, 0, {'exact': True}, budget, rearm_diagnostic=True)

    def test_runner_keeps_original_cases_separate_and_propagates_diagnostic_failure(self):
        from contextlib import ExitStack, nullcontext
        from types import SimpleNamespace
        from tools.rust_capsule_project import read_json

        def exercise(selected, fail=False, ready=False):
            calls = []; peers = []
            class Peer:
                def __init__(self, *_args, **_kwargs):self.index = len(peers); peers.append(self)
                def origin(self):return {}
                def close(self):
                    count = 1 if self.index == 0 else 0
                    return {'startedRequests': count, 'acceptedConnections': count, 'openConnections': 0,
                        'rejectedRequests': 0, 'committedMutations': 0}
            class Client:
                def __init__(self, *_args, **_kwargs):pass
                def call(self, *_args, **_kwargs):
                    return {'data': {'operation': {'publication': {'id': 'stub'}}}}
            def invoke(_client, _node, _target, _peer, _probe, mode, label, **kwargs):
                calls.append((label, mode, kwargs))
                if fail and mode in (8, 9):raise ValueError('diagnostic-trap')
                return {'case': label, 'receipt': {'path': 'controls/'+label+'.json'}}
            target = {'name': 'fixture', 'generation': 1}
            replacements = [(node.shared, 'identities', lambda _x: {'component.wasm': {'sha256': 'stub'}}),
                (node, 'file_identity', lambda *_args: {'sha256': 'stub', 'bytes': 1}),
                (node, 'run_bounded_result', lambda *_args, **_kwargs: SimpleNamespace(returncode=0)),
                (node, 'build_environment', lambda *_args: {}), (node, 'owned_cancellation', lambda: nullcontext(None)),
                (node, 'Peer', Peer), (node, 'cleanup_owner', lambda *_args: None),
                (node, 'RecordingClient', Client), (node, 'configuration', lambda *_args: Path('stub')),
                (node, 'connect', lambda *_args: SimpleNamespace(startup_record={'providers': {}})),
                (node, 'Probe', lambda *_args: object()), (node, 'prepare', lambda *_args: {}),
                (node, 'deploy', lambda *_args, **_kwargs: target), (node.base, 'grants', lambda *_args: ({}, [])),
                (node, 'invoke', invoke), (node, 'sample', lambda *_args: {}),
                (node, 'delete_all', lambda *_args: None), (node, 'stop', lambda *_args: None),
                (node, 'stopped_record', lambda *_args: {'reaped': True, 'record': {'clean': True}}),
                (node, 'validate_peer', lambda *_args: None)]
            with tempfile.TemporaryDirectory() as temporary, ExitStack() as patches:
                for owner, name, replacement in replacements:
                    patches.enter_context(patch.object(owner, name, replacement))
                output = Path(temporary)/'campaign'
                native = {key: Path(key) for key in ('capsule_authoring', 'latent', 'latentd')}
                if fail:
                    with self.assertRaisesRegex(ValueError, 'diagnostic-trap'):
                        node.run(Path('artifact'), native, output, deadline=10**20,
                            rearm_diagnostic=selected, ready_witness=ready)
                    stage = 'capacity-2-ready-9' if ready else 'capacity-2-rearm-8'
                    self.assertEqual(read_json(output/'FAILED.json')['stage'], stage)
                    self.assertFalse((output/'qualification.json').exists())
                    self.assertFalse(any(label == stage+'-fresh' for label, _, _ in calls))
                    return
                result = node.run(Path('artifact'), native, output, deadline=10**20,
                    rearm_diagnostic=selected, ready_witness=ready)
                self.assertEqual(result['invocations'], 19 if selected or ready else 17)
                self.assertEqual(len(result['cases']), 17)
                self.assertEqual(sum(mode == 8 for _, mode, _ in calls), int(selected))
                if selected:
                    self.assertEqual(len(result['timerRearmDiagnostic']['cases']), 2)
                    self.assertFalse(result['timerRearmDiagnostic']['timerRearmFixQualified'])
                    selected_call = next(kwargs for _, mode, kwargs in calls if mode == 8)
                    self.assertIs(selected_call['rearm_diagnostic'], True)
                else:self.assertNotIn('timerRearmDiagnostic', result)
                if ready:
                    self.assertEqual(len(result['readyTimerRetirementWitness']['cases']), 2)
                    self.assertFalse(result['readyTimerRetirementWitness']['ordinaryTimerDriverQualified'])
                    self.assertIs(next(kwargs for _, mode, kwargs in calls if mode == 9)['ready_witness'], True)
                else:self.assertNotIn('readyTimerRetirementWitness', result)
        exercise(False); exercise(True); exercise(True, fail=True)
        exercise(False, ready=True); exercise(False, fail=True, ready=True)

    def row(self):
        return {'processReaped': True, 'exitCode': 0, 'decoded': ['1:'+node.EXPECTED[0]],
            'response': {'outcomeKnown': True, 'category': 'success', 'data': {'resolvedRevision': {'exact': True},
                'consumption': {'outboundRequests': '0', 'cpuFuel': '17', 'peakMemoryBytes': '100'}}}}

    def test_results_bind_original_budget_revision_and_managed_oracle(self):
        row = self.row(); budget = {'cpuFuel': 1000000000, 'memoryBytes': 134217728}
        node.checked(row, 0, {'exact': True}, budget)
        for mutate in (lambda r: r.update(processReaped=False),
                       lambda r: r.update(decoded=['1:tasks:accepted']),
                       lambda r: r['response'].update(outcomeKnown=False),
                       lambda r: r['response']['data'].update(resolvedRevision={}),
                       lambda r: r['response']['data']['consumption'].update(outboundRequests='1'),
                       lambda r: r['response']['data']['consumption'].update(cpuFuel=True)):
            changed = copy.deepcopy(row); mutate(changed)
            with self.assertRaises((WorkflowError, ValueError)):
                node.checked(changed, 0, {'exact': True}, budget)

    def test_zero_native_terminal_never_becomes_typed_exception_or_application_success(self):
        row = self.row(); row.update(exitCode=4, decoded=[])
        row['response'].update(category='platform-failure', error={'code': 'guest-trap'})
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 134217728}
        result = node.checked(row, 7, {'exact': True}, budget, installation_refusal=True)
        self.assertFalse(result['originalManagedExceptionTransported'])
        self.assertFalse(result['diagnosticCauseIndependentlyTyped'])
        for code in ('resource-exhausted', 'permission-denied', 'deadline-exceeded'):
            changed = copy.deepcopy(row); changed['response']['error']['code'] = code
            with self.subTest(code=code), self.assertRaises((WorkflowError, ValueError)):
                node.checked(changed, 7, {'exact': True}, budget, installation_refusal=True)
        with self.assertRaises((WorkflowError, ValueError)):
            node.checked(row, 7, {'exact': True}, budget)

    def test_partial_failure_is_retained_and_cleanup_cannot_replace_primary_exception(self):
        original = ValueError('synthetic public primary')
        class Owner:
            def exited(self): raise original
        class Process:
            owner = Owner()
            def close(self): raise RuntimeError('synthetic cleanup')
        class Client:
            deadline = 10**20
            evidence = Path('unused-control-directory')
        peer = type('Peer', (), {'observation': lambda _: {'requests': []}, 'origin': lambda _: {'host': '127.0.0.1', 'port': 1}})()
        with patch.object(node, 'selected_revision', return_value={}), patch.object(node, 'start_call', return_value=Process()), \
                patch.object(node, 'retain_partial') as retained, patch.object(node, 'write_json'):
            with self.assertRaises(ValueError) as caught:
                node.invoke(Client(), None, {}, peer, None, 0, 'control')
        self.assertIs(caught.exception, original)
        retained.assert_called_once()

    def test_periodic_closed_diagnostic_is_never_a_qualified_capacity_outcome(self):
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 134217728}
        row = self.row(); row['decoded'] = ['1:'+node.EXPECTED[3]]
        node.checked(row, 3, {'exact': True}, budget)
        for value in ('periodic:diagnostic:2:fixture-assertion',
                      'periodic:diagnostic:6:admission-refused',
                      'periodic:diagnostic:7:unknown'):
            failed = copy.deepcopy(row); failed['decoded'] = ['1:'+value]
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                node.checked(failed, 3, {'exact': True}, budget)


if __name__ == '__main__':
    unittest.main()
