use super::super::{fixtures, supply_chain::authority};
use super::package_fixture;
pub(super) use crate::bindings::BindingDefinition;
use crate::{
    bindings::{BindingLimits, ConfiguredBindingProvider, PreparedBindingUpdate},
    DeploymentStore,
};
pub(super) use fixtures::{run, TempRoot};
pub(super) use latent_artifacts::ArtifactRepository;
use latent_artifacts::{DirectoryArtifactRepository, PackageAdmissionUpload};
pub(super) use latent_capabilities::broker::{ActivationCapabilityBroker, ProviderRegistration};
use latent_core::{
    CapabilityId, ContractId, FunctionId, PolicyId, SystemActivationClock, TenantId,
};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_policy::capability::{MutationRequest, PolicyStore, RecordKind};
use latent_routing::InvocationTarget;
use serde_json::json;
pub(super) use std::sync::Arc;
use std::time::{Duration, Instant};
pub(super) type Store = crate::DirectoryDeploymentRepository;
const CAP: &str = "latent:clock/monotonic@0.1.0";
pub(super) struct Fixture {
    pub store: Store,
    pub authority: Arc<authority::Authority>,
    pub releases: Arc<DirectoryArtifactRepository>,
    pub broker: Arc<ActivationCapabilityBroker>,
    pub provider: ProviderRegistration,
    pub policies: Arc<PolicyStore>,
    pub roots: [TempRoot; 3],
}
impl Fixture {
    pub fn new() -> Self {
        Self::create(false, Default::default())
    }
    pub fn with_local() -> Self {
        Self::create(true, Default::default())
    }
    pub fn with_plan_limit(maximum_plans: usize) -> Self {
        Self::create(
            false,
            latent_capabilities::broker::CapabilityBrokerLimits {
                maximum_plans,
                ..Default::default()
            },
        )
    }
    fn create(local: bool, limits: latent_capabilities::broker::CapabilityBrokerLimits) -> Self {
        let roots = [TempRoot::new(), TempRoot::new(), TempRoot::new()];
        let bundle = consumer_package();
        let mut bundles = vec![bundle];
        if local {
            bundles.push(super::local::package());
        }
        let artifacts: Vec<_> = bundles.iter().map(artifact).collect();
        let release = artifacts[0].descriptor.release_digest.clone();
        let local_release = artifacts
            .get(1)
            .map(|artifact| artifact.descriptor.release_digest.clone());
        let authority = authority::Authority::new_many(artifacts);
        let releases = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                &roots[0].0,
                Default::default(),
                Default::default(),
                authority.clone(),
            )
            .unwrap(),
        );
        for bundle in bundles {
            let input = bundle.into_input();
            run(releases.admit_package(
                &TenantId("tests".into()),
                PackageAdmissionUpload {
                    manifest: input.manifest,
                    configuration: input.configuration,
                    layers: input.layers,
                    signatures: Vec::new(),
                    provenance: Vec::new(),
                    sboms: Vec::new(),
                },
                &mut |_| Ok(()),
            ))
            .unwrap();
        }
        let store = open(&roots[1], &releases);
        if let Some(local_release) = local_release {
            let mut provider = fixtures::deployment("clock-provider", "tests", &local_release);
            provider.service = latent_core::ServiceId("clock-host".into());
            run(store.apply(provider)).unwrap();
        }
        let mut deployment = fixtures::deployment("consumer", "tests", &release);
        deployment.service = latent_core::ServiceId("packaging".into());
        deployment
            .grants
            .push(latent_manifest::CapabilityGrantSpec::new(
                CapabilityId(CAP.into()),
                PolicyId("clock".into()),
            ));
        run(store.apply(deployment)).unwrap();
        let policies = Arc::new(
            PolicyStore::open(
                &roots[2].0.join("policy"),
                Default::default(),
                releases.lifecycle_authority(),
            )
            .unwrap(),
        );
        let policy = policy(
            store
                .read_catalog()
                .record_by_id(&latent_core::DeploymentId("consumer".into()))
                .unwrap()
                .publication
                .as_ref()
                .unwrap()
                .as_str(),
        );
        let digest = format!("sha256:{}", "7".repeat(64));
        for (id, kind, value) in [
            ("clock", RecordKind::Policy, policy),
            (
                "installed",
                RecordKind::ProviderBinding,
                json!({"formatVersion":1,"tenant":"tests","capability":CAP,"providerProfile":"clock-v1","configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":[]}}),
            ),
        ] {
            let bytes = serde_json::to_vec(&value).unwrap();
            policies
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
                    deadline(),
                    |_| Ok(()),
                )
                .unwrap();
        }
        let broker = Arc::new(
            ActivationCapabilityBroker::new(
                releases.lifecycle_authority(),
                policies.clone(),
                Arc::new(SystemActivationClock),
                limits,
            )
            .unwrap(),
        );
        let provider = broker
            .register_provider(latent_capabilities::broker::ProviderConfiguration {
                capability: CAP,
                profile: "clock-v1",
                configuration_digest: &digest,
                configuration_epoch: 1,
                restriction_json: br#"{"operations":[]}"#,
                minimum_call_charges: &[],
            })
            .unwrap();
        Self {
            store,
            authority,
            releases,
            broker,
            provider,
            policies,
            roots,
        }
    }
    pub fn install(&self) {
        self.store
            .commit_binding_update(
                prepare(
                    &self.store,
                    self.broker.clone(),
                    &self.provider,
                    vec![definition()],
                )
                .unwrap(),
            )
            .unwrap();
    }
    pub fn replace_policy(&self) {
        let bytes = serde_json::to_vec(&policy(
            self.store
                .read_catalog()
                .record_by_id(&latent_core::DeploymentId("consumer".into()))
                .unwrap()
                .publication
                .as_ref()
                .unwrap()
                .as_str(),
        ))
        .unwrap();
        self.policies
            .mutate(
                MutationRequest {
                    tenant: "tests",
                    actor: "operator",
                    id: "clock",
                    kind: RecordKind::Policy,
                    operation_id: "replace",
                    expected_revision: self
                        .policies
                        .get("tests", RecordKind::Policy, "clock", 65536, deadline())
                        .unwrap()
                        .value()
                        .as_ref()
                        .unwrap()
                        .revision,
                    document: Some(&bytes),
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
    }
}
fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(10)
}
fn policy(publication: &str) -> serde_json::Value {
    json!({"formatVersion":1,"tenant":"tests","rules":[{"id":"allow","effect":"allow","principals":[{"kind":"user","subject":"alice"}],"services":["packaging"],"publications":[publication],"capability":CAP,"operations":["now-nanos"],"resources":{"kind":"clock"},"ceiling":{"operations":4,"inputBytes":128,"outputBytes":256,"wallTimeMillis":5000}}]})
}
pub(super) fn open(root: &TempRoot, releases: &Arc<DirectoryArtifactRepository>) -> Store {
    run(Store::open_with_catalog(
        &root.0,
        releases.clone(),
        Default::default(),
        releases.lifecycle_authority(),
        Arc::new(
            latent_manifest::RuntimeCompatibilityProfile::new(
                "wasmtime",
                "47.0.4",
                "x86_64-unknown-linux-gnu",
                &["x86_64.sse2"],
                64 * 1024 * 1024,
                100_000_000,
            )
            .unwrap(),
        ),
    ))
    .unwrap()
}
pub(super) fn target() -> InvocationTarget {
    InvocationTarget {
        tenant: TenantId("tests".into()),
        service: latent_core::ServiceId("packaging".into()),
        contract: ContractId(package_fixture::component::CONTRACT.into()),
        function: FunctionId("inspect".into()),
        route: None,
    }
}
pub(super) fn definition() -> BindingDefinition {
    let document = json!({"apiVersion":latent_manifest::MANIFEST_API_VERSION,"kind":"Binding","metadata":{"name":"clock-binding","tenant":"tests"},"spec":{"consumer":{"service":"packaging","contract":CAP},"provider":{"service":"clock-host","contract":CAP},"mode":"host"}});
    BindingDefinition {
        manifest: JsonManifestCodec::default()
            .decode_binding(&serde_json::to_vec(&document).unwrap())
            .unwrap(),
        provider_binding_id: "installed".into(),
        allowed_modes: vec![latent_manifest::BindingMode::Host],
        restriction_json: br#"{"operations":[]}"#.to_vec(),
    }
}
pub(super) fn prepare(
    store: &Store,
    broker: Arc<ActivationCapabilityBroker>,
    provider: &ProviderRegistration,
    definitions: Vec<BindingDefinition>,
) -> Result<PreparedBindingUpdate, latent_core::PlatformError> {
    let current = store.read_publication();
    run(store.prepare_binding_update(
        current.routes.generation,
        current.transaction,
        definitions,
        broker,
        vec![ConfiguredBindingProvider {
            tenant: TenantId("tests".into()),
            service: latent_core::ServiceId("clock-host".into()),
            reference: provider.reference(),
            local_deployment: None,
        }],
        BindingLimits::default(),
    ))
}

fn artifact(bundle: &latent_packaging::PackageBundle) -> latent_artifacts::CapsuleArtifact {
    let mut artifact = fixtures::artifact("checked-binding");
    artifact.manifest = JsonManifestCodec::default()
        .decode_capsule(bundle.blob("capsule.json").unwrap())
        .unwrap();
    artifact.component_bytes = bundle.blob("component.wasm").unwrap().to_vec();
    artifact.descriptor.release_digest = artifact.manifest.component_digest.clone();
    artifact.descriptor.size_bytes = artifact.component_bytes.len() as u64;
    artifact.contracts = latent_artifacts::decode_contract_metadata(
        bundle.blob("contracts.json").unwrap(),
        Default::default(),
    )
    .unwrap();
    artifact
}

// Tenant-agnostic immutable content receives a separate tenant admission below.
pub(super) fn consumer_package() -> latent_packaging::PackageBundle {
    let mut input = package_fixture::capsule(Default::default());
    package_fixture::mutate_json(&mut input, "capsule.json", |m| {
        m["metadata"].as_object_mut().unwrap().remove("tenant");
        m["metadata"]["name"] = json!("packaging");
    });
    latent_packaging::build_package(input, Default::default()).unwrap()
}
