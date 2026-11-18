"""Bounded attribution controls; synthetic rows do not qualify native execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import qualify_typescript_runtime_retirement as gate
from tools.rust_capsule_project import ROOT


def document():
    rows = []
    for identity, mode, outcome in gate.EXPECTED:
        row = {'case': identity, 'mode': mode, 'outcome': outcome,
               'idle': {name: 0 for name in gate.IDLE}}
        if outcome == 'Succeeded': row.update(decoded=[42], cpuFuel=100, peakMemoryBytes=65536)
        if mode in (0, 5, 6): row['pending'] = {'stores': 1, 'calls': 1, 'readWaits': 1}
        if outcome == 'GuestTrap': row['callbackOriginProven'] = False
        rows.append(row)
    return {'schemaVersion': 'latent.typescript.runtime-retirement.v1', 'status': 'passed', 'cases': rows,
            'fullTicketQualification': False, 'crossTenantQualified': False}


def encoded(value):
    return (f'test {gate.CASE} ... ok\n\nTYPESCRIPT_RETIREMENT '+json.dumps(value)+
            f'\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; {3} filtered out; finished in 0.01s\n').encode()


def witness():
    events = (
        ('root-admitted', 1, 1, 0, 0, ''), ('start-accepted', 2, 2, 0, 1, ''),
        ('next-entered', 3, 2, 1, 1, ''), ('root-close', 4, 2, 0, 1, ''),
        ('root-settled', 5, 1, 0, 1, '|true|true'), ('start-accepted', 6, 1, 0, 1, ''),
        ('next-entered', 7, 1, 1, 1, ''),
    )
    return ''.join(f'{gate.WITNESS_PREFIX}|typescript|{event}|{sequence}|{tasks}|{waits}|{timers}{same}\n'
                   for event, sequence, tasks, waits, timers, same in events).encode()


class RetirementQualification(unittest.TestCase):
    def test_exact_native_command_cannot_select_zero_or_all_ignored_cases(self):
        self.assertEqual(gate.test_command(), ['cargo', 'test', '--locked', '-p', 'latent-wasmtime',
            '--test', 'local_service', gate.CASE, '--', '--ignored', '--exact', '--show-output', '--test-threads=1'])

    def test_one_complete_ordered_packet_retains_pending_and_physical_idle_separately(self):
        value = document()
        observed = gate.observation(encoded(value), 3, witness())
        observed_witness = observed.pop('acceptedAfterRootWitness')
        self.assertEqual(observed, value)
        self.assertTrue(observed_witness['sameOriginalRoot'])
        self.assertTrue(observed_witness['originalTaskCountReduced'])
        self.assertTrue(observed_witness['rootSettledBeforeNestedTimer'])
        self.assertEqual([row['event'] for row in observed_witness['events']], list(gate.WITNESS_EVENTS))
        self.assertEqual(sum('pending' in row for row in value['cases']), 4)
        self.assertEqual(len(value['cases']), 12)

    def test_missing_duplicate_reordered_outcome_or_failed_native_result_is_not_qualification(self):
        value = document()
        for changed in (value['cases'][:-1], [value['cases'][0], *value['cases'][:-1]], list(reversed(value['cases']))):
            selected = copy.deepcopy(value); selected['cases'] = changed
            with self.subTest(count=len(changed)), self.assertRaises(RuntimeError): gate.observation(encoded(selected), 3, witness())
        for raw in (encoded(value).replace(b'1 passed', b'0 passed'),
                    encoded(value).replace(b'0 ignored', b'1 ignored'),
                    encoded(value)+b'TYPESCRIPT_RETIREMENT {}\n',
                    encoded(value).replace(f'test {gate.CASE} ... ok'.encode(), b'test another ... ok'),
                    encoded(value).replace(f'test {gate.CASE} ... ok'.encode(), f'test prefix::{gate.CASE} ... ok'.encode()),
                    encoded(value)+f'test {gate.CASE} ... ok\n'.encode(),
                    encoded(value)+b'test another ... ok\n',
                    encoded(value).replace(b'0 measured', b'1 measured'),
                    encoded(value).replace(f'{3} filtered'.encode(), b'999 filtered'),
                    encoded(value)+b'test result: ok. 0 passed; 0 failed; 0 ignored;\n'):
            with self.subTest(output=raw[:50]), self.assertRaises(RuntimeError): gate.observation(raw, 3, witness())

    def test_unretired_boolean_or_unavailable_owner_and_unobserved_pending_are_refused(self):
        for key, amount in (('stores', 1), ('readWaits', False), ('calls', None)):
            value = document(); value['cases'][0]['idle'][key] = amount
            with self.subTest(owner=key), self.assertRaisesRegex(RuntimeError, 'original-owners-idle'):
                gate.observation(encoded(value), 3, witness())
        for index in (2, 4, 6, 10):
            value = document(); value['cases'][index]['pending']['readWaits'] = 0
            with self.subTest(index=index), self.assertRaisesRegex(RuntimeError, 'real-pending-owners'):
                gate.observation(encoded(value), 3, witness())

    def test_result_or_callback_cause_claim_cannot_replace_exact_observed_semantics(self):
        for key, changed in (('decoded', [41]), ('cpuFuel', 0), ('peakMemoryBytes', True)):
            value = document(); value['cases'][0][key] = changed
            with self.subTest(field=key), self.assertRaisesRegex(RuntimeError, 'real-success'):
                gate.observation(encoded(value), 3, witness())
        value = document(); value['cases'][8]['callbackOriginProven'] = True
        with self.assertRaisesRegex(RuntimeError, 'no-callback-cause-inference'): gate.observation(encoded(value), 3, witness())

    def test_root_close_and_nested_timer_need_exact_order_and_live_owners(self):
        lines = witness().splitlines(keepends=True)
        invalid = (b'', b''.join(lines[:-1]), b''.join([lines[0], lines[1], lines[2], lines[4], lines[3], *lines[5:]]),
                   witness().replace(b'|root-close|4|2|0|1', b'|root-close|4|0|0|1'),
                   witness().replace(b'|next-entered|7|1|1|1', b'|next-entered|7|1|0|1'),
                   witness().replace(b'|root-settled|5|1|0|1|true|true', b'|root-settled|5|1|0|1|false|true'),
                   witness().replace(b'|root-settled|5|1|0|1|true|true', b'|root-settled|5|1|0|1|true|false'),
                   witness()+lines[0], gate.WITNESS_PREFIX.encode()+b'|overflow\n')
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                gate.observation(encoded(document()), 3, raw)

    def test_witness_is_read_from_the_exact_bounded_command_stderr(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); logs = root/'logs'; logs.mkdir()
            path = logs/'03-exact-signed-native-retirement.stderr.txt'
            path.write_bytes(witness())
            self.assertEqual(gate.witness_output(root, 3, 'exact-signed-native-retirement'), witness())
            path.write_bytes(b"x" * (4*1024**2 + 1))
            with self.assertRaises(ValueError): gate.witness_output(root, 3, 'exact-signed-native-retirement')

    def test_build_requires_actual_component_source_observation_and_assembled_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = {'packageAssembled': True}
            for name, field in (('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'),
                                ('build-observation.json', 'observationDigest')):
                raw = (name+'\n').encode(); (root/name).write_bytes(raw)
                marker[field] = 'sha256:'+hashlib.sha256(raw).hexdigest()
            (root/'package-inputs.json').write_bytes(b'{}\n')
            (root/'BUILD-COMPLETE.json').write_bytes(json.dumps(marker).encode())
            self.assertEqual(set(gate.build_proof(root)['files']), {'component.wasm', 'source-inputs.json', 'build-observation.json'})
            (root/'component.wasm').write_bytes(b'different component')
            with self.assertRaisesRegex(RuntimeError, 'actual-build-observation'): gate.build_proof(root)

    def test_four_original_typescript_case_bodies_remain_byte_identical(self):
        raw = (ROOT/'crates/latent-wasmtime/tests/local_service/runtime/typescript.rs').read_bytes()
        original = raw.split(b'fn retirement_request(', 1)[0].rstrip(b'\n')
        self.assertEqual(hashlib.sha256(original).hexdigest(), '0c815dd806277414f68f1a803b05d97b4098ba6b8974b59cd788b2b21fe39a82')


if __name__ == '__main__': unittest.main()
