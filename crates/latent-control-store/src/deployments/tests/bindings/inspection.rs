use super::*;
use latent_capabilities::broker::diagnostics::{BindingState, CapabilityInspectionSource};
use latent_core::{DeploymentId, TenantId};

#[test]
fn inspection_preserves_scope_versions_and_stale_unavailable_plans() {
    let f = Fixture::new();
    let tenant = target().tenant;
    let deployment = f
        .store
        .current
        .read()
        .unwrap()
        .routes
        .deployments
        .keys()
        .next()
        .unwrap()
        .clone();
    assert!(f
        .store
        .inspect(&tenant, &deployment)
        .unwrap()
        .plan
        .is_none());
    f.install();
    let selected = f.store.inspect(&tenant, &deployment).unwrap();
    selected.check_owner(&f.broker).unwrap();
    assert_eq!(
        f.store.binding_version().unwrap(),
        (selected.generation, selected.catalog_transaction)
    );
    let plan = selected.plan.unwrap();
    assert_eq!(
        plan.inspect_bindings(&tenant).unwrap()[0].state,
        BindingState::Current
    );
    assert!(f
        .store
        .inspect(&TenantId("foreign".into()), &deployment)
        .is_err());
    assert!(f
        .store
        .inspect(&tenant, &DeploymentId("missing".into()))
        .is_err());
    f.replace_policy();
    let stale = f.store.inspect(&tenant, &deployment).unwrap();
    assert_eq!(
        stale.plan.unwrap().inspect_bindings(&tenant).unwrap()[0].state,
        BindingState::PolicyChanged
    );
    f.provider.retire();
    assert_eq!(
        f.store
            .inspect(&tenant, &deployment)
            .unwrap()
            .plan
            .unwrap()
            .inspect_bindings(&tenant)
            .unwrap()[0]
            .state,
        BindingState::ProviderUnavailable
    );
}
