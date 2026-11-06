from pathlib import Path
import runpy
runpy.run_path('.github/pr1657_pressure_patch.py')
p=Path('crates/latent-http/src/streaming/exchange.rs'); s=p.read_text()
needle='    let limits = inner.streaming.expect("stream profile");\n'
assert s.count(needle)==1
s=s.replace(needle,'''    let diagnostic_request = match input.destination.url.path() {
        "/conformance/hold/headers" => 1,
        "/conformance/body/partial" => 2,
        "/conformance/json" => 3,
        _ => 0,
    };
    eprintln!("LSF-COMBINED-HTTP:{}:1", diagnostic_request);
'''+needle)
for before,after in [
 ('    let ready = admission.wait().await?;', '    let ready = admission.wait().await?;\n    eprintln!("LSF-COMBINED-HTTP:{}:2", diagnostic_request);'),
 ('    let opening = async {', '    eprintln!("LSF-COMBINED-HTTP:{}:3", diagnostic_request);\n    let opening = async {'),
 ('        let answers = inner', '        eprintln!("LSF-COMBINED-HTTP:{}:4", diagnostic_request);\n        let answers = inner'),
 ('        let mut socket = network::connect_with_reason(', '        eprintln!("LSF-COMBINED-HTTP:{}:5", diagnostic_request);\n        let mut socket = network::connect_with_reason('),
 ('        let Network::Http(connection) = socket.resource() else {', '        eprintln!("LSF-COMBINED-HTTP:{}:6", diagnostic_request);\n        let Network::Http(connection) = socket.resource() else {'),
 ('    Ok(Box::new(Upload {', '    eprintln!("LSF-COMBINED-HTTP:{}:7", diagnostic_request);\n    Ok(Box::new(Upload {')]:
    assert s.count(before)==1,before
    s=s.replace(before,after)
p.write_text(s)
p=Path('tools/rust_thread_http_sibling_node.py');s=p.read_text()
needle='    finally:\n        process.close()'
assert s.count(needle)==1
s=s.replace(needle,'''    finally:
        try:
            import re
            node.drain()
            write_json(output / 'terminal-peer.json', peer.observation())
            markers = [line.decode('ascii') for line in bytes(node.buffers[1]).splitlines()
                       if re.fullmatch(rb'LSF-COMBINED-(?:ROOT:[0-9]{1,4}:[0-9]{1,3}|PRESSURE:[0-9]{1,2}:[0-9]{1,4}:[0-9]{1,4}|HTTP:[0-9]:[0-9])', line)]
            write_json(output / 'closed-stage-observation.json', {'markers': markers[:128], 'diagnosticOnly': True})
        except (OSError, ValueError, TypeError, WorkflowError):
            pass
        process.close()''')
p.write_text(s)
