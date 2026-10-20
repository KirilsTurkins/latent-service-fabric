//! Real checked package -> binding compiler -> broker plan; no guest execution.
use super::*;
use crate::bindings::{BindingLimits, ConfiguredBindingProvider};
use crate::DeploymentStore;
use latent_capabilities::broker::ProviderConfiguration;
use latent_core::{CapabilityId, DeploymentId, PlatformErrorCode, PolicyId, ServiceId, TenantId};
use latent_manifest::{CapabilityGrantSpec, JsonManifestCodec, ManifestCodec};
use latent_policy::capability::{MutationRequest, RecordKind};
use serde_json::json;
use std::time::{Duration, Instant};

const PHASE: &str = "latent:http/phase-timing@0.4.0";
const PHASE_PROFILE: &str = "bounded-streaming-http-phase-timing-v1";

fn bundle(legacy_operations: bool) -> latent_packaging::PackageBundle {
    let mut input = package_fixture::phase_type_owner_capsule(legacy_operations);
    package_fixture::mutate_json(&mut input, "capsule.json", |manifest| {
        manifest["metadata"]
            .as_object_mut()
            .unwrap()
            .remove("tenant");
        manifest["metadata"]["name"] = json!("packaging");
    });
    latent_packaging::build_package(input, Default::default()).unwrap()
}

fn phase_definition() -> BindingDefinition {
    let document = json!({"apiVersion":latent_manifest::MANIFEST_API_VERSION,"kind":"Binding",
        "metadata":{"name":"phase-binding","tenant":"tests"},"spec":{
            "consumer":{"service":"packaging","contract":PHASE},
            "provider":{"service":"phase-host","contract":PHASE},"mode":"host"}});
    BindingDefinition {
        manifest: JsonManifestCodec::default()
            .decode_binding(&serde_json::to_vec(&document).unwrap())
            .unwrap(),
        provider_binding_id: "phase-installed".into(),
        allowed_modes: vec![latent_manifest::BindingMode::Host],
        restriction_json: br#"{"operations":[]}"#.to_vec(),
    }
}

fn phase_provider(f: &Fixture) -> ProviderRegistration {
    let digest = format!("sha256:{}", "8".repeat(64));
    let provider = f
        .broker
        .register_provider(ProviderConfiguration {
            capability: PHASE,
            profile: PHASE_PROFILE,
            configuration_digest: &digest,
            configuration_epoch: 1,
            restriction_json: br#"{"operations":[]}"#,
            minimum_call_charges: &[],
        })
        .unwrap();
    let original = f
        .store
        .read_catalog()
        .record_by_id(&DeploymentId("consumer".into()))
        .unwrap()
        .deployment
        .clone();
    let mut deployment = (*original).clone();
    deployment.grants.push(CapabilityGrantSpec::new(
        CapabilityId(PHASE.into()),
        PolicyId("phase".into()),
    ));
    run(f.store.apply(deployment)).unwrap();
    let publication = f
        .store
        .read_catalog()
        .record_by_id(&DeploymentId("consumer".into()))
        .unwrap()
        .publication
        .as_ref()
        .unwrap()
        .as_str()
        .to_owned();
    let policy = json!({"formatVersion":1,"tenant":"tests","rules":[{"id":"phase-only","effect":"allow",
        "principals":[{"kind":"user","subject":"alice"}],"services":["packaging"],"publications":[publication],
        "capability":PHASE,"operations":["open","write","finish","read","chunk-bytes","trailers","abort-upload","abort-body"],
        "resources":{"kind":"http","origins":[{"scheme":"http","host":"127.0.0.1","port":32123}],
            "methods":["GET"],"paths":["/"],"pathPrefixes":[]},
        "ceiling":{"operations":16,"inputBytes":128,"outputBytes":256,"wallTimeMillis":5000}}]});
    let binding = json!({"formatVersion":1,"tenant":"tests","capability":PHASE,"providerProfile":PHASE_PROFILE,
        "configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":[]}});
    for (id, kind, value) in [
        ("phase", RecordKind::Policy, policy),
        ("phase-installed", RecordKind::ProviderBinding, binding),
    ] {
        let bytes = serde_json::to_vec(&value).unwrap();
        f.policies
            .mutate(
                MutationRequest {
                    tenant: "tests",
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
    provider
}

#[test]
fn phase_nominal_owner_compiles_without_legacy_authority_but_phase_and_callable_imports_remain_required(
) {
    for legacy_operations in [false, true] {
        let f = Fixture::with_checked_package(bundle(legacy_operations));
        let phase = phase_provider(&f);
        let current = f.store.read_publication();
        let prepared = run(f.store.prepare_binding_update(
            current.routes.generation,
            current.transaction,
            vec![definition(), phase_definition()],
            f.broker.clone(),
            vec![
                ConfiguredBindingProvider {
                    tenant: TenantId("tests".into()),
                    service: ServiceId("clock-host".into()),
                    reference: f.provider.reference(),
                    local_deployment: None,
                },
                ConfiguredBindingProvider {
                    tenant: TenantId("tests".into()),
                    service: ServiceId("phase-host".into()),
                    reference: phase.reference(),
                    local_deployment: None,
                },
            ],
            BindingLimits::default(),
        ));
        if legacy_operations {
            assert_eq!(
                prepared
                    .err()
                    .expect("callable legacy import needs its binding")
                    .code,
                PlatformErrorCode::PermissionDenied
            );
            assert_eq!(f.store.binding_inventory().1, 0);
            continue;
        }
        f.store.commit_binding_update(prepared.unwrap()).unwrap();
        let revision = f.store.pin().unwrap().resolve(&target(), None).unwrap();
        assert!(f.store.plan(&revision).unwrap().matches_revision(&revision));
        assert_eq!(f.store.binding_inventory().1, 2);
        assert_eq!(f.store.binding_inventory().2, 1);
        // The actual phase grant remains necessary even though this tiny binary
        // prunes every phase operation. No legacy provider/grant exists here.
        let original = f
            .store
            .read_catalog()
            .record_by_id(&DeploymentId("consumer".into()))
            .unwrap()
            .deployment
            .clone();
        let mut missing = (*original).clone();
        missing.grants.retain(|grant| grant.capability.0 != PHASE);
        run(f.store.apply(missing)).unwrap();
        let revision = f.store.pin().unwrap().resolve(&target(), None).unwrap();
        assert_eq!(
            f.store.plan(&revision).err().unwrap().code,
            PlatformErrorCode::PermissionDenied
        );
        run(f.store.apply((*original).clone())).unwrap();
        let revision = f.store.pin().unwrap().resolve(&target(), None).unwrap();
        assert!(f.store.plan(&revision).is_ok());
    }
}
