"""Temporary closed numeric observations; no readiness/authority changes."""
from pathlib import Path


def replace(path, old, new):
    p = Path(path)
    data = p.read_text()
    assert data.count(old) == 1, (path, old)
    p.write_text(data.replace(old, new))


path = 'crates/latent-wasmtime/src/host/streaming_http/upload.rs'
replace(path, 'let body = match upload {', 'eprintln!("LSF1657 finish-begin {}", target.rep());\n            let body = match upload {')
replace(path, '            access.with(|mut access| {\n                let mut store = access.as_context_mut();\n                checkpoint(&mut store)?;\n                let result = body.and_then', '            eprintln!("LSF1657 finish-ready {} {}", target.rep(), u32::from(body.is_ok()));\n            access.with(|mut access| {\n                let mut store = access.as_context_mut();\n                checkpoint(&mut store)?;\n                let result = body.and_then')
replace(path, '                    let result = wit::Response {', '                    eprintln!("LSF1657 finish-return {} {}", target.rep(), rep);\n                    let result = wit::Response {')
path = 'crates/vendor/wasmtime/src/runtime/component/concurrent.rs'
replace(path, '        log::trace!("waitable check for {guest_thread:?}; set {:?}", params.set);', '        log::trace!("waitable check for {guest_thread:?}; set {:?}", params.set);\n        if matches!(check, WaitableCheck::Wait) {\n            std::eprintln!("LSF1657 canonical-wait {} {} {}", guest_thread.task.rep(), guest_thread.thread.rep(), params.set.rep());\n        }')
replace(path, '        waitable.on_delivery(store, self, event)?;', '        std::eprintln!("LSF1657 canonical-deliver {} {} {} {}", guest_task.rep(), set.rep(), handle, event.parts().0);\n        waitable.on_delivery(store, self, event)?;')
path = 'crates/latent-wasmtime/src/host/streaming_http/body.rs'
replace(path, 'let rep = source.rep();', 'let rep = source.rep();\n                eprintln!("LSF1657 read-begin {} {}", rep, maximum);')
replace(path, 'let result = value.read(maximum as usize).await;', 'let result = value.read(maximum as usize).await;\n                        eprintln!("LSF1657 read-ready {} {}", rep, u32::from(result.is_ok()));')
replace(path, 'let chunk = pending.reservation.rep();', 'let chunk = pending.reservation.rep();\n                        eprintln!("LSF1657 read-return {} {}", rep, chunk);')
replace(path, 'checkpoint(&mut store)?;\n                    let result = store\n', 'checkpoint(&mut store)?;\n                    eprintln!("LSF1657 chunk-bytes {}", value.rep());\n                    let result = store\n')
path = 'tools/rust_thread_http_sibling_node.py'
replace(path, '        process.close()\n', '        node.drain()\n        import re\n        trace = [line.decode("ascii") for line in bytes(node.buffers[1]).splitlines()\n                 if re.fullmatch(rb"LSF1657 [a-z-]+(?: [0-9]+){1,4}", line)]\n        require(len(trace) <= 256, "closed-progress-observation-bound")\n        write_json(output / "http-progress.json", trace)\n        process.close()\n')
