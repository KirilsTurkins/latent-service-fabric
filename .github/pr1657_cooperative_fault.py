"""Disposable numeric fault observation for the exact recompiled adapter."""
from pathlib import Path
import os, runpy, subprocess
runpy.run_path('.github/pr1657_cooperative_graph.py')
def replace(path, old, new):
    p=Path(path);s=p.read_text();assert s.count(old)==1,(path,old);p.write_text(s.replace(old,new))
replace('crates/latent-wasmtime/src/config/engine.rs',
    '        engine_config.wasm_backtrace_max_frames(backtrace_limit);',
    '''        #[cfg(feature = "development-rust-http-combined")]
        let backtrace_limit = if matches!(self.native_thread_profile, Some(NativeThreadProfile::RustContext40CombinedHttpDiagnosticV1)) {
            Some(std::num::NonZeroUsize::new(16).expect("fixed diagnostic frame cap"))
        } else { backtrace_limit };
        engine_config.wasm_backtrace_max_frames(backtrace_limit);''')
replace('crates/latent-wasmtime/src/backend.rs',
    '        #[cfg(feature = "rust-thread-trap-diagnostic")]\n        if let Err(error) = &call_result {',
    '''        #[cfg(feature = "development-rust-http-combined")]
        if let Err(error) = &call_result {
            if matches!(&runtime.threading, crate::component_threading::Authentication::RustCombinedHttpVerified(_)) {
                if let Some(trap) = error.downcast_ref::<wasmtime::Trap>() {
                    eprintln!("LSF-COOPERATIVE-TRAP:{}", *trap as u8);
                }
                if let Some(trace) = error.downcast_ref::<wasmtime::WasmBacktrace>() {
                    for (ordinal, frame) in trace.frames().iter().take(16).enumerate() {
                        eprintln!("LSF-COOPERATIVE-FAULT:{ordinal}:{}:{}:{}", frame.func_index(),
                            frame.module_offset().unwrap_or(usize::MAX),
                            frame.func_offset().unwrap_or(usize::MAX));
                    }
                }
            }
        }
        #[cfg(feature = "rust-thread-trap-diagnostic")]
        if let Err(error) = &call_result {''')
replace('tools/rust_thread_http_sibling_node.py', '    finally:\n        process.close()',
    '''    finally:
        try:
            import re
            node.drain()
            markers = [line.decode('ascii') for line in bytes(node.buffers[1]).splitlines()
                       if re.fullmatch(rb'LSF-COOPERATIVE-(?:TRAP:[0-9]{1,3}|FAULT:[0-9]{1,2}:[0-9]{1,10}:[0-9]{1,20}:[0-9]{1,20})', line)]
            write_json(output / 'cooperative-fault.json', {'markers': markers[:17], 'diagnosticOnly': True})
            write_json(output / 'cooperative-terminal-peer.json', peer.observation())
        except (OSError, ValueError, TypeError, WorkflowError):
            pass
        process.close()''')
out=Path(os.environ['RUNNER_TEMP'])/'pr1657-cooperative'
(out/'diagnostic-source.patch').write_bytes(subprocess.check_output(['git','diff','--binary']))
print('Numeric-only original trap frames installed on the exact authenticated graph; no guest text or native addresses.')
