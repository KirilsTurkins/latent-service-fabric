use super::*;
use latent_core::{
    native_capacity::NativeCapacityLimits, test_support::TestClock, ActivationClock,
};
use latent_state::embedded::{EmbeddedStore, StoreLimits};
use std::time::Duration;

#[test]
fn expired_original_native_fence_refuses_tenant_publication_without_releasing_live_ownership() {
    let store =
        EmbeddedStore::open_file(tempfile::tempfile().unwrap(), StoreLimits::default()).unwrap();
    let clock = Arc::new(TestClock::new(1_000, Instant::now(), 2));
    let native =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), clock.clone()).unwrap();
    let reservation = native
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                request_bytes: REQUEST_BYTES,
                work_bytes: WORK_BYTES,
                response_bytes: 0,
            },
            clock.monotonic_now() + Duration::from_secs(30),
        )
        .unwrap();
    let prepared = tenant::prepare_install(
        &store.snapshot().unwrap(),
        &[super::super::validation::test_quota("alpha")],
    )
    .unwrap();
    assert!(prepared.retained_bytes() as u64 <= WORK_BYTES);
    clock.advance(Duration::from_secs(30));
    assert!(matches!(
        prepared.publish(&store, || accept(&reservation, &[])),
        Err(FencedStoreError::Fence(_))
    ));
    assert!(store
        .snapshot()
        .unwrap()
        .get(&tenant::guard_key())
        .unwrap()
        .is_none());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(reservation);
    assert!(native.snapshot().unwrap().physically_retired());
}

