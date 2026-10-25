"""Pure reader/filesystem controls; no signed/runtime/compiler credit."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import compatibility_closure_matrix as matrix
from tools import guest_compatibility_outcomes as outcomes
from tools.dev_workflow.common import digest
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import write_json


class CompatibilityClosureMatrix(unittest.TestCase):
    def test_exact_case_results_and_order_cannot_be_replaced_by_a_matching_unknown_trap(self):
        component = digest(b'component'); expected = [{'ok': 'api|c|unsupported'}]
        budget = dict(cpuFuel=100, memoryBytes=100, logBytes=0)
        usage = {key: 0 for key in matrix.node.ZERO_EFFECTS}
        usage.update(cpuFuel=1, peakMemoryBytes=1, logBytes=0)
        response = {'category': 'success', 'outcomeKnown': True,
            'data': {'resolvedRevision': {'releaseDigest': component}, 'consumption': usage}}
        rows = []
        for label in ('probe', 'fresh-after-probe'):
            raw = {'processReaped': True, 'exitCode': 0, 'response': copy.deepcopy(response), 'decoded': expected}
            rows.append({'mode': 'probe', 'label': label, 'invocation': raw,
                'originalDiagnostic': outcomes.original(raw['response']), 'operationObservation': None})
        value = {'status': 'passed', 'component': {'sha256': component}, 'targetBudget': budget,
            'nodeShutdown': {'reaped': True, 'record': {'clean': True}},
            'programme': {'status': 'passed', 'kind': 'api-pair', 'cases': rows}}
        matrix.signed(value, component, 2, expected=expected)
        for mutate in ('return', 'trap', 'order', 'kind'):
            changed = copy.deepcopy(value)
            if mutate == 'return': changed['programme']['cases'][0]['invocation']['decoded'] = [{'ok': 'wrong'}]
            elif mutate == 'order': changed['programme']['cases'].reverse()
            elif mutate == 'kind': changed['programme']['kind'] = 'typescript-resources'
            else:
                raw = changed['programme']['cases'][0]['invocation']
                raw.update(exitCode=4, decoded=None)
                raw['response'].update(category='platform-failure', error={'code': 'guest-trap', 'details': []})
                changed['programme']['cases'][0]['originalDiagnostic'] = outcomes.original(raw['response'])
            with self.subTest(mutation=mutate), self.assertRaisesRegex(ValueError, 'compatibility-matrix-exact-original'):
                matrix.signed(changed, component, 2, expected=expected)

    def test_missing_mandatory_cells_and_historical_scope_are_not_runtime_credit(self):
        for cells in ({}, {cell: {} for cell in matrix.CELLS[:-1]}):
            with self.assertRaisesRegex(ValueError, 'missing-or-extra-required-cells'):
                matrix.assemble(cells, source_commit='a' * 40)
        rows = matrix.historical()
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(row['currentNativeExecutionClaimed'] is False for row in rows))

    def test_public_projection_excludes_keys_caches_and_refuses_union_change_or_overflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'source'; source.mkdir()
            write_json(source / 'qualified.json', {'status': 'source-control-only'})
            signed = source / 'baseline-node/signed'; signed.mkdir(parents=True)
            (signed / 'publisher.key').write_bytes(b'private-test-key')
            cache = source / 'compiler-cache'; cache.mkdir(); (cache / 'unused').write_bytes(b'not-public')
            public = root / 'public'; admitted = matrix.retain(source, public)
            self.assertEqual(set(admitted['files']), {'qualified.json'})
            self.assertEqual(matrix.read_retained(public), {'status': 'source-control-only'})
            (public / 'qualified.json').write_bytes(b'{}\n')
            with self.assertRaisesRegex(ValueError, 'original-union'):
                matrix.read_retained(public)
            with patch.object(matrix, 'MAX_PUBLIC_BYTES', matrix.PUBLIC_METADATA_RESERVE + 1), \
                    self.assertRaises(WorkflowError):
                matrix.retain(source, root / 'over-bound')
            self.assertFalse((root / 'over-bound').exists())


if __name__ == '__main__': unittest.main()
