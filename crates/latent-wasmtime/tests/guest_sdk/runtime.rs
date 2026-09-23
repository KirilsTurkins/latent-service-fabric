//! Explicit test-operator grants for a managed guest's runtime effects.
//! Used only by the language-selected SDK gate, never by production admission.
#![allow(dead_code)]
use latent_artifacts::ReleaseUseEligibility;
use latent_capabilities::broker::{
    random::RandomProvider, ActivationCapabilityBroker, ActivationCapabilityRuntime,
    CapabilityBindingSpec, ProviderBudgetRequirement, ProviderConfiguration, ProviderReference,
    ProviderRegistration,
};
use latent_core::{ArtifactBlobDigest, BudgetDimension, CapabilityId, PolicyId, PublicationId};
use latent_manifest::{BindingMode, CapabilityGrantSpec, JsonManifestCodec, ManifestCodec};
use latent_policy::capability::{MutationRequest, PolicyStore, RecordKind};
use serde_json::json;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

const CLOCKS: [(&str, &str, &str); 2] = [
    (
        "latent:clock/monotonic@0.1.0",
        "activation-monotonic-v1",
        "now-nanos",
    ),
    (
        "latent:clock/wall@0.1.0",
        "activation-wall-v1",
        "now-unix-millis",
    ),
];
const RANDOM: &str = "latent:random/random@0.1.0";

pub fn enabled() -> bool {
    matches!(
        std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(),
        Ok("go" | "java")
    )
}

pub fn java() -> bool {
    std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref() == Ok("java")
}

fn capabilities() -> &'static [&'static str] {
    if java() {
        &[CLOCKS[0].0, CLOCKS[1].0]
    } else {
        &[CLOCKS[0].0, CLOCKS[1].0, RANDOM]
    }
}

pub fn memory(default: u64) -> u64 {
    if enabled() {
        64 * 1024 * 1024
    } else {
        default
    }
}

struct Entry {
    reference: ProviderReference,
    operation: Vec<String>,
    policy: Vec<String>,
    binding: String,
    definition: ArtifactBlobDigest,
}

#[derive(Default)]
pub struct Runtime {
    entries: Vec<Entry>,
    clocks: Vec<ProviderRegistration>,
    random: Option<Arc<RandomProvider>>,
}

impl Runtime {
    pub fn entropy_calls(&self) -> u64 {
        self.random
            .as_ref()
            .map_or(0, |provider| provider.snapshot().u64_calls)
    }

    pub fn new(
        broker: &ActivationCapabilityBroker,
        policies: &PolicyStore,
        publication: &ReleaseUseEligibility,
        main_capability: &str,
    ) -> Self {
        Self::scoped(
            broker,
            policies,
            "tests",
            &["generic"],
            &[publication.publication().clone()],
            ("service", "generic-test"),
            main_capability == RANDOM,
        )
    }

    pub fn scoped(
        broker: &ActivationCapabilityBroker,
        policies: &PolicyStore,
        tenant: &str,
        services: &[&str],
        publications: &[PublicationId],
        principal: (&str, &str),
        existing_random: bool,
    ) -> Self {
        let mut owner = Self::default();
        if !enabled() {
            return owner;
        }
        for (capability, profile, operation) in CLOCKS {
            let digest = latent_artifacts::package::artifact_blob_digest(profile.as_bytes());
            let registration = broker
                .register_provider(ProviderConfiguration {
                    capability,
                    profile,
                    configuration_digest: digest.as_str(),
                    configuration_epoch: 1,
                    restriction_json: br#"{"operations":[]}"#,
                    minimum_call_charges: &[ProviderBudgetRequirement {
                        operation,
                        dimension: BudgetDimension::CpuFuel,
                        minimum: 100,
                    }],
                })
                .unwrap();
            owner.add(registration.reference(), operation);
            owner.clocks.push(registration);
        }
        if !existing_random && !java() {
            let random = RandomProvider::system(
                broker,
                1,
                latent_capabilities::broker::random::RandomLimits::default(),
            )
            .unwrap();
            owner.add(random.reference(), "u64-value");
            owner.random = Some(random);
        }
        for entry in &owner.entries {
            let capability = entry.reference.capability();
            for (id, kind, document) in [
                (
                    entry.policy[0].as_str(),
                    RecordKind::Policy,
                    json!({
                        "formatVersion":1,"tenant":tenant,"rules":[{
                            "id":"runtime","effect":"allow",
                            "principals":[{"kind":principal.0,"subject":principal.1}],
                            "services":services,"publications":publications.iter().map(PublicationId::as_str).collect::<Vec<_>>(),
                            "capability":capability,"operations":entry.operation,
                            "resources":{"kind":if capability == RANDOM {"random"} else {"clock"}},
                            "ceiling":{"operations":4096,"inputBytes":0,"outputBytes":32768,"wallTimeMillis":5000}
                        }]
                    }),
                ),
                (
                    entry.binding.as_str(),
                    RecordKind::ProviderBinding,
                    json!({
                        "formatVersion":1,"tenant":tenant,"capability":capability,
                        "providerProfile":entry.reference.profile(),
                        "configurationDigest":entry.reference.configuration_digest(),
                        "configurationEpoch":1,"restriction":{"operations":entry.operation}
                    }),
                ),
            ] {
                policies
                    .mutate(
                        MutationRequest {
                            tenant,
                            actor: "sdk-runtime-operator",
                            id,
                            kind,
                            operation_id: id,
                            expected_revision: 0,
                            document: Some(&serde_json::to_vec(&document).unwrap()),
                        },
                        Instant::now() + Duration::from_secs(10),
                        |_| Ok(()),
                    )
                    .unwrap();
            }
        }
        owner
    }

