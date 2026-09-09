"""Replay a real debug protocol fixture; never promote it to release evidence."""
import copy
import gzip
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.optimization_backend_revision.budget.parse import parse
from tools.optimization_backend_revision.evidence import Artifacts
from tools.optimization_evidence.common import canonical, sha256


class Fixture:
    def __init__(self, root, variant='candidate'):
        self.root = root
        self.variant = variant
        source = Path(__file__).parent / 'fixtures/budget_lifecycle'
        self.raw = json.loads(gzip.decompress((source / f'{variant}.json.gz').read_bytes()))
        for name in ('capsule', 'contracts', 'deployment'):
            shutil.copyfile(source / f'generic-{name}.json', root / f'generic-{name}.json')
        self.identity = copy.deepcopy(self.raw['identity'])
        self.selected = copy.deepcopy(self.raw['plan'])
        value = self.raw['fixture']
        self.component = {'path': 'generic/generic-capsule.wasm', 'sha256': value['component_sha256'], 'bytes': value['component_bytes']}

    def replay(self):
        (self.root / 'budget.json').write_bytes(canonical(self.raw))
        refs = []
        for path in sorted(self.root.glob('*.json')):
            data = path.read_bytes()
            refs.append({'path': path.name, 'sha256': sha256(data), 'bytes': str(len(data))})
        artifacts = Artifacts(self.root, refs, set())
        artifacts.path(next(row for row in refs if row['path'] == 'budget.json'))
        return parse(self.raw, self.selected, self.identity, artifacts, self.root / 'budget.json', self.component, self.variant)

    def offers(self):
        return [row for row in self.raw['samples'] if row['kind'] == 'invoke']


class ActualLifecycleFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(Path(self.temporary.name))

    def test_actual_functional_graph_and_identity_scope(self):
        value = self.fixture.replay()
        self.assertEqual(self.fixture.identity['qualification'], 'functional-debug-only')
        self.assertEqual((value['samples'], value['commands'], value['diagnostic_event_count']), ('23', '57', '202'))
        self.assertEqual(value['process_cpu']['status'], 'available')
        self.assertEqual(value['waits']['final']['live'], '0')
        self.assertEqual(value['shutdown']['quarantinedCells'], 0)

    def test_actual_control_missing_preledger_decision_remains_unobserved(self):
        fixture = Fixture(self.fixture.root, 'control')
        value = fixture.replay()
        self.assertEqual((value['samples'], value['commands']), ('23', '57'))
        unobserved = [row for row in value['deadline_observations'] if row['case'] != 'delayed-body'
                      and not row['terminal_decision_observed']]
        self.assertEqual([row['ordinal'] for row in unobserved], ['5', '6', '13', '17'])
        self.assertTrue(all(row['native_terminal_decision_overshoot_nanos'] is None for row in unobserved))

    def test_rehashed_missing_or_duplicate_offer_fails(self):
        offers = self.fixture.offers()
        offers[-1]['ordinal'] = offers[-2]['ordinal']
        with self.assertRaisesRegex(ValueError, 'missing-duplicate-or-reordered'):
            self.fixture.replay()

    def test_rehashed_queue_witness_cannot_claim_other_holders(self):
        self.fixture.offers()[7]['queue_witness']['holder_ids'][0] = self.fixture.offers()[0]['activation_id']
        with self.assertRaisesRegex(ValueError, 'queue-witness-crossed'):
            self.fixture.replay()

    def test_rehashed_body_expired_before_dispatch_is_not_ingress_delay(self):
        offer = self.fixture.offers()[9]
        offer['body_gate']['released_nanos'] = offer['dispatch_nanos']
        with self.assertRaisesRegex(ValueError, 'body-gate-clock'):
            self.fixture.replay()

    def test_rehashed_command_cannot_move_after_its_case_cleanup(self):
        row = next(row for row in self.fixture.raw['samples'] if row['kind'] == 'command' and row['operation'] == 'cancel')
        row['started_nanos'] = row['finished_nanos'] = self.fixture.raw['diagnostic']['collector_finished_nanos']
        with self.assertRaisesRegex(ValueError, 'control-order-or-clock|outside-case-window|cancel-after-terminal'):
            self.fixture.replay()

    def test_rehashed_changed_transport_cannot_hide_native_limit(self):
        self.fixture.offers()[15]['transport_budget_millis'] = '5'
        with self.assertRaisesRegex(ValueError, 'transport-boundary'):
            self.fixture.replay()

    def test_rehashed_candidate_terminal_expiry_must_be_actual_ledger(self):
        event = next(row['observation'] for row in self.fixture.raw['diagnostic']['records']
                     if row['token'] == '0' and row['observation']['kind'] == 'terminal-decision')
        event['expires_at_nanos'] = str(int(event['expires_at_nanos']) + 1)
        with self.assertRaisesRegex(ValueError, 'terminal-deadline-crossed'):
            self.fixture.replay()

    def test_rehashed_reserved_grant_and_live_timer_are_rejected(self):
        event = next(row['observation'] for row in self.fixture.raw['diagnostic']['records'] if row['observation']['kind'] == 'admitted-ledger')
        event['budget']['reserved_dimensions_zero'] = False
        with self.assertRaisesRegex(ValueError, 'diagnostic-grant'):
            self.fixture.replay()
        event['budget']['reserved_dimensions_zero'] = True
        self.fixture.raw['final_waits']['live'] = '1'
        with self.assertRaisesRegex(ValueError, 'wait-ownership|live-wait'):
            self.fixture.replay()

    def test_rehashed_foreign_cpu_and_missing_compiler_join_cannot_pass(self):
        self.fixture.raw['process_cpu']['after']['pid'] = '1'
        with self.assertRaisesRegex(ValueError, 'process-cpu-crossed|foreign-process-cpu'):
            self.fixture.replay()
        self.fixture.raw['process_cpu']['after']['pid'] = self.fixture.raw['process_cpu']['before']['pid']
        self.fixture.raw['shutdown'].pop('compiler')
        with self.assertRaisesRegex(ValueError, 'compiler-shutdown-unobserved'):
            self.fixture.replay()

    def test_rehashed_persisted_memory_grant_mismatch_fails(self):
        path = self.fixture.root / 'generic-deployment.json'
        value = json.loads(path.read_bytes())
        value['spec']['resources']['memoryBytes'] = 16_777_216
        data = canonical(value)
        path.write_bytes(data)
        self.fixture.raw['fixture']['deployment'].update(sha256=sha256(data), bytes=str(len(data)))
        with self.assertRaisesRegex(ValueError, 'persisted-grant'):
            self.fixture.replay()

    def test_rehashed_success_cannot_omit_its_actual_deadline_lineage(self):
        for row in self.fixture.raw['diagnostic']['records']:
            event = row['observation']
            if row['token'] == '0' and event['kind'] in ('admission-check', 'admitted-ledger', 'execution-deadline'):
                row['observation'] = {'kind': 'lifecycle-phase', 'phase': 'received', 'observed_at_nanos': event['observed_at_nanos']}
        with self.assertRaisesRegex(ValueError, 'required-deadline-lineage'):
            self.fixture.replay()

    def test_rehashed_feasibility_floor_cannot_be_unavailable(self):
        event = next(row['observation'] for row in self.fixture.raw['diagnostic']['records']
                     if row['token'] == '0' and row['observation']['kind'] == 'admission-check')
        event['required_nanos'] = None
        with self.assertRaisesRegex(ValueError, 'required-feasibility-policy'):
            self.fixture.replay()

    def test_rehashed_terminal_failure_cannot_be_completed(self):
        offer = self.fixture.offers()[15]
        offer['retained_status'].update(phase='running', terminal_state='completed')
        command = next(row for row in self.fixture.raw['samples'] if row['kind'] == 'command'
                       and row['operation'] == 'status' and row['target'] == offer['activation_id'])
        command['response'] = copy.deepcopy(offer['retained_status'])
        event = next(row['observation'] for row in self.fixture.raw['diagnostic']['records']
                     if row['token'] == offer['diagnostic_token'] and row['observation']['kind'] == 'terminal-winner')
        event['terminal_state'] = 'completed'
        with self.assertRaisesRegex(ValueError, 'terminal-code-state'):
            self.fixture.replay()

    def test_rehashed_ingress_must_preserve_recorded_header_allowance(self):
        event = next(row['observation'] for row in self.fixture.raw['diagnostic']['records']
                     if row['token'] == '7' and row['observation']['kind'] == 'ingress')
        event['expires_at_nanos'] = str(int(event['expires_at_nanos']) + 10_000_000)
        event['deadline_unix_millis'] = str(int(event['deadline_unix_millis']) + 10)
        with self.assertRaisesRegex(ValueError, 'ingress-not-original-timeout'):
            self.fixture.replay()

    def test_rehashed_node_snapshots_cannot_be_outside_measured_run(self):
        samples = [self.fixture.raw['initial_node'], self.fixture.raw['before_shutdown']]
        samples += [row['node'] for row in self.fixture.raw['samples'] if row['kind'] == 'checkpoint']
        for row in samples:
            for name in ('started_micros', 'finished_micros'):
                row[name] = str(int(row[name]) + 200_000_000)
        with self.assertRaisesRegex(ValueError, 'outside-case-window|outside-run|checkpoint-clock-regressed'):
            self.fixture.replay()

    def test_rehashed_accepted_cancel_cannot_start_after_response(self):
        offer = self.fixture.offers()[21]
        commands = [row for row in self.fixture.raw['samples'] if row['kind'] == 'command' and row['target'] == offer['activation_id']]
        cancel = next(row for row in commands if row['operation'] == 'cancel')
        status = next(row for row in commands if row['operation'] == 'status')
        cancel['started_nanos'] = cancel['finished_nanos'] = status['started_nanos']
        with self.assertRaisesRegex(ValueError, 'cancel-after-terminal'):
            self.fixture.replay()


if __name__ == '__main__':
    unittest.main()
