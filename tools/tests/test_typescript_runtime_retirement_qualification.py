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
        if mode in (0, 5): row['pending'] = {'stores': 1, 'calls': 1, 'readWaits': 1}
        if outcome == 'GuestTrap': row['callbackOriginProven'] = False
        rows.append(row)
    return {'schemaVersion': 'latent.typescript.runtime-retirement.v1', 'status': 'passed', 'cases': rows,
            'fullTicketQualification': False, 'crossTenantQualified': False}


def encoded(value):
    return (f'test {gate.CASE} ... ok\n\nTYPESCRIPT_RETIREMENT '+json.dumps(value)+
            '\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 456 filtered out;\n').encode()


class RetirementQualification(unittest.TestCase):
    def test_exact_native_command_cannot_select_zero_or_all_ignored_cases(self):
        self.assertEqual(gate.test_command(), ['cargo', 'test', '--locked', '-p', 'latent-wasmtime',
            '--test', 'local_service', gate.CASE, '--', '--ignored', '--exact', '--show-output', '--test-threads=1'])

    def test_one_complete_ordered_packet_retains_pending_and_physical_idle_separately(self):
        value = document()
        self.assertEqual(gate.observation(encoded(value)), value)
        self.assertEqual(sum('pending' in row for row in value['cases']), 3)
        self.assertEqual(len(value['cases']), 10)

    def test_missing_duplicate_reordered_outcome_or_failed_native_result_is_not_qualification(self):
        value = document()
        for changed in (value['cases'][:-1], [value['cases'][0], *value['cases'][:-1]], list(reversed(value['cases']))):
            selected = copy.deepcopy(value); selected['cases'] = changed
            with self.subTest(count=len(changed)), self.assertRaises(RuntimeError): gate.observation(encoded(selected))
        for raw in (encoded(value).replace(b'1 passed', b'0 passed'),
                    encoded(value).replace(b'0 ignored', b'1 ignored'),
                    encoded(value)+b'TYPESCRIPT_RETIREMENT {}\n',
                    encoded(value).replace(f'test {gate.CASE} ... ok'.encode(), b'test another ... ok')):
            with self.subTest(output=raw[:50]), self.assertRaises(RuntimeError): gate.observation(raw)

    def test_unretired_boolean_or_unavailable_owner_and_unobserved_pending_are_refused(self):
        for key, amount in (('stores', 1), ('readWaits', False), ('calls', None)):
            value = document(); value['cases'][0]['idle'][key] = amount
            with self.subTest(owner=key), self.assertRaisesRegex(RuntimeError, 'original-owners-idle'):
                gate.observation(encoded(value))
        for index in (2, 4, 6):
            value = document(); value['cases'][index]['pending']['readWaits'] = 0
            with self.subTest(index=index), self.assertRaisesRegex(RuntimeError, 'real-pending-owners'):
                gate.observation(encoded(value))

    def test_result_or_callback_cause_claim_cannot_replace_exact_observed_semantics(self):
        for key, changed in (('decoded', [41]), ('cpuFuel', 0), ('peakMemoryBytes', True)):
            value = document(); value['cases'][0][key] = changed
            with self.subTest(field=key), self.assertRaisesRegex(RuntimeError, 'real-success'):
                gate.observation(encoded(value))
        value = document(); value['cases'][8]['callbackOriginProven'] = True
        with self.assertRaisesRegex(RuntimeError, 'no-callback-cause-inference'): gate.observation(encoded(value))

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
