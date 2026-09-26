use super::*;
use crate::bindings::{BindingLimits, ConfiguredBindingProvider, PreparedBindingUpdate};
use latent_core::{DeploymentId, PlatformError, ServiceId, TenantId};
use latent_manifest::BindingMode;

fn provider(f: &Fixture) -> ConfiguredBindingProvider {
    ConfiguredBindingProvider {
        tenant: TenantId("tests".into()),
        service: ServiceId("clock-host".into()),
        reference: f.provider.reference(),
        local_deployment: None,
    }
}
fn update(
    f: &Fixture,
    definitions: Vec<BindingDefinition>,
    providers: Vec<ConfiguredBindingProvider>,
    limits: BindingLimits,
) -> Result<PreparedBindingUpdate, PlatformError> {
    let current = f.store.read_publication();
    run(f.store.prepare_binding_update(
        current.routes.generation,
        current.transaction,
        definitions,
        f.broker.clone(),
        providers,
        limits,
    ))
}

#[test]
fn selection_denies_missing_cross_tenant_ambiguous_and_unsupported_providers() {
    let f = Fixture::new();
    let before = f.store.generation();
    assert!(update(&f, vec![definition()], vec![], BindingLimits::default()).is_err());
    let mut foreign = provider(&f);
    foreign.tenant = TenantId("other".into());
    assert!(update(
        &f,
        vec![definition()],
        vec![foreign],
        BindingLimits::default()
    )
    .is_err());
    assert!(update(
        &f,
        vec![definition()],
        vec![provider(&f), provider(&f)],
        BindingLimits::default()
    )
    .is_err());
    for mode in [BindingMode::Inline, BindingMode::Remote] {
        let mut d = definition();
        d.manifest.mode = mode;
        assert!(update(&f, vec![d], vec![provider(&f)], BindingLimits::default()).is_err());
    }
    let mut d = definition();
    d.manifest.provider.contract.0 = "latent:clock/monotonic@0.2.0".into();
    assert!(update(&f, vec![d], vec![provider(&f)], BindingLimits::default()).is_err());
    assert_eq!(f.store.generation(), before);
    assert_eq!(f.store.binding_inventory().1, 0);
    f.install(); // Every rejected preparation releases its control-work permit.
}

#[test]
fn auto_cannot_widen_explicit_host_only_modes() {
    let f = Fixture::with_local();
    let mut d = definition();
    d.manifest.mode = BindingMode::Auto;
    let mut local = provider(&f);
    local.local_deployment = Some(DeploymentId("clock-provider".into()));
    assert!(update(&f, vec![d.clone()], vec![local], BindingLimits::default()).is_err());
    let mut local = provider(&f);
    local.local_deployment = Some(DeploymentId("clock-provider".into()));
    let prepared = update(
        &f,
        vec![d],
        vec![local, provider(&f)],
        BindingLimits::default(),
    )
    .unwrap();
    f.store.commit_binding_update(prepared).unwrap();
    assert_eq!(f.store.binding_inventory().2, 2);
}

#[test]
fn retained_generations_and_preparation_owners_are_bounded() {
    let f = Fixture::new();
    let limits = BindingLimits {
        maximum_retained_generations: 1,
        ..BindingLimits::default()
    };
    let first = update(&f, vec![definition()], vec![provider(&f)], limits).unwrap();
    let other = Fixture::new();
    assert!(other.store.commit_binding_update(first).is_err());
    let first = update(&f, vec![definition()], vec![provider(&f)], limits).unwrap();
    f.store.commit_binding_update(first).unwrap();
    let old = f.store.pin().unwrap();
    let next = update(&f, vec![definition()], vec![provider(&f)], limits).unwrap();
    f.store.commit_binding_update(next).unwrap();
    assert!(f.store.pin().is_err());
    drop(old);
    assert!(f.store.pin().is_ok());
}

#[test]
fn replacement_needs_only_current_and_tentative_plan_capacity() {
    let f = Fixture::with_plan_limit(2);
    f.install();
    f.install();
    f.install();
    assert_eq!(f.broker.snapshot().plans, 1);
}

#[test]
fn removing_a_local_provider_retains_unavailable_binding_history() {
    let f = Fixture::with_local();
    super::local::install(&f);
    let old = f.store.pin().unwrap();
    let revision = old.resolve(&target(), None).unwrap();
    let plan = f.store.plan(&revision).unwrap();
    run(crate::DeploymentStore::delete(
        &f.store,
        &DeploymentId("clock-provider".into()),
    ))
    .unwrap();
    assert!(plan.check_eligible().is_err());
    assert_eq!(f.store.binding_inventory().1, 1);
    assert_eq!(f.store.binding_inventory().3, 1);
}

#[test]
fn restart_rejects_invalid_binding_even_with_a_recomputed_envelope_checksum() {
    let f = Fixture::new();
    f.install();
    let path = f.roots[1].0.join("catalog.json");
    let mut record: crate::deployments::persistence::Record =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    record.payload.capability_bindings.as_mut().unwrap()[0].allowed_modes =
        vec![BindingMode::Remote];
    record.checksum =
        latent_artifacts::content_digest(&serde_json::to_vec(&record.payload).unwrap()).0;
    let invalid = serde_json::to_vec(&record).unwrap();
    let profile = f.store.runtime_profile.clone().unwrap();
    drop(f.store);
    std::fs::write(&path, &invalid).unwrap();
    let reopened = run(Store::open_with_catalog(
        &f.roots[1].0,
        f.releases.clone(),
        crate::DirectoryDeploymentRepositoryConfig::default(),
        f.releases.lifecycle_authority(),
        profile,
    ));
    assert!(reopened.is_err());
    assert_eq!(std::fs::read(path).unwrap(), invalid);
}
