"""Finite wiring/source refusal controls; no signed execution is simulated."""
import ast
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import c_timed_runtime_fixture as fixture, c_timed_runtime_node as node
from tools import c_thread_runtime_fixture as original_fixture, c_thread_runtime_node as original
from tools import qualify_c_timed_runtime as qualification
from tools.c_guest import standard_facilities, threading
from tools.c_guest.compiler import Compiler


class CTimedRuntime(unittest.TestCase):
    def test_clock_bindings_do_not_expand_original_cell_limits_or_default_authority(self):
        settings = {'workers': {'runtime': 1, 'control': 1}, 'cells': [
            {'capacity': 1, 'queueCapacity': 2, 'maximumMemoryBytes': 67108864}],
            'audit': {'mode': 'durable', 'records': 1024, 'diskBytes': 16777216,
                'queuedOperations': 8, 'queryOwners': 2},
            'execution': {'maximumCpuFuel': 10000000000, 'maximumWallTimeMillis': 5000},
            'providers': {'bindings': [{'name': 'original-http-binding'}]}}
        capsule = {'imports': [{'contract': name, 'optional': False} for name in fixture.IMPORTS],
            'execution': {'limits': {'memoryBytes': 33554432, 'wallTimeLimitMillis': 5000}}}
        before = copy.deepcopy(settings)
        selected = node.configure(copy.deepcopy(settings), capsule)
        for name in ('workers', 'cells', 'execution'):
            self.assertEqual(selected[name], before[name])
        self.assertEqual(selected['providers']['activationRuntime']['limits'], original_fixture.LIMITS)
        self.assertEqual(len(selected['providers']['bindings']), 6)
        self.assertNotIn('grants', selected)
        # Actual ActivationRuntimeInstallation::validate_installation forbids
        # sharing its tenant/service identity with a scalar provider.
        runtime = selected['providers']['activationRuntime']['identity']
        for name, (contract, _, _, _) in node.profiles('c').items():
            scalar = selected['providers'][name]['identity']
            self.assertNotEqual((scalar['tenant'], scalar['service']),
                (runtime['tenant'], runtime['service']))
            binding = next(row for row in selected['providers']['bindings']
                if row.get('contract') == contract)
            self.assertEqual(binding['providerService'], scalar['service'])
        for bad in (capsule['imports'][:-1], [*capsule['imports'], capsule['imports'][0]],
                    [dict(row, optional=True) for row in capsule['imports']]):
            with self.assertRaisesRegex(RuntimeError, 'five-explicit-imports'):
                node.configure(copy.deepcopy(settings), dict(capsule, imports=bad))

    def test_real_fixture_keeps_original_envelope_and_one_c_translation_unit_with_explicit_clock_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = original_fixture.prepare(root / 'original')
            after = fixture.prepare(root / 'timed')
            old = json.loads((before / 'capsule-project.json').read_bytes())
            new = json.loads((after / 'capsule-project.json').read_bytes())
            self.assertEqual(new, dict(old, runtimeProfile=standard_facilities.PROFILE))
            self.assertEqual(new['limits']['memoryBytes'], 33554432)
            self.assertEqual(new['limits']['cpuFuel'], 1000000000)
            self.assertEqual(new['limits']['wallTimeLimitMillis'], 5000)
            self.assertEqual(sorted(path.name for path in (after / 'src').glob('*.c')), ['main.c'])
            self.assertEqual((before / 'src/main.c').read_bytes(), (after / 'src/main.c').read_bytes())
            self.assertEqual((after / 'src/timing.h').read_bytes(),
                (fixture.ROOT / fixture.FIXTURE / 'timing.h').read_bytes())
            self.assertNotIn('grants', new)
        # The node's signing, original protocol, shutdown, byte recheck and
        # bounded teardown are the complete original run function.
        def function(module, name):
            tree = ast.parse(Path(module.__file__).read_text())
            return ast.dump(next(value for value in tree.body
                if isinstance(value, ast.FunctionDef) and value.name == name), include_attributes=False)
        self.assertEqual(function(node, 'run'), function(original, 'run'))

    def test_timer_result_requires_same_closed_mode_real_positive_owner_counts_and_canonical_numbers(self):
        for mode in fixture.MODES:
            timers = 2 if 'broadcast' in mode else 1
            value = 'timed:' + mode + ':' + str(timers) + ':3:2:6388000'
            self.assertEqual(fixture.observation(value, mode)['timers'], timers)
            for changed in (value.replace(':' + str(timers) + ':3:', ':0:3:'),
                            value.replace(':' + str(timers) + ':3:', ':9:3:'),
                            value.replace(':3:2:', ':17:2:'), value.replace(':3:2:', ':3:1:'),
                            value + ':extra', value.replace(':' + str(timers) + ':3:', ':0' + str(timers) + ':3:'),
                            value.replace(':6388000', ':33554433'), value.replace(':6388000', ':0'),
                            value.replace('timed:', 'joined:', 1)):
                with self.subTest(mode=mode, changed=changed), self.assertRaises(ValueError):
                    fixture.observation(changed, mode)
        for value, mode in ((True, fixture.MODES[0]), ('timed:unknown:1:3:2:3', 'unknown')):
            with self.assertRaises(ValueError): fixture.observation(value, mode)

    def test_exact_original_twenty_prefix_and_independent_five_authorities_precede_fresh_timer(self):
        # Harness doubles check only programme wiring. They do not execute a
        # guest, produce signed evidence or claim an elapsed timer.
        grants = [{'capability': value, 'policy': str(index)}
                  for index, value in enumerate(fixture.IMPORTS)]
        target = {'grants': [], 'publication': 'publication', 'generation': '1'}
        invoked, denied, deployments = [], [], []
        def deploy(*args, **kwargs):
            deployments.append(kwargs['grants']); return dict(target, grants=kwargs['grants'])
        def invoke(*args, **kwargs):
            mode, activation = args[-2:]; invoked.append((mode, activation)); return {'mode': mode}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(node, 'install', return_value=grants), \
                patch.object(node, 'deploy', side_effect=deploy), \
                patch.object(node, 'start_call', return_value=SimpleNamespace()), \
                patch.object(original, 'finish_call', return_value={'double': True}), \
                patch.object(original, 'denied', side_effect=lambda row: denied.append(row)), \
                patch.object(original, 'retire', return_value={'double': True}), \
                patch.object(original, 'invoke', side_effect=invoke), \
                patch.object(node, 'invoke_timed', side_effect=invoke), \
                patch.object(node, 'selected_revision', return_value={'double': True}):
            record = node.programme(None, None, None, None, target, Path(directory))
        self.assertEqual(len(record['outcomes']), 36)
        self.assertEqual(record['originalTwentyOutcomePrefix'], 20)
        self.assertEqual([mode for mode, _ in invoked[:18]], [
            'pthread', 'c11', 'mixed', 'invalid', 'pressure', 'root-return', 'application-error',
            'root-trap', 'pthread', 'callback-trap', 'c11', 'cancel', 'mixed', 'deadline', 'pthread',
            'sync-pthread', 'sync-mixed', 'pthread'])
        self.assertEqual([mode for mode, _ in invoked[18:-1]], list(fixture.MODES))
        self.assertEqual(invoked[-1], ('timed-sleep-c11', 'c-thread-fresh-timed'))
        self.assertEqual(len(denied), 5)
        for index, missing in enumerate(original.IMPORTS):
            self.assertEqual(deployments[index], [row for row in grants if row['capability'] != missing])
        for index, missing in enumerate(fixture.IMPORTS[2:]):
            self.assertEqual(deployments[index + 3], [row for row in grants if row['capability'] != missing])
        self.assertEqual(deployments[2], grants)
        self.assertEqual(deployments[-1], grants)

    def test_clock_inputs_are_frozen_before_observation_and_cannot_be_replaced_after_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'time.h'; path.write_bytes(b'first-authenticated-input-double')
            key = next(iter(threading.CLOCK_LIBC))
            compiler = Compiler.__new__(Compiler)
            compiler.paths = {'zig': Path(directory) / 'zig'}
            compiler.threading_clock_inputs = {}; compiler.materials = {}
            with patch.object(threading, 'clock_libc_inputs', return_value={key: path}):
                compiler.select_threading_clock_inputs()
                frozen = copy.deepcopy(compiler.materials)
                compiler.select_threading_clock_inputs(); self.assertEqual(compiler.materials, frozen)
                path.write_bytes(b'changed-after-observation')
                with self.assertRaisesRegex(ValueError, 'clock-input-changed'):
                    compiler.select_threading_clock_inputs()
                self.assertEqual(compiler.materials, frozen)
        source = (fixture.ROOT / 'tools/c_capsule_build.py').read_text()
        self.assertLess(source.index('compiler.select_threading_clock_inputs()'),
                        source.index('materials = list(compiler.materials.values())'))
        self.assertIn('c-timed-all-original-twenty-and-sixteen-timed-outcomes',
                      Path(qualification.__file__).read_text())


if __name__ == '__main__': unittest.main()
