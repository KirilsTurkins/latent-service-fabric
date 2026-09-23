//! Explicit control renewals cover both metadata and full binding package reads.
use super::fixture::*;
use crate::bindings::{BindingLimits, ConfiguredBindingProvider, PreparedBindingUpdate};
use crate::deployment_operations::{DeploymentOperationContext, DeploymentOperationRequest};
use crate::DeploymentStore;
use latent_artifacts::{ReleaseActor, ReleaseActorKind};
use latent_core::{DeploymentId, PlatformError, RouteGeneration, ServiceId, TenantId};
use latent_manifest::BindingMode;
use std::sync::atomic::Ordering;

fn reset(f: &Fixture, fail_at: u64) {
    f.authority.control_renewals.store(0, Ordering::SeqCst);
    f.authority
        .fail_control_renewal
        .store(fail_at, Ordering::SeqCst);
    super::super::super::bindings::compile::PACKAGE_READS.with(|reads| reads.set(0));
}

fn renewals(f: &Fixture) -> u64 {
    f.authority.control_renewals.load(Ordering::SeqCst)
}

fn package_reads() -> usize {
    super::super::super::bindings::compile::PACKAGE_READS.with(std::cell::Cell::get)
}

fn bytes(f: &Fixture) -> Vec<u8> {
    std::fs::read(f.roots[1].0.join("catalog.json")).unwrap()
}

fn unchanged(f: &Fixture, original: &[u8], version: (RouteGeneration, u64)) {
    assert_eq!(bytes(f), original);
    assert_eq!(f.store.binding_version().unwrap(), version);
}

#[test]
fn managed_binding_lease_failures_never_repeat_reads_or_publish_partial_plans() {
    let f = Fixture::new();
    let original = bytes(&f);
    let version = f.store.binding_version().unwrap();
    // Initial control renewal, metadata package, then full binding package.
    for fail_at in 1..=3 {
        reset(&f, fail_at);
        assert_eq!(
            prepare(&f.store, f.broker.clone(), &f.provider, vec![definition()])
                .err()
                .unwrap()
                .message,
            "fixture-control-lease-unavailable"
        );
        assert_eq!(renewals(&f), fail_at);
        assert_eq!(package_reads(), 0);
        unchanged(&f, &original, version);
    }
    reset(&f, 4);
    let prepared = prepare(&f.store, f.broker.clone(), &f.provider, vec![definition()]).unwrap();
    assert_eq!(renewals(&f), 3);
    assert_eq!(package_reads(), 1);
    assert_eq!(
        f.store
            .commit_binding_update(prepared)
            .err()
            .unwrap()
            .message,
        "fixture-control-lease-unavailable"
    );
    assert_eq!(renewals(&f), 4);
    unchanged(&f, &original, version);

    reset(&f, 0);
    let prepared = prepare(&f.store, f.broker.clone(), &f.provider, vec![definition()]).unwrap();
    drop(prepared); // Cancellation does not publish or repeat preparation.
    assert_eq!(renewals(&f), 3);
    unchanged(&f, &original, version);
    reset(&f, 0);
    f.install();
    assert_eq!(renewals(&f), 4);
    assert_eq!(package_reads(), 1);
    assert_eq!(f.store.binding_inventory().2, 1);
}

#[test]
fn managed_inherited_bindings_renew_each_distinct_package_but_never_replay() {
    let f = Fixture::with_local();
    f.install();
    let consumer = f
        .store
        .read_catalog()
        .record_by_id(&DeploymentId("consumer".into()))
        .unwrap()
        .deployment
        .clone();
    let mut duplicate = (*consumer).clone();
    duplicate.id = DeploymentId("duplicate".into());
    duplicate.metadata.name = duplicate.id.0.clone();
    run(f.store.apply(duplicate)).unwrap();
    let original = bytes(&f);
    let version = f.store.binding_version().unwrap();
    let request = DeploymentOperationRequest::Apply {
        context: DeploymentOperationContext {
            tenant: TenantId("tests".into()),
            actor: ReleaseActor {
                kind: ReleaseActorKind::Host,
                subject: "operator".into(),
            },
            operation_id: "inherited-bindings".into(),
            expected_state_version: version.1,
        },
        manifest: (*consumer).clone(),
        expected_generation: f.store.read_catalog().versions[&consumer.id],
    };
    // Initial renewal, two metadata packages, then two binding packages.
    // The duplicate consumer shares only this compilation's checked package.
    reset(&f, 5);
    assert_eq!(
        run(f.store.prepare_operation(request.clone()))
            .err()
            .unwrap()
            .message,
        "fixture-control-lease-unavailable"
    );
    assert_eq!(renewals(&f), 5);
    assert_eq!(package_reads(), 1);
    unchanged(&f, &original, version);
    reset(&f, 0);
    let prepared = run(f.store.prepare_operation(request.clone())).unwrap();
    assert_eq!(renewals(&f), 5);
    assert_eq!(package_reads(), 2);
    drop(prepared);
    unchanged(&f, &original, version);
    reset(&f, 0);
    let prepared = run(f.store.prepare_operation(request.clone())).unwrap();
    let committed = f.store.commit_operation(prepared).unwrap();
    assert!(!committed.value().replayed);
    committed.value().durability.as_ref().unwrap();
    drop(committed);
    assert_eq!(renewals(&f), 6);
    let committed_bytes = bytes(&f);
    reset(&f, 1);
    let replay = run(f.store.prepare_operation(request)).unwrap();
    assert!(f.store.commit_operation(replay).unwrap().value().replayed);
    assert_eq!(renewals(&f), 0);
    assert_eq!(package_reads(), 0);
    assert_eq!(bytes(&f), committed_bytes);
}

fn prepare_local(f: &Fixture) -> Result<PreparedBindingUpdate, PlatformError> {
    let mut binding = definition();
    binding.manifest.mode = BindingMode::IsolatedLocal;
    binding.allowed_modes = vec![BindingMode::IsolatedLocal];
    let version = f.store.binding_version().unwrap();
    run(f.store.prepare_binding_update(
        version.0,
        version.1,
        vec![binding],
        f.broker.clone(),
        vec![ConfiguredBindingProvider {
            tenant: TenantId("tests".into()),
            service: ServiceId("clock-host".into()),
            reference: f.provider.reference(),
            local_deployment: Some(DeploymentId("clock-provider".into())),
        }],
        BindingLimits::default(),
    ))
}

#[test]
fn managed_local_binding_renews_before_provider_reads_and_preserves_commit_fences() {
    let f = Fixture::with_local();
    let original = bytes(&f);
    let version = f.store.binding_version().unwrap();
    // Initial renewal, two metadata, two consumer reads, one local provider.
    for fail_at in 1..=6 {
        reset(&f, fail_at);
        assert_eq!(
            prepare_local(&f).err().unwrap().message,
            "fixture-control-lease-unavailable"
        );
        assert_eq!(renewals(&f), fail_at);
        assert!(package_reads() <= 2);
        unchanged(&f, &original, version);
    }
    reset(&f, 0);
    let prepared = prepare_local(&f).unwrap();
    assert_eq!(renewals(&f), 6);
    assert_eq!(package_reads(), 3);
    // Renewal cannot revive a revoked policy or bypass commit's live fence.
    f.replace_policy();
    assert!(f.store.commit_binding_update(prepared).is_err());
    assert_eq!(renewals(&f), 7);
    unchanged(&f, &original, version);
    reset(&f, 0);
    f.store
        .commit_binding_update(prepare_local(&f).unwrap())
        .unwrap();
    assert_eq!(renewals(&f), 7);
    assert_eq!(package_reads(), 3);
}
