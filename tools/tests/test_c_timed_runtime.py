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
        for mode in (*fixture.MODES, fixture.SELECT_MODE):
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
        self.assertEqual(len(record['outcomes']), 37)
        self.assertEqual(record['originalThirtySixOutcomePrefix'], 36)
        self.assertEqual(record['originalTwentyOutcomePrefix'], 20)
        self.assertEqual([mode for mode, _ in invoked[:18]], [
            'pthread', 'c11', 'mixed', 'invalid', 'pressure', 'root-return', 'application-error',
            'root-trap', 'pthread', 'callback-trap', 'c11', 'cancel', 'mixed', 'deadline', 'pthread',
            'sync-pthread', 'sync-mixed', 'pthread'])
        self.assertEqual([mode for mode, _ in invoked[18:-2]], list(fixture.MODES))
        self.assertEqual(invoked[-2], ('timed-sleep-c11', 'c-thread-fresh-timed'))
        self.assertEqual(invoked[-1], (fixture.SELECT_MODE, 'c-thread-timed-select'))
        self.assertEqual(len(denied), 5)
        for index, missing in enumerate(original.IMPORTS):
            self.assertEqual(deployments[index], [row for row in grants if row['capability'] != missing])
        for index, missing in enumerate(fixture.IMPORTS[2:]):
            self.assertEqual(deployments[index + 3], [row for row in grants if row['capability'] != missing])
        self.assertEqual(deployments[2], grants)
        self.assertEqual(deployments[-1], grants)

    def test_select_witness_requires_one_timer_and_cannot_turn_failure_into_success(self):
        with self.assertRaisesRegex(ValueError, 'select-exact-timer'):
            fixture.observation('timed:timed-select:2:3:2:6388000', fixture.SELECT_MODE)
        revision = {'id': 'selected'}
        process = SimpleNamespace()
        consumption = {name: '0' for name in ('outboundRequests', 'stateReadBytes', 'stateWriteBytes',
            'blobReadBytes', 'blobWriteBytes', 'logBytes', 'effectCount', 'childCalls')}
        for code in ('guest-trap', 'cancelled', 'deadline'):
            row = {'processReaped': True, 'exitCode': 4, 'decoded': None,
                'response': {'outcomeKnown': True, 'requestDispatched': True,
                    'data': {'resolvedRevision': revision, 'consumption': consumption},
                    'error': {'code': code}}}
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory, \
                    patch.object(node, 'selected_revision', return_value=revision), \
                    patch.object(node, 'start_call', return_value=process), \
                    patch.object(original, 'finish_call', return_value=row), \
                    patch.object(original, 'retain_partial') as retained, \
                    patch.object(original, 'close_call') as closed, \
                    patch.object(original, 'retire') as retired:
                with self.assertRaisesRegex(RuntimeError, 'c-timed-ordinary-success'):
                    node.invoke_timed(None, None, {}, Path(directory), fixture.SELECT_MODE, 'select-failure')
                retained.assert_called_once()
                closed.assert_called_once_with(process, primary_failure=True)
                retired.assert_not_called()

    def test_original_timed_failure_stops_before_select(self):
        grants = [{'capability': value, 'policy': str(index)}
                  for index, value in enumerate(fixture.IMPORTS)]
        target = {'grants': [], 'publication': 'publication', 'generation': '1'}
        entered = []
        def deploy(*args, **kwargs):
            return dict(target, grants=kwargs['grants'])
        def original_invoke(*args, **kwargs):
            return {'mode': args[-2]}
        def fail_timed(*args, **kwargs):
            entered.append(args[-2])
            raise RuntimeError('original timed failure')
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(node, 'install', return_value=grants), \
                patch.object(node, 'deploy', side_effect=deploy), \
                patch.object(node, 'start_call', return_value=SimpleNamespace()), \
                patch.object(original, 'finish_call', return_value={'double': True}), \
                patch.object(original, 'denied'), \
                patch.object(original, 'retire', return_value={'double': True}), \
                patch.object(original, 'invoke', side_effect=original_invoke), \
                patch.object(node, 'invoke_timed', side_effect=fail_timed):
            with self.assertRaisesRegex(RuntimeError, 'original timed failure'):
                node.programme(None, None, None, None, target, Path(directory))
        self.assertEqual(entered, [fixture.MODES[0]])
        self.assertNotIn(fixture.SELECT_MODE, entered)

    def test_clock_inputs_are_frozen_before_observation_and_cannot_be_replaced_after_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'time.h'; path.write_bytes(b'first-authenticated-input-double')
            key = next(iter(threading.CLOCK_LIBC))
            compiler = Compiler.__new__(Compiler)
            compiler.paths = {'zig': Path(directory) / 'zig'}
            compiler.sdk = Path(directory) / 'sdk'
            (compiler.sdk / 'runtime').mkdir(parents=True)
            response = compiler.sdk / 'runtime/timed-symbols.rsp'
            response.write_bytes(threading.TIME_RESPONSE)
            poll_path = Path(directory) / 'poll.h'; poll_path.write_bytes(b'first-poll-input-double')
            poll_key = next(iter(threading.POLL_LIBC))
            compiler.threading_clock_inputs = {}; compiler.threading_poll_inputs = {}; compiler.materials = {}
            from types import SimpleNamespace
            compiler.isolation = SimpleNamespace(receipt={})
            with patch.object(threading, 'clock_libc_inputs', return_value={key: path}), \
                    patch.object(threading, 'poll_libc_inputs', return_value={poll_key: poll_path}):
                compiler.select_threading_clock_inputs()
                self.assertEqual(compiler.isolation.receipt['cTimedSourceMapping']['mode'], 'fixed-sdk-response-v1')
                self.assertFalse(compiler.isolation.receipt['cTimedSourceMapping']['selectPrecisionQualified'])
                frozen = copy.deepcopy(compiler.materials)
                compiler.select_threading_clock_inputs(); self.assertEqual(compiler.materials, frozen)
                path.write_bytes(b'changed-after-observation')
                with self.assertRaisesRegex(ValueError, 'clock-input-changed'):
                    compiler.select_threading_clock_inputs()
                self.assertEqual(compiler.materials, frozen)
                path.write_bytes(b'first-authenticated-input-double')
                poll_path.write_bytes(b'changed-poll-after-observation')
                with self.assertRaisesRegex(ValueError, 'poll-input-changed'):
                    compiler.select_threading_clock_inputs()
                self.assertEqual(compiler.materials, frozen)
                poll_path.write_bytes(b'first-poll-input-double')
                response.write_bytes(threading.TIME_RESPONSE + b'-Wl,--allow-undefined\n')
                with self.assertRaisesRegex(ValueError, 'response-preimage'):
                    compiler.select_threading_clock_inputs()
                # This guard runs immediately before any Zig use of the @file.
                with self.assertRaisesRegex(ValueError, 'response-preimage'):
                    compiler.run('zig', '@' + str(response))
                self.assertEqual(compiler.materials, frozen)
                response.unlink()
                legacy = Compiler.__new__(Compiler)
                legacy.paths = compiler.paths; legacy.sdk = compiler.sdk
                legacy.threading_clock_inputs = {}; legacy.threading_poll_inputs = {}; legacy.materials = {}
                legacy.isolation = SimpleNamespace(receipt={})
                legacy.select_threading_clock_inputs()
                self.assertEqual(legacy.isolation.receipt['cTimedSourceMapping']['mode'], 'legacy-sleep-defines')
                self.assertFalse(legacy.isolation.receipt['cTimedSourceMapping']['selectPrecisionQualified'])
                self.assertIsNone(legacy.threading_time_alias)
        source = (fixture.ROOT / 'tools/c_capsule_build.py').read_text()
        self.assertLess(source.index('compiler.select_threading_clock_inputs()'),
                        source.index('materials = list(compiler.materials.values())'))
        self.assertIn('c-timed-all-original-twenty-and-sixteen-timed-outcomes',
                      Path(qualification.__file__).read_text())


    def test_timed_validation_failure_preserves_error_and_root_tls_cleanup(self):
        # Execute the actual fixture branch and destructor with native pthread
        # TLS. The validator is forced to fail; no guest or ledger is simulated.
        import os
        import shutil
        import subprocess
        if os.name != 'posix' or not shutil.which('cc'):
            self.skipTest('native POSIX compiler required')
        root = fixture.ROOT / 'tools/fixtures/c-thread-runtime'
        main = (root / 'main.c').read_text()
        timing = (root / 'timing.h').read_text()

        def between(source, start, end):
            begin = source.index(start)
            return source[begin:source.index(end, begin)]

        validation = between(timing, 'static unsigned timed_validation(void)', '\nstatic bool timed_children')
        self.assertNotIn('pthread_create(', validation)
        self.assertNotIn('thrd_create(', validation)
        children = timing[timing.index('static bool timed_children'):]
        branch = between(children, '    unsigned failure = timed_validation();', '\n    if (timed_c11) {')
        self.assertLess(children.index(branch), children.index('pthread_create('))
        self.assertLess(children.index(branch), children.index('thrd_create('))
        require = between(main, 'static void require(int predicate)', '\n#if LSF_C_TIMED_CLOCK')
        destructor = between(main, 'static void destructor(void *value)', '\n\nstatic void *worker')
        number = between(main, 'static void number(char **output', '\n\nstatic void observed_result')
        prefix = r'''
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
typedef struct { const char *ptr; size_t len; } probe_string_t;
static _Thread_local unsigned local;
static pthread_key_t key;
static pthread_t root_id;
static unsigned forced_failure, forced_errno, destructed, input_freed;
static int intercepted_setspecific(pthread_key_t k,const void *v) {
    int result=pthread_setspecific(k,v); if (v==NULL) errno=97; return result;
}
static __attribute__((unused)) int intercepted_key_delete(pthread_key_t k) {
    int result=pthread_key_delete(k); errno=98; return result;
}
#define pthread_setspecific intercepted_setspecific
#define pthread_key_delete intercepted_key_delete
#define FIXTURE_DESTRUCT() (++destructed)
'''
        suffix = r'''
static unsigned timed_validation(void) { return forced_failure; }
static void probe_string_dup(probe_string_t *error,const char *value) {
    error->ptr=strdup(value); error->len=strlen(value);
    if (!error->ptr || write(1,value,error->len)!=(ssize_t)error->len || write(1,"\n",1)!=1) _exit(91);
}
static void probe_string_free(probe_string_t *input) { (void)input; input_freed=1; }
static bool run_error_branch(probe_string_t *input,probe_string_t *error) {
'''
        end = r'''
    return true;
}
static void *activation(void *unused) {
    (void)unused;
    root_id=pthread_self();local=70;
    require(pthread_key_create(&key,destructor)==0);
    require(pthread_setspecific(key,(void *)(uintptr_t)77)==0);
    errno=(int)forced_errno;
    probe_string_t input={0},error={0};
    bool ok=run_error_branch(&input,&error);
    if (ok || !input_freed || !error.ptr) _exit(92);
    free((void *)error.ptr);
    return NULL;
}
static void caught_trap(int signal_number) { (void)signal_number;_exit(86); }
int main(int argc,char **argv) {
    if (argc!=3) return 90;
    forced_failure=(unsigned)strtoul(argv[1],NULL,10);
    forced_errno=(unsigned)strtoul(argv[2],NULL,10);
    if (signal(SIGILL,caught_trap)==SIG_ERR) return 93;
    pthread_t root;
    if (pthread_create(&root,NULL,activation,NULL)!=0 || pthread_join(root,NULL)!=0) return 94;
    return destructed ? 95 : 0;
}
'''
        harness = prefix + require + '\n' + destructor + '\n' + number + '\n' + suffix + branch + end
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.c'
            executable = Path(directory) / 'control'
            source.write_text(harness)
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread',
                            str(source), '-o', str(executable)], check=True, capture_output=True, timeout=30)
            for failure, error in ((1, 5), (7, 23), (14, 0)):
                with self.subTest(failure=failure, error=error):
                    result = subprocess.run([str(executable), str(failure), str(error)],
                                            capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, f'timed-validation:{failure}:{error}\n'.encode())



if __name__ == '__main__': unittest.main()
