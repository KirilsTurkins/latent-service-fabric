"""Captured Go scheduler transformations for the finite activation profile."""
from pathlib import Path
import hashlib
import re

from tools.go_guest.runtime import checked_sources, replace_once

PROFILE = 'go-component-activation-v1'
CHECKPOINT_PROFILE = 'go-component-activation-v2'
TIMER_PROFILE = 'go-component-activation-v3'
INITIALIZER_PROFILE = 'go-component-activation-v4'
TIMER_PROFILES = {TIMER_PROFILE, INITIALIZER_PROFILE}
CHECKPOINT_PROFILES = {CHECKPOINT_PROFILE, *TIMER_PROFILES}
PROFILES = {PROFILE, *CHECKPOINT_PROFILES}
PREIMAGES = {
    'runtime/runtime2.go': '7d66ed912f68b1259947807ca1bdf79ee7e54c6a61a716d88db663d570af66da',
    'runtime/time.go': 'cf2ae4e953a3315c226499f553a8e8e1529d27ceac166b4fb75e8d7b3a4fa682',
    'runtime/mfinal.go': '49d40539afdd927355c9cfbfabc7130c561d0a19e68ca5e621082e58e9d96cd7',
    'runtime/mcleanup.go': 'bda3732f12dc16750994d6ce6b10b6844beb2ea1aa854c3407be757097f04207',
    'runtime/mgc.go': 'b1cb75ff1b5da577a1af442d5c52da2a08328510e4e70f66cb88d92e02a5b33e',
    'runtime/mgcsweep.go': '81139b39aeacd63e86bdadb6e921882e871bb30c87479b454aa5d82adc0c91aa',
    'runtime/mgcscavenge.go': '8d462284b9cc551410de1d19b910e4d263d29869596314c0a8dc4af8f8afa25b',
    'runtime/pinner.go': '6f638fb797edb1ed42601f11a086c8f6a34f095d7c85b9f53773e59528ff38bd',
    'os/file_unix.go': '877dd004355c475e8805b5700061604558422da057037556e0cf6edeb36ab7ec',
}
ASYNC_SHA256 = '0ab89732e936c9f766ca571e7f56d6406b1fd0a2d28931f5c8d2c86bdedf786b'


def runtime_sources(goroot: Path, sources: dict[str, str], sdk: Path, *, checkpoints=False, timers=False, initializers=False):
    sources.update(checked_sources(goroot, PREIMAGES))
    sources['runtime/runtime2.go'] = replace_once(sources['runtime/runtime2.go'],
        '\tvalgrindStackID uintptr\n}', '\tvalgrindStackID uintptr\n\tlsfOwner [2]uint64\n\tlsfParked bool\n}')
    text = sources['runtime/proc.go']
    text = replace_once(text, '\tmp := acquirem() // disable preemption because we hold M and P in local vars.',
        '\tlsfOwner := lsfNewTask(fn, callergp)\n\tmp := acquirem() // disable preemption because we hold M and P in local vars.')
    text = replace_once(text, '\tnewg.parentGoid = callergp.goid',
        '\tnewg.lsfOwner = lsfOwner\n\tnewg.parentGoid = callergp.goid')
    text = replace_once(text, 'func gdestroy(gp *g) {',
        'func gdestroy(gp *g) {\n\tlsfTaskDestroyed(gp)')
    text = replace_once(text, 'func ready(gp *g, traceskip int, next bool) {',
        'func ready(gp *g, traceskip int, next bool) {\n\tlsfTaskWake(gp)')
    # GC and netpoll can inject runnable goroutines without ready(). Observe
    # the common actual resume transition as well, exactly once per park.
    text = replace_once(text, 'func execute(gp *g, inheritTime bool) {',
        'func execute(gp *g, inheritTime bool) {\n\tif gp.lsfParked { lsfTaskWake(gp) }')
    text = replace_once(text, '\tcasgstatus(gp, _Grunning, _Gwaiting)\n\tif trace.ok() {',
        '\tcasgstatus(gp, _Grunning, _Gwaiting)\n\tlsfTaskPark(gp)\n\tif trace.ok() {')
    text = replace_once(text, '\t\tif !ok {\n\t\t\ttrace := traceAcquire()',
        '\t\tif !ok {\n\t\t\tlsfTaskWake(gp)\n\t\t\ttrace := traceAcquire()')
    sources['runtime/proc.go'] = text
    text = sources['runtime/time.go']
    text = replace_once(text, 'func timeSleep(ns int64) {',
        'func timeSleep(ns int64) {\n\tif lsfActivationActive {\n\t\tif ns > 0 { lsfActivationSleep(ns) }\n\t\treturn\n\t}')
    # NewTimer/After/AfterFunc/Ticker need timer heap rearm and callback ownership,
    # not just an alias for a sleeping task. They remain an explicit profile gap.
    text = replace_once(text,
        'func newTimer(when, period int64, f func(arg any, seq uintptr, delay int64), arg any, c *hchan) *timeTimer {',
        'func newTimer(when, period int64, f func(arg any, seq uintptr, delay int64), arg any, c *hchan) *timeTimer {\n'
        '\tif lsfActivationActive { lsfFail("LSF Go timer API is not qualified by this profile") }')
    sources['runtime/time.go'] = text
    sources['runtime/mfinal.go'] = replace_once(sources['runtime/mfinal.go'],
        'func SetFinalizer(obj any, finalizer any) {',
        'func SetFinalizer(obj any, finalizer any) {\n'
        '\tif finalizer != nil {\n'
        '\t\tf := efaceOf(&finalizer)\n'
        '\t\tif f._type.Kind() != abi.Func { lsfFail("LSF Go application finalizer callbacks are not qualified") }\n'
        '\t\tswitch funcname(findfunc((*funcval)(f.data).fn)) {\n'
        '\t\tcase "runtime.(*Pinner).Pin.func1", "os.(*file).close":\n'
        '\t\tdefault: lsfFail("LSF Go application finalizer callbacks are not qualified")\n\t\t}\n\t}')
    sources['runtime/mcleanup.go'] = replace_once(sources['runtime/mcleanup.go'],
        'func AddCleanup[T, S any](ptr *T, cleanup func(S), arg S) Cleanup {',
        'func AddCleanup[T, S any](ptr *T, cleanup func(S), arg S) Cleanup {\n\tlsfFail("LSF Go cleanup callbacks are not qualified")')
    sources['runtime/os_wasip1.go'] += '\n' + (sdk / 'runtime/activation_bridge.go.in').read_text()
    if checkpoints:
        sources['runtime/os_wasip1.go'] += '\n' + (sdk / 'runtime/checkpoint_bridge.go.in').read_text()
    if timers:
        from tools.go_guest.timers import runtime_sources as timer_sources
        timer_sources(goroot, sources, sdk)
    if initializers:
        from tools.go_guest.initializers import runtime_sources as initializer_sources
        initializer_sources(sources, sdk)


