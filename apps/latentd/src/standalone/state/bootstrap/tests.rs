use super::*;
use latent_core::{native_capacity::NativeAdmissionClass, ClockSample, SystemActivationClock};
use latent_effects::authority::{AuthorityError, CommitLink, EffectScope, EffectTime};
use std::{
    path::Path,
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};

pub(in crate::standalone::state) fn settings(root: &Path) -> crate::config::state::StateSettings {
    let mut input = crate::config::state::tests::input();
    input["createIfMissing"] = true.into();
    input["operations"] = serde_json::json!([]);
    input["tenantQuotas"] = serde_json::json!([]);
    input["checkpointRoot"] = serde_json::to_value(root.join("private-checkpoint")).unwrap();
    crate::config::state::derive(&serde_json::from_value(input).unwrap(), root).unwrap()
}

struct Clock {
    start: Instant,
    millis: AtomicU64,
}

impl Clock {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            start: Instant::now(),
            millis: AtomicU64::new(0),
        })
    }
}

impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(10_000, self.monotonic_now())
    }

    fn monotonic_now(&self) -> Instant {
        self.start + Duration::from_millis(self.millis.load(Ordering::SeqCst))
    }
}

#[test]
fn bootstrap_prepays_the_original_recovery_owner_without_opening_files_or_installing_rules() {
    let root = tempfile::tempdir().unwrap();
    let settings = settings(root.path());
    let clock: Arc<dyn ActivationClock> = Arc::new(SystemActivationClock);
    let bootstrap = StateBootstrap::new_state(&settings, &clock).unwrap();
    let original = bootstrap.original();
    assert!(original.is_from_owner(&bootstrap.native));
    assert_eq!(original.class(), NativeAdmissionClass::Recovery);
    assert_eq!(original.work_bytes(), settings.startup_work_bytes);
    assert_eq!(original.original_deadline(), bootstrap.deadline);
    assert!(Arc::ptr_eq(&bootstrap.clock, &clock));
    assert!(bootstrap.authority.uses_native_capacity(&bootstrap.native));
    let snapshot = bootstrap.native.snapshot().unwrap();
    assert_eq!(snapshot.ordinary.slots, 0);
    assert_eq!(snapshot.recovery.slots, 1);
    assert!(bootstrap.opened_store.is_none());
    assert!(!settings.store.root.exists());
    let scope = EffectScope {
        tenant: "tenant".into(),
        namespace: "namespace".into(),
        incarnation: 1,
        publication: "publication".into(),
        binding: "http".into(),
        operation: "http".into(),
    };
    let link = CommitLink {
        command: "command".into(),
        caller_scope: "caller".into(),
        attempt: 1,
        commit: "commit".into(),
        effect: "e".repeat(64),
        sequence: 0,
    };
    assert_eq!(
        bootstrap.authority.capture(
            &scope,
            link,
            1,
            "a".repeat(64),
            EffectTime {
                unix_millis: 1000,
                continuity_proven: true,
            },
        ),
        Err(AuthorityError::PolicyBlocked)
    );
}

#[test]
fn namespace_metadata_cannot_allocate_before_the_same_store_or_after_original_close() {
    let root = tempfile::tempdir().unwrap();
    let settings = settings(root.path());
    let clock: Arc<dyn ActivationClock> = Arc::new(SystemActivationClock);
    let mut bootstrap = StateBootstrap::new_state(&settings, &clock).unwrap();
    assert!(bootstrap.open_namespaces(&settings).is_err());
    assert!(bootstrap.namespaces.is_none());
    assert!(!settings.store.root.exists());
    bootstrap.native.close();
    assert!(bootstrap.open_namespaces(&settings).is_err());
    assert!(bootstrap.namespaces.is_none());
    assert_eq!(bootstrap.native.snapshot().unwrap().recovery.slots, 1);
}

#[test]
fn affine_initializer_memory_survives_bootstrap_drop_until_its_last_real_owner_retires() {
    let root = tempfile::tempdir().unwrap();
    let settings = settings(root.path());
    let clock: Arc<dyn ActivationClock> = Arc::new(SystemActivationClock);
    let mut bootstrap = StateBootstrap::new_state(&settings, &clock).unwrap();
    let native = bootstrap.native.clone();
    let memory = bootstrap.take_memory().unwrap();
    assert!(bootstrap.take_memory().is_err());
    drop(bootstrap);
    let snapshot = native.snapshot().unwrap();
    assert!(snapshot.admission_closed);
    assert_eq!(snapshot.recovery.slots, 1);
    assert!(!snapshot.physically_retired());
    drop(memory);
    assert!(native.snapshot().unwrap().physically_retired());
}

