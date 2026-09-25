use super::*;
use crate::bindings::{BindingLimits, ConfiguredBindingProvider};
use latent_core::{ServiceId, TenantId};

fn providers(provider: &ProviderRegistration) -> Vec<ConfiguredBindingProvider> {
    vec![ConfiguredBindingProvider {
        tenant: TenantId("tests".into()),
        service: ServiceId("clock-host".into()),
        reference: provider.reference(),
        local_deployment: None,
    }]
}

#[test]
fn configured_provider_restart_preserves_exact_versions_and_durable_bytes() {
    let fixture = Fixture::new();
    fixture.install();
    let Fixture {
        store,
        authority,
        releases,
        broker,
        provider,
        policies: _,
        roots,
    } = fixture;
    let versions = store.binding_version().unwrap();
    let revision = store.pin().unwrap().resolve(&target(), None).unwrap();
    let bytes = std::fs::read(roots[1].0.join("catalog.json")).unwrap();
    drop(store);
    authority
        .control_renewals
        .store(0, std::sync::atomic::Ordering::SeqCst);
    authority
        .fail_control_renewal
        .store(1, std::sync::atomic::Ordering::SeqCst);
    let reopened = open(&roots[1], &releases);
    assert!(reopened.plan(&revision).is_err());
    run(reopened.activate_configured_bindings(
        reopened.binding_definitions().unwrap(),
        broker.clone(),
        providers(&provider),
        BindingLimits::default(),
    ))
    .unwrap();
    assert_eq!(
        authority
            .control_renewals
            .load(std::sync::atomic::Ordering::SeqCst),
        0
    );
    assert_eq!(reopened.binding_version().unwrap(), versions);
    assert_eq!(
        std::fs::read(roots[1].0.join("catalog.json")).unwrap(),
        bytes
    );
    assert!(reopened.plan(&revision).is_ok());
    assert!(run(reopened.activate_configured_bindings(
        reopened.binding_definitions().unwrap(),
        broker,
        providers(&provider),
        BindingLimits::default(),
    ))
    .is_err());
    provider.retire();
    assert!(reopened.plan(&revision).is_err());
}

#[test]
fn startup_cannot_silently_replace_durable_bindings_or_install_foreign_provider_owners() {
    let fixture = Fixture::new();
    fixture.install();
    let Fixture {
        store,
        authority: _,
        releases,
        broker,
        provider,
        policies: _,
        roots,
    } = fixture;
    let versions = store.binding_version().unwrap();
    drop(store);
    let reopened = open(&roots[1], &releases);
    let mut definitions = reopened.binding_definitions().unwrap();
    definitions[0].provider_binding_id = "different".into();
    assert!(run(reopened.activate_configured_bindings(
        definitions,
        broker,
        providers(&provider),
        BindingLimits::default(),
    ))
    .is_err());
    let foreign = Fixture::new();
    assert!(run(reopened.activate_configured_bindings(
        reopened.binding_definitions().unwrap(),
        foreign.broker.clone(),
        providers(&foreign.provider),
        BindingLimits::default(),
    ))
    .is_err());
    assert_eq!(reopened.binding_version().unwrap(), versions);
    assert_eq!(reopened.binding_inventory().2, 0);
}

#[test]
fn configured_startup_does_not_accept_arbitrary_local_adapter_registrations() {
    let fixture = Fixture::new();
    let mut installed = providers(&fixture.provider);
    installed[0].local_deployment = Some(latent_core::DeploymentId("clock-provider".into()));
    assert!(run(fixture.store.activate_configured_bindings(
        vec![definition()],
        fixture.broker.clone(),
        installed,
        BindingLimits::default(),
    ))
    .is_err());
    assert!(fixture.store.binding_definitions().unwrap().is_empty());
}
