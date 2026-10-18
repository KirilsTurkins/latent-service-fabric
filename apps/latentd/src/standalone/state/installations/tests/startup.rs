//! Real signed deferred HTTP installation for the actual readiness consumer.
mod dispatch_policy;

use super::*;
use latent_capabilities::broker::{
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
    secrets::CredentialScope,
    ActivationCapabilityBroker, CapabilityBrokerLimits,
};
use latent_core::SystemActivationClock;
use latent_effects::runtime::DeferredEffectAdapter;
use latent_http::{
    deferred::QualifiedHttpEndpoint, HttpAddressPolicy, HttpCredentialReference, HttpDestination,
    HttpLimits, HttpProvider, HttpProviderConfig, HttpResolution,
};
use latent_policy::capability::HttpOrigin;
use latent_secrets::{
    LocalSecretStore, SecretLimits, SecretPurpose, SecretSource, SecretSpec, SystemSecretClock,
};
use std::os::unix::fs::PermissionsExt;

pub(in crate::standalone::state) struct HttpFixture {
    _root: tempfile::TempDir,
    _catalog: Arc<DirectoryArtifactRepository>,
    _policy: Arc<PolicyStore>,
    pools: Arc<ProviderPools>,
    secrets: LocalSecretStore,
    provider: HttpProvider,
    endpoint: QualifiedHttpEndpoint,
}

pub(super) fn declaration() -> Vec<u8> {
    let mut declaration: serde_json::Value = serde_json::from_slice(&super::declaration()).unwrap();
    declaration["operations"][0]["mode"] = "strict-command".into();
    serde_json::to_vec(&declaration).unwrap()
}

impl HttpFixture {
    #[expect(
        clippy::too_many_lines,
        reason = "The installed provider retains its real broker, pools and protected credential until physical shutdown"
    )]
    pub(in crate::standalone::state) async fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let catalog = Arc::new(
            DirectoryArtifactRepository::open(
                root.path().join("provider-catalog"),
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        );
        let policy = Arc::new(
            PolicyStore::open(
                &root.path().join("provider-policy"),
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
        let origin = HttpOrigin {
            scheme: "https".into(),
            host: "localhost".into(),
            port: 443,
        };
        let config = HttpProviderConfig {
            format_version: 1,
            public_roots: true,
            extra_roots: vec![],
            limits: HttpLimits::default(),
            destinations: vec![HttpDestination {
                origin: origin.clone(),
                addresses: HttpAddressPolicy {
                    networks: vec!["127.0.0.0/8".parse().unwrap()],
                    special_addresses: vec!["127.0.0.1".parse().unwrap()],
                },
                resolution: HttpResolution::Static {
                    addresses: vec!["127.0.0.1".parse().unwrap()],
                },
                allowed_request_headers: vec![],
                redirect_destinations: vec![],
            }],
        };
        let directory = root.path().join("secrets");
        std::fs::create_dir(&directory).unwrap();
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
        std::fs::write(
            directory.join("token"),
            b"Bearer synthetic-startup-reference",
        )
        .unwrap();
        std::fs::set_permissions(
            directory.join("token"),
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
                    reference: "http-auth".into(),
                    source: SecretSource::File {
                        name: "token".into(),
                    },
                    purpose: SecretPurpose::ProviderCredential {
                        provider_id: "http".into(),
                        origin: origin.clone(),
                    },
                    media_type: "text/plain".into(),
                    version: "1".into(),
                    expires_at_unix_millis: None,
                }],
                deadline,
            )
            .unwrap()
            .await
            .unwrap();
        let credential = secrets
            .bind_credential(
                CredentialScope {
                    tenant: TenantId("tests".into()),
                    provider_id: "http".into(),
                    origin: origin.clone(),
                },
                "http-auth".into(),
            )
            .unwrap();
        let provider = HttpProvider::install_with_secret_references(
            pools.clone(),
            "http",
            1,
            0,
            config,
            vec![HttpCredentialReference {
                destination: 0,
                name: "authorization".into(),
                binding: credential,
            }],
        )
        .unwrap();
        let endpoint = QualifiedHttpEndpoint {
            format_version: 1,
            origin,
            operation_path: "/effect".into(),
            lookup_prefix: "/receipts/".into(),
            endpoint_incarnation: "c".repeat(64),
            retention_millis: 60_000,
            media_type: "text/plain".into(),
            maximum_payload_bytes: 8192,
        };
        Self {
            _root: root,
            _catalog: catalog,
            _policy: policy,
            pools,
            secrets,
            provider,
            endpoint,
        }
    }

    fn adapter(&self, clock: Arc<AdapterClock>) -> latent_http::deferred::HttpEffectAdapter {
        self.provider
            .deferred_adapter("tests", self.endpoint.clone(), clock)
            .unwrap()
    }

    pub(super) fn installation(&self) -> super::super::super::InstalledHttpEffects {
        let mut installed = super::super::super::InstalledHttpEffects::empty();
        installed.adapters = vec![Arc::new(
            self.adapter(installed.clock.clone())
                .with_authorization(installed.registry.clone()),
        )];
        installed
    }

    fn requirements(&self) -> Vec<u8> {
        let adapter = self.adapter(Arc::new(AdapterClock::default()));
        let ceiling = latent_effects::authority::DispatchCeiling {
            maximum_payload_bytes: 8192,
            maximum_response_bytes: 32768,
            maximum_attempts: 3,
            maximum_age_millis: 60_000,
            attempt_timeout_millis: 5000,
        };
        serde_json::to_vec(&json!({"formatVersion":1,"protocol":"lsf-atomic-idempotent-http-v1",
            "capsule":"tests/packaging","deployment":"deployment","stateBinding":"binding","namespace":"orders",
            "companionDigest":latent_artifacts::package::artifact_blob_digest(&declaration()).to_string(),
            "binding":"approved-http","operation":"http","adapter":"qualified-http-effect-v1",
            "payloadFormat":"http-body-value-v1","idempotencyProfile":adapter.profile().idempotency_profile,
            "ceiling":ceiling})).unwrap()
    }

    pub(super) fn configuration(&self, requirements: &[u8]) -> serde_json::Value {
        json!({"requirementsDigest":latent_artifacts::package::artifact_blob_digest(requirements).to_string(),
            "providerId":"http","providerIncarnation":self.endpoint.endpoint_incarnation,"credentialReference":"http-auth",
            "stagingBinding":"intent-stage","stagingPolicies":["stage"],"dispatchBinding":"intent-dispatch","dispatchPolicies":["dispatch"],
            "dispatchAuthority":{"formatVersion":1,"mode":"signed-service-integration"}})
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
                json!({"formatVersion":1,"tenant":"tests",
                "capability":latent_capabilities::namespace::INTENT_CONTRACT,"providerProfile":adapter.profile().adapter,
                "configurationDigest":format!("sha256:{}",adapter.profile().idempotency_profile.strip_prefix("qualified-http-v1:").unwrap()),
                "configurationEpoch":reference.configuration_epoch(),"restriction":{"operations":[]}}),
            ),
            (
                RecordKind::Policy,
                "dispatch",
                json!({"formatVersion":1,"tenant":"tests","rules":[{
                "id":"dispatcher","effect":"allow","principals":[{"kind":"service","subject":subject}],
                "services":["tests/packaging"],"publications":[publication.as_str()],"capability":latent_capabilities::broker::http::HTTP_CAPABILITY,
                "operations":["send"],"resources":{"kind":"http","origins":[self.endpoint.origin],"methods":["GET","POST"],"paths":[],"pathPrefixes":["/"]},
                "ceiling":{"operations":1,"inputBytes":8192,"outputBytes":32768,"wallTimeMillis":5000}}]}),
            ),
            (
                RecordKind::ProviderBinding,
                "intent-dispatch",
                json!({"formatVersion":1,"tenant":"tests",
                "capability":latent_capabilities::broker::http::HTTP_CAPABILITY,"providerProfile":reference.profile(),
                "configurationDigest":reference.configuration_digest(),"configurationEpoch":reference.configuration_epoch(),
                "restriction":{"operations":[]}}),
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
                .unwrap_or_else(|error| panic!("initial {id} fixture refused: {error:?}"));
        }
    }

    pub(in crate::standalone::state) async fn setup(&self) -> Setup {
        Setup::configured_installation(Some(self.requirements()), false, false, Some(self)).await
    }

    pub(in crate::standalone::state) async fn finish(self) {
        drop(self.provider);
        self.secrets.close();
        assert!(self
            .pools
            .shutdown(Instant::now() + Duration::from_secs(20))
            .await
            .unwrap()
            .is_clean());
    }
}

