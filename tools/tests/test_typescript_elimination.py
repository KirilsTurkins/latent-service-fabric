"""Adverse reader controls; model inputs never stand in for compiler/runtime results."""
import copy
import unittest

from tools.rust_capsule_project import digest
from tools.typescript_elimination_fixture import CALLBACK, LIBRARY, expected
from tools.typescript_elimination_evidence import CALLBACK_PATH, LIBRARY_PATH, contribution
from tools.typescript_elimination_node import outcome


def compiler_model(selected):
    sources = [(CALLBACK_PATH, CALLBACK), (LIBRARY_PATH, LIBRARY)]
    inputs = {LIBRARY_PATH: {'bytesInOutput': 30}, 'src/main.ts': {'bytesInOutput': 70}}
    if selected:
        inputs[CALLBACK_PATH] = {'bytesInOutput': 90}
    return {'capturedInputs': [{'path': name, 'digest': digest(code.encode()), 'size': len(code.encode())}
            for name, code in sources],
        'inputs': {name: {'bytes': len(code.encode())} for name, code in sources},
        'outputs': {'application.mjs': {'entryPoint': 'src/main.ts', 'imports': [], 'exports': ['api'], 'inputs': inputs}},
        'standardClockProfile': 'lsf-standard-clock-unsupported-v1',
        'standardEntropyProfile': 'lsf-math-random-unsupported-v1'}


def invocation_model(reached):
    return {'processReaped': True, 'exitCode': 0, 'decoded': expected(7, 42, reached),
        'response': {'outcomeKnown': True, 'requestDispatched': True, 'schemaVersion': 'latent.cli.result.v1',
            'command': 'invoke', 'category': 'success', 'error': None}}


class TypeScriptEliminationTests(unittest.TestCase):
    def test_both_finite_witnesses_keep_arbitrary_api_unknown(self):
        for selected in (False, True):
            result = contribution(compiler_model(selected), selected=selected)
            self.assertEqual(result['callbackModuleRetained'], selected)
            self.assertEqual(result['arbitraryApiClassification'], 'unknown')
            self.assertFalse(result['runtimeExecutionQualified'])
            self.assertFalse(result['fullComponentEngineApiAbsentClaimed'])

    def test_retained_module_cannot_be_relabelled_eliminated_or_reverse(self):
        for selected in (False, True):
            with self.assertRaises((ValueError, RuntimeError)):
                contribution(compiler_model(selected), selected=not selected)

    def test_foreign_source_duplicate_input_or_runtime_profile_is_rejected(self):
        original = compiler_model(True)
        variants = []
        value = copy.deepcopy(original); value['capturedInputs'][0]['digest'] = 'sha256:' + '0' * 64; variants.append(value)
        value = copy.deepcopy(original); value['capturedInputs'].append(value['capturedInputs'][0]); variants.append(value)
        value = copy.deepcopy(original); value['standardClockProfile'] = 'lsf-standard-clock-native-v1'; variants.append(value)
        value = copy.deepcopy(original); value['outputs']['application.mjs']['imports'] = [{'path': 'node:fs'}]; variants.append(value)
        value = copy.deepcopy(original); value['outputs']['application.mjs']['inputs'][CALLBACK_PATH]['bytesInOutput'] = True; variants.append(value)
        for value in variants:
            with self.assertRaises((ValueError, RuntimeError)):
                contribution(value, selected=True)

    def test_raw_return_requires_the_selected_branch_refusal_flag(self):
        for reached in (False, True):
            result = outcome('typescript', invocation_model(reached), 7, 42, reached)
            self.assertEqual(result['nativeRefusalVerified'], reached)
            with self.assertRaises((ValueError, RuntimeError)):
                outcome('typescript', invocation_model(reached), 7, 42, not reached)

    def test_uncaught_failure_and_success_are_never_interchangeable(self):
        row = invocation_model(True)
        with self.assertRaises((ValueError, RuntimeError)):
            outcome('typescript', row, 13, None, True)
        row.update(exitCode=4, decoded=None)
        row['response'].update(category='platform-failure', error={'code': 'guest-trap'}, data={'terminalState': 'guest_trap'})
        result = outcome('typescript', row, 13, None, True)
        self.assertEqual(result['category'], 'guest-trap')
        self.assertFalse(result['preciseInstructionCauseProved'])
        with self.assertRaises((ValueError, RuntimeError)):
            outcome('typescript', row, 7, 42, True)


if __name__ == '__main__':
    unittest.main()
