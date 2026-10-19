"""Ordinary getrandom, rand_core OsRng and std HashMap in a captured library."""
import json
from pathlib import Path
import shutil

from tools import cargo_native_authoring as authoring, rust_application_dependencies as native
from tools import rust_dependency_authoring as review, rust_standard_logging_inputs as standard
from tools.application_dependencies import LOCK
from tools.build_snapshot import digest
from tools.dev_workflow.common import require
from tools.rust_capsule_project import snapshot

PACKAGE = 'outside-standard-entropy-library'
RESOURCE = 'outside-standard-entropy-resource'
VERSION = '0.1.0'
CASES = ('empty', 'one', 'wide', 'uninit', 'scalar', 'os-rng', 'hashmap', 'large', 'too-large')
COUNTS = dict(zip(CASES, (0, 1, 257, 33, 2, 33, 257, 4096, 65537)))
LIBRARY = r'''use rand_core::TryRngCore;
use std::sync::atomic::{AtomicUsize, Ordering};
static CALLS: AtomicUsize = AtomicUsize::new(0);
pub fn run(mode: &str) -> String {
    assert_eq!(CALLS.fetch_add(1, Ordering::Relaxed), 0, "mutable entropy library state leaked");
    assert_eq!(outside_standard_entropy_resource::text(), "Grüße");
    assert_eq!(outside_standard_entropy_resource::bytes(), &[0, 127, 128, 255]);
    let count = match mode {
        "empty" => { getrandom::fill(&mut []).unwrap(); 0 }
        "one" => { getrandom::fill(&mut [0; 1]).unwrap(); 1 }
        "wide" => {
            let mut guarded = [0x5a; 259]; getrandom::fill(&mut guarded[1..258]).unwrap();
            assert_eq!((guarded[0], guarded[258]), (0x5a, 0x5a)); 257
        }
        "uninit" => {
            let mut values = [core::mem::MaybeUninit::uninit(); 33];
            assert_eq!(getrandom::fill_uninit(&mut values).unwrap().len(), 33); 33
        }
        "scalar" => { let _ = getrandom::u32().unwrap(); let _ = getrandom::u64().unwrap(); 2 }
        "os-rng" => { let mut os = rand_core::OsRng; os.try_fill_bytes(&mut [0; 33]).unwrap(); 33 }
        "hashmap" | "std-denied" => {
            let mut values = std::collections::HashMap::new();
            for index in 0..257 { values.insert(index, index * 3); }
            for index in 0..257 { assert_eq!(values.get(&index), Some(&(index * 3))); }
            values.len()
        }
        "large" => { getrandom::fill(&mut [0; 4096]).unwrap(); 4096 }
        "too-large" => {
            let mut bytes = vec![0x5a; 65537];
            assert_eq!(getrandom::fill(&mut bytes), Err(getrandom::Error::new_custom(1)));
            assert!(bytes.iter().all(|value| *value == 0x5a)); 65537
        }
        "denied" => {
            let mut bytes = [0x5a; 33];
            assert_eq!(getrandom::fill(&mut bytes), Err(getrandom::Error::new_custom(2)));
            assert!(bytes.iter().all(|value| *value == 0));
            return "ordinary-entropy:denied|typed=budget-exhausted|cleared=1|fresh=1".to_owned();
        }
        "trap" => { getrandom::fill(&mut [0; 33]).unwrap(); panic!("requested entropy trap"); }
        "fuel" => { getrandom::fill(&mut [0; 33]).unwrap(); loop { core::hint::spin_loop(); } }
        _ => panic!("unknown finite entropy case"),
    };
    format!("ordinary-entropy:{mode}|count={count}|assets=7+4|fresh=1")
}
'''


def expected(mode):
    if mode == 'denied':
        return 'ordinary-entropy:denied|typed=budget-exhausted|cleared=1|fresh=1'
    return f'ordinary-entropy:{mode}|count={COUNTS[mode]}|assets=7+4|fresh=1'