#[tokio::test]
async fn expired_and_closed_original_boot_owners_refuse_before_any_business_file_is_opened() {
    for expire in [false, true] {
        let root = tempfile::tempdir().unwrap();
        let settings = settings(root.path());
        let clock = Clock::new();
        let projection: Arc<dyn ActivationClock> = clock.clone();
        let mut bootstrap = StateBootstrap::new_state(&settings, &projection).unwrap();
        let native = bootstrap.native.clone();
        if expire {
            clock.millis.store(5000, Ordering::SeqCst);
        } else {
            native.close();
        }
        assert!(bootstrap.open_store(&settings).await.is_err());
        assert!(bootstrap.memory.is_some());
        assert!(bootstrap.opened_store.is_none());
        assert!(!settings.store.root.exists());
        assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
        drop(bootstrap);
        assert!(native.snapshot().unwrap().physically_retired());
    }
}

#[test]
fn changed_startup_sizing_is_refused_before_global_admission_or_authority_shell_allocation() {
    let root = tempfile::tempdir().unwrap();
    let mut settings = settings(root.path());
    settings.startup_work_bytes -= 1;
    let clock: Arc<dyn ActivationClock> = Arc::new(SystemActivationClock);
    assert!(StateBootstrap::new_state(&settings, &clock).is_err());
    assert!(!settings.store.root.exists());
}

#[test]
fn actual_effect_rule_metadata_keeps_the_same_resident_charge_after_bootstrap_retirement() {
    let root = tempfile::tempdir().unwrap();
    let settings = settings(root.path());
    let clock: Arc<dyn ActivationClock> = Arc::new(SystemActivationClock);
    let bootstrap = StateBootstrap::new_state(&settings, &clock).unwrap();
    let native = bootstrap.native.clone();
    let authority = bootstrap.authority.clone();
    let original = Arc::downgrade(&bootstrap.original());
    assert!(authority.uses_native_capacity(&native));
    let total = native.snapshot().unwrap().recovery.bytes;
    assert_eq!(
        total,
        settings.startup_work_bytes
            + latent_core::native_capacity::NATIVE_RESERVATION_METADATA_BYTES
    );
    drop(bootstrap);
    assert!(native.snapshot().unwrap().admission_closed);
    assert_eq!(native.snapshot().unwrap().recovery.bytes, total);
    assert!(original.upgrade().is_some());
    assert!(!settings.store.root.exists());
    drop(authority);
    assert!(original.upgrade().is_none());
    assert!(native.snapshot().unwrap().physically_retired());
}

#[tokio::test]
async fn mixed_opened_configuration_cannot_change_store_checkpoint_or_installed_target_before_initialization(
) {
    for selected in [
        "store",
        "checkpoint",
        "native",
        "incarnation",
        "entity",
        "route",
        "epoch",
    ] {
        let root = tempfile::tempdir().unwrap();
        let input = crate::config::state::tests::input();
        let config = serde_json::from_value(input).unwrap();
        let original = crate::config::state::derive(&config, root.path()).unwrap();
        let clock: Arc<dyn ActivationClock> = Arc::new(SystemActivationClock);
        let mut bootstrap = StateBootstrap::new_state(&original, &clock).unwrap();
        let mut changed = original.clone();
        match selected {
            "store" => changed.store.root = root.path().join("different-state"),
            "checkpoint" => changed.checkpoint_root = root.path().join("different-checkpoint"),
            "native" => changed.native.recovery.bytes += 1024,
            "incarnation" => changed.operations[0].incarnation += 1,
            "entity" => changed.operations[0].entity = Some("different-entity".into()),
            "route" => changed.operations[0].route = Some("different-route".into()),
            "epoch" => changed.configuration_epoch += 1,
            _ => unreachable!(),
        }
        assert!(bootstrap.matches(&original));
        assert!(!bootstrap.matches(&changed));
        assert!(bootstrap.open_store(&changed).await.is_err());
        assert!(bootstrap.memory.is_some());
        assert!(bootstrap.opened_store.is_none());
        assert_eq!(bootstrap.native.snapshot().unwrap().recovery.slots, 1);
        assert!(!original.store.root.exists());
        assert!(!changed.store.root.exists());
    }
}
