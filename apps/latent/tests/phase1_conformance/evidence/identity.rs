use std::io::Read;
use std::path::Path;

use latent_testkit::conformance::{FileIdentity, ReportIdentity};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::sha256;
use crate::fixtures::{bounded_file, required_path, Fixtures};

pub(super) fn load(public_config: &Value, fixtures: &Fixtures) -> ReportIdentity {
    let mut identity: ReportIdentity = serde_json::from_slice(&bounded_file(
        &required_path("LSF_PHASE1_IDENTITY"),
        64 * 1024,
    ))
    .expect("runner source identity");
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let lock = bounded_file(&root.join("Cargo.lock"), 1024 * 1024);
    assert_eq!(
        identity.cargo_lock_sha256,
        sha256(&lock),
        "actual locked source identity"
    );
    let binaries = [
        file("latent", Path::new(env!("CARGO_BIN_EXE_latent"))),
        file("latentd", &required_path("LSF_LATENTD_BIN")),
    ];
    for actual in &binaries {
        verify(&identity.binaries, actual);
    }
    let current = file(
        "process-test",
        &std::env::current_exe().expect("current test executable"),
    );
    verify(&identity.binaries, &current);
    let original = [
        ("echo", "LSF_ECHO_COMPONENT"),
        ("generic", "LSF_GENERIC_COMPONENT"),
        ("capabilities", "LSF_CAPABILITIES_COMPONENT"),
    ];
    for (name, variable) in original {
        let actual = file(name, &required_path(variable));
        verify(&identity.fixtures, &actual);
    }
    for (name, package) in [
        "generic-variant",
        "echo-variant",
        "capabilities-package",
        "dormant-variant",
    ]
    .into_iter()
    .zip(fixtures.packages())
    {
        identity.fixtures.push(file(name, &package.component));
        identity
            .fixtures
            .push(file(&format!("{name}-manifest"), &package.manifest));
        identity
            .fixtures
            .push(file(&format!("{name}-contracts"), &package.contracts));
    }
    identity.config_sha256 =
        sha256(&serde_json::to_vec(public_config).expect("canonical public configuration"));
    identity
}

fn verify(expected: &[FileIdentity], actual: &FileIdentity) {
    let expected = expected
        .iter()
        .find(|entry| entry.name == actual.name)
        .expect("runner input identity");
    assert_eq!(expected.sha256, actual.sha256, "actual file digest");
    assert_eq!(expected.bytes, actual.bytes, "actual file size");
}

fn file(name: &str, path: &Path) -> FileIdentity {
    let mut input = std::fs::File::open(path).expect("identified input file");
    let expected = input.metadata().expect("input metadata").len();
    assert!(
        expected > 0 && expected <= 1024 * 1024 * 1024,
        "bounded input identity stream"
    );
    let mut hash = Sha256::new();
    let mut buffer = vec![0_u8; 64 * 1024].into_boxed_slice();
    let mut bytes = 0_u64;
    loop {
        let count = input.read(&mut buffer).expect("streamed identity input");
        if count == 0 {
            break;
        }
        bytes += u64::try_from(count).expect("read size");
        assert!(bytes <= expected, "input changed during hashing");
        hash.update(&buffer[..count]);
    }
    assert_eq!(bytes, expected);
    FileIdentity {
        name: name.to_owned(),
        sha256: format!("sha256:{:x}", hash.finalize()),
        bytes,
    }
}

pub(super) fn environment() -> Value {
    let kernel = bounded_file(Path::new("/proc/sys/kernel/osrelease"), 4096);
    let kernel = std::str::from_utf8(&kernel).expect("kernel release").trim();
    let rust = std::env::var("LSF_PHASE1_RUST_VERSION").expect("actual runner rustc version");
    assert!(!rust.is_empty() && rust.len() <= 256);
    let lock = bounded_file(
        &Path::new(env!("CARGO_MANIFEST_DIR")).join("../../Cargo.lock"),
        1024 * 1024,
    );
    let lock = std::str::from_utf8(&lock).expect("Cargo lock UTF-8");
    let wasmtime = lock
        .split("[[package]]")
        .find(|package| package.lines().any(|line| line == "name = \"wasmtime\""))
        .expect("pinned Wasmtime package")
        .lines()
        .find_map(|line| {
            line.strip_prefix("version = \"")
                .and_then(|version| version.strip_suffix('"'))
        })
        .expect("pinned Wasmtime version");
    json!({"os":std::env::consts::OS,"architecture":std::env::consts::ARCH,"kernel":kernel,
        "rust_version":rust,"wasmtime_version":wasmtime})
}
