"""Captured ordinary Rust clients and two default pools for a gated witness.

This prepares source only. It neither selects an unqualified component route
nor claims that compilation, HTTP, sibling progress or a signed call succeeded.
"""
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import cargo_native_authoring as authoring
from tools import rust_standard_logging_inputs as standard
from tools import rust_standard_thread_profile as thread
from tools import rust_wasi_http_runtime_fixture as http
from tools.application_dependencies import LOCK
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, canonical, digest, inventory, read_file, read_json, snapshot, write_json


SIBLING = r'''
// Developer-owned fixture code; Waki and Golem remain unchanged dependencies.
// The peer holds this partial body until the other pool's request is pending.
pub fn thread_http_sibling(endpoint: &str) -> Result<String, String> {
    let partial = format!("{endpoint}/conformance/body/partial");
    let client = golem_wasi_http::Client::new();
    let response = client.get(partial.as_str()).send().map_err(|e| e.to_string())?;
    if response.status().as_u16() != 200 { return Err("sibling partial status".into()); }
    // Golem 0.2.0's Read implementation takes its body on each call, so
    // read_to_end panics on a subsequent read. Its consuming bytes() API
    // retains the original stream through all chunks and actual EOF.
    let body = response.bytes().map_err(|e| e.to_string())?;
    if body.len() != 4109 || !body.starts_with(b"first-second-")
        || !body[13..].iter().all(|byte| *byte == b'x') {
        return Err("sibling partial body".into());
    }
    drop(body);
    // The second JSON request is issued only after the first was received,
    // decoded and checked by the unchanged ordinary Golem client path.
    request("golem", "repeat", &format!("{endpoint}/conformance/json"))
}
'''

ENTRY = r'''    if let Some(endpoint) = name.strip_prefix("thread-http|") {
        let endpoint = endpoint.to_owned();
        let held_url = format!("{endpoint}/conformance/hold/headers");
        let first = futures_executor::ThreadPool::new().map_err(|e| e.to_string())?;
        let second = futures_executor::ThreadPool::new().map_err(|e| e.to_string())?;
        let (started_send, started_receive) = std::sync::mpsc::channel::<()>();
        let (held_send, held_receive) = std::sync::mpsc::channel::<Result<String, String>>();
        let (sibling_send, sibling_receive) = std::sync::mpsc::channel::<Result<String, String>>();
        first.spawn_ok(async move {
            let _ = started_send.send(());
            let value = __ALPHA__::request("waki", "json", &held_url);
            let _ = held_send.send(value);
        });
        started_receive.recv().map_err(|e| e.to_string())?;
        second.spawn_ok(async move {
            let value = __DELTA__::thread_http_sibling(&endpoint);
            let _ = sibling_send.send(value);
        });
        let sibling = sibling_receive.recv().map_err(|e| e.to_string())??;
        let held = held_receive.recv().map_err(|e| e.to_string())??;
        drop(first);
        drop(second);
        return Ok(format!("thread-http:{held}:{sibling}"));
    }
'''


def prepare(output: Path, nonce: str):
    app, outside, specs = http.prepare(output, nonce)
    project = read_json(app / 'capsule-project.json')
    original_limits = dict(project['limits'])
    require(original_limits['outboundRequests'] == 8
            and original_limits['memoryBytes'] == 16_777_216
            and original_limits['cpuFuel'] == 1_000_000_000
            and original_limits['wallTimeLimitMillis'] == 5000,
            'rust-thread-http-original-http-budget')
    project['runtimeProfile'] = standard.THREAD
    (app / 'capsule-project.json').write_bytes(canonical(project))

    world_path = app / 'wit/world.wit'
    world = read_file(world_path)
    marker = b'world service {'
    require(world.count(marker) == 1
            and b'latent:runtime-native/threads@0.1.0' not in world
            and b'latent:clock/wall@0.1.0' not in world,
            'rust-thread-http-original-world')
    additions = (b'\n    import latent:runtime-native/threads@0.1.0;'
                 b'\n    import latent:clock/wall@0.1.0;')
    world_path.write_bytes(world.replace(marker, marker + additions, 1))
    native_wit = app / 'wit/deps/native-runtime/package.wit'
    native_wit.parent.mkdir(parents=True, exist_ok=False)
    native_wit.write_bytes(read_file(ROOT / 'wit/platform/native-runtime/package.wit'))

    source_path = app / 'src/lib.rs'
    source = read_file(source_path)
    binding = b'with: {'
    require(source.count(binding) == 1, 'rust-thread-http-original-bindings')
    extra = (b'with: {"latent:runtime-native/threads@0.1.0": generate,'
             b'"latent:clock/wall@0.1.0": generate,')
    source = source.replace(binding, extra, 1)
    marker = b'    let fields: Vec<&str> = name.splitn(4, \'|\').collect();'
    require(source.count(marker) == 1, 'rust-thread-http-original-dispatch')
    alpha, delta = (spec['package'].replace('-', '_') for spec in specs)
    entry = ENTRY.replace('__ALPHA__', alpha).replace('__DELTA__', delta).encode()
    source_path.write_bytes(source.replace(marker, entry + marker, 1))

    developer = outside[1] / 'src/lib.rs'
    original = read_file(developer)
    require(original == http.LIBRARY.encode(), 'rust-thread-http-original-developer-crate')
    developer.write_bytes(original + SIBLING.encode())
    require(read_json(app / 'capsule-project.json')['limits'] == original_limits,
            'rust-thread-http-budget-changed')
    return app, outside, specs


def capture(app: Path, outside: list[Path], specs: list[dict], cargo: Path) -> dict:
    # Normal captured dependencies, including the maintained executor port;
    # this does not grant authority, run a client or open the builder gate.
    authoring.author(app, 'add', identity=thread.EXECUTOR, version=thread.EXECUTOR_VERSION,
                     target='cfg(target_arch = "wasm32")', features=['thread-pool'], cargo=cargo)
    result = http.capture(app, outside, specs, cargo)
    lock = read_json(app / LOCK, 8 * 1024 * 1024)
    selected = [row for row in lock['artifacts']
                if row['metadata'].get('package') == thread.EXECUTOR]
    require(len(selected) == 1 and selected[0]['metadata'].get('version') == thread.EXECUTOR_VERSION
            and selected[0]['metadata'].get('vendorChecksum', {}).get('package')
                == thread.EXECUTOR_ARCHIVE_SHA256,
            'rust-thread-http-authentic-executor-capture')
    return {**result, 'runtimeArtifact': selected[0]['id'], 'sourceOnly': True,
            'actualGuestExecuted': False, 'siblingProgressQualified': False}


def main():
    import argparse
    import secrets
    from tools import rust_owned_thread_fixture as owned
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cargo', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    nonce = secrets.token_hex(8)
    app, outside, specs = prepare(args.output, nonce)
    result = capture(app, outside, specs, args.cargo)
    receipt = {**result, 'nonce': nonce, 'sourceDigest': digest(inventory(snapshot(app))),
        'publicExport': owned.PUBLIC, 'postReturnExport': owned.POST,
        'ordinaryThreadPoolQualified': False}
    write_json(args.report, receipt)


if __name__ == '__main__':
    main()
