use super::*;
use latent_capabilities::broker::secrets::CredentialScope;
use latent_secrets::{
    LocalSecretStore, SecretLimits, SecretPurpose, SecretSource, SecretSpec, SystemSecretClock,
};
use std::{fs, os::unix::fs::PermissionsExt};

pub(super) struct Fixture {
    pub http: HttpFixture,
    pub secrets: LocalSecretStore,
    pub clock: Arc<Clock>,
    pub adapter: QualifiedHttpEffectAdapter,
    pub authority: EffectAuthorityOwner,
    pub rule: EffectRule,
    root: std::path::PathBuf,
}

impl Fixture {
    pub async fn new(port: u16, root_certificate: Vec<u8>, timeout: u64) -> Self {
        Self::with_horizon(port, root_certificate, timeout, 10_000).await
    }

    pub async fn with_horizon(
        port: u16,
        root_certificate: Vec<u8>,
        timeout: u64,
        horizon: u64,
    ) -> Self {
        let mut config = http_config(port);
        config.destinations[0].origin.scheme = "https".into();
        config.destinations[0].allowed_request_headers.clear();
        config.destinations[0].redirect_destinations.clear();
        config.limits.maximum_redirects = 0;
        config.limits.maximum_request_body_bytes = 65_536;
        config.extra_roots.push(root_certificate);
        let http = HttpFixture::new(config);
        let root = http.directory.path().join("effect-secrets");
        fs::create_dir(&root).unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        write(&root, b"synthetic-alpha");
        let secrets = LocalSecretStore::open(
            http.pools.clone(),
            root.clone(),
            SecretLimits::default(),
            vec![],
            Arc::new(SystemSecretClock),
        )
        .unwrap()
        .await
        .unwrap();
        let origin = http.provider.inner.config.destinations[0].origin.clone();
        secrets
            .reload(0, specs(&origin, "1"))
            .unwrap()
            .await
            .unwrap();
        let binding = secrets
            .bind_credential(
                CredentialScope {
                    tenant: TenantId("a".into()),
                    provider_id: "http".into(),
                    origin: origin.clone(),
                },
                "effect-auth".into(),
            )
            .unwrap();
        let clock = Arc::new(Clock(AtomicU64::new(100)));
        let adapter = QualifiedHttpEffectAdapter::new(
            &http.provider,
            PutOnceContract {
                tenant: TenantId("a".into()),
                provider_id: "http".into(),
                origin,
                provider_incarnation: "a".repeat(64),
                retention_horizon_millis: horizon,
                maximum_body_bytes: 65_536,
                retry_delay_millis: 10,
            },
            1,
            binding,
            clock.clone(),
        )
        .unwrap();
        let rule = rule(&http, &adapter, timeout);
        let authority = EffectAuthorityOwner::new(8, 4, 100).unwrap();
        authority.publish(rule.clone()).unwrap();
        Self {
            http,
            secrets,
            clock,
            adapter,
            authority,
            rule,
            root,
        }
    }

    pub fn retained(
        &self,
        index: u64,
        bytes: &[u8],
    ) -> (DurableEffectAuthority, PayloadRecord, EffectRecord) {
        let value = Value {
            bytes: bytes.to_vec(),
            media_type: "application/octet-stream".into(),
            metadata: vec![],
        };
        let authority = self
            .authority
            .capture(
                &self.rule.scope,
                CommitLink {
                    command: format!("command-{index}"),
                    caller_scope: "user-a".into(),
                    attempt: 1,
                    commit: format!("commit-{index}"),
                    effect: format!("{index:064x}"),
                    sequence: 0,
                },
                bytes.len() as u64,
                payload_digest(&value).unwrap(),
                self.clock.observe(),
            )
            .unwrap();
        let payload = PayloadRecord::new(&authority, value).unwrap();
        let record = EffectRecord::committed(&authority).unwrap();
        (authority, payload, record)
    }

    pub fn accepted(
        &self,
        authority: &DurableEffectAuthority,
        payload: PayloadRecord,
        record: &mut EffectRecord,
    ) -> (
        DispatchContext,
        AttemptIdentity,
        latent_core::BoxFuture<'static, AdapterOutcome>,
    ) {
        let attempt = record.claim(1, self.clock.observe()).unwrap();
        let mut context = self
            .authority
            .accept(authority, attempt.attempt(), self.clock.observe())
            .unwrap();
        let operation = context
            .accept_with(
                authority,
                attempt.attempt(),
                self.clock.observe(),
                |grant| self.adapter.accept(grant, payload, attempt.clone()),
            )
            .unwrap()
            .unwrap();
        (context, attempt, operation)
    }

    pub async fn run(&self, index: u64, bytes: &[u8]) -> AdapterOutcome {
        let (authority, payload, mut record) = self.retained(index, bytes);
        let (context, attempt, operation) = self.accepted(&authority, payload, &mut record);
        record.begin_send(&attempt).unwrap();
        let outcome = watched(operation).await;
        context.retire().unwrap();
        outcome
    }

    pub async fn rotate(&self) {
        write(&self.root, b"synthetic-beta");
        let origin = &self.http.provider.inner.config.destinations[0].origin;
        self.secrets
            .reload(1, specs(origin, "2"))
            .unwrap()
            .await
            .unwrap();
    }

    pub async fn snapshot(&self) -> latent_capabilities::broker::pools::ProviderPoolSnapshot {
        watched(async {
            loop {
                match self.http.pools.snapshot() {
                    Ok(snapshot) => return snapshot,
                    Err(error)
                        if error.code == latent_core::PlatformErrorCode::ResourceExhausted
                            && error.message == "capability-busy" =>
                    {
                        // Wait only for the pool's bookkeeping lock. This
                        // never resubmits an accepted provider operation.
                        tokio::task::yield_now().await;
                    }
                    Err(error) => panic!("provider snapshot failed: {error:?}"),
                }
            }
        })
        .await
    }

    pub async fn finish(self) {
        self.secrets.close();
        drop(self.adapter);
        self.http.clean().await;
        assert_eq!(
            self.authority.owners().unwrap(),
            latent_effects::authority::DispatchOwners::default()
        );
    }
}

fn rule(http: &HttpFixture, adapter: &QualifiedHttpEffectAdapter, timeout: u64) -> EffectRule {
    EffectRule {
        scope: EffectScope {
            tenant: "a".into(),
            namespace: "orders".into(),
            incarnation: 7,
            publication: http.publication.publication().as_str().into(),
            binding: "qualified-http".into(),
            operation: HTTP_EFFECT_OPERATION.into(),
        },
        profile: adapter.profile().clone(),
        policy_revision: 1,
        credential_epoch: 1,
        protected_credential_reference: "effect-auth".into(),
        ceiling: DispatchCeiling {
            maximum_payload_bytes: 65_536,
            maximum_response_bytes: 2048,
            maximum_attempts: 3,
            maximum_age_millis: 10_000,
            attempt_timeout_millis: timeout,
        },
        enabled: true,
    }
}

fn specs(origin: &latent_policy::capability::HttpOrigin, version: &str) -> Vec<SecretSpec> {
    vec![SecretSpec {
        tenant: TenantId("a".into()),
        reference: "effect-auth".into(),
        source: SecretSource::File {
            name: "token".into(),
        },
        purpose: SecretPurpose::ProviderCredential {
            provider_id: "http".into(),
            origin: origin.clone(),
        },
        media_type: "text/plain".into(),
        version: version.into(),
        expires_at_unix_millis: None,
    }]
}

fn write(root: &std::path::Path, value: &[u8]) {
    let path = root.join("token");
    fs::write(&path, value).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
}
