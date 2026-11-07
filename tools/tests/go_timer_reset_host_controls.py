"""Known Go timer Reset defect and a separate cooperative-gate host model.

These host doubles compile selected emitted functions with stub timer/host calls.
They do not execute a component, real timer provider, GC or g0 callback. The
baseline is intentionally expected to reproduce the known duplicate owner; a
future production fix must replace that expectation with the corrected contract.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import patch

from tools.go_guest import activation, timers

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tools/tests/fixtures'
TIME_SOURCE = FIXTURES / 'go_runtime_time_go1_27_3.go.txt'
GO_LICENSE = FIXTURES / 'go_runtime_stack_go1_27_3.LICENSE.txt'
BASELINE = FIXTURES / 'go_timer_reset_baseline.go.txt'
CANDIDATE = FIXTURES / 'go_timer_reset_gate_candidate.go.txt'
TIME_SHA256 = 'cf2ae4e953a3315c226499f553a8e8e1529d27ceac166b4fb75e8d7b3a4fa682'
LICENSE_SHA256 = '911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad'


def checked_time_source(source, license_bytes):
    if (hashlib.sha256(source).hexdigest() != TIME_SHA256
            or activation.PREIMAGES['runtime/time.go'] != TIME_SHA256
            or hashlib.sha256(license_bytes).hexdigest() != LICENSE_SHA256):
        raise ValueError('go-timer-host-control-upstream-or-license-drift')
    return source.decode('utf-8')


def emitted_time_source():
    # Invoke the actual activation/timer transforms on the exact pinned time.go.
    # Unrelated runtime sources are inert test doubles: only time.go is compiled
    # into this host control, and the real timer bridge is selected separately.
    original = checked_time_source(TIME_SOURCE.read_bytes(), GO_LICENSE.read_bytes())
    inputs = {
        'runtime/time.go': original,
        'runtime/runtime2.go': '\tvalgrindStackID uintptr\n}',
        'runtime/mfinal.go': 'func SetFinalizer(obj any, finalizer any) {',
        'runtime/mcleanup.go': 'func AddCleanup[T, S any](ptr *T, cleanup func(S), arg S) Cleanup {',
    }
    proc = '\n'.join((
        '\tmp := acquirem() // disable preemption because we hold M and P in local vars.',
        '\tnewg.parentGoid = callergp.goid',
        'func gdestroy(gp *g) {',
        'func ready(gp *g, traceskip int, next bool) {',
        'func execute(gp *g, inheritTime bool) {',
        '\tcasgstatus(gp, _Grunning, _Gwaiting)\n\tif trace.ok() {',
        '\t\tif !ok {\n\t\t\ttrace := traceAcquire()',
    ))
    sources = {'runtime/proc.go': proc, 'runtime/os_wasip1.go': ''}
    root = Path('unused-host-double-goroot')
    with patch.object(activation, 'checked_sources', return_value=inputs) as checked, \
            patch.object(activation, 'canonical_map_source', return_value=''), \
            patch.object(timers, 'checked_sources', return_value={}) as checked_heap:
        activation.runtime_sources(root, sources, ROOT / 'sdk/go-guest', timers=True)
    checked.assert_called_once_with(root, activation.PREIMAGES)
    checked_heap.assert_called_once_with(root, {
        'runtime/mheap.go': '848cedd74ae1d10af65eb3beed88ddd7d22d184a64a5a7477251c4886e8a459d'})
    return sources['runtime/time.go']


def extract(source, name):
    start = source.index('func ' + name + '(')
    return source[start:source.index('\n}', start) + 2]


def host_source(candidate):
    time_source = emitted_time_source()
    bridge = (ROOT / 'sdk/go-guest/runtime/timer_bridge.go.in').read_text(encoding='utf-8')
    async_source = (ROOT / 'sdk/go-guest/runtime/timer_async.go.in').read_text(encoding='utf-8')
    names = ('resetTimer', 'stopTimer') if candidate else ('resetTimer',)
    functions = [extract(time_source, name) for name in names]
    if candidate:
        # This is an injected model, not shipped timer code. The fixture seeds
        # its channel directly; real newTimer publication is not exercised.
        for index, word in enumerate(('active', 'stopped')):
            original = '\t' + word + ' := t.stop()'
            if functions[index].count(original) != 1:
                raise ValueError('go-timer-host-control-gate-injection-drift')
            gated = '\t<-t.lsfGate\n\tdefer func() { t.lsfGate <- struct{}{} }()\n' + original
            functions[index] = functions[index].replace(original, gated)
    bridge_names = ['lsfReserveTimer', 'lsfInstallTimer', 'lsfPublishTimer',
                    'lsfSweepCollectedTimers', 'lsfStopTimerSlot', 'lsfRetireTimer']
    if candidate:
        bridge_names += ['lsfBeforeTimerCallback', 'lsfAfterTimerCallback']
    functions.extend(extract(bridge, name) for name in bridge_names)
    functions.extend(extract(async_source, name)
                     for name in ('lsfActivationTimerStopped', 'lsfActivationTimerFence'))
    original_receive = '(<-wait.done)'
    if functions[-1].count(original_receive) != 1:
        raise ValueError('go-timer-host-control-fence-drift')
    # The seam signals entry, then performs the same real channel receive. It
    # creates a deterministic overlap rather than claiming a real host wait.
    functions[-1] = functions[-1].replace(original_receive, 'controlledFenceReceive(wait)')
    package = 'timergate' if candidate else 'timerreset'
    return 'package ' + package + '\n\nimport "unsafe"\n\n' + '\n\n'.join(functions) + '\n'


def assert_source_binding(case):
    source, license_bytes = TIME_SOURCE.read_bytes(), GO_LICENSE.read_bytes()
    case.assertIn('func resetTimer(', checked_time_source(source, license_bytes))
    for altered, license_input in ((source + b'\n', license_bytes), (source, license_bytes + b'\n')):
        with case.assertRaisesRegex(ValueError, 'upstream-or-license-drift'):
            checked_time_source(altered, license_input)
    baseline = host_source(False)
    candidate = host_source(True)
    case.assertNotIn('<-t.lsfGate', baseline)
    case.assertEqual(candidate.count('<-t.lsfGate'), 2)
    case.assertIn('controlledFenceReceive(wait)', baseline)
    case.assertIn('controlledFenceReceive(wait)', candidate)


def run_host_doubles(case, go):
    # The caller is the existing guarded Go host-control test. The designated
    # hosted owners explicitly require Go before invoking that existing test.
    case.assertTrue(go, 'Go host control requires an installed compiler')
    env = dict(os.environ, GO111MODULE='off', GOENV='off', GOFLAGS='', GOWORK='off',
               GOTOOLCHAIN='local', GOMAXPROCS='1', GOOS='', GOARCH='',
               CGO_ENABLED='0', GOPROXY='off')
    env.pop('GOROOT', None)
    for candidate in (False, True):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'timer.go').write_text(host_source(candidate), encoding='utf-8')
            (root / 'timer_test.go').write_bytes((CANDIDATE if candidate else BASELINE).read_bytes())
            result = subprocess.run([go, 'test', '-count=1', '-timeout=30s', '-v', '.'],
                                    cwd=root, env=env, text=True, capture_output=True, timeout=180)
        output = result.stdout + result.stderr
        if not candidate:
            case.assertNotEqual(result.returncode, 0,
                                'known baseline defect did not reproduce; review the production change')
            for expected in ('--- PASS: TestSequentialResetsKeepOneOwner',
                             '--- FAIL: TestOverlappingResetsKeepOneOwner',
                             'slots=[[7 2] [7 3]]', 'replacement=[7 2] current=[7 3]',
                             'firstActive=true secondActive=false'):
                case.assertIn(expected, output)
            print('Go timer host double: expected baseline duplicate-owner defect reproduced', flush=True)
        else:
            case.assertEqual(result.returncode, 0, output)
            for name in ('TestResetResetSerializesAndKeepsBothTrue',
                         'TestResetStopSerializesAndLeavesStopped',
                         'TestStopResetSerializesAndReturnsFalseForReset',
                         'TestStopStopSerializesAndSecondIsFalse',
                         'TestOneShotCallbackMayRetireWithoutTakingGate',
                         'TestRecoverablePanicReleasesGateForFollowingStop'):
                case.assertIn('--- PASS: ' + name, output)
            print('Go timer host double: unshipped gate model passed; no guest or g0 claim', flush=True)