def install(project: Path, outside: Path, cargo: Path):
    initial = snapshot(project)
    require(json.loads(initial['capsule-project.json']).get('runtimeProfile') == standard.ENTROPY,
            'rust-entropy-fixture-explicit-profile')
    outside.mkdir(mode=0o700)
    library, resource = outside / PACKAGE, outside / RESOURCE
    for directory in (library, resource):
        (directory / 'src').mkdir(parents=True)
    (resource / 'Cargo.toml').write_text(f'[package]\nname="{RESOURCE}"\nversion="{VERSION}"\n'
        'edition="2021"\nlicense="Apache-2.0"\n', encoding='utf-8', newline='\n')
    (resource / 'src/lib.rs').write_text('pub fn text() -> &\'static str { include_str!("text.txt") }\n'
        'pub fn bytes() -> &\'static [u8] { include_bytes!("bytes.bin") }\n', encoding='utf-8', newline='\n')
    text, binary = 'Grüße'.encode(), bytes((0, 127, 128, 255))
    (resource / 'src/text.txt').write_bytes(text)
    (resource / 'src/bytes.bin').write_bytes(binary)
    (library / 'Cargo.toml').write_text(f'[package]\nname="{PACKAGE}"\nversion="{VERSION}"\n'
        'edition="2021"\nlicense="Apache-2.0"\n[dependencies]\ngetrandom="=0.3.4"\n'
        'rand_core={version="=0.9.3",features=["os_rng"]}\n'
        f'{RESOURCE}={{path="../{RESOURCE}"}}\n', encoding='utf-8', newline='\n')
    (library / 'src/lib.rs').write_text(LIBRARY, encoding='utf-8', newline='\n')
    marker = b'    let name = name.trim();'
    original = initial['src/lib.rs']
    require(original.count(marker) == 1, 'rust-entropy-fixture-original-template')
    code = original.replace(marker, b'    if let Some(mode) = name.strip_prefix("entropy:") {\n'
        b'        return Ok(outside_standard_entropy_library::run(mode));\n    }\n' + marker, 1)
    (project / 'src/lib.rs').write_bytes(code)
    authoring.author(project, 'add', identity=PACKAGE, version=VERSION, local=library, cargo=cargo)
    candidate = outside / 'candidate.json'
    lock = native.resolve(project, candidate, cargo=cargo)
    require(lock['selection']['runtimeProfile'] == standard.ENTROPY, 'rust-entropy-native-selected-profile')
    packages = {(row['metadata'].get('package'), row['metadata'].get('version')) for row in lock['artifacts']}
    require({(PACKAGE, VERSION), (RESOURCE, VERSION), ('getrandom', '0.3.4'), ('rand_core', '0.9.3')} <= packages,
            'rust-entropy-native-closure')
    executables = [row for row in lock['artifacts'] if row['role'] == 'build-tool']
    require(len(executables) == 1 and executables[0]['metadata']['package'] == 'getrandom'
            and executables[0]['metadata']['version'] == '0.3.4'
            and executables[0]['metadata']['executableKinds'] == [['custom-build']],
            'rust-entropy-only-audited-executable-input')
    before = candidate.read_bytes()
    review.review(project, candidate, digest(before))
    require(review.status(project)['status'] == 'verified' and (project / LOCK).read_bytes() == before
            and (project / 'sdk-lock.json').read_bytes() == initial['sdk-lock.json'],
            'rust-entropy-exact-review-and-SDK-stability')
    for directory in (library, resource):
        require(directory.resolve(strict=True).parent == outside.resolve(strict=True), 'rust-entropy-owned-originals')
        shutil.rmtree(directory)
    return {'formatVersion': 1, 'runtimeProfile': standard.ENTROPY, 'libraryDigest': digest(LIBRARY.encode()),
        'sourceDigest': digest(code), 'textDigest': digest(text), 'binaryDigest': digest(binary),
        'candidateDigest': digest(before), 'sdkLockDigest': digest(initial['sdk-lock.json']),
        'originalsRemoved': not library.exists() and not resource.exists(),
        'catalogueRegistration': False, 'normalExecutableApprovalRequired': True,
        'ordinaryAPIs': ['getrandom::fill', 'getrandom::fill_uninit', 'getrandom::u32', 'getrandom::u64',
                         'rand_core::OsRng', 'std::collections::HashMap']}