    fn add(&mut self, reference: ProviderReference, operation: &str) {
        let id = self.entries.len();
        self.entries.push(Entry {
            reference,
            operation: vec![operation.into()],
            policy: vec![format!("sdk-runtime-policy-{id}")],
            binding: format!("sdk-runtime-binding-{id}"),
            definition: latent_artifacts::package::artifact_blob_digest(operation.as_bytes()),
        });
    }

    pub fn bindings<'a>(
        &'a self,
        original: &[CapabilityBindingSpec<'a>],
    ) -> Vec<CapabilityBindingSpec<'a>> {
        original
            .iter()
            .map(|v| CapabilityBindingSpec {
                definition_digest: v.definition_digest,
                provider: v.provider,
                imported_operations: v.imported_operations,
                policy_ids: v.policy_ids,
                provider_binding_id: v.provider_binding_id,
                deployment_restriction_json: v.deployment_restriction_json,
            })
            .chain(self.entries.iter().map(|v| CapabilityBindingSpec {
                definition_digest: Some(&v.definition),
                provider: &v.reference,
                imported_operations: &v.operation,
                policy_ids: &v.policy,
                provider_binding_id: &v.binding,
                deployment_restriction_json: br#"{"operations":[]}"#,
            }))
            .collect()
    }

    pub fn install(&self, runtime: &ActivationCapabilityRuntime) {
        if let Some(random) = &self.random {
            runtime.install_random(random.clone()).unwrap();
        }
    }

    pub fn definitions(
        &self,
        tenant: &str,
        services: &[&str],
    ) -> Vec<latent_control_store::bindings::BindingDefinition> {
        self.entries.iter().flat_map(|entry| services.iter().map(move |service| {
            let document = json!({"apiVersion":latent_manifest::MANIFEST_API_VERSION,"kind":"Binding",
                "metadata":{"name":format!("{}-{service}",entry.binding),"tenant":tenant},
                "spec":{"consumer":{"service":service,"contract":entry.reference.capability()},
                    "provider":{"service":"sdk-runtime","contract":entry.reference.capability()},"mode":"host"}});
            latent_control_store::bindings::BindingDefinition {
                manifest:JsonManifestCodec::default().decode_binding(&serde_json::to_vec(&document).unwrap()).unwrap(),
                provider_binding_id:entry.binding.clone(),allowed_modes:vec![BindingMode::Host],
                restriction_json:br#"{"operations":[]}"#.to_vec(),
            }
        })).collect()
    }

    pub fn providers(
        &self,
        tenant: &str,
    ) -> Vec<latent_control_store::bindings::ConfiguredBindingProvider> {
        self.entries
            .iter()
            .map(
                |entry| latent_control_store::bindings::ConfiguredBindingProvider {
                    tenant: latent_core::TenantId(tenant.into()),
                    service: latent_core::ServiceId("sdk-runtime".into()),
                    reference: entry.reference.clone(),
                    local_deployment: None,
                },
            )
            .collect()
    }
}

pub fn grants() -> Vec<CapabilityGrantSpec> {
    if !enabled() {
        return vec![];
    }
    capabilities()
        .iter()
        .enumerate()
        .map(|(i, capability)| {
            CapabilityGrantSpec::new(
                CapabilityId((*capability).into()),
                PolicyId(format!("sdk-runtime-policy-{i}")),
            )
        })
        .collect()
}

pub fn imports(request: &mut latent_executor::ExecutionRequest) {
    if !enabled() {
        return;
    }
    for &capability in capabilities() {
        if !request
            .imports
            .iter()
            .any(|value| value.contract == capability)
        {
            request.imports.push(latent_executor::BoundImport {
                capability: CapabilityId(capability.into()),
                contract: capability.into(),
                opaque_handle: "descriptive-only".into(),
            });
        }
    }
}
