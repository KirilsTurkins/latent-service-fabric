//! A genuinely derived protected PHASE4 input and persisted signed binding graph.
use super::{Catalogs, NodeSettings, TempDir};
use crate::{config::NodeConfig, standalone::state::SignedFixture};
use latent_artifacts::ArtifactRepository;
use latent_control_store::DeploymentStore;
use latent_core::{CapabilityId, PolicyId, ResourceBudget, TenantId};
use latent_manifest::CapabilityGrantSpec;
use latent_policy::capability::{MutationRequest, RecordKind};
use latent_policy::supply_chain::{SupplyChainClock, SystemSupplyChainClock};
use serde_json::json;
use std::{
    os::unix::fs::PermissionsExt,
    path::Path,
    time::{Duration, Instant},
};

fn write_protected(path: &Path, value: &serde_json::Value) {
    std::fs::write(path, serde_json::to_vec(value).unwrap()).unwrap();
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).unwrap();
}

fn settings(directory: &TempDir, signed: &SignedFixture) -> NodeSettings {
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let policy = directory.path().join("policy.json");
    write_protected(&policy, &signed.policy);
    let mut state = crate::config::state::tests::input();
    state["checkpointRoot"] = json!(directory.path().join("checkpoint"));
    state["operations"] = json!([]);
    state["tenantQuotas"] = json!([]);
    state["store"]["recovery"]["maximumJobBytes"] = 8_396_800_u64.into();
    state["store"]["recovery"]["retainedBytes"] = 16_777_216_u64.into();
    let path = directory.path().join("node.json");
    write_protected(
        &path,
        &json!({
            "formatVersion":1,"dataDirectory":directory.path().join("node"),
            "nodeId":"catalog-retirement","bind":"127.0.0.1:0","shutdownGraceMillis":5000,
            "budgetProfile":{"mode":"phase4","maximumStateReadBytes":0,"maximumStateWriteBytes":0,
                "maximumEffectCount":0,"maximumOutboundRequests":8,
                "maximumBlobReadBytes":65536,"maximumBlobWriteBytes":65536},
            "credentials":[{"token":"LSF-PUBLIC-CATALOG-RETIREMENT-TEST-ONLY",
                "subject":"operator","tenant":"tests","role":"operator"}],
            "audit":{"mode":"durable"},"rollouts":{"mode":"manual"},
            "capabilityPolicies":{"formatVersion":1},"state":state,
            "supplyChain":{"mode":"enforced","policyFile":policy,"clockLeaseSeconds":5},
            "providers":{"formatVersion":1,"clockMonotonic":{"identity":{"id":"clock",
                "tenant":"tests","service":"clock-host","epoch":1}},
                "bindings":[{"name":"clock-binding","tenant":"tests","consumerService":"tests/packaging",
                    "providerService":"clock-host","contract":"latent:clock/monotonic@0.1.0",
                    "providerBinding":"installed"}]}
        }),
    );
    let config = NodeConfig::load(&path).unwrap();
    let settings = config.derive().unwrap();
    assert!(settings.credentials_from_protected_file);
    assert_eq!(settings.budget_profile, latent_core::BudgetProfile::Phase4);
    assert!(settings.state.as_ref().unwrap().operations.is_empty());
    settings
}

#[expect(
    clippy::too_many_lines,
    reason = "The new public-inspector input persists its authentic signed package, policy and compiled binding before retiring the setup owners"
)]
pub(super) async fn warm(directory: &TempDir) -> NodeSettings {
    let signed = SignedFixture::freshly_signed();
    let settings = settings(directory, &signed);
    let catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let release = catalogs
        .artifacts
        .admit_package(&TenantId("tests".into()), signed.upload(), &mut |_| Ok(()))
        .await
        .unwrap();
    let publication = release.publication.as_ref().unwrap();
    let descriptor =
        serde_json::to_value(&catalogs.providers.as_ref().unwrap().descriptors()[0]).unwrap();
    let grant = json!({"formatVersion":1,"tenant":"tests","rules":[{"id":"allow","effect":"allow",
        "principals":[{"kind":"user","subject":"alice"}],"services":["tests/packaging"],
        "publications":[publication.as_str()],"capability":"latent:clock/monotonic@0.1.0",
        "operations":["now-nanos"],"resources":{"kind":"clock"},
        "ceiling":{"operations":4,"inputBytes":128,"outputBytes":256,"wallTimeMillis":5000}}]});
    let binding = json!({"formatVersion":1,"tenant":"tests","capability":"latent:clock/monotonic@0.1.0",
        "providerProfile":descriptor["profile"],"configurationDigest":descriptor["configurationDigest"],
        "configurationEpoch":1,"restriction":{"operations":[]}});
    let deadline = catalogs.state.as_ref().unwrap().deadline;
    for (id, kind, document) in [
        ("clock", RecordKind::Policy, grant),
        ("installed", RecordKind::ProviderBinding, binding),
    ] {
        let document = serde_json::to_vec(&document).unwrap();
        catalogs
            .policies
            .as_ref()
            .unwrap()
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
                deadline,
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
    catalogs.deployments.apply(deployment).await.unwrap();
    catalogs
        .validate_composition(&settings, &catalogs.clock)
        .unwrap();
    assert_eq!(catalogs.deployments.binding_inventory().2, 1);
    let policy = catalogs.policies.as_ref().unwrap().handle().store().clone();
    assert!(policy.retained_read_owners() > 0);
    let native = catalogs.state.as_ref().unwrap().native.clone();
    assert!(Instant::now() < deadline);
    assert!(catalogs.retire_recovery(&settings).await);
    assert_eq!(policy.retained_read_owners(), 0);
    assert!(native.snapshot().unwrap().physically_retired());
    await_original_restart_floor(&settings).await;
    settings
}

async fn await_original_restart_floor(settings: &NodeSettings) {
    let path = settings.data_directory.join("supply-chain/floor.json");
    let original = std::fs::read(&path).unwrap();
    let floor: serde_json::Value = serde_json::from_slice(&original).unwrap();
    let restart_not_before = floor["restartNotBefore"].as_u64().unwrap();
    let until = Instant::now() + settings.shutdown_grace();
    tokio::time::timeout_at(until.into(), async {
        while SystemSupplyChainClock.now().unwrap() < restart_not_before {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("the retired setup owner's original restart floor must elapse");
    assert_eq!(std::fs::read(path).unwrap(), original);
}
