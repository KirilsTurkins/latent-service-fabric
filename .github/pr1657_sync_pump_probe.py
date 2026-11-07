"""Exercise synchronous observation while the actual async driver is pending."""
from pathlib import Path
import os,subprocess

def edit(name,before,after):
 p=Path(name);s=p.read_text();assert s.count(before)==1,(name,before);p.write_text(s.replace(before,after))
probe='tools/toolchain-smoke/examples/rust_http_pump_probe.rs'
edit(probe,'            export drain: async func();','            export drain: async func();\n            export poke: func();')
edit(probe,'impl Guest for Control {','impl Guest for Control {\n    fn poke() { pump::Pump::current().step(); }')
host='tools/toolchain-smoke/examples/rust_http_pump_control.rs'
edit(host,'    let engine = Engine::new(&config)?;', '''    if std::env::args().any(|arg| arg == "--native-profile") {
        config.wasm_component_model_more_async_builtins(true)
            .wasm_component_model_threading(true)
            .wasm_component_model_async_stackful(true);
    }
    let engine = Engine::new(&config)?;''')
edit(host,'    let drain = instance.get_typed_func::<(), ()>(&mut store, "drain")?;', '''    let drain = instance.get_typed_func::<(), ()>(&mut store, "drain")?;
    let poke = instance.get_typed_func::<(), ()>(&mut store, "poke")?;''')
edit(host,'            let mut second_returned = false;', '''            let mut second_returned = false;
            let mut observation = Box::pin(poke.call_concurrent(access, ()));
            let mut observed = false;''')
edit(host,'                            gates[1].release();', '''                            if !observed {
                                match observation.as_mut().poll(cx) {
                                    Poll::Ready(result) => { result?; observed = true; }
                                    Poll::Pending => return Poll::Pending,
                                }
                            }
                            gates[1].release();''')
out=Path(os.environ['RUNNER_TEMP'])/'pr1657-sync-pump';out.mkdir()
for name in (probe,host):
 subprocess.run(['rustfmt','--edition','2021','--config','skip_children=true',name],check=True)
 target=out/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(Path(name).read_bytes())
(out/'probe-source.patch').write_bytes(subprocess.check_output(['git','diff','--binary']))
