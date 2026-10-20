"""Ordinary independent WASI HTTP clients in a developer-owned captured crate.

This finite input control installs no HTTP adapter, executor, provider or grant.
The published libraries remain unchanged; normal Cargo capture and executable
input review are required before their first offline compilation.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil

from tools import cargo_native_authoring as authoring, rust_application_dependencies as native
from tools import rust_dependency_authoring as review
from tools.application_dependencies import LOCK
from tools.phase2_operator_process import require
from tools.rust_capsule_project import create, digest, fresh, inventory, read_file, snapshot

CLIENTS = {
    ('waki', '0.5.1'): '6e2db2daf1dfbadf228fd8b3c22b96a359135fd673b3d2c203274ee6a0df9c77',
    ('golem-wasi-http', '0.2.0'): '6e80794383f6d363e1f756c5ec9fa6ca0459824e54f9eef53b6b03491fb9d166',
}
LIBRARY = '''pub fn request(client: &str, url: &str) -> Result<(u16, Vec<u8>), String> {
    match client {
        "waki" => {
            let response = waki::Client::new().get(url).send().map_err(|e| e.to_string())?;
            let status = response.status_code();
            let bytes = response.body().map_err(|e| e.to_string())?;
            Ok((status, bytes))
        }
        "golem" => {
            let response = golem_wasi_http::Client::new().get(url).send().map_err(|e| e.to_string())?;
            let status = response.status().as_u16();
            let bytes = response.bytes().map_err(|e| e.to_string())?;
            Ok((status, bytes.to_vec()))
        }
        _ => Err("unknown HTTP input control".into()),
    }
}
'''


def specification(nonce: str) -> dict:
    require(type(nonce) is str and re.fullmatch('[0-9a-f]{16}', nonce) is not None,
            'rust-http-input-nonce')
    return {'package': 'outside-http-' + nonce,
            'version': f'0.{int(nonce[:4], 16) + 1}.{int(nonce[4:8], 16) + 1}'}


def prepare(output: Path, nonce: str):
    value = specification(nonce)
    root = fresh(output)
    application = create(root / 'application', 'greeting', name='http-input-' + nonce)
    before = snapshot(application)
    outside = fresh(root / 'original-library')
    (outside / 'src').mkdir()
    manifest = (f'[package]\nname="{value["package"]}"\nversion="{value["version"]}"\n'
        'edition="2021"\nlicense="Apache-2.0"\n[dependencies]\n'
        'waki="=0.5.1"\ngolem-wasi-http="=0.2.0"\n')
    (outside / 'Cargo.toml').write_bytes(manifest.encode())
    (outside / 'src/lib.rs').write_bytes(LIBRARY.encode())
    marker = b'    let name = name.trim();'
    require(before['src/lib.rs'].count(marker) == 1, 'rust-http-input-template-shape')
    call = value['package'].replace('-', '_')
    code = (f'    if let Some((client, url)) = name.split_once("|") {{\n'
        f'        let (status, body) = {call}::request(client, url)?;\n'
        '        return Ok(format!("http-input:{client}:{status}:{}", body.len()));\n'
        '    }\n').encode()
    (application / 'src/lib.rs').write_bytes(before['src/lib.rs'].replace(marker, code + marker, 1))
    require(all(read_file(application / name) == raw for name, raw in before.items() if name != 'src/lib.rs'),
            'rust-http-input-immutable-normal-sdk')
    return application, outside, value


def captured_clients(lock: dict) -> list[dict]:
    selected = []
    for (package, version), checksum in CLIENTS.items():
        rows = [row for row in lock['artifacts'] if row['metadata'].get('package') == package
                and row['metadata'].get('version') == version]
        require(len(rows) == 1, 'rust-http-input-published-client-missing-or-ambiguous')
        row = rows[0]
        require(row['metadata'].get('vendorChecksum', {}).get('package') == checksum
                and row['metadata'].get('sdkCompilerInput') is False and row['role'] == 'application',
                'rust-http-input-unchanged-upstream-client-required')
        selected.append({'package': package, 'version': version, 'artifact': row['id'],
            'archiveSha256': 'sha256:' + checksum, 'capturedOriginal': row['original'],
            'selectedFeatures': row['metadata']['features']})
    return selected


def capture(application: Path, outside: Path, value: dict, cargo: Path) -> dict:
    original = snapshot(outside)
    sdk = read_file(application / 'sdk-lock.json')
    authoring.author(application, 'add', identity=value['package'], version=value['version'],
                     local=outside, cargo=cargo)
    candidate = outside.parent / 'candidate.json'
    lock = native.resolve(application, candidate, cargo=cargo)
    clients = captured_clients(lock)
    require(any(row['metadata'].get('package') == value['package']
                and row['metadata'].get('version') == value['version']
                and row['role'] == 'application' for row in lock['artifacts']),
            'rust-http-input-developer-owned-crate-missing')
    executables = [row for row in lock['artifacts'] if row['role'] == 'build-tool']
    require(any(row['metadata'].get('package') == 'waki-macros'
                and ['proc-macro'] in row['metadata']['executableKinds'] for row in executables),
            'rust-http-input-mandatory-proc-macro-not-captured')
    raw = read_file(candidate, 8*1024**2)
    review.review(application, candidate, digest(raw))
    require(review.status(application)['status'] == 'verified'
            and read_file(application / LOCK, 8*1024**2) == raw
            and read_file(application / 'sdk-lock.json') == sdk, 'rust-http-input-exact-lock-review')
    require(outside.resolve(strict=True).parent == application.resolve(strict=True).parent
            and outside.name == 'original-library' and snapshot(outside) == original,
            'rust-http-input-original-owner-before-removal')
    shutil.rmtree(outside)
    return {'developerCrate': value, 'developerSource': digest(inventory(original)), 'clients': clients,
        'candidateDigest': digest(raw), 'sdkLockDigest': digest(sdk), 'originalLibraryRemoved': not outside.exists(),
        'executableInputs': executables, 'implicitExecutableApproval': False,
        'catalogueRegistration': False, 'runtimeBackendInstalled': False, 'signedQualification': False}
