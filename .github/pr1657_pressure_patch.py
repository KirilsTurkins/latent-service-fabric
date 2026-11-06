from pathlib import Path
import runpy
runpy.run_path('.github/pr1657_root_vocabulary.py')
# Separate diagnostic only: test a finite operator Native-count selection.
# Original signed guest memory, fuel, wall deadline, requests and peer gates stay fixed.
p=Path('tools/rust_thread_http_combined_node.py')
s=p.read_text(); needle="    activation['nativeThreads'] = True\n"
assert s.count(needle)==1
p.write_text(s.replace(needle,needle+"    activation['limits']['nativeOwners'] = 12\n"))
p=Path('crates/latent-wasmtime/src/native_stacks/workers.rs')
s=p.read_text();needle='.map_err(|_| wasmtime::Error::msg("native-worker-original-native-limit"))?;'
assert s.count(needle)==1
s=s.replace(needle,''' .map_err(|error| {
                let cause = match error.message.as_str() {
                    "runtime-owner-limit" => 1,
                    "runtime-token" => 2,
                    "runtime-admission-closed" => 3,
                    _ => 0,
                };
                eprintln!("LSF-COMBINED-PRESSURE:{}:{}:{}", cause,
                    self.runtime.snapshot().owners[6], self.active.load(Ordering::Acquire));
                wasmtime::Error::msg("native-worker-original-native-limit")
            })?;''')
p.write_text(s)
p=Path('crates/latent-wasmtime/src/native_stacks.rs')
s=p.read_text();needle='        Ok(stack)\n'
assert s.count(needle)==1
s=s.replace(needle,'''        eprintln!("LSF-COMBINED-PRESSURE:9:{}:{}", stack.context.runtime.snapshot().owners[6],
            stack.context.active.load(Ordering::Acquire));
        Ok(stack)
''')
p.write_text(s)
p=Path('tools/rust_thread_http_sibling_node.py')
s=p.read_text().replace("rb'LSF-COMBINED-ROOT:[0-9]{1,4}:[0-9]{1,3}'", "rb'LSF-COMBINED-(?:ROOT:[0-9]{1,4}:[0-9]{1,3}|PRESSURE:[0-9]{1,2}:[0-9]{1,4}:[0-9]{1,4})'")
s=s.replace("'markers': markers[:8]", "'markers': markers[:64]")
p.write_text(s)
print('Diagnostic operator nativeOwners=12; original guest budgets unchanged')