#[test]
fn committed_tenant_installation_preserves_rows_when_original_delivery_fence_expires() {
    let store =
        EmbeddedStore::open_file(tempfile::tempfile().unwrap(), StoreLimits::default()).unwrap();
    let clock = Arc::new(TestClock::new(1_000, Instant::now(), 2));
    let native =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), clock.clone()).unwrap();
    let reservation = native
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                request_bytes: REQUEST_BYTES,
                work_bytes: WORK_BYTES,
                response_bytes: 0,
            },
            clock.monotonic_now() + Duration::from_secs(30),
        )
        .unwrap();
    let quota = super::super::validation::test_quota("alpha");
    let prepared =
        tenant::prepare_install(&store.snapshot().unwrap(), std::slice::from_ref(&quota)).unwrap();
    prepared
        .publish(&store, || accept(&reservation, &[]))
        .unwrap();
    let original = tenant::inspect(&store.snapshot().unwrap(), &quota.tenant)
        .unwrap()
        .unwrap();
    clock.advance(Duration::from_secs(30));
    assert!(accept(&reservation, &[]).is_err());
    assert_eq!(
        tenant::inspect(&store.snapshot().unwrap(), &quota.tenant).unwrap(),
        Some(original)
    );
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(reservation);
    assert!(native.snapshot().unwrap().physically_retired());
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod native {
    use super::*;
    use latent_core::test_support::{
        block_on,
        coordination::{PollProbe, Rendezvous, Stage, WATCHDOG},
    };
    use latent_state::protected_store::ProtectedStoreConfig;
    use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf, pin::pin, sync::mpsc};

    fn fixture() -> (tempfile::TempDir, ProtectedStoreConfig) {
        let directory = std::env::var_os("LATENT_STATE_TEST_ROOT")
            .map_or_else(std::env::temp_dir, PathBuf::from);
        let root = tempfile::tempdir_in(directory).unwrap();
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let mut config = ProtectedStoreConfig::bounded_linux(root.path().to_path_buf());
        config.create_if_missing = true;
        (root, config)
    }
    async fn open(
        config: ProtectedStoreConfig,
        quotas: Vec<TenantQuota>,
    ) -> Arc<ProtectedStoreOwner> {
        let validator = super::super::super::validation::test_validation(quotas);
        Arc::new(
            ProtectedStoreOwner::start_validated_view(
                config,
                super::super::super::validation::STARTUP_VALIDATION_BYTES,
                move |view| validator.validate(view),
            )
            .unwrap()
            .await
            .expect("protected ext4 initialization must run on the qualified native fixture root"),
        )
    }
    async fn finish(store: &ProtectedStoreOwner) {
        store.close();
        let deadline = Instant::now() + WATCHDOG;
        assert!(
            store
                .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
                .unwrap()
                .await
                .clean
        );
        store.reap_retired_threads().unwrap();
    }

    #[tokio::test]
    async fn actual_protected_recovery_installer_reopens_exact_accounting_without_rewriting_rows() {
        let (_root, mut config) = fixture();
        let quotas = vec![super::super::super::validation::test_quota("alpha")];
        let native = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
        let store = open(config.clone(), quotas.clone()).await;
        install(&store, &native, &quotas, &[], Instant::now() + WATCHDOG)
            .await
            .unwrap();
        assert!(native.snapshot().unwrap().physically_retired());
        let tenant = quotas[0].tenant.clone();
        let original = store
            .with_store(StoreIoKind::RecoveryRead, 4096, move |engine| {
                tenant::inspect(&engine.snapshot()?, &tenant)
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        assert_eq!(original.generation, 1);
        assert_eq!(original.usage.metadata_rows, 1);
        finish(&store).await;
        drop(store);
        config.create_if_missing = false;
        let reopened = open(config, quotas.clone()).await;
        install(&reopened, &native, &quotas, &[], Instant::now() + WATCHDOG)
            .await
            .unwrap();
        let tenant = quotas[0].tenant.clone();
        assert_eq!(
            reopened
                .with_store(StoreIoKind::RecoveryRead, 4096, move |engine| {
                    tenant::inspect(&engine.snapshot()?, &tenant)
                })
                .unwrap()
                .await
                .unwrap()
                .unwrap(),
            Some(original)
        );
        assert!(native.snapshot().unwrap().physically_retired());
        finish(&reopened).await;
    }

    #[tokio::test]
    async fn detached_queued_tenant_installation_keeps_original_lease_and_refuses_expired_publication(
    ) {
        let (_root, config) = fixture();
        let quotas = vec![super::super::super::validation::test_quota("alpha")];
        let store = open(config, quotas.clone()).await;
        let clock = Arc::new(TestClock::new(1_000, Instant::now(), 2));
        let native =
            NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), clock.clone())
                .unwrap();
        let rendezvous = Rendezvous::new(1);
        let worker = rendezvous.clone();
        let (notice, ready) = mpsc::channel();
        let blocker = store
            .with_store(StoreIoKind::RecoveryWrite, 4096, move |_| {
                let (registration, mut retained) = worker.track(()).unwrap();
                retained.commit(Stage::Entered).unwrap();
                let mut pause = pin!(retained.pause());
                PollProbe::default().pending(pause.as_mut());
                notice
                    .send(worker.blocked(registration, Stage::Entered).unwrap())
                    .unwrap();
                block_on(pause);
                Ok(())
            })
            .unwrap();
        let ticket = ready.recv_timeout(WATCHDOG).unwrap();
        let mut install = Box::pin(super::super::install(
            &store,
            &native,
            &quotas,
            &[],
            clock.monotonic_now() + Duration::from_secs(30),
        ));
        PollProbe::default().pending(install.as_mut());
        assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
        assert_eq!(store.snapshot().unwrap().recovery_accepted, 2);
        drop(install);
        assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
        clock.advance(Duration::from_secs(30));
        rendezvous.release(ticket).unwrap();
        blocker.await.unwrap().unwrap();
        native.close();
        let drain = native
            .drain_async(clock.monotonic_now() + WATCHDOG, std::future::pending())
            .unwrap();
        assert!(
            latent_core::test_support::coordination::with_watchdog(WATCHDOG, drain)
                .await
                .clean
        );
        assert_eq!(
            store.failure(),
            None,
            "expired authorization is not storage failure"
        );
        assert!(store
            .with_store(StoreIoKind::RecoveryRead, 4096, |engine| {
                engine.snapshot()?.get(&tenant::guard_key())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
            .is_none());
        assert!(native.snapshot().unwrap().physically_retired());
        finish(&store).await;
    }
}
