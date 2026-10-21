"""Unseen captured crates using two unchanged published ordinary HTTP factories.

No application transport, executor, callback adapter or library patch is supplied.
The normal builder alone selects the separately prepared standard-WASI backend.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil

from tools import cargo_native_authoring as authoring, rust_application_dependencies as native
from tools import rust_dependency_authoring as review, rust_wasi_http_fixture as original
from tools.application_dependencies import LOCK
from tools.phase2_operator_process import require
from tools.rust_capsule_project import (ROOT, canonical, create, digest, fresh, inventory,
    read_file, read_json, snapshot)
from tools.rust_wasi_http_profile import AUTHORITY

SERVICE = 'rust-wasi-http'
PACKAGE = 'outside-wasi-http-'
LIBRARY = r'''use std::io::Read;
use std::error::Error as _;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::Duration;
static ENTRIES: AtomicU32 = AtomicU32::new(0);

fn error_record(phase: &str, error: &(impl std::fmt::Debug + std::fmt::Display),
    public: serde_json::Value) -> String {
    let display = error.to_string();
    let debug = format!("{error:?}");
    let display_bound: String = display.chars().take(512).collect();
    let debug_bound: String = debug.chars().take(1024).collect();
    let truncated = display_bound != display || debug_bound != debug;
    let value = serde_json::json!({"phase": phase, "display": display_bound,
        "debug": debug_bound, "displayBytes": display.len(), "debugBytes": debug.len(),
        "truncated": truncated, "public": public});
    format!("library-error:{value}")
}
macro_rules! waki_error {
    ($phase:expr, $error:expr) => {{
        let error = $error;
        let code = error.downcast_ref::<waki::ErrorCode>().map(|v| format!("{v:?}"));
        let json = error.downcast_ref::<serde_json::Error>().is_some();
        error_record($phase, &error,
            serde_json::json!({"typedWasiErrorCode": code, "serdeJsonError": json}))
    }};
}
fn golem_error(phase: &str, error: golem_wasi_http::Error) -> String {
    let mut source = error.source();
    let mut json = false;
    for _ in 0..8 {
        if let Some(value) = source {
            json |= value.downcast_ref::<serde_json::Error>().is_some();
            source = value.source();
        } else { break; }
    }
    error_record(phase, &error, serde_json::json!({"isBuilder": error.is_builder(),
        "isRequest": error.is_request(), "isBody": error.is_body(), "isDecode": error.is_decode(),
        "isTimeout": error.is_timeout(), "isStatus": error.is_status(), "serdeJsonError": json,
        "sourceDisplay": error.source().map(|v| v.to_string())}))
}
fn domain(status: u16, value: serde_json::Value) -> Result<String, String> {
    if status == 404 || status == 500 {
        if value["status"].as_u64() != Some(status as u64)
            || value["message"].as_str() != Some("domain-error") { return Err("bad error domain".into()); }
        return Ok(format!("{status}:domain-error"));
    }
    if status != 200 || value["id"].as_u64() != Some(7)
        || value["name"].as_str() != Some("caf\u{e9}")
        || value["items"][0].as_str() != Some("first")
        || value["items"][1].as_str() != Some("\u{3bb}")
        || value["empty"].as_str() != Some("") { return Err("bad success domain".into()); }
    Ok(format!("{status}:domain:7:caf\u{e9}:first|\u{3bb}:"))
}
fn echo(status: u16, value: serde_json::Value) -> Result<String, String> {
    if status != 200 || value["method"].as_str() != Some("POST")
        || value["bodyBase64"].as_str() != Some("AAECAw==")
        || value["customHeaderBase64"].as_str() != Some("cnVzdC1jbGllbnQ=")
        || value["contentLengthPresent"].as_bool() != Some(true)
        || value["contentTypePresent"].as_bool() != Some(false) {
        return Err("bad binary request conversion".into());
    }
    Ok("200:echo:POST:AAECAw==".into())
}
fn prefix(bytes: &[u8]) -> Result<String, String> {
    if bytes != b"firs" { return Err("bad partial body".into()); }
    Ok("200:partial:4".into())
}
fn waki(mode: &str, url: &str) -> Result<String, String> {
    let client = waki::Client::new();
    if mode == "capacity" {
        let mut held = Vec::new();
        for _ in 0..9 {
            match client.get(url).send() {
                Ok(response) => held.push(response),
                Err(error) => {
                    let accepted = held.len();
                    drop(held);
                    return Ok(format!("capacity:{accepted}:{}", waki_error!("send", error)));
                }
            }
        }
        drop(held);
        return Err("original resource envelope did not refuse nine held responses".into());
    }
    let mut request = if mode == "post" || mode == "uncertain-post" {
        client.post(url).header("x-conformance", "rust-client").body(vec![0u8, 1, 2, 3])
    } else { client.get(url) };
    if mode == "reserved-auth" { request = request.header("authorization", "caller-field"); }
    if mode == "reserved-cookie" { request = request.header("cookie", "fixture=local"); }
    if mode == "timeout-option" { request = request.connect_timeout(Duration::from_millis(25)); }
    let response = match request.send() { Ok(v) => v, Err(error) => return Ok(waki_error!("send", error)) };
    let status = response.status_code();
    if mode == "trap-open" { panic!("controlled ordinary HTTP root trap"); }
    if mode == "root-drop" { drop(response); return Ok("root-dropped-body".into()); }
    if mode == "early-drop" {
        let bytes = match response.chunk(4) { Ok(Some(v)) => v,
            Ok(None) => return Err("missing partial body".into()),
            Err(error) => return Ok(waki_error!("partial-read", error)) };
        drop(response); return prefix(&bytes);
    }
    if mode == "redirect" { drop(response); return Ok(format!("{status}:redirect-stopped")); }
    if mode == "post" {
        return match response.json::<serde_json::Value>() {
            Ok(v) => echo(status, v), Err(error) => Ok(waki_error!("json", error)) };
    }
    if mode == "json" || mode == "status" || mode == "malformed-json" {
        return match response.json::<serde_json::Value>() {
            Ok(v) => domain(status, v), Err(error) => Ok(waki_error!("json", error)) };
    }
    match response.body() {
        Ok(bytes) => Ok(format!("{status}:bytes:{}", bytes.len())),
        Err(error) => Ok(waki_error!("body", error)),
    }
}
fn golem(mode: &str, url: &str) -> Result<String, String> {
    let client = golem_wasi_http::Client::new();
    if mode == "capacity" {
        let mut held = Vec::new();
        for _ in 0..9 {
            match client.get(url).send() {
                Ok(response) => held.push(response),
                Err(error) => {
                    let accepted = held.len();
                    drop(held);
                    return Ok(format!("capacity:{accepted}:{}", golem_error("send", error)));
                }
            }
        }
        drop(held);
        return Err("original resource envelope did not refuse nine held responses".into());
    }
    let mut request = if mode == "post" || mode == "uncertain-post" {
        client.post(url).header("x-conformance", "rust-client").body(vec![0u8, 1, 2, 3])
    } else { client.get(url) };
    if mode == "reserved-auth" { request = request.header("authorization", "caller-field"); }
    if mode == "reserved-cookie" { request = request.header("cookie", "fixture=local"); }
    if mode == "timeout-option" { request = request.timeout(Duration::from_millis(25)); }
    let mut response = match request.send() { Ok(v) => v, Err(error) => return Ok(golem_error("send", error)) };
    let status = response.status().as_u16();
    if mode == "trap-open" { panic!("controlled ordinary HTTP root trap"); }
    if mode == "root-drop" { drop(response); return Ok("root-dropped-body".into()); }
    if mode == "early-drop" {
        let mut bytes = [0u8; 4];
        let count = match response.read(&mut bytes) { Ok(v) => v,
            Err(error) => return Ok(error_record("partial-read", &error,
                serde_json::json!({"ioErrorKind": format!("{:?}", error.kind())}))) };
        if count != 4 {
            return Err("missing partial body".into());
        }
        drop(response); return prefix(&bytes);
    }
    if mode == "redirect" { drop(response); return Ok(format!("{status}:redirect-stopped")); }
    if mode == "status" && !response.error_for_status_ref().err().is_some_and(|e| e.is_status()
        && e.status().map(|s| s.as_u16()) == Some(status)) {
        return Err("missing real status error".into());
    }
    if mode == "post" {
        return match response.json::<serde_json::Value>() {
            Ok(v) => echo(status, v), Err(error) => Ok(golem_error("json", error)) };
    }
    if mode == "json" || mode == "status" || mode == "malformed-json" {
        return match response.json::<serde_json::Value>() {
            Ok(v) => domain(status, v), Err(error) => Ok(golem_error("json", error)) };
    }
    match response.bytes() {
        Ok(bytes) => Ok(format!("{status}:bytes:{}", bytes.len())),
        Err(error) => Ok(golem_error("body", error)),
    }
}
pub fn request(client: &str, mode: &str, url: &str) -> Result<String, String> {
    if ENTRIES.fetch_add(1, Ordering::SeqCst) != 0 { return Err("stale outside client state".into()); }
    let call = match client { "waki" => waki, "golem" => golem, _ => return Err("unknown client".into()) };
    let result = if mode == "repeat" {
        let first = call("json", url)?;
        let second = call("json", url)?;
        if first != second { return Err("different repeated domain".into()); }
        format!("repeat:{first}")
    } else { call(mode, url)? };
    Ok(format!("fresh:{client}:{result}"))
}
'''


def specification(nonce: str) -> list[dict]:
    require(type(nonce) is str and re.fullmatch('[0-9a-f]{16}', nonce) is not None,
        'rust-http-runtime-nonce')
    return [{'package': PACKAGE + label + '-' + nonce,
        'version': f'{index}.{int(nonce[:4],16)+1}.{int(nonce[4:8],16)+1}', 'alias': label}
        for index, label in enumerate(('alpha', 'delta'), 1)]


def prepare(output: Path, nonce: str):
    specs = specification(nonce)
    root = fresh(output)
    app = create(root/'application', 'greeting', name=SERVICE)
    initial = snapshot(app)
    outside = []
    for spec in specs:
        source = fresh(root/('outside-'+spec['alias']))
        (source/'src').mkdir()
        manifest = (f'[package]\nname="{spec["package"]}"\nversion="{spec["version"]}"\n'
            'edition="2021"\nlicense="Apache-2.0"\n[dependencies]\n'
            'waki={version="=0.5.1",features=["json"]}\n'
            'golem-wasi-http={version="=0.2.0",features=["json"]}\nserde_json="=1.0.149"\n')
        (source/'Cargo.toml').write_bytes(manifest.encode())
        (source/'src/lib.rs').write_bytes(LIBRARY.encode())
        outside.append(source)
    marker = b'    let name = name.trim();'
    require(initial['src/lib.rs'].count(marker) == 1, 'rust-http-runtime-original-template')
    calls = '\n'.join(f'            "{s["alias"]}" => {s["package"].replace("-","_")}::request(client,mode,url),'
        for s in specs)
    code = ('''    let fields: Vec<&str> = name.splitn(4, '|').collect();
    if let [library, client, mode, url] = fields.as_slice() {
        return match *library {
''' + calls + '''
            _ => Err("unknown outside library".into()),
        };
    }
''').encode()
    (app/'src/lib.rs').write_bytes(initial['src/lib.rs'].replace(marker, code+marker, 1))
    # All dependencies are declared; selection grants no authority. The actual
    # normal componentizer must consume these three through the selected port.
    world = initial['wit/world.wit']
    require(world.count(b'world service {') == 1, 'rust-http-runtime-original-world')
    imports = b''.join(b'\n    import '+name.encode()+b';' for name in sorted(AUTHORITY))
    (app/'wit/world.wit').write_bytes(world.replace(b'world service {',b'world service {'+imports,1))
    for name, directory in (('clock-monotonic','clock'),('runtime','activation-runtime'),('http','http-v3')):
        target=app/'wit/deps'/name
        target.mkdir(parents=True,exist_ok=True)
        (target/'package.wit').write_bytes(read_file(ROOT/('wit/platform/'+directory+'/package.wit')))
    project=read_json(app/'capsule-project.json')
    # Same finite typed-HTTP profile as the original normal http-status template.
    project['limits'].update(outboundRequests=8,memoryBytes=16777216,cpuFuel=1000000000,wallTimeLimitMillis=5000)
    (app/'capsule-project.json').write_bytes(canonical(project))
    changed={'src/lib.rs','wit/world.wit','capsule-project.json'}
    require(all(read_file(app/name)==raw for name,raw in initial.items() if name not in changed),
        'rust-http-runtime-original-sdk-and-bindings')
    return app, outside, specs


def capture(app: Path, outside: list[Path], specs: list[dict], cargo: Path) -> dict:
    require(len(outside)==len(specs)==2, 'rust-http-runtime-two-unseen-crates')
    originals=[snapshot(path) for path in outside]
    sdk=read_file(app/'sdk-lock.json')
    for path,spec in zip(outside,specs):
        authoring.author(app,'add',identity=spec['package'],version=spec['version'],local=path,cargo=cargo)
    candidate=app.parent/'candidate.json'
    lock=native.resolve(app,candidate,cargo=cargo)
    clients=original.captured_clients(lock)
    for spec in specs:
        rows=[r for r in lock['artifacts'] if r['metadata'].get('package')==spec['package']
            and r['metadata'].get('version')==spec['version'] and r['role']=='application']
        require(len(rows)==1, 'rust-http-runtime-varied-crate-not-captured')
    for row in clients:
        require('json' in row['selectedFeatures'], 'rust-http-runtime-ordinary-library-json-required')
    executables=[r for r in lock['artifacts'] if r['role']=='build-tool']
    require(len(executables)==15 and any(r['metadata'].get('package')=='waki-macros'
        and ['proc-macro'] in r['metadata'].get('executableKinds',[]) for r in executables),
        'rust-http-runtime-exact-captured-executable-closure')
    raw=read_file(candidate,8*1024**2)
    review.review(app,candidate,digest(raw))
    require(review.status(app)['status']=='verified' and read_file(app/LOCK,8*1024**2)==raw
        and read_file(app/'sdk-lock.json')==sdk, 'rust-http-runtime-exact-normal-capture-review')
    for path,before in zip(outside,originals):
        require(path.resolve(strict=True).parent==app.resolve(strict=True).parent
            and path.name in {'outside-alpha','outside-delta'} and snapshot(path)==before,
            'rust-http-runtime-original-owner-before-removal')
        shutil.rmtree(path)
    return {'developerCrates':specs,'developerSources':[digest(inventory(v)) for v in originals],
        'clients':clients,'candidateDigest':digest(raw),'sdkLockDigest':digest(sdk),
        'originalLibrariesRemoved':all(not p.exists() for p in outside),
        'executableInputs':executables,'implicitExecutableApproval':False,
        'catalogueRegistration':False,'applicationTransportInjected':False,'libraryCodePatched':False}
