use super::*;
use latent_capabilities::broker::{pools::ProviderPoolLimits, secrets::CredentialScope};
use latent_http::{
    HttpAddressPolicy, HttpDestination, HttpLimits, HttpProviderConfig, HttpResolution,
};
use latent_policy::capability::HttpOrigin;
use latent_secrets::vault::{
    VaultConfig, VaultEncoding, VaultLimits, VaultReference, VAULT_SECRETS_PROFILE,
};
use latent_secrets::{SecretPurpose, SecretSource, SecretSpec};

pub const FIRST_TOKEN: &str = "lsf-public-vault-reader-a";
pub const SECOND_TOKEN: &str = "lsf-public-vault-reader-b";
pub fn config(port: u16, root: Vec<u8>) -> VaultConfig {
    VaultConfig {
        format_version: 1,
        namespace: None,
        limits: VaultLimits::default(),
        references: [
            ("allowed", "tests", None, None),
            ("opaque", "tests", Some(1), None),
            ("tenant-only", "other", None, None),
            ("expired", "tests", None, Some(900)),
        ]
        .into_iter()
        .map(|(reference, tenant, version, expiry)| VaultReference {
            tenant: tenant.into(),
            reference: reference.into(),
            mount: "secret".into(),
            path: "fixture".into(),
            field: "value".into(),
            version,
            encoding: VaultEncoding::Utf8,
            media_type: "text/plain".into(),
            expires_at_unix_millis: expiry,
        })
        .collect(),
        transport: HttpProviderConfig {
            format_version: 1,
            public_roots: false,
            extra_roots: vec![root],
            limits: HttpLimits::default(),
            destinations: vec![HttpDestination {
                origin: HttpOrigin {
                    scheme: "https".into(),
                    host: "127.0.0.1".into(),
                    port,
                },
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
        },
    }
}
pub fn configured() -> VaultConfig {
    let port = std::env::var("LSF_VAULT_TEST_PORT")
        .expect("owned test port")
        .parse()
        .unwrap();
    let root =
        std::fs::read(std::env::var_os("LSF_VAULT_TEST_CA").expect("owned test CA")).unwrap();
    config(port, root)
}
fn credentials(config: &VaultConfig, version: &str) -> Vec<SecretSpec> {
    ["tests", "other"]
        .into_iter()
        .map(|tenant| SecretSpec {
            tenant: TenantId(tenant.into()),
            reference: "vault-auth".into(),
            source: SecretSource::File {
                name: "value".into(),
            },
            purpose: SecretPurpose::ProviderCredential {
                provider_id: "secrets".into(),
                origin: config.transport.destinations[0].origin.clone(),
            },
            media_type: "text/plain".into(),
            version: version.into(),
            expires_at_unix_millis: None,
        })
        .collect()
}
pub async fn fixture(
    config: VaultConfig,
    audit: Option<latent_audit::AuditHandle>,
) -> Fixture<VaultSecretProvider> {
    Fixture::with_provider(
        audit,
        ProviderPoolLimits::default(),
        VAULT_SECRETS_PROFILE,
        move |path, pools, store, clock| async move {
            write(&path.join("secrets/value"), FIRST_TOKEN.as_bytes());
            store
                .reload(1, credentials(&config, "2"))
                .unwrap()
                .await
                .unwrap();
            let credentials = ["tests", "other"]
                .into_iter()
                .map(|tenant| {
                    store
                        .bind_credential(
                            CredentialScope {
                                tenant: TenantId(tenant.into()),
                                provider_id: "secrets".into(),
                                origin: config.transport.destinations[0].origin.clone(),
                            },
                            "vault-auth".into(),
                        )
                        .unwrap()
                })
                .collect();
            let provider =
                VaultSecretProvider::install(pools, "secrets", 1, 0, config, credentials, clock)
                    .unwrap();
            let reference = provider.reference();
            (provider, reference)
        },
    )
    .await
}
pub fn expire(f: &Fixture<VaultSecretProvider>) {
    f.secret_clock.mono.fetch_add(5001, Ordering::AcqRel);
    f.secret_clock.now.fetch_add(5001, Ordering::AcqRel);
    f.provider.prune_expired().unwrap();
}
pub async fn rotate(f: &Fixture<VaultSecretProvider>, config: &VaultConfig, token: &str) {
    write(&f.directory.path().join("secrets/value"), token.as_bytes());
    let current = f.secrets.snapshot().unwrap().generation;
    f.secrets
        .reload(current, credentials(config, &(current + 1).to_string()))
        .unwrap()
        .await
        .unwrap();
}
pub fn control(operation: &str) {
    let output = std::process::Command::new("python3")
        .arg(std::env::var_os("LSF_VAULT_TEST_CONTROL").expect("owned control script"))
        .arg(std::env::var("LSF_VAULT_TEST_PORT").unwrap())
        .arg(std::env::var_os("LSF_VAULT_TEST_PEM").unwrap())
        .arg(operation)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "bounded Vault fixture control failed"
    );
    assert_eq!(output.stdout, b"Vault fixture control passed\n");
}
pub async fn idle(f: &Fixture<VaultSecretProvider>) {
    for _ in 0..100 {
        if f.io.snapshot() == latent_capabilities::broker::io::IoSnapshot::default() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
    f.idle();
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    assert_eq!(f.provider.snapshot().unwrap().active_reads, 0);
}
