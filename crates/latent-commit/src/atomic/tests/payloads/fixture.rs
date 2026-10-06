//! Reuse the existing real publication/broker fixture; no guest execution claim.
use latent_capabilities::broker::*;
#[path = "../../../../../latent-capabilities/src/broker/tests/fixture.rs"]
mod authority;
use super::super::*;
use latent_blobs::{
    local::{LocalBlobLimits, LocalBlobStore},
    provider::{CapturedLocalPayload, LocalBlobProvider},
};
use latent_capabilities::broker::{
    blob::BlobReference,
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
};
use latent_policy::capability::{MutationRequest, RecordKind};
use latent_state::{
    store_identity::StoreIdentity,
    tenant::{TenantQuota, TenantUsage},
};
use serde_json::json;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

pub struct Fixture {
    pub authority: authority::Fixture,
    pub provider: LocalBlobProvider,
    pub state: EmbeddedStore,
    pub blob: latent_core::BlobReference,
    pub session: CapabilitySession,
    pub effects: EffectAuthorityOwner,
    pub root: tempfile::TempDir,
}
impl Fixture {
    pub fn new() -> Self {
        let authority = authority::Fixture::new(CapabilityBrokerLimits::default());
        let root = tempfile::tempdir().unwrap();
        let state = open(&root.path().join("state.redb"));
        let view = state.snapshot().unwrap();
        let initialized = StoreIdentity::new("payload-envelope-a".into())
            .unwrap()
            .prepare_initialization(&view)
            .unwrap()
            .unwrap();
        drop(view);
        state.apply(initialized).unwrap();
        let view = state.snapshot().unwrap();
        let quota = TenantQuota {
            tenant: TenantId("a".into()),
            limits: TenantUsage {
                state_keys: 128,
                state_bytes: 4 * 1024 * 1024,
                tombstone_keys: 128,
                tombstone_bytes: 4 * 1024 * 1024,
                result_rows: 128,
                result_bytes: 4 * 1024 * 1024,
                effect_rows: 128,
                effect_bytes: 4 * 1024 * 1024,
                payload_bytes: 4 * 1024 * 1024,
                recovery_bytes: 4 * 1024 * 1024,
                metadata_rows: 1024,
                metadata_bytes: 8 * 1024 * 1024,
            },
        };
        let installed = latent_state::tenant::prepare_install(&view, &[quota]).unwrap();
        drop(view);
        installed.publish(&state, || Ok::<_, ()>(())).unwrap();
        let namespace = NamespaceRecord {
            tenant: TenantId("a".into()),
            id: StateNamespaceId("aggregate".into()),
            version: NamespaceVersion {
                incarnation: 1,
                generation: 1,
            },
            state_schema: schema(),
            status: NamespaceStatus::Active,
            quota: NamespaceQuota::default(),
            pins: NamespacePins::default(),
        };
        state
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: RowKey {
                        family: Family::Namespace,
                        key: namespace_record_key(&namespace.tenant, &namespace.id).unwrap(),
                    },
                    value: Some(namespace.encode().unwrap()),
                }],
            })
            .unwrap();
        let blobs = root.path().join("blobs");
        std::fs::create_dir(&blobs).unwrap();
        let store = LocalBlobStore::open_durable(
            &blobs,
            "private",
            LocalBlobLimits {
                maximum_objects: 4,
                maximum_object_bytes: 64,
                maximum_disk_bytes: 65536,
                maximum_stages: 4,
                maximum_stage_bytes: 128,
                maximum_handles: 8,
                maximum_chunk_bytes: 8,
                ..LocalBlobLimits::default()
            },
            &state,
        )
        .unwrap();
        let mut writer = store
            .create(
                &TenantId("a".into()),
                "application/octet-stream",
                Some(4),
                &|| Ok(()),
            )
            .unwrap();
        writer.write(0, b"body", &|| Ok(())).unwrap();
        let blob = writer.seal(&|| Ok(())).unwrap();
        let pools = Arc::new(
            ProviderPools::new(
                authority.broker.clone(),
                Arc::new(IoRuntime::new(IoLimits::default()).unwrap()),
                tokio::runtime::Handle::current(),
                ProviderPoolLimits::default(),
            )
            .unwrap(),
        );
        let provider = LocalBlobProvider::install(pools, "payload-local", 1, 0, store).unwrap();
        let reference = provider.reference();
        let publication = authority.publication.publication().as_str();
        for (id, kind, value) in [
            (
                "payload-policy",
                RecordKind::Policy,
                json!({"formatVersion":1,"tenant":"a","rules":[{"id":"open","effect":"allow","principals":[{"kind":"user","subject":"alice"}],"services":["echo"],"publications":[publication],"capability":"latent:blob/blob@0.2.0","operations":["open"],"resources":{"kind":"blob","namespaces":["private"]},"ceiling":{"operations":32,"inputBytes":4096,"outputBytes":4096,"wallTimeMillis":15000}}]}),
            ),
            (
                "payload-binding",
                RecordKind::ProviderBinding,
                json!({"formatVersion":1,"tenant":"a","capability":"latent:blob/blob@0.2.0","providerProfile":"linux-immutable-blobs-v1","configurationDigest":provider.store().configuration_digest().unwrap(),"configurationEpoch":1,"restriction":{"operations":[]}}),
            ),
        ] {
            let raw = serde_json::to_vec(&value).unwrap();
            authority
                .policies
                .mutate(
                    MutationRequest {
                        tenant: "a",
                        actor: "operator",
                        id,
                        kind,
                        operation_id: id,
                        expected_revision: 0,
                        document: Some(&raw),
                    },
                    Instant::now() + Duration::from_secs(15),
                    |_| Ok(()),
                )
                .unwrap();
        }
        let plan = authority
            .broker
            .compile_invocation_plan(
                &authority.revision,
                Some(&latent_core::DeploymentId("echo-deployment".into())),
                &[CapabilityBindingSpec {
                    definition_digest: Some(&latent_artifacts::package::artifact_blob_digest(
                        b"payload fixture binding v1",
                    )),
                    provider: &reference,
                    imported_operations: &["open".into()],
                    policy_ids: &["payload-policy".into()],
                    provider_binding_id: "payload-binding",
                    deployment_restriction_json: br#"{"operations":[]}"#,
                }],
                &authority.publication,
                &[],
                &[],
                &[],
                None,
                Instant::now() + Duration::from_secs(15),
            )
            .unwrap();
        let (mut request, mut control) = authority.request("payload-command");
        request.imports = vec![latent_executor::BoundImport {
            capability: latent_core::CapabilityId("latent:blob/blob@0.2.0".into()),
            contract: "latent:blob/blob@0.2.0".into(),
            opaque_handle: "not-authority".into(),
        }];
        request.budget.blob_read_bytes = 65536;
        request.budget.outbound_requests = 32;
        request.activation.budget = request.budget.clone();
        control.budget = latent_core::ActivationBudget::new(
            latent_core::EffectiveActivationBudget::admit_at(
                &request.budget,
                &request.budget,
                &request.budget,
                None,
                latent_core::ClockSample::system_now(),
            )
            .unwrap(),
        );
        request.activation.deadline_unix_millis = control.budget.deadline().unix_millis();
        let session = authority
            .broker
            .open_session(plan, &request, &control, &authority.publication)
            .unwrap();
        let effects = EffectAuthorityOwner::new(4, 4, 0).unwrap();
        effects
            .publish(EffectRule {
                scope: EffectScope {
                    tenant: "a".into(),
                    namespace: "aggregate".into(),
                    incarnation: 1,
                    publication: publication.into(),
                    binding: "approved-event".into(),
                    operation: "event".into(),
                },
                profile: DispatchProfile {
                    provider: "events".into(),
                    destination: "events.subject".into(),
                    adapter: "qualified-test-v1".into(),
                    intent_format: 1,
                    payload_format: "lsf-value-v1".into(),
                    idempotency_profile: "qualified-test-idempotency-v1".into(),
                },
                policy_revision: 1,
                credential_epoch: 1,
                protected_credential_reference: "protected-events".into(),
                ceiling: DispatchCeiling {
                    maximum_payload_bytes: 1024,
                    maximum_response_bytes: 1024,
                    maximum_attempts: 3,
                    maximum_age_millis: 5000,
                    attempt_timeout_millis: 100,
                },
                enabled: true,
            })
            .unwrap();
        Self {
            authority,
            provider,
            state,
            blob,
            session,
            effects,
            root,
        }
    }
    pub fn input(&self, key: &str) -> AdmissionInput {
        let mut request = input(key);
        request.key.tenant = "a".into();
        request.source.publication = self.authority.publication.publication().as_str().into();
        request
    }
    pub fn claim(&self, key: &str) -> AdmittedCommand {
        let view = self.state.snapshot().unwrap();
        let AdmissionDecision::New(prepared) =
            PreparedAdmission::prepare(&view, self.input(key), time(100), |_, _| Ok(())).unwrap()
        else {
            panic!("new physical claim");
        };
        drop(view);
        prepared.publish(&self.state, || Ok(())).unwrap()
    }
    pub async fn capture(&self) -> CapturedLocalPayload {
        tokio::time::timeout(
            Duration::from_secs(15),
            self.provider
                .capture_reference(
                    &self.session,
                    BlobReference {
                        digest: self.blob.digest.0.clone(),
                        size: self.blob.size_bytes,
                        media_type: self.blob.media_type.clone(),
                    },
                )
                .unwrap(),
        )
        .await
        .unwrap()
        .unwrap()
    }
}
