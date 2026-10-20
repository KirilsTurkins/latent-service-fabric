import copy
import hashlib
import json
from pathlib import Path
import unittest

from tools.java_guest.surface import matches


class ExactJavaPhaseSurface(unittest.TestCase):
    def observed(self):
        value = json.loads((Path(__file__).parent/'fixtures/java_phase_surface_0bdb.json').read_bytes())
        return value['expected'], value['actual']

    def test_actual_pair_requires_selected_profile_and_preserves_both_inputs(self):
        expected, actual = self.observed(); original = copy.deepcopy((expected, actual))
        self.assertFalse(matches(expected, actual))
        self.assertTrue(matches(expected, actual, phase_profile=True))
        self.assertTrue(matches(expected, expected))
        self.assertEqual((expected, actual), original)
        for invalid in (False, None, 1, 'true'):
            with self.subTest(selected=invalid):
                self.assertFalse(matches(expected, actual, phase_profile=invalid))

    def test_source_response_resource_and_phase_mutations_never_gain_an_exception(self):
        expected, actual = self.observed()
        legacy = 'latent:http/streaming@0.3.0'; phase = 'latent:http/phase-timing@0.4.0'
        for selected in ('response', 'body', 'phase-operation', 'callable-legacy', 'missing-phase'):
            changed = copy.deepcopy(expected)
            changed_actual = copy.deepcopy(actual)
            if selected == 'response':
                changed['imports'][legacy]['types']['response']['record'][0]['type'] = 'u32'
            elif selected == 'body':
                changed['imports'][legacy]['types']['body']['resource'] = legacy+'/foreign-body'
                changed_actual['imports'][legacy]['types']['body']['resource'] = legacy+'/foreign-body'
            elif selected == 'phase-operation':
                function = next(iter(changed['imports'][phase]['functions'].values()))
                function['result'] = 'u8'
                next(iter(changed_actual['imports'][phase]['functions'].values()))['result'] = 'u8'
            elif selected == 'callable-legacy':
                changed['imports'][legacy]['functions']['read'] = {'kind': 'freestanding', 'params': [], 'result': None}
                changed_actual['imports'][legacy]['functions'] = copy.deepcopy(changed['imports'][legacy]['functions'])
            else:
                del changed['imports'][phase]
                del changed_actual['imports'][phase]
            with self.subTest(selected=selected):
                self.assertFalse(matches(changed, changed_actual, phase_profile=True))

    def test_compiled_body_owner_operations_exports_and_extra_omissions_remain_strict(self):
        expected, actual = self.observed()
        legacy = 'latent:http/streaming@0.3.0'; phase = 'latent:http/phase-timing@0.4.0'
        for selected in ('body-owner', 'missing-body', 'phase-operation', 'export', 'extra-type', 'response'):
            changed = copy.deepcopy(actual)
            if selected == 'body-owner':
                changed['imports'][legacy]['types']['body']['resource'] = legacy+'/foreign-body'
            elif selected == 'missing-body':
                del changed['imports'][legacy]['types']['body']
            elif selected == 'phase-operation':
                next(iter(changed['imports'][phase]['functions'].values()))['result'] = 'u8'
            elif selected == 'export':
                interface = next(iter(changed['exports'].values()))
                next(iter(interface['functions'].values()))['result'] = 'u8'
            elif selected == 'extra-type':
                changed['imports'][legacy]['types']['unreviewed'] = 'u32'
            else:
                changed['imports'][legacy]['types']['response'] = {'record': []}
            with self.subTest(selected=selected):
                self.assertFalse(matches(expected, changed, phase_profile=True))

    def test_both_full_source_interface_hashes_and_default_compiler_gate_remain_bound(self):
        expected, actual = self.observed()
        for name, pinned in (
            ('latent:http/streaming@0.3.0', '644e5f46ecaf961a9d242665cdf3d1a45cf898946f9a10405201b6fe080abbc7'),
            ('latent:http/phase-timing@0.4.0', 'aafabc979dcda4dd99280880f1266de8be366fa5fd6dd275fbe5017d7fd29aef')):
            raw = json.dumps(expected['imports'][name], sort_keys=True, separators=(',', ':')).encode()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), pinned)
        source = (Path(__file__).parents[1]/'java_guest/compiler.py').read_text()
        self.assertIn('matching_wit_surface(expected, actual, phase_profile=http_client_phase_profile)', source)
        self.assertIn('raise ValueError("compiled Java component changed authoritative WIT semantics")', source)
        legacy = copy.deepcopy(expected); del legacy['imports']['latent:http/phase-timing@0.4.0']
        self.assertTrue(matches(legacy, legacy))
        changed = copy.deepcopy(legacy); del changed['imports']['latent:http/streaming@0.3.0']['types']['response']
        self.assertFalse(matches(legacy, changed, phase_profile=True))


if __name__ == '__main__':
    unittest.main()
