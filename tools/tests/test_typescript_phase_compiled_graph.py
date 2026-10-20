"""Actual parser graphs retain every phase/resource identity after type pruning."""
import copy
import json
from pathlib import Path
import unittest

from tools.typescript_guest import runtime_profile as runtime

ROOT = Path(__file__).resolve().parents[2]
WORLD = 'examples:lsf-typescript-activation/selected@1.0.0'


class PhaseCompiledGraphTests(unittest.TestCase):
    def observed(self):
        value = json.loads((ROOT/'tools/tests/fixtures/typescript_runtime_profile/phase-component-f139.json').read_bytes())
        self.assertEqual(value['source'], 'f139baeb76f93b1b44cec16f5e10a041cf0b69b9')
        self.assertEqual(value['parser'], 'wasm-tools1.254.0')
        self.assertEqual(value['engineInput']['coreDigest'],
                         'sha256:9bf6966e64b260d5789c936cd3aaaa26f05b35a61f6c073a5262fead4547ae5c')
        return value

    def matches(self, value, **overrides):
        options = {'profile': runtime.IMPORT_PROFILE, 'engine_input': value['engineInput'],
                   'source_splicer_digest': value['sourceSplicerInputDigest']}
        options.update(overrides)
        return runtime.compiled_world_matches(value['selected'], value['component'], WORLD, **options)

    def test_actual_normal_emission_omits_only_unused_response_and_existing_readiness(self):
        value = self.observed(); original = copy.deepcopy(value)
        expected = runtime.public_graph(value['selected'], WORLD)
        actual = runtime.public_component_graph(value['component'])
        self.assertNotEqual(expected, actual)
        owner = 'latent:http/streaming@0.3.0'
        self.assertEqual(set(expected['imports'][owner]['types']) - set(actual['imports'][owner]['types']), {'response'})
        self.assertEqual(expected['imports'][owner]['functions'], {})
        self.assertEqual(actual['imports'][owner]['functions'], {})
        self.assertTrue(self.matches(value))
        self.assertEqual(value, original)

    def test_omission_requires_original_import_engine_and_splicer_envelope(self):
        value = self.observed()
        for options in ({'profile': runtime.CLOCK_PROFILE}, {'profile': runtime.ASYNC_PROFILE},
                        {'engine_input': None}, {'source_splicer_digest': None},
                        {'source_splicer_digest': runtime.digest(b'foreign')}):
            with self.subTest(options=options):self.assertFalse(self.matches(value, **options))
        changed = dict(value['engineInput'], qualification='passed')
        self.assertFalse(self.matches(value, engine_input=changed))

    def test_every_remaining_nominal_type_and_phase_operation_is_mandatory(self):
        value = self.observed()
        for name in next(i for i in value['component']['interfaces'] if i['name']=='streaming')['types']:
            changed = copy.deepcopy(value)
            del next(i for i in changed['component']['interfaces'] if i['name']=='streaming')['types'][name]
            with self.subTest(type=name):self.assertFalse(self.matches(changed))
        for name in next(i for i in value['component']['interfaces'] if i['name']=='phase-timing')['functions']:
            changed = copy.deepcopy(value)
            del next(i for i in changed['component']['interfaces'] if i['name']=='phase-timing')['functions'][name]
            with self.subTest(function=name):self.assertFalse(self.matches(changed))
        changed = copy.deepcopy(value)
        interface = next(i for i in changed['component']['interfaces'] if i['name']=='streaming')
        changed['component']['types'][interface['types']['request']]['kind']['record']['fields'][0]['type']='u32'
        self.assertFalse(self.matches(changed))

    def test_changed_unused_source_type_and_additional_legacy_operations_still_refuse(self):
        value = self.observed()
        changed = copy.deepcopy(value)
        interface = next(i for i in changed['selected']['interfaces'] if i['name']=='streaming')
        changed['selected']['types'][interface['types']['response']]['kind']['record']['fields'][0]['type']='u32'
        self.assertFalse(self.matches(changed))
        for side in ('selected', 'component'):
            changed = copy.deepcopy(value)
            interface = next(i for i in changed[side]['interfaces'] if i['name']=='streaming')
            phase = next(i for i in changed[side]['interfaces'] if i['name']=='phase-timing')
            interface['functions']['hidden'] = copy.deepcopy(phase['functions']['open'])
            with self.subTest(side=side):self.assertFalse(self.matches(changed))


if __name__ == '__main__':unittest.main()
