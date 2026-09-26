use super::fixture::*;
use crate::{
    bindings::{BindingLimits, ConfiguredBindingProvider},
    DeploymentStore,
};
use latent_artifacts::*;
use latent_capabilities::broker::CapabilityPlanSource;
use latent_core::{DeploymentId, ServiceId, TenantId};
use latent_policy::capability::{MutationRequest, RecordKind};
use latent_routing::RouteResolver;
use serde_json::json;
use std::time::{Duration, Instant};
#[test]
fn identical_checked_package_has_independent_tenant_plans_and_revocation() {
    let f = Fixture::new();
    f.install();
    let primary = f
        .store
        .read_catalog()
        .record_by_id(&DeploymentId("consumer".into()))
        .unwrap()
        .clone();
    let package = consumer_package().into_input();
    run(f.releases.admit_package(
        &TenantId("other".into()),
        PackageAdmissionUpload {
            manifest: package.manifest,
            configuration: package.configuration,
            layers: package.layers,
            signatures: Vec::new(),
            provenance: Vec::new(),
            sboms: Vec::new(),
        },
        &mut |_| Ok(()),
    ))
    .unwrap();
    let other = f
        .releases
        .select_execution_publication(&TenantId("other".into()), &primary.deployment.release, None)
        .unwrap()
        .unwrap();
    assert_ne!(Some(&other.id), primary.publication.as_ref());
    let mut deployment = (*primary.deployment).clone();
    deployment.id = DeploymentId("other-consumer".into());
    deployment.metadata.name = "other-consumer".into();
    deployment.metadata.tenant = Some(TenantId("other".into()));
    deployment.publication = Some(other.id.clone());
    run(f.store.apply(deployment)).unwrap();
    let cap = "latent:clock/monotonic@0.1.0";
    let digest = format!("sha256:{}", "7".repeat(64));
    for (id, kind, value) in [
        (
            "clock",
            RecordKind::Policy,
            json!({"formatVersion":1,"tenant":"other","rules":[{"id":"allow","effect":"allow","principals":[{"kind":"user","subject":"bob"}],"services":["packaging"],"publications":[other.id.as_str()],"capability":cap,"operations":["now-nanos"],"resources":{"kind":"clock"},"ceiling":{"operations":4,"inputBytes":128,"outputBytes":256,"wallTimeMillis":5000}}]}),
        ),
        (
            "installed",
            RecordKind::ProviderBinding,
            json!({"formatVersion":1,"tenant":"other","capability":cap,"providerProfile":"clock-v1","configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":[]}}),
        ),
    ] {
        let bytes = serde_json::to_vec(&value).unwrap();
        f.policies
            .mutate(
                MutationRequest {
                    tenant: "other",
                    actor: "operator",
                    id,
                    kind,
                    operation_id: id,
                    expected_revision: 0,
                    document: Some(&bytes),
                },
                Instant::now() + Duration::from_secs(10),
                |_| Ok(()),
            )
            .unwrap();
    }
    let mut other_definition = definition();
    other_definition.manifest.metadata.tenant = Some(TenantId("other".into()));
    let providers = || {
        ["tests", "other"]
            .into_iter()
            .map(|tenant| ConfiguredBindingProvider {
                tenant: TenantId(tenant.into()),
                service: ServiceId("clock-host".into()),
                reference: f.provider.reference(),
                local_deployment: None,
            })
            .collect()
    };
    let current = f.store.read_publication();
    let prepared = run(f.store.prepare_binding_update(
        current.routes.generation,
        current.transaction,
        vec![definition(), other_definition],
        f.broker.clone(),
        providers(),
        BindingLimits::default(),
    ))
    .unwrap();
    f.store.commit_binding_update(prepared).unwrap();
    let a = f.store.pin().unwrap().resolve(&target(), None).unwrap();
    let mut other_target = target();
    other_target.tenant = TenantId("other".into());
    let b = f.store.pin().unwrap().resolve(&other_target, None).unwrap();
    assert_eq!(a.release, b.release);
    assert_ne!(a.publication, b.publication);
    assert!(f.store.plan(&a).is_ok());
    assert!(f.store.plan(&b).is_ok());
    let mut forged = b.clone();
    forged.publication = a.publication.clone();
    assert!(f.store.plan(&forged).is_err());
    let reference = primary
        .publication_reference(f.releases.as_ref())
        .unwrap()
        .unwrap();
    f.releases
        .change_publication_lifecycle(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId("tests".into())),
                actor: ReleaseActor {
                    subject: "operator".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: "revoke-primary".into(),
                    expected_generation: 1,
                }),
            },
            &reference,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert!(f.store.plan(&a).is_err());
    assert!(f.store.plan(&b).is_ok());
    assert_eq!(f.store.binding_definitions().unwrap().len(), 2);
    // An unrelated refresh keeps the denied desired row, and cannot block the
    // other tenant merely because its component is byte-identical.
    let current = f.store.read_publication();
    let prepared = run(f.store.prepare_binding_update(
        current.routes.generation,
        current.transaction,
        f.store.binding_definitions().unwrap(),
        f.broker.clone(),
        providers(),
        BindingLimits::default(),
    ))
    .unwrap();
    f.store.commit_binding_update(prepared).unwrap();
    let b = f.store.pin().unwrap().resolve(&other_target, None).unwrap();
    assert!(f.store.plan(&b).is_ok());
}
