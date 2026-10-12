use latent_capabilities::broker::{
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
    secrets::TlsCredentialScope,
    ActivationCapabilityBroker, CapabilityBrokerLimits,
};
use latent_core::{SystemActivationClock, TenantId};
use latent_nats::{
    triggers::{NatsTriggers, RootBudget, TriggerBinding, TriggerConfig},
    NatsCredential, NatsEndpoint,
};
use latent_secrets::{
    LocalSecretStore, SecretLimits, SecretPurpose, SecretSource, SecretSpec, SystemSecretClock,
};
use std::{os::unix::fs::PermissionsExt, path::Path, sync::Arc};

pub fn config() -> TriggerConfig {
    TriggerConfig {
        format_version: 1,
        endpoint: NatsEndpoint {
            server_name: "127.0.0.1".into(),
            peer: format!("127.0.0.1:{}", std::env::var("LSF_NATS_TEST_PORT").unwrap())
                .parse()
                .unwrap(),
            allow_non_public_peer: true,
        },
        public_roots: false,
        extra_roots: vec![std::fs::read(std::env::var("LSF_NATS_TEST_CA").unwrap()).unwrap()],
        bindings: ["a", "b"]
            .into_iter()
            .map(|name| TriggerBinding {
                id: format!("trigger-{name}"),
                tenant: format!("tenant-{name}"),
                principal_subject: "event-ingress".into(),
                service: "callee".into(),
                contract: super::component::CALLEE.into(),
                function: "answer".into(),
                route: None,
                stream: format!("TRIGGER{}", name.to_uppercase()),
                consumer: "PROCESS".into(),
                filter_subject: format!("lsf.trigger.{name}"),
                budget: RootBudget {
                    cpu_fuel: 100_000_000,
                    memory_bytes: 4_194_304,
                    wall_time_millis: 1500,
                    child_calls: 0,
                    outbound_requests: 0,
                    blob_read_bytes: 0,
                    blob_write_bytes: 0,
                    log_bytes: 0,
                },
            })
            .collect(),
        maximum_payload_bytes: 1024,
        operation_timeout_millis: 2000,
        poll_interval_millis: 10,
        maximum_deliveries: 3,
        ack_wait_millis: 3500,
        redelivery_delay_millis: 100,
    }
}
pub async fn install(
    root: &Path,
    catalog: &latent_artifacts::DirectoryArtifactRepository,
    config: TriggerConfig,
) -> (NatsTriggers, Arc<ProviderPools>, LocalSecretStore) {
    let policies = Arc::new(
        latent_policy::capability::PolicyStore::open(
            &root.join("policies"),
            latent_policy::capability::PolicyStoreLimits::default(),
            catalog.lifecycle_authority(),
        )
        .unwrap(),
    );
    let broker = Arc::new(
        ActivationCapabilityBroker::new(
            catalog.lifecycle_authority(),
            policies,
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
    let directory = root.join("secrets");
    std::fs::create_dir_all(&directory).unwrap();
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
    std::fs::write(directory.join("password"), b"lsf-public-nats-password").unwrap();
    std::fs::set_permissions(
        directory.join("password"),
        std::fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    let secrets = LocalSecretStore::open(
        pools.clone(),
        directory,
        SecretLimits::default(),
        vec![],
        Arc::new(SystemSecretClock),
    )
    .unwrap()
    .await
    .unwrap();
    let specs = ["a", "b"]
        .into_iter()
        .map(|name| SecretSpec {
            tenant: TenantId(format!("tenant-{name}")),
            reference: "nats-password".into(),
            source: SecretSource::File {
                name: "password".into(),
            },
            purpose: SecretPurpose::TlsProviderCredential {
                provider_id: "triggers".into(),
                destination: config.endpoint.credential_destination(),
            },
            media_type: "application/octet-stream".into(),
            version: "1".into(),
            expires_at_unix_millis: None,
        })
        .collect();
    secrets.reload(0, specs).unwrap().await.unwrap();
    let credentials = ["a", "b"]
        .into_iter()
        .map(|name| NatsCredential {
            username: Some(format!("trigger-{name}")),
            secret: secrets
                .bind_tls_credential(
                    TlsCredentialScope {
                        tenant: TenantId(format!("tenant-{name}")),
                        provider_id: "triggers".into(),
                        destination: config.endpoint.credential_destination(),
                    },
                    "nats-password".into(),
                )
                .unwrap(),
        })
        .collect();
    let triggers =
        NatsTriggers::install(pools.clone(), "triggers", 1, 0, config, credentials).unwrap();
    (triggers, pools, secrets)
}
