use std::fs;

use latent_core::{PlatformErrorCode, ReleaseDigest};
use latent_wasmtime::{
    AotResourceSnapshot, IsolatedAotCompiler, ValidatedAotProfile, WasmtimeConfig,
};

use super::support::{self, Fixture};

#[test]
fn tampered_component_is_rejected_by_the_fresh_catalog_read() {
    let fixture = Fixture::tiny();
    let compiler = support::compiler(support::limits());
    let job = compiler
        .reserve(fixture.source(), fixture.release())
        .unwrap();
    let mut changed = fixture.artifact.component_bytes.clone();
    changed[0] ^= 1;
    fs::write(fixture.component_path(), changed).unwrap();
    assert_eq!(
        job.run().unwrap_err().code,
        PlatformErrorCode::CorruptArtifact
    );
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}

#[test]
fn queued_job_cannot_upgrade_its_revoked_lifecycle_capability() {
    let fixture = Fixture::tiny();
    let compiler = support::compiler(support::limits());
    let job = compiler
        .reserve(fixture.source(), fixture.release())
        .unwrap();
    fixture.revoke();
    let before = fixture.repository.verification_snapshot();
    assert_eq!(
        job.run().unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(fixture.repository.verification_snapshot(), before);
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}

#[test]
fn over_budget_and_noncanonical_sources_fail_before_fresh_io() {
    let fixture = Fixture::tiny();
    let mut limits = support::limits();
    limits.resources.maximum_input_bytes = 1;
    let compiler = support::compiler(limits);
    let before = fixture.repository.verification_snapshot();
    assert_eq!(
        compiler
            .reserve(fixture.source(), fixture.release())
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted,
    );
    let uppercase = ReleaseDigest(fixture.release().0.to_ascii_uppercase());
    assert_eq!(
        compiler
            .reserve(fixture.source(), &uppercase)
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::InvalidArgument,
    );
    assert_eq!(fixture.repository.verification_snapshot(), before);
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}

#[test]
fn compiler_binary_digest_and_actual_engine_profile_are_checked() {
    let limits = support::limits();
    let profile =
        ValidatedAotProfile::from_config(&WasmtimeConfig::default(), limits.compiler).unwrap();
    let mut different = wasmtime::Config::new();
    different.wasm_component_model(true).consume_fuel(false);
    assert_eq!(
        profile
            .check_engine(&wasmtime::Engine::new(&different).unwrap())
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    let mut digest = support::executable_digest();
    digest[0] ^= 1;
    assert_eq!(
        IsolatedAotCompiler::new(
            support::executable(),
            digest,
            profile,
            support::authority(limits),
            limits
        )
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::PermissionDenied
    );
}

#[test]
fn invalid_portable_bytes_fail_in_the_child_without_a_trusted_output() {
    let fixture = Fixture::new(b"invalid portable component".to_vec());
    let compiler = support::compiler(support::limits());
    let result = compiler
        .reserve(fixture.source(), fixture.release())
        .unwrap()
        .run();
    assert!(
        result.is_err(),
        "catalog integrity alone cannot make invalid bytes compilable"
    );
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}
