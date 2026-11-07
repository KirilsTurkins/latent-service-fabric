"""Prepare explicit source changes on the known PR head; no runtime test bypass."""
from pathlib import Path
import json, os, subprocess
ROOT = Path.cwd()
NAMES = ['sdk/wasi-http-runtime/poll.rs', 'sdk/wasi-http-runtime/io.rs',
    'sdk/wasi-http-runtime/state.rs', 'tools/toolchain-smoke/examples/rust_wasi_http_runtime.rs',
    'tools/toolchain-smoke/Cargo.toml', 'tools/rust_wasi_http_inputs.py', 'Cargo.lock',
    'sdk/wasi-http-runtime/pump.rs', 'sdk/wasi-http-runtime/pump_tests.rs',
    'sdk/wasi-http-runtime/timer.rs', 'tools/toolchain-smoke/examples/rust_http_pump_probe.rs',
    'tools/toolchain-smoke/examples/rust_http_pump_control.rs']
def edit(name, before, after, count=1):
    p=ROOT/name; s=p.read_text(); assert s.count(before)==count, (name,before,s.count(before))
    p.write_text(s.replace(before,after))
edit(NAMES[0], 'pub fn poll(inputs:', 'pub async fn poll(inputs:')
edit(NAMES[0], '        Self::wait(&sources)', '        Self::wait(&sources).await')
edit(NAMES[0], '    fn wait(sources:', '    async fn wait(sources:')
edit(NAMES[0], 'pump::Pump::current().poll(sources)', 'pump::Pump::current().poll(sources).await')
edit(NAMES[0], 'Self::wait(&[self.source.clone()]);', 'Self::wait(&[self.source.clone()]).await;')
edit(NAMES[1], 'pump::Pump::current().poll(&[source]);', 'pump::Pump::current().poll(&[source]).await;', 3)
edit(NAMES[1], 'pump::Pump::current().poll(&[ready]);', 'pump::Pump::current().poll(&[ready]).await;')
edit(NAMES[2], 'impl pump::Progress for Exchange {\n    fn progress', '''impl pump::Progress for Exchange {
    fn pending(&self) -> bool {
        !self.cancelled.get() && (self.work.borrow().is_some() || self.request.borrow().is_some())
    }

    fn progress''')
edit(NAMES[2], '''        // Bound immediate metadata/body state transitions per poll; canonical
        // waits suspend the caller while the node keeps the original owners.''', '''        // Bound immediate transitions per driver poll. Pending canonical imports
        // register the real driver waker; no callback blocks a sibling export.''')
edit(NAMES[2], '        }\n    }\n}\nimpl Drop for Exchange', '''        }
        // Four immediate completions may leave further real work (for example
        // draining a body). Reschedule that bounded work, never invent readiness.
        context.waker().wake_by_ref();
    }
}
impl Drop for Exchange''')
edit(NAMES[3], '''// These exact shared owners, cap and readiness machinery are not a second
// provider, runtime budget, cache or executor. The existing .NET source/output
// stays unchanged; each selected component has only this one instance.''', '''// Preserve the original authority owners and finite resource cap. Rust async
// exports use a callback-safe readiness driver; the CLR's blocking pump and
// its independently qualified source remain unchanged.''')
edit(NAMES[3], '../../../sdk/dotnet-guest/runtime/http/pump.rs', '../../../sdk/wasi-http-runtime/pump.rs')
edit(NAMES[3], '../../../sdk/dotnet-guest/runtime/http/timer.rs', '../../../sdk/wasi-http-runtime/timer.rs')
edit(NAMES[3], 'poll::Pollable::poll(inputs)', 'poll::Pollable::poll(inputs).await')
edit(NAMES[3], 'pump::Pump::current().drain_retired();', 'pump::Pump::current().drain_retired().await;')
edit(NAMES[4], '[dependencies]\n', '''[features]
# Selected only by the standard HTTP adapter recipe, not other smoke products.
rust-wasi-http-cooperative = ["wit-bindgen/async-spawn", "wit-bindgen/inter-task-wakeup"]

[dependencies]
''')
with (ROOT/NAMES[4]).open('a') as stream:
    stream.write('''
[[example]]
name = "rust-http-pump-probe"
path = "examples/rust_http_pump_probe.rs"
crate-type = ["cdylib"]
required-features = ["rust-wasi-http-cooperative"]
test = false
bench = false
doc = false

[[example]]
name = "rust-http-pump-control"
path = "examples/rust_http_pump_control.rs"
test = false
bench = false
doc = false
''')
edit(NAMES[5], "for name in ('owner', 'pump', 'quota', 'timer'))", "for name in ('owner', 'quota'))")
edit(NAMES[5], "'-p', 'latent-toolchain-smoke', '--example', EXAMPLE,", "'-p', 'latent-toolchain-smoke', '--example', EXAMPLE,\n            '--features', 'rust-wasi-http-cooperative',")
edit(NAMES[6], '''checksum = "b85a987ab61d365382d25c7d47e26edd48941b3bf6e3fbf76eff918bc71dab06"
dependencies = [
 "bitflags",
''', '''checksum = "b85a987ab61d365382d25c7d47e26edd48941b3bf6e3fbf76eff918bc71dab06"
dependencies = [
 "bitflags",
 "futures",
''')
s=(ROOT/'sdk/dotnet-guest/runtime/http/timer.rs').read_text()
s=s.replace('pinned CLR event loop', 'callback-safe Rust driver')
s=s.replace('impl pump::Progress for Timer {', '''impl pump::Progress for Timer {
    fn pending(&self) -> bool { self.work.borrow().is_some() }
''')
(ROOT/NAMES[9]).write_text(s)
OUT=Path(os.environ['RUNNER_TEMP'])/'pr1657-pump'; OUT.mkdir()
(OUT/'files.json').write_text(json.dumps(NAMES,indent=2)+'\n')
print('Rust adapter patch prepared; CLR sources and signed original programme unchanged.')
