//! Signed event installation with a real installed provider and protected credential.
use super::*;
use latent_capabilities::broker::{
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
    secrets::TlsCredentialScope,
    ActivationCapabilityBroker, CapabilityBrokerLimits,
};
use latent_core::SystemActivationClock;
use latent_effects::{
    authority::{CommitLink, EffectScope},
    runtime::DeferredEffectAdapter,
};
use latent_nats::deferred::DeferredEventAuthorization;
use latent_nats::{
    deferred::JetStreamQualification, NatsConfig, NatsCredential, NatsEndpoint, NatsPublisher,
    TopicMapping,
};
use latent_secrets::{
    LocalSecretStore, SecretLimits, SecretPurpose, SecretSource, SecretSpec, SystemSecretClock,
};
use std::os::unix::fs::PermissionsExt;

pub(super) struct EventFixture {
    _root: tempfile::TempDir,
    _catalog: Arc<DirectoryArtifactRepository>,
    _policy: Arc<PolicyStore>,
    pools: Arc<ProviderPools>,
    secrets: LocalSecretStore,
    publisher: NatsPublisher,
}
impl EventFixture {
    #[expect(
        clippy::too_many_lines,
        reason = "The real provider retains its broker, protected credential and pools until physical shutdown"
    )]
    async fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let catalog = Arc::new(
            DirectoryArtifactRepository::open(
                root.path().join("catalog"),
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        );
        let policy = Arc::new(
            PolicyStore::open(
                &root.path().join("policy"),
                PolicyStoreLimits::default(),
                catalog.lifecycle_authority(),
            )
            .unwrap(),
        );
        let broker = Arc::new(
            ActivationCapabilityBroker::new(
                catalog.lifecycle_authority(),
                policy.clone(),
                Arc::new(SystemActivationClock),
                CapabilityBrokerLimits::default(),
            )
            .unwrap(),
        );
        let pools = Arc::new(
            ProviderPools::new(
                broker,
                Arc::new(IoRuntime::new(IoLimits::default()).unwrap()),
                tokio::runtime::Handle::current(),
                ProviderPoolLimits::default(),
            )
            .unwrap(),
        );
        let config = NatsConfig {
            format_version: 1,
            endpoint: NatsEndpoint {
                server_name: "localhost".into(),
                peer: "127.0.0.1:4222".parse().unwrap(),
                allow_non_public_peer: true,
            },
            public_roots: true,
            extra_roots: vec![],
            topics: vec![TopicMapping {
                tenant: "tests".into(),
                topic: "updated".into(),
                subject: "lsf.allowed".into(),
                stream: "DURABLE".into(),
                duplicate_window_millis: 30_000,
            }],
            idempotency_namespace: "fixture".into(),
            maximum_payload_bytes: 8192,
            timeout_millis: 5000,
        };
        let directory = root.path().join("secrets");
        std::fs::create_dir(&directory).unwrap();
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
        std::fs::write(directory.join("password"), b"fixture-secret").unwrap();
        std::fs::set_permissions(
            directory.join("password"),
            std::fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        let deadline = Instant::now() + Duration::from_secs(20);
        let secrets = LocalSecretStore::open_before(
            pools.clone(),
            directory,
            SecretLimits::default(),
            vec![],
            Arc::new(SystemSecretClock),
            deadline,
        )
        .unwrap()
        .await
        .unwrap();
        secrets
            .reload_before(
                0,
                vec![SecretSpec {
                    tenant: TenantId("tests".into()),
                    reference: "event-secret".into(),
                    source: SecretSource::File {
                        name: "password".into(),
                    },
                    purpose: SecretPurpose::TlsProviderCredential {
                        provider_id: "events".into(),
                        destination: config.endpoint.credential_destination(),
                    },
                    media_type: "application/octet-stream".into(),
                    version: "1".into(),
                    expires_at_unix_millis: None,
                }],
                deadline,
            )
            .unwrap()
            .await
            .unwrap();
        let credential = secrets
            .bind_tls_credential(
                TlsCredentialScope {
                    tenant: TenantId("tests".into()),
                    provider_id: "events".into(),
                    destination: config.endpoint.credential_destination(),
                },
                "event-secret".into(),
            )
            .unwrap();
        let publisher = NatsPublisher::install(
            pools.clone(),
            "events",
            1,
            0,
            config,
            vec![NatsCredential {
                username: Some("fixture".into()),
                secret: credential,
            }],
        )
        .unwrap();
        Self {
            _root: root,
            _catalog: catalog,
            _policy: policy,
            pools,
            secrets,
            publisher,
        }
    }
    fn adapter(&self, clock: Arc<AdapterClock>) -> latent_nats::deferred::JetStreamEffectAdapter {
        self.publisher
            .deferred_adapter(
                "tests",
                "updated",
                JetStreamQualification {
                    format_version: 1,
                    server_version: "2.14.6".into(),
                    stream_created: "2026-01-01T00:00:00Z".into(),
                    maximum_messages: 1000,
                    maximum_bytes: 1_000_000,
                    maximum_age_millis: 60_000,
                    maximum_message_bytes: 16_384,
                },
                clock,
            )
            .unwrap()
    }
    pub(super) fn installation(&self) -> super::super::InstalledHttpEffects {
        let mut installed = super::super::InstalledHttpEffects::empty();
        installed.events = vec![Arc::new(
            self.adapter(installed.clock.clone())
                .with_authorization(installed.event_registry.clone()),
        )];
        installed
    }
    fn requirements(&self) -> Vec<u8> {
        let adapter = self.adapter(Arc::new(AdapterClock::default()));
        serde_json::to_vec(&json!({"formatVersion":1,"protocol":"lsf-jetstream-event-v1", "capsule":"tests/packaging","deployment":"deployment","stateBinding":"binding","namespace":"orders", "companionDigest":latent_artifacts::package::artifact_blob_digest(&startup::declaration()).to_string(), "binding":"approved-event","operation":"event","adapter":"nats-jetstream-effect-v1", "payloadFormat":"nats-event-value-v1","idempotencyProfile":adapter.profile().idempotency_profile, "ceiling":{"maximum_payload_bytes":8192,"maximum_response_bytes":16384,"maximum_attempts":3,"maximum_age_millis":60000,"attempt_timeout_millis":5000}})).unwrap()
    }
    pub(super) fn configuration(&self, requirements: &[u8]) -> serde_json::Value {
        let adapter = self.adapter(Arc::new(AdapterClock::default()));
        json!({"requirementsDigest":latent_artifacts::package::artifact_blob_digest(requirements).to_string(), "providerId":"events","providerIncarnation":adapter.provider_reference().configuration_digest().strip_prefix("sha256:").unwrap(),"credentialReference":"event-secret", "stagingBinding":"intent-stage","stagingPolicies":["stage"],"dispatchBinding":"intent-dispatch","dispatchPolicies":["dispatch"], "dispatchAuthority":{"formatVersion":1,"mode":"signed-service-integration"}})
    }
    pub(super) fn install_policy(
        &self,
        policy: &PolicyStore,
        publication: &latent_core::PublicationId,
    ) {
        let adapter = self.adapter(Arc::new(AdapterClock::default()));
        let reference = adapter.provider_reference();
        let subject = latent_core::InvocationPrincipal::local_service_subject(
            &TenantId("tests".into()),
            &latent_core::ServiceId("tests/packaging".into()),
        );
        for (kind, id, value) in [
            (
                RecordKind::Policy,
                "stage",
                json!({"formatVersion":1,"tenant":"tests","rules":[]}),
            ),
            (
                RecordKind::ProviderBinding,
                "intent-stage",
                json!({"formatVersion":1,"tenant":"tests","capability":latent_capabilities::namespace::INTENT_CONTRACT,"providerProfile":adapter.profile().adapter,"configurationDigest":format!("sha256:{}",adapter.profile().idempotency_profile.strip_prefix("js-window-v1:").unwrap()),"configurationEpoch":reference.configuration_epoch(),"restriction":{"operations":[]}}),
            ),
            (
                RecordKind::Policy,
                "dispatch",
                json!({"formatVersion":1,"tenant":"tests","rules":[{"id":"dispatcher","effect":"allow","principals":[{"kind":"service","subject":subject}],"services":["tests/packaging"],"publications":[publication.as_str()],"capability":latent_capabilities::broker::events::EVENTS_CAPABILITY,"operations":["publish"],"resources":{"kind":"events","subjects":["updated"]},"ceiling":{"operations":1,"inputBytes":8192,"outputBytes":16384,"wallTimeMillis":5000}}]}),
            ),
            (
                RecordKind::ProviderBinding,
                "intent-dispatch",
                json!({"formatVersion":1,"tenant":"tests","capability":latent_capabilities::broker::events::EVENTS_CAPABILITY,"providerProfile":reference.profile(),"configurationDigest":reference.configuration_digest(),"configurationEpoch":reference.configuration_epoch(),"restriction":{"operations":[]}}),
            ),
        ] {
            policy
                .mutate(
                    MutationRequest {
                        tenant: "tests",
                        actor: "operator",
                        kind,
                        id,
                        operation_id: id,
                        expected_revision: 0,
                        document: Some(&serde_json::to_vec(&value).unwrap()),
                    },
                    Instant::now() + Duration::from_secs(10),
                    |_| Ok(()),
                )
                .unwrap_or_else(|error| panic!("event fixture {id}: {error:?}"));
        }
    }
    async fn finish(self) {
        drop(self.publisher);
        self.secrets.close();
        assert!(self
            .pools
            .shutdown(Instant::now() + Duration::from_secs(20))
            .await
            .unwrap()
            .is_clean());
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn configured_event_inspection_keeps_original_provider_identity_without_credentials() {
    let event = EventFixture::new().await;
    let adapter = event.adapter(Arc::new(AdapterClock::default()));
    let reference = adapter.provider_reference();
    let inspected = super::super::super::inspection::configured_event(&adapter);
    assert_eq!(
        inspected.configuration_digest,
        reference.configuration_digest()
    );
    assert_eq!(
        inspected.configuration_epoch,
        reference.configuration_epoch()
    );
    assert_eq!(inspected.profile, *adapter.profile());
    let wire = serde_json::to_string(&inspected).unwrap();
    assert!(!wire.contains("fixture-secret"));
    assert!(!wire.contains("event-secret"));
    drop(adapter);
    event.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_event_rule_installs_only_for_current_namespace_and_original_provider() {
    let event = EventFixture::new().await;
    let mut setup = Setup::configured_installation(
        Some(event.requirements()),
        false,
        false,
        None,
        false,
        Some(&event),
    )
    .await;
    let before_namespace = load(
        &setup.kernel,
        &setup.fixture.settings,
        &setup.owners,
        setup.policy.clone(),
        setup.services(),
        &setup.effects,
    )
    .await
    .unwrap();
    let operation = &setup.fixture.settings.operations[0];
    let absent_scope = latent_effects::authority::EffectScope {
        tenant: operation.tenant.0.clone(),
        namespace: "orders".into(),
        incarnation: operation.incarnation,
        publication: operation.publication.as_str().into(),
        binding: "approved-event".into(),
        operation: "event".into(),
    };
    let absent_link = latent_effects::authority::CommitLink {
        command: "before-namespace".into(),
        caller_scope: "event-policy-caller".into(),
        attempt: 1,
        commit: "event-policy-commit".into(),
        effect: "3".repeat(64),
        sequence: 0,
    };
    assert!(setup
        .authority
        .capture(
            &absent_scope,
            absent_link,
            1,
            "7".repeat(64),
            setup.effects.command_time().unwrap()
        )
        .is_err());
    drop(before_namespace);
    let installed = startup::installed(&setup).await;
    assert_eq!(installed.installations.len(), 1);
    let operation = &setup.fixture.settings.operations[0];
    let scope = EffectScope {
        tenant: operation.tenant.0.clone(),
        namespace: "orders".into(),
        incarnation: operation.incarnation,
        publication: operation.publication.as_str().into(),
        binding: "approved-event".into(),
        operation: "event".into(),
    };
    let time = setup.effects.command_time().unwrap();
    let captured = setup
        .authority
        .capture(
            &scope,
            CommitLink {
                command: "event-policy-command".into(),
                caller_scope: "event-policy-caller".into(),
                attempt: 1,
                commit: "event-policy-commit".into(),
                effect: "3".repeat(64),
                sequence: 0,
            },
            1,
            "7".repeat(64),
            time,
        )
        .unwrap();
    let mut physical = setup.authority.accept(&captured, 1, time).unwrap();
    let grant = physical
        .accept_with(&captured, 1, time, |grant| grant)
        .unwrap();
    let registry = &setup.services.http.event_registry;
    assert!(registry.check_current(&grant, "updated").is_ok());
    assert!(registry.check_current(&grant, "other").is_err());
    setup.policy.retire();
    assert!(registry.check_current(&grant, "updated").is_err());
    drop(grant);
    physical.retire().unwrap();
    drop(installed);
    setup.services.http = super::super::InstalledHttpEffects::empty();
    setup.finish().await;
    event.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_event_rule_rejects_changed_provider_profile() {
    let event = EventFixture::new().await;
    let mut document: serde_json::Value = serde_json::from_slice(&event.requirements()).unwrap();
    document["idempotencyProfile"] = format!("js-window-v1:{}", "0".repeat(64)).into();
    let mut setup = Setup::configured_installation(
        Some(serde_json::to_vec(&document).unwrap()),
        false,
        false,
        None,
        false,
        Some(&event),
    )
    .await;
    let result = load(
        &setup.kernel,
        &setup.fixture.settings,
        &setup.owners,
        setup.policy.clone(),
        setup.services(),
        &setup.effects,
    )
    .await;
    assert!(result.is_err());
    drop(result);
    setup.services.http = super::super::InstalledHttpEffects::empty();
    setup.finish().await;
    event.finish().await;
}