pub(in crate::standalone::state) async fn installed(setup: &Setup) -> InstalledState {
    let loaded = load(
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
    let quota = policy::maximum_quota(&setup.fixture.settings, operation).unwrap();
    loaded
        .management
        .as_ref()
        .unwrap()
        .execute_state(
            AuthenticatedInvocationContext::new(operator()),
            c::MutateNamespaceRequest {
                namespace: Some(c::InspectNamespaceRequest {
                    profile: Some(contract::current_profile()),
                    namespace: Some(t::NamespaceSelector {
                        tenant: "tests".into(),
                        namespace: "orders".into(),
                        incarnation: "1".into(),
                    }),
                    authorization_publication: Some(c::PublicationRef {
                        tenant: "tests".into(),
                        id: operation.publication.as_str().into(),
                    }),
                }),
                mutation: c::NamespaceMutationKind::Create as i32,
                operation_id: "startup-create".into(),
                expected_generation: Some(0),
                configuration: Some(c::NamespaceConfiguration {
                    state_schema: format!("sha256:{}", "1".repeat(64)),
                    quota: Some(c::NamespaceQuota {
                        state_keys: quota.state_keys,
                        state_bytes: quota.state_bytes,
                        result_rows: quota.result_rows,
                        result_bytes: quota.result_bytes,
                        effect_rows: quota.effect_rows,
                        effect_bytes: quota.effect_bytes,
                        payload_bytes: quota.payload_bytes,
                        recovery_bytes: quota.recovery_bytes,
                    }),
                }),
            }
            .into(),
        )
        .await
        .unwrap();
    drop(loaded);
    let loaded = load(
        &setup.kernel,
        &setup.fixture.settings,
        &setup.owners,
        setup.policy.clone(),
        setup.services(),
        &setup.effects,
    )
    .await
    .unwrap();
    assert!(loaded.http_rules);
    assert_eq!(loaded.installations.len(), 1);
    loaded
}
