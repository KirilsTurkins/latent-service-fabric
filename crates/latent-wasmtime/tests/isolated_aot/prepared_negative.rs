//! These tiny files test input selection only; they are never approved as workers.
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

use sha2::{Digest, Sha256};

use super::support::{self, prepared, Directory};

struct Inputs {
    root: Directory,
    original: PathBuf,
    document: serde_json::Value,
}
impl Inputs {
    fn new() -> Self {
        let root = Directory::new();
        let original = root.path().join("cargo-original");
        let copy = root.path().join("compiler");
        for path in [&original, &copy] {
            fs::write(path, b"fixture identity, not a worker").unwrap();
            fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
        }
        let record = |path: &PathBuf| {
            serde_json::json!({
                "path": path,
                "sha256": prepared::digest(path).unwrap(),
                "bytes": path.metadata().unwrap().len(),
            })
        };
        let document = serde_json::json!({
            "schema": "latent.aot-test-inputs.v1",
            "profile": "debug-all-features-v2",
            "entries": {"compiler": {"original": record(&original), "prepared": record(&copy)}},
        });
        Self {
            root,
            original,
            document,
        }
    }
    fn write(&self) -> (PathBuf, [u8; 32]) {
        let path = self.root.path().join("manifest.json");
        let bytes = serde_json::to_vec(&self.document).unwrap();
        fs::write(&path, &bytes).unwrap();
        (path, Sha256::digest(&bytes).into())
    }
    fn result(&self) -> Result<prepared::Executable, &'static str> {
        let (path, identity) = self.write();
        prepared::load(&path, identity, "compiler", &self.original)
    }
}

#[test]
fn prepared_missing_and_modified_executables_are_rejected() {
    for missing in [true, false] {
        let inputs = Inputs::new();
        let path = inputs.root.path().join("compiler");
        assert!(inputs.result().is_ok());
        if missing {
            fs::remove_file(path).unwrap();
            assert_eq!(inputs.result().err(), Some("missing-executable"));
        } else {
            fs::write(path, b"different identity, not worker").unwrap();
            assert_eq!(inputs.result().err(), Some("modified-prepared-executable"));
        }
    }
}

#[test]
fn prepared_wrong_digest_profile_and_stale_identities_are_rejected() {
    let inputs = Inputs::new();
    let (path, mut identity) = inputs.write();
    identity[0] ^= 1;
    assert_eq!(
        prepared::load(&path, identity, "compiler", &inputs.original).err(),
        Some("stale-manifest-identity")
    );
    let mut inputs = Inputs::new();
    inputs.document["profile"] = "release".into();
    assert_eq!(
        inputs.result().err(),
        Some("wrong-manifest-schema-or-profile")
    );
    let mut inputs = Inputs::new();
    inputs.document["entries"]["compiler"]["prepared"]["sha256"] =
        serde_json::to_value([0_u8; 32]).unwrap();
    assert_eq!(inputs.result().err(), Some("modified-prepared-executable"));
    let inputs = Inputs::new();
    fs::write(&inputs.original, b"stale Cargo product").unwrap();
    assert_eq!(inputs.result().err(), Some("stale-original-identity"));
}

#[test]
fn prepared_wrong_role_and_symlinks_are_rejected() {
    let inputs = Inputs::new();
    let (path, identity) = inputs.write();
    assert_eq!(
        prepared::load(&path, identity, "arbitrary-worker", &inputs.original).err(),
        Some("wrong-executable-role")
    );
    let copy = inputs.root.path().join("compiler");
    fs::remove_file(&copy).unwrap();
    std::os::unix::fs::symlink(&inputs.original, &copy).unwrap();
    assert_eq!(
        inputs.result().err(),
        Some("noncanonical-or-nonexecutable-file")
    );
}

#[test]
fn replacement_after_configuration_is_rejected_and_compilation_recovers() {
    use latent_core::PlatformErrorCode;
    use latent_wasmtime::{
        AotResourceSnapshot, IsolatedAotCompiler, ValidatedAotProfile, WasmtimeConfig,
    };
    // Mutation targets and owners are private; never write to the shared input.
    let directory = Directory::new();
    let target = directory.path().join("replaceable-compiler");
    fs::copy(support::executable(), &target).unwrap();
    let limits = support::limits();
    let profile =
        ValidatedAotProfile::from_config(&WasmtimeConfig::default(), limits.compiler).unwrap();
    let compiler = IsolatedAotCompiler::new(
        &target,
        support::executable_digest(),
        profile,
        support::authority(limits),
        limits,
    )
    .unwrap();
    // Appending bytes preserves a runnable ELF, but changes its exact identity.
    // Rename a private replacement after configuration; never mutate shared input.
    use std::io::Write;
    let replacement = directory.path().join("replacement");
    fs::copy(support::executable(), &replacement).unwrap();
    fs::set_permissions(&replacement, fs::Permissions::from_mode(0o700)).unwrap();
    fs::OpenOptions::new()
        .append(true)
        .open(&replacement)
        .unwrap()
        .write_all(&[0])
        .unwrap();
    fs::rename(replacement, &target).unwrap();
    let fixture = support::Fixture::tiny();
    let failure = compiler
        .reserve(fixture.source(), fixture.release())
        .unwrap()
        .run()
        .unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(failure.message, "aot-running-executable-mismatch");
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
    let compiler = support::compiler(limits);
    let output = compiler
        .reserve(fixture.source(), fixture.release())
        .unwrap()
        .run()
        .unwrap();
    support::authority(limits)
        .verify(&output, output.compatibility())
        .unwrap();
    assert!(!output.output().is_empty());
    drop(output);
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}
