"""Unchanged ordinary stdio in an outside transitive pure Rust library."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

from tools import cargo_native_authoring as authoring, rust_application_dependencies as native
from tools import rust_dependency_authoring as review, rust_standard_logging_inputs as standard
from tools.application_dependencies import LOCK
from tools.build_snapshot import canonical, digest
from tools.dev_workflow.common import require
from tools.rust_capsule_project import snapshot

PACKAGE = 'outside-standard-stdio-library'
RESOURCE = 'outside-standard-stdio-resource'
VERSION = '0.1.0'
LIBRARY = r'''use std::io::{self, ErrorKind, IoSlice, Read, Write};
use std::sync::atomic::{AtomicUsize, Ordering};
static CALLS: AtomicUsize = AtomicUsize::new(0);
fn fresh() { assert_eq!(CALLS.fetch_add(1, Ordering::Relaxed), 0); }
pub fn run(mode: &str) -> String {
    fresh();
    let text = outside_standard_stdio_resource::text();
    match mode {
        "formatted" => { println!("outside ordinary library: {}", 42); }
        "stderr" => { eprint!("outside error {text}"); io::stderr().flush().unwrap(); }
        "utf8" => { io::stdout().write_all(text.as_bytes()).unwrap(); }
        "vectors" => {
            let vectors = [IoSlice::new(b"Gr\xc3"), IoSlice::new(b"\xbc\xc3\x9fe")];
            assert_eq!(io::stdout().write_vectored(&vectors).unwrap(), text.len());
        }
        "invalid" => { assert_eq!(io::stdout().write(&[255]).unwrap_err().kind(), ErrorKind::InvalidData); }
        "incomplete" => { assert_eq!(io::stdout().write(&[195]).unwrap_err().kind(), ErrorKind::InvalidData); }
        "too-large" => { assert_eq!(io::stdout().write(&[b'x'; 257]).unwrap_err().kind(), ErrorKind::InvalidInput); }
        "too-many-vectors" => {
            let vectors = [IoSlice::new(b"x"); 17];
            assert_eq!(io::stdout().write_vectored(&vectors).unwrap_err().kind(), ErrorKind::InvalidInput);
        }
        "empty" => { assert_eq!(io::stdout().write(&[]).unwrap(), 0); io::stdout().flush().unwrap(); }
        "budget" => {
            let mut exhausted = false;
            for _ in 0..80 {
                if let Err(error) = io::stdout().write_all(&[b'x'; 256]) {
                    assert_eq!(error.kind(), ErrorKind::QuotaExceeded); exhausted = true; break;
                }
            }
            assert!(exhausted);
        }
        "closed" => {
            assert_eq!(io::stdout().write(b"outside").unwrap_err().kind(), ErrorKind::Unsupported);
            assert_eq!(io::stdout().write_all(b"outside").unwrap_err().kind(), ErrorKind::Unsupported);
            assert_eq!(io::stdout().flush().unwrap_err().kind(), ErrorKind::Unsupported);
            assert_eq!(io::stderr().write(b"outside").unwrap_err().kind(), ErrorKind::Unsupported);
            assert_eq!(io::stderr().flush().unwrap_err().kind(), ErrorKind::Unsupported);
            assert_eq!(io::stdin().read(&mut [0]).unwrap_err().kind(), ErrorKind::Unsupported);
            assert_eq!(io::stdin().read_line(&mut String::new()).unwrap_err().kind(), ErrorKind::Unsupported);
            assert_eq!(io::stdout().write(&[]).unwrap(), 0);
        }
        "trap" => { io::stdout().write_all(b"before library trap").unwrap(); panic!("ordinary outside library trap"); }
        "fuel" => { io::stdout().write_all(b"before library fuel").unwrap(); loop { std::hint::spin_loop(); } }
        _ => panic!("unknown fixed stdio probe"),
    }
    format!("ordinary-stdio:{mode}|resource={text}|fresh=1")
}
'''


def install(project: Path, outside: Path, cargo: Path, profile: str) -> dict:
    require(profile in {standard.CLOSED, standard.PROFILE}, 'rust-stdio-fixture-profile')
    initial = snapshot(project)
    descriptor = json.loads(initial['capsule-project.json'])
    require(descriptor.get('runtimeProfile') == profile, 'rust-stdio-fixture-created-profile')
    descriptor['limits']['logBytes'] = 16384 if profile == standard.PROFILE else 0
    (project / 'capsule-project.json').write_bytes(canonical(descriptor))
    outside.mkdir(mode=0o700)
    library, resource = outside / PACKAGE, outside / RESOURCE
    for path in (library, resource): (path / 'src').mkdir(parents=True)
    (resource / 'Cargo.toml').write_text(f'''[package]
name = "{RESOURCE}"
version = "{VERSION}"
edition = "2021"
license = "Apache-2.0"
''', encoding='utf-8')
    (resource / 'src/lib.rs').write_text('pub fn text() -> &\'static str { include_str!("text.txt") }\n', encoding='utf-8')
    text = bytes((71, 114, 195, 188, 195, 159, 101))
    (resource / 'src/text.txt').write_bytes(text)
    (library / 'Cargo.toml').write_text(f'''[package]
name = "{PACKAGE}"
version = "{VERSION}"
edition = "2021"
license = "Apache-2.0"
[dependencies]
{RESOURCE} = {{path = "../{RESOURCE}"}}
''', encoding='utf-8')
    (library / 'src/lib.rs').write_text(LIBRARY, encoding='utf-8')
    original = initial['src/lib.rs']
    marker = b'    let name = name.trim();'
    require(original.count(marker) == 1, 'rust-stdio-fixture-greeting-preimage')
    source = original.replace(marker, b'    if let Some(mode) = name.strip_prefix("stdio:") {\n'
        b'        return Ok(outside_standard_stdio_library::run(mode));\n    }\n' + marker, 1)
    (project / 'src/lib.rs').write_bytes(source)
    authoring.author(project, 'add', identity=PACKAGE, version=VERSION, local=library, cargo=cargo)
    candidate = outside / 'candidate.json'
    lock = native.resolve(project, candidate, cargo=cargo)
    require(lock['selection']['runtimeProfile'] == profile and not lock['executableInputs'],
            'rust-stdio-fixture-selected-pure-profile')
    packages = {(row['metadata'].get('package'), row['metadata'].get('version'))
                for row in lock['artifacts'] if row['role'] == 'application'}
    require({(PACKAGE, VERSION), (RESOURCE, VERSION)} <= packages, 'rust-stdio-fixture-transitive-library-missing')
    reviewed = candidate.read_bytes()
    review.review(project, candidate, digest(reviewed))
    require(review.status(project)['status'] == 'verified' and (project / LOCK).read_bytes() == reviewed,
            'rust-stdio-fixture-review-not-exact')
    require((project / 'sdk-lock.json').read_bytes() == initial['sdk-lock.json'], 'rust-stdio-fixture-SDK-lock-mutated')
    for path in (library, resource):
        require(path.resolve(strict=True).parent == outside.resolve(strict=True), 'rust-stdio-fixture-cleanup-scope')
        shutil.rmtree(path)
    return {'formatVersion': 1, 'runtimeProfile': profile, 'applicationPackage': PACKAGE,
        'transitiveResourcePackage': RESOURCE, 'version': VERSION, 'candidateDigest': digest(reviewed),
        'originalLibraryDigest': digest(LIBRARY.encode()), 'resourceDigest': digest(text),
        'applicationSourceDigest': digest(source), 'sdkLockDigest': digest(initial['sdk-lock.json']),
        'executableInputs': [], 'originalsRemoved': True, 'catalogueRegistration': False}
