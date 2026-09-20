//! Executed guest calls into the protected local secret provider.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "local_secrets/component.rs"]
mod component;
#[path = "local_secrets/fixture.rs"]
mod fixture;
#[path = "local_secrets/packages.rs"]
mod packages;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;
use fixture::*;
use latent_capabilities::broker::secrets::{SecretError, SecretInvoker};

fn marker(first: u8, version: u8, length: u64) -> u64 {
    (u64::from(first) << 32) | (u64::from(version) << 16) | length
}
async fn invoke(f: &Fixture, mode: u32) -> u64 {
    let (request, control) = f.request("same-public-activation-id", mode);
    let report = f.backend.invoke_contained(request, &control).await;
    let GuestOutcome::Returned {
        output,
        consumption,
        ..
    } = report.outcome.unwrap()
    else {
        panic!("guest result")
    };
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert!(control
        .budget
        .finalize_at(Some(&consumption), Instant::now())
        .violation()
        .is_none());
    f.idle();
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    serde_json::from_slice::<Vec<String>>(&output).unwrap()[0]
        .parse()
        .unwrap()
}
async fn shutdown(f: &Fixture) {
    f.secrets.close();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
async fn guest_read_version_errors_rotation_and_cell_reuse() {
    let f = Fixture::new().await;
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5));
    assert_eq!(invoke(&f, 1).await, 1001); // No matching read grant.
    assert_eq!(invoke(&f, 2).await, 1001); // Provider credential is never raw data.
    assert_eq!(invoke(&f, 3).await, 1000); // Same spelling in another tenant.
    assert_eq!(invoke(&f, 4).await, 1002);
    assert_eq!(invoke(&f, 5).await, marker(b'A', b'1', 5));
    write(&f.directory.path().join("secrets/value"), b"Beta");
    assert_eq!(f.secrets.reload(1, specs("2")).unwrap().await.unwrap(), 2);
    assert_eq!(invoke(&f, 0).await, marker(b'B', b'2', 4));
    shutdown(&f).await;
}

#[tokio::test]
async fn held_read_is_rejected_after_rotation_and_keeps_old_generation_charged() {
    let f = Fixture::new().await;
    let (session, _) = f.session("retained");
    let value = f
        .provider
        .read(&session, "allowed".into())
        .unwrap()
        .await
        .unwrap();
    f.secrets.reload(1, specs("2")).unwrap().await.unwrap();
    let snapshot = f.secrets.snapshot().unwrap();
    assert_eq!(snapshot.retained_generations, 2);
    assert!(f.secrets.reload(2, specs("3")).is_err());
    let mut copied = false;
    assert!(matches!(
        value.disclose(&mut |_| copied = true),
        Err(SecretError::Unavailable)
    ));
    assert!(!copied);
    assert_eq!(f.secrets.snapshot().unwrap().retained_generations, 1);
    assert_eq!(f.secrets.reload(2, specs("3")).unwrap().await.unwrap(), 3);
    drop(session);
    f.idle();
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'3', 5));
    shutdown(&f).await;
}

#[tokio::test]
async fn failed_reload_preserves_generation_and_current_guest_value() {
    let f = Fixture::new().await;
    let path = f.directory.path().join("secrets/value");
    std::fs::remove_file(&path).unwrap();
    assert!(f.secrets.reload(1, specs("2")).unwrap().await.is_err());
    assert_eq!(f.secrets.snapshot().unwrap().generation, 1);
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5));
    assert!(f.secrets.reload(0, specs("2")).is_err());
    shutdown(&f).await;
}

#[tokio::test]
async fn cancellation_stale_sessions_revocation_and_traps_release_reads() {
    let f = Fixture::new().await;
    let (session, control) = f.session("cancelled-read");
    let value = f
        .provider
        .read(&session, "allowed".into())
        .unwrap()
        .await
        .unwrap();
    control.probe.0.store(true, Ordering::Release);
    let mut copied = false;
    assert!(value.disclose(&mut |_| copied = true).is_err());
    assert!(!copied);
    assert!(f.provider.read(&session, "allowed".into()).is_err());
    drop(session);
    f.idle();
    let (request, control) = f.request("trap", 6);
    let report = f.backend.invoke_contained(request, &control).await;
    assert!(matches!(
        report.outcome.unwrap(),
        GuestOutcome::Trapped { .. }
    ));
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    f.idle();
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5));
    f.revoke();
    let (request, control) = f.request("revoked", 0);
    let report = f.backend.invoke_contained(request, &control).await;
    // Revocation may reject activation admission before the guest can call read.
    assert!(report.outcome.is_err() || matches!(report.outcome, Ok(GuestOutcome::Trapped { .. })));
    f.idle();
    shutdown(&f).await;
}

#[tokio::test]
async fn expiry_is_checked_at_disclosure_and_cannot_be_undone_by_clock_rollback() {
    let f = Fixture::new().await;
    let mut next = specs("2");
    next[0].expires_at_unix_millis = Some(1100);
    f.secrets.reload(1, next).unwrap().await.unwrap();
    let (session, _) = f.session("expires");
    let value = f
        .provider
        .read(&session, "allowed".into())
        .unwrap()
        .await
        .unwrap();
    f.secret_clock.now.store(1200, Ordering::Release);
    assert!(matches!(
        value.disclose(&mut |_| panic!("expired material copied")),
        Err(SecretError::Expired)
    ));
    f.secret_clock.now.store(1000, Ordering::Release);
    drop(session);
    assert_eq!(invoke(&f, 0).await, 1002);
    shutdown(&f).await;
}

#[tokio::test]
async fn dormant_deployments_acquire_no_secret_owner_or_provider_work() {
    let f = Fixture::new().await;
    let before = f.secrets.snapshot().unwrap();
    f.dormant_deployments().await;
    let after = f.secrets.snapshot().unwrap();
    assert_eq!(before.generation, after.generation);
    assert_eq!(before.retained_generations, after.retained_generations);
    assert_eq!(
        before.reserved_generation_bytes,
        after.reserved_generation_bytes
    );
    shutdown(&f).await;
}

#[path = "local_secrets/audit.rs"]
mod audit;
#[path = "local_secrets/ownership.rs"]
mod ownership;

#[path = "local_secrets/environment.rs"]
mod environment;
#[path = "local_secrets/limits.rs"]
mod limits;
#[path = "local_secrets/startup.rs"]
mod startup;
#[path = "local_secrets/tls_credentials.rs"]
mod tls_credentials;