def async_source(dependency: Path, sdk: Path, *, checkpoints=False, timers=False, initializers=False) -> tuple[Path, str]:
    path = dependency / 'wit/async/async.go'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ASYNC_SHA256:
        raise ValueError('go-activation-dispatcher-source-drift')
    text = replace_once(raw.decode(), 'func Run(closure func()) uint32 {',
        'func Run(closure func()) uint32 {\n\tlsfActivationEnter()')
    text = replace_once(text, '\t\t\treturn CALLBACK_CODE_EXIT',
        '\t\t\tlsfActivationLeave()\n\t\t\treturn CALLBACK_CODE_EXIT')
    if checkpoints:
        text = replace_once(text, 'yielding    chan unit', 'yielding    []chan unit')
        text = replace_once(text, '\t\tyielding <- unit{}',
            '\t\tfor _, channel := range yielding { channel <- unit{} }')
        text = replace_once(text, '\tstate.yielding = channel',
            '\tstate.yielding = append(state.yielding, channel)')
        text += '\n' + (sdk / 'runtime/checkpoint_async.go.in').read_text()
    if timers:
        from tools.go_guest.timers import async_source as timer_source
        text = timer_source(text, sdk)
    if initializers:
        from tools.go_guest.initializers import async_source as initializer_source
        text = initializer_source(text)
    return path, text + '\n' + (sdk / 'runtime/activation_async.go.in').read_text()


def exports(directory: Path):
    path = directory / 'wit_exports.go'
    text = path.read_text()
    # Each async generated call seals only after the ordinary handler returned
    # and all accepted sibling goroutines have actually exited.
    text, count = re.subn(r'(?m)^(\s*)(wasm_export_task_return_[A-Za-z0-9_]+\()',
        r'\1lsfActivationFinish()\n\1\2', text)
    if not count:
        raise ValueError('go-activation-requires-async-exports')
    if re.search(r'(?m)^//go:wasmexport (?!\[async-lift\]|\[callback\])', text):
        raise ValueError('go-activation-synchronous-export-unsupported')
    text += '\n//go:linkname lsfActivationFinish runtime.lsfActivationFinish\nfunc lsfActivationFinish()\n'
    # Generated main already imports runtime. The blank unsafe import permits
    # linkname without exposing a source-level application runtime facade.
    text = text.replace('import (', 'import (\n\t_ "unsafe"', 1)
    path.write_text(text)
