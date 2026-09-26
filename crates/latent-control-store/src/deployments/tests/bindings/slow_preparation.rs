//! A fake clock advances after real package inspection, never by sleeping.
use super::fixture::*;
use crate::bindings::{BindingLimits, ConfiguredBindingProvider};
use latent_core::{PlatformErrorCode, ServiceId, TenantId};
use std::sync::atomic::{AtomicU64, Ordering};

struct InspectionHook;
impl InspectionHook {
    fn set(action: impl FnOnce() + 'static) -> Self {
        super::super::super::bindings::compile::AFTER_PACKAGE_INSPECTION.with(|hook| {
            assert!(hook.borrow_mut().replace(Box::new(action)).is_none());
        });
        Self
    }
}
impl Drop for InspectionHook {
    fn drop(&mut self) {
        super::super::super::bindings::compile::AFTER_PACKAGE_INSPECTION.with(|hook| {
            hook.borrow_mut().take();
        });
    }
}

fn slow(
    f: &Fixture,
    change: fn(&super::super::supply_chain::authority::State),
) -> (InspectionHook, Arc<AtomicU64>) {
    f.authority
        .state
        .clock_lease_until
        .store(105, Ordering::SeqCst);
    f.authority.control_renewals.store(0, Ordering::SeqCst);
    let state = f.authority.state.clone();
    let inspected = Arc::new(AtomicU64::new(0));
    let calls = inspected.clone();
    let hook = InspectionHook::set(move || {
        calls.fetch_add(1, Ordering::SeqCst);
        state.now.fetch_add(6, Ordering::SeqCst);
        change(&state);
    });
    (hook, inspected)
}

#[test]
fn slow_control_package_preparation_renews_before_plan_and_releases_cancelled_owners() {
    let f = Fixture::new();
    let original = std::fs::read(f.roots[1].0.join("catalog.json")).unwrap();
    let version = f.store.binding_version().unwrap();
    let (_hook, inspected) = slow(&f, |_| {});
    let prepared = prepare(&f.store, f.broker.clone(), &f.provider, vec![definition()]).unwrap();
    assert_eq!(inspected.load(Ordering::SeqCst), 1);
    assert_eq!(f.authority.state.now.load(Ordering::SeqCst), 106);
    assert_eq!(
        f.authority.state.clock_lease_until.load(Ordering::SeqCst),
        111
    );
    assert_eq!(f.broker.snapshot().plans, 1);
    assert!(prepare(&f.store, f.broker.clone(), &f.provider, vec![definition()]).is_err());
    drop(prepared); // Cancellation returns the one work permit and tentative plan.
    assert_eq!(f.broker.snapshot().plans, 0);
    assert_eq!(f.store.binding_version().unwrap(), version);
    assert_eq!(
        std::fs::read(f.roots[1].0.join("catalog.json")).unwrap(),
        original
    );
    f.install();
    assert_eq!(f.store.binding_inventory().2, 1);
}

#[test]
fn slow_control_package_preparation_cannot_renew_revoked_or_expired_proofs() {
    for expired in [false, true] {
        let f = Fixture::new();
        let original = std::fs::read(f.roots[1].0.join("catalog.json")).unwrap();
        let version = f.store.binding_version().unwrap();
        let (_hook, inspected) = slow(
            &f,
            if expired {
                |state| state.until.store(106, Ordering::SeqCst)
            } else {
                |state| state.active.store(false, Ordering::SeqCst)
            },
        );
        let error = prepare(&f.store, f.broker.clone(), &f.provider, vec![definition()])
            .err()
            .unwrap();
        assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
        assert_eq!(
            error.message,
            if expired {
                "fixture-expired"
            } else {
                "fixture-revoked"
            }
        );
        assert_eq!(inspected.load(Ordering::SeqCst), 1);
        assert_eq!(
            f.authority.state.clock_lease_until.load(Ordering::SeqCst),
            111
        );
        assert_eq!(f.broker.snapshot().plans, 0);
        assert_eq!(f.store.binding_version().unwrap(), version);
        assert_eq!(
            std::fs::read(f.roots[1].0.join("catalog.json")).unwrap(),
            original
        );
    }
}

#[test]
fn slow_startup_package_preparation_never_renews_control_authority() {
    let f = Fixture::new();
    f.install();
    let Fixture {
        store,
        authority,
        releases,
        broker,
        provider,
        roots,
        policies: _,
    } = f;
    let original = std::fs::read(roots[1].0.join("catalog.json")).unwrap();
    let version = store.binding_version().unwrap();
    drop(store);
    let reopened = open(&roots[1], &releases);
    authority
        .state
        .clock_lease_until
        .store(105, Ordering::SeqCst);
    authority.control_renewals.store(0, Ordering::SeqCst);
    let state = authority.state.clone();
    let _hook = InspectionHook::set(move || {
        state.now.store(106, Ordering::SeqCst);
    });
    let error = run(reopened.activate_configured_bindings(
        reopened.binding_definitions().unwrap(),
        broker.clone(),
        vec![ConfiguredBindingProvider {
            tenant: TenantId("tests".into()),
            service: ServiceId("clock-host".into()),
            reference: provider.reference(),
            local_deployment: None,
        }],
        BindingLimits::default(),
    ))
    .err()
    .unwrap();
    assert_eq!(error.message, "fixture-clock-lease-uncovered");
    assert_eq!(authority.control_renewals.load(Ordering::SeqCst), 0);
    assert_eq!(
        authority.state.clock_lease_until.load(Ordering::SeqCst),
        105
    );
    assert_eq!(broker.snapshot().plans, 0);
    assert_eq!(reopened.binding_version().unwrap(), version);
    assert_eq!(
        std::fs::read(roots[1].0.join("catalog.json")).unwrap(),
        original
    );
}
