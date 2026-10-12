use super::*;
use latent_artifacts::AdmissionAuthority;
use latent_core::{PlatformErrorCode, TenantId};
use std::sync::{mpsc, Arc};

fn owner(fixture: &Fixture, root: &std::path::Path) -> SupplyChainAuthority {
    SupplyChainAuthority::open(root, fixture.approved(), fixture.clock.clone(), 5).unwrap()
}

#[test]
fn held_authority_fence_reports_busy_and_recovers_after_release() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let inner = Arc::clone(&authority.inner);
    let (held_sender, held_receiver) = mpsc::sync_channel(0);
    let (release_sender, release_receiver) = mpsc::sync_channel(0);

    let holder = std::thread::spawn(move || {
        let _guard = inner.state.write().unwrap();
        held_sender.send(()).unwrap();
        release_receiver.recv().unwrap();
    });
    held_receiver.recv().unwrap();

    let error = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert_eq!(error.message, "admission-authority-busy");
    assert!(error.retryable);
    assert_eq!(error.details.len(), 1);
    assert_eq!(error.details[0].kind, "admission.currentness");
    assert_eq!(
        error.details[0].fields["reason"],
        "admission-authority-busy"
    );

    release_sender.send(()).unwrap();
    holder.join().unwrap();
    authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
}

#[test]
fn poisoned_authority_fence_stays_fail_closed_across_retries() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let inner = Arc::clone(&authority.inner);

    let poisoner = std::thread::spawn(move || {
        let _guard = inner.state.write().unwrap();
        panic!("intentional admission authority poison");
    });
    assert!(poisoner.join().is_err());

    for _ in 0..2 {
        let error = authority
            .verify(&TenantId("tests".into()), fixture.upload())
            .err()
            .unwrap();
        assert_eq!(error.code, PlatformErrorCode::Unavailable);
        assert_eq!(error.message, "admission-authority-poisoned");
    }

    let renew_error = authority.renew_clock_lease().unwrap_err();
    assert_eq!(renew_error.code, PlatformErrorCode::Unavailable);
    assert_eq!(renew_error.message, "admission-authority-poisoned");
}

#[test]
fn unwinding_shared_reader_retires_currentness_for_readers_and_writers() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    let inner = Arc::clone(&authority.inner);
    let poisoner = std::thread::spawn(move || {
        let _guard = inner.read().unwrap();
        panic!("intentional admission reader poison");
    });
    assert!(poisoner.join().is_err());
    for _ in 0..2 {
        assert_eq!(
            admitted.grant.check_current().unwrap_err().message,
            "admission-authority-poisoned"
        );
        assert_eq!(
            admitted
                .grant
                .with_current(&mut |check| check.check())
                .unwrap_err()
                .message,
            "admission-authority-poisoned"
        );
    }
    assert_eq!(
        authority.renew_clock_lease().unwrap_err().message,
        "admission-authority-poisoned"
    );
}
