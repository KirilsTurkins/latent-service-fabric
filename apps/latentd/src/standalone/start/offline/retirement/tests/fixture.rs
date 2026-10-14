//! Actual signed package, compiled binding and subsystem owners, without guest qualification.
use super::{settings, Catalogs, TempDir};
use crate::{
    config::{ConfiguredProviders, NodeSettings, SupplyChainSettings},
    standalone::{
        audit::AuditRuntime, policies::PolicyRuntime, providers::ProviderRuntime,
        providers::ProviderServices, rollouts::RolloutRuntime, start::control::StartupControl,
        state::SignedFixture,
    },
};
use latent_artifacts::{AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository};
use latent_control_store::{DeploymentStore, DirectoryDeploymentRepository};
use latent_core::{CapabilityId, PolicyId, ResourceBudget, SystemActivationClock, TenantId};
use latent_manifest::CapabilityGrantSpec;
use latent_policy::{
    capability::{MutationRequest, RecordKind},
    supply_chain::SupplyChainAuthority,
};
use serde_json::json;
use std::{sync::Arc, time::Duration, time::Instant};

pub(super) fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(5)
}

#[expect(
    clippy::too_many_lines,
    reason = "the real signed fixture composes the original catalog and configured binding owners"
)]
pub(super) async fn warm(directory: &TempDir) -> (NodeSettings, Catalogs) {
    let mut settings = settings(directory);
    let signed = SignedFixture::new();
    settings.supply_chain = SupplyChainSettings::Enforced {
        policy: serde_json::to_vec(&signed.policy)
            .unwrap()
            .into_boxed_slice(),
        lease_seconds: 5,
    };
    settings.providers = Some(Box::new(serde_json::from_value::<ConfiguredProviders>(json!({
        "formatVersion":1,"clockMonotonic":{"identity":{"id":"clock","tenant":"tests",
            "service":"clock-host","epoch":1}},
        "bindings":[{"name":"clock-binding","tenant":"tests","consumerService":"tests/packaging",
            "providerService":"clock-host","contract":"latent:clock/monotonic@0.1.0",
            "providerBinding":"installed"}]
    })).unwrap()));
    let runtime = tokio::runtime::Handle::current();
    let clock: Arc<dyn latent_core::ActivationClock> = Arc::new(SystemActivationClock);
    let authority = Arc::new(
        SupplyChainAuthority::open_with_runtime(
            &settings.data_directory.join("trust"),
            signed.approved(),
            signed.clock.clone(),
            5,
            Arc::clone(&settings.runtime_profile),
        )
        .unwrap(),
    );
    let control = StartupControl::start(
        authority.clone(),
        settings.load_sample_interval,
        &runtime,
        clock.clone(),
    );
    let audit = AuditRuntime::open(
        settings.data_directory.join("audit"),
        settings.audit,
        runtime.clone(),
    )
    .await
    .unwrap()
    .unwrap();
    let artifacts = Arc::new(
        DirectoryArtifactRepository::open_enforced(
            settings.data_directory.join("releases"),
            settings.artifacts,
            AdmissionStorageLimits::default(),
            authority.clone(),
        )
        .unwrap(),
    );
    let release = artifacts
        .admit_package(&TenantId("tests".into()), signed.upload(), &mut |_| Ok(()))
        .await
        .unwrap();
    let publication = release.publication.as_ref().unwrap();
    let policies = PolicyRuntime::open_with_rejection(
        &settings.data_directory.join("capability-policies"),
        settings.capability_policies,
        artifacts.lifecycle_authority(),
        Some(&runtime),
        None,
    )
    .unwrap()
    .unwrap();
    let deployments = Arc::new(
        DirectoryDeploymentRepository::open_with_catalog(
            settings.data_directory.join("deployments"),
            artifacts.clone(),
            settings.deployments,
            artifacts.lifecycle_authority(),
            Arc::clone(&settings.runtime_profile),
        )
        .await
        .unwrap(),
    );
    let providers = Box::new(
        ProviderRuntime::open(
            &settings,
            &artifacts,
            &deployments,
            policies.handle().store().clone(),
            ProviderServices {
                audit: audit.handle(),
                clock: clock.clone(),
                control: runtime.clone(),
                telemetry: None,
            },
        )
        .await
        .unwrap(),
    );
    let descriptor = serde_json::to_value(&providers.descriptors()[0]).unwrap();
    let grant = json!({"formatVersion":1,"tenant":"tests","rules":[{"id":"allow","effect":"allow",
        "principals":[{"kind":"user","subject":"alice"}],"services":["tests/packaging"],
        "publications":[publication.as_str()],"capability":"latent:clock/monotonic@0.1.0",
        "operations":["now-nanos"],"resources":{"kind":"clock"},
        "ceiling":{"operations":4,"inputBytes":128,"outputBytes":256,"wallTimeMillis":5000}}]});
    let binding = json!({"formatVersion":1,"tenant":"tests","capability":"latent:clock/monotonic@0.1.0",
        "providerProfile":descriptor["profile"],"configurationDigest":descriptor["configurationDigest"],
        "configurationEpoch":1,"restriction":{"operations":[]}});
    for (id, kind, document) in [
        ("clock", RecordKind::Policy, grant),
        ("installed", RecordKind::ProviderBinding, binding),
    ] {
        let document = serde_json::to_vec(&document).unwrap();
        policies
            .handle()
            .store()
            .mutate(
                MutationRequest {
                    tenant: "tests",
                    actor: "operator",
                    id,
                    kind,
                    operation_id: id,
                    expected_revision: 0,
                    document: Some(&document),
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
    }
    let mut deployment = latent_wire::management::deployment_manifest_from_proto(
        latent_wire::management::proto::Deployment {
            id: "consumer".into(),
            metadata: Some(latent_wire::management::proto::ObjectMetadata {
                name: "consumer".into(),
                tenant: Some("tests".into()),
                ..Default::default()
            }),
            service: "tests/packaging".into(),
            release_digest: release.descriptor.release_digest.0.clone(),
            route_weight: 1,
            resources: Some(latent_wire::management::control_budget_to_proto(
                &ResourceBudget {
                    cpu_fuel: 1000,
                    memory_bytes: 65536,
                    wall_time_limit_millis: Some(1000),
                    child_calls: 0,
                    outbound_requests: 0,
                    state_read_bytes: 0,
                    state_write_bytes: 0,
                    blob_read_bytes: 0,
                    blob_write_bytes: 0,
                    log_bytes: 128,
                    effect_count: 0,
                },
            )),
            availability: Some(latent_wire::management::proto::AvailabilityPolicy {
                minimum_cached_copies: 1,
                minimum_zones: 1,
            }),
            placement: Some(latent_wire::management::proto::PlacementPolicy {
                trust_class: "local".into(),
                architectures: vec!["x86_64".into()],
                ..Default::default()
            }),
            ..Default::default()
        },
    )
    .unwrap();
    deployment.grants.push(CapabilityGrantSpec::new(
        CapabilityId("latent:clock/monotonic@0.1.0".into()),
        PolicyId("clock".into()),
    ));
    deployments.apply(deployment).await.unwrap();
    let rollouts = RolloutRuntime::start(
        deployments.clone(),
        audit.handle(),
        settings.rollouts.unwrap().coordinator,
        &runtime,
    )
    .unwrap();
    rollouts.wait_started(deadline()).await.unwrap();
    let catalogs = Catalogs {
        profile: settings.check_config().unwrap(),
        artifacts,
        deployments,
        supply_chain: Some(authority),
        control: Some(control),
        audit: Some(audit),
        rollouts: Some(rollouts),
        policies: Some(policies),
        capabilities: None,
        providers: Some(providers),
        telemetry: None,
        state: None,
        clock,
    };
    catalogs
        .validate_composition(&settings, &catalogs.clock)
        .unwrap();
    (settings, catalogs)
}
