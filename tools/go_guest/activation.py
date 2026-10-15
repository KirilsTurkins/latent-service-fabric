"""Captured Go scheduler transformations for the finite activation profile."""
from pathlib import Path
import hashlib
import re

from tools.go_guest.runtime import checked_sources, replace_once

PROFILE = 'go-component-activation-v1'
PREIMAGES = {
    'runtime/runtime2.go': '7d66ed912f68b1259947807ca1bdf79ee7e54c6a61a716d88db663d570af66da',
    'runtime/time.go': 'cf2ae4e953a3315c226499f553a8e8e1529d27ceac166b4fb75e8d7b3a4fa682',
}
ASYNC_SHA256 = '0ab89732e936c9f766ca571e7f56d6406b1fd0a2d28931f5c8d2c86bdedf786b'


def runtime_sources(goroot: Path, sources: dict[str, str], sdk: Path):
    sources.update(checked_sources(goroot, PREIMAGES))
    sources['runtime/runtime2.go'] = replace_once(sources['runtime/runtime2.go'],
        'type g struct {', 'type g struct {\n\tlsfOwner [2]uint64')
    text = sources['runtime/proc.go']
    text = replace_once(text, '\tmp := acquirem() // disable preemption because we hold M and P in local vars.',
        '\tlsfOwner := lsfNewTask(fn, callergp)\n\tmp := acquirem() // disable preemption because we hold M and P in local vars.')
    text = replace_once(text, '\tnewg.parentGoid = callergp.goid',
        '\tnewg.lsfOwner = lsfOwner\n\tnewg.parentGoid = callergp.goid')
    text = replace_once(text, 'func gdestroy(gp *g) {',
        'func gdestroy(gp *g) {\n\tlsfTaskDestroyed(gp)')
    sources['runtime/proc.go'] = text
    text = sources['runtime/time.go']
    text = replace_once(text, 'func timeSleep(ns int64) {',
        'func timeSleep(ns int64) {\n\tif lsfActivationActive {\n\t\tif ns > 0 { lsfActivationSleep(ns) }\n\t\treturn\n\t}')
    # NewTimer/After/AfterFunc/Ticker need timer heap rearm and callback ownership,
    # not just an alias for a sleeping task. They remain an explicit profile gap.
    text = replace_once(text,
        'func newTimer(when, period int64, f func(arg any, seq uintptr, delay int64), arg any, c *hchan) *timeTimer {',
        'func newTimer(when, period int64, f func(arg any, seq uintptr, delay int64), arg any, c *hchan) *timeTimer {\n'
        '\tif lsfActivationActive { throw("LSF Go timer API is not qualified by this profile") }')
    sources['runtime/time.go'] = text
    sources['runtime/os_wasip1.go'] += '\n' + (sdk / 'runtime/activation_bridge.go.in').read_text()


def async_source(dependency: Path, sdk: Path) -> tuple[Path, str]:
    path = dependency / 'wit/async/async.go'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ASYNC_SHA256:
        raise ValueError('go-activation-dispatcher-source-drift')
    text = replace_once(raw.decode(), 'func Run(closure func()) uint32 {',
        'func Run(closure func()) uint32 {\n\tlsfActivationEnter()')
    text = replace_once(text, '\t\t\treturn CALLBACK_CODE_EXIT',
        '\t\t\tlsfActivationLeave()\n\t\t\treturn CALLBACK_CODE_EXIT')
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
