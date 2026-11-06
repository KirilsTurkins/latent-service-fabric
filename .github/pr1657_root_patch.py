from pathlib import Path
import json, re, os
root=Path.cwd()
# Source literals only; neither private error text nor guest inputs are exported.
rows=[]
seen=set()
for base in ('crates/vendor/wasmtime/src/runtime/component','crates/latent-wasmtime/src/host', 'crates/latent-wasmtime/src/native_stacks.rs', 'crates/latent-wasmtime/src/native_tables.rs'):
 p=root/base
 for path in sorted(p.rglob('*.rs')) if p.is_dir() else [p]:
  text=path.read_text()
  for match in re.finditer(r'"([^"\\\n]{1,192})"',text):
   value=match[1]
   if not value.isascii() or value in seen or '{' in value or '}' in value: continue
   seen.add(value)
   rows.append({'code':len(rows)+1,'source':path.relative_to(root).as_posix(),'line':text.count('\n',0,match.start())+1,'literal':value})
assert 0<len(rows)<4096
out=Path(os.environ['RUNNER_TEMP'])/'rust-combined-root'
out.mkdir(exist_ok=True)
(out/'source-error-vocabulary.json').write_text(json.dumps(rows,indent=2)+'\n')
code='''
        #[cfg(feature = "development-rust-http-combined")]
        if let Err(error) = &call_result {
            if matches!(&runtime.threading, crate::component_threading::Authentication::RustCombinedHttpVerified(_)) {
                use std::fmt::Write as _;
                use zeroize::Zeroize as _;
                struct Bounded<'a> { bytes: &'a mut [u8], used: usize }
                impl std::fmt::Write for Bounded<'_> {
                    fn write_str(&mut self, value: &str) -> std::fmt::Result {
                        if value.len() > self.bytes.len() - self.used { return Err(std::fmt::Error); }
                        self.bytes[self.used..self.used + value.len()].copy_from_slice(value.as_bytes());
                        self.used += value.len();
                        Ok(())
                    }
                }
                const MESSAGES: &[&str] = &__MESSAGES__;
                let mut bytes = [0_u8; 192];
                let mut sink = Bounded { bytes: &mut bytes, used: 0 };
                let complete = write!(&mut sink, "{}", error.root_cause()).is_ok();
                let code = if complete {
                    MESSAGES.iter().position(|value| value.as_bytes() == &sink.bytes[..sink.used]).map_or(0, |index| index + 1)
                } else { 0 };
                bytes.zeroize();
                let flags = u8::from(error.is::<wasmtime::Trap>())
                    | (u8::from(error.is::<latent_core::BudgetError>()) << 1)
                    | (u8::from(error.is::<latent_core::PlatformError>()) << 2)
                    | (u8::from(error.is::<wasmtime::WasmtimeBug>()) << 3)
                    | (u8::from(error.is::<wasmtime::component::ResourceTableError>()) << 4)
                    | (u8::from(error.is::<std::io::Error>()) << 5);
                eprintln!("LSF-COMBINED-ROOT:{code}:{flags}");
            }
        }
'''.replace('__MESSAGES__',json.dumps([r['literal'] for r in rows]))
p=root/'crates/latent-wasmtime/src/backend.rs'
s=p.read_text();needle='        #[cfg(feature = "rust-thread-trap-diagnostic")]\n        if let Err(error) = &call_result {'
assert s.count(needle)==1
p.write_text(s.replace(needle,code+needle))
p=root/'tools/rust_thread_http_sibling_node.py'
s=p.read_text();needle='        retain_refused_call(client, node, peer, process, output, deadline)\n        raise'
assert s.count(needle)==1
s=s.replace(needle,'''        retain_refused_call(client, node, peer, process, output, deadline)
        try:
            import re
            node.drain()
            markers = [line.decode('ascii') for line in bytes(node.buffers[1]).splitlines()
                       if re.fullmatch(rb'LSF-COMBINED-ROOT:[0-9]{1,4}:[0-9]{1,3}', line)]
            write_json(output / 'closed-root-observation.json', {'markers': markers[:8], 'diagnosticOnly': True})
        except (OSError, ValueError, TypeError, WorkflowError):
            pass
        raise''')
p.write_text(s)
print('static source messages',len(rows))
