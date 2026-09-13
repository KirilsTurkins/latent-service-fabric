use std::sync::Arc;
use std::time::Duration;

use latent_artifacts::{content_digest, preparation_metadata_fingerprint, LifecycleScope};
use latent_core::{PlatformErrorCode, TenantId};
use latent_wasmtime::{AotResourceSnapshot, TrustedAotCompilerAuthority};
use zeroize::Zeroizing;

use super::support::{self, Fixture};

#[test]
fn real_compile_binds_exact_source_and_keeps_output_capacity_until_drop() {
    let fixture = Fixture::tiny();
    let limits = support::limits();
    let compiler = support::compiler(limits);
    let expected_metadata = preparation_metadata_fingerprint(
        &fixture.artifact.descriptor,
        &fixture.artifact.manifest,
        &fixture.artifact.contracts,
        limits.maximum_metadata_bytes,
        32,
    )
    .unwrap();
    let output = compiler
        .reserve(fixture.source(), fixture.release())
        .unwrap()
        .run()
        .unwrap();
    assert!(!output.output().is_empty());
    assert!(output.output().len() <= support::OUTPUT_BYTES);
    assert_eq!(
        output.output_digest().as_str(),
        content_digest(output.output()).0
    );
    assert_eq!(
        output.compatibility().component().as_str(),
        fixture.release().0
    );
    assert_eq!(
        output.compatibility().component_bytes(),
        fixture.artifact.component_bytes.len() as u64
    );
    assert_eq!(
        output.compatibility().metadata_digest(),
        expected_metadata.digest()
    );
    assert_eq!(
        output.compatibility().scope(),
        &LifecycleScope::Tenant(TenantId("tests".into()))
    );
    assert!(output.compatibility().package().is_none());
    assert_eq!(output.compiler_identity(), support::COMPILER_NAME);
    assert!(output.receipt().len() <= 8192);
    support::authority(limits)
        .verify(&output, output.compatibility())
        .unwrap();
    let other = TrustedAotCompilerAuthority::new(
        support::COMPILER_NAME,
        Zeroizing::new([38; 32]),
        limits.compiler,
    )
    .unwrap();
    assert_eq!(
        other
            .verify(&output, output.compatibility())
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );

    let retained = compiler.snapshot();
    assert_eq!(retained.jobs, 0);
    assert_eq!(retained.input_bytes, 0);
    assert_eq!(retained.document_bytes, 0);
    assert_eq!(retained.output_owners, 1);
    assert_eq!(retained.native_bytes, support::OUTPUT_BYTES);
    assert!(retained.output_metadata_bytes > 0);
    assert_eq!(
        Arc::strong_count(&fixture.repository),
        1,
        "output must not retain the catalog root owner"
    );
    assert_eq!(
        compiler
            .reserve(fixture.source(), fixture.release())
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted,
    );
    assert_eq!(
        compiler.snapshot(),
        retained,
        "failed reservation is atomic"
    );
    compiler.shutdown(Duration::from_secs(1)).unwrap();
    assert_eq!(
        compiler.snapshot(),
        retained,
        "shutdown cannot refund retained native bytes"
    );
    drop(output);
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}

#[test]
fn cancelled_unstarted_job_retains_its_reservation_until_consumed() {
    let fixture = Fixture::tiny();
    let compiler = support::compiler(support::limits());
    let job = compiler
        .reserve(fixture.source(), fixture.release())
        .unwrap();
    let before = fixture.repository.verification_snapshot();
    let reserved = compiler.snapshot();
    assert_eq!(reserved.jobs, 1);
    job.control().cancel();
    assert_eq!(compiler.snapshot(), reserved);
    assert_eq!(job.run().unwrap_err().code, PlatformErrorCode::Cancelled);
    assert_eq!(fixture.repository.verification_snapshot(), before);
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}

#[test]
fn queued_deadline_is_not_restarted_when_the_job_runs() {
    let fixture = Fixture::tiny();
    let mut limits = support::limits();
    limits.job_timeout = Duration::from_millis(10);
    let compiler = support::compiler(limits);
    let job = compiler
        .reserve(fixture.source(), fixture.release())
        .unwrap();
    let before = fixture.repository.verification_snapshot();
    std::thread::sleep(Duration::from_millis(25));
    assert_eq!(compiler.snapshot().jobs, 1);
    assert_eq!(
        job.run().unwrap_err().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(fixture.repository.verification_snapshot(), before);
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}

#[test]
fn shutdown_does_not_refund_a_held_job_and_closes_admission() {
    let fixture = Fixture::tiny();
    let compiler = support::compiler(support::limits());
    let job = compiler
        .reserve(fixture.source(), fixture.release())
        .unwrap();
    let reserved = compiler.snapshot();
    assert_eq!(
        compiler.shutdown(Duration::ZERO).unwrap_err().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(compiler.snapshot(), reserved);
    assert_eq!(
        compiler
            .reserve(fixture.source(), fixture.release())
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::Cancelled,
    );
    drop(job);
    compiler.shutdown(Duration::from_secs(1)).unwrap();
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}
