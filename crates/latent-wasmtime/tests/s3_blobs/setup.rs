use super::*;
use latent_blobs::s3::{S3Config, S3Inventory, S3Limits, S3_BLOB_PROFILE};
use latent_capabilities::broker::{pools::ProviderPoolLimits, secrets::CredentialScope};
use latent_http::{
    HttpAddressPolicy, HttpDestination, HttpLimits, HttpProviderConfig, HttpResolution,
};
use latent_policy::capability::HttpOrigin;
use latent_secrets::{
    LocalSecretStore, SecretLimits, SecretPurpose, SecretSource, SecretSpec, SystemSecretClock,
};
use std::{os::unix::fs::PermissionsExt, path::PathBuf};

pub fn config(port: u16, root: Vec<u8>) -> S3Config {
    S3Config {
        format_version: 1,
        namespace: "private".into(),
        region: "us-east-1".into(),
        bucket: "lsf-test-bucket".into(),
        prefix: "conformance/".into(),
        limits: S3Limits {
            maximum_records: 8,
            ..S3Limits::default()
        },
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
pub fn configured() -> (S3Config, String) {
    let port = std::env::var("LSF_S3_TEST_PORT")
        .expect("owned test port")
        .parse()
        .unwrap();
    let root = std::fs::read(std::env::var_os("LSF_S3_TEST_CA").expect("owned test CA")).unwrap();
    (
        config(port, root),
        "LSFPUBLICS3TEST\nLSF-PUBLIC-TEST-ONLY-S3-SECRET".into(),
    )
}
pub async fn fixture(config: S3Config, key: String) -> Fixture<S3BlobProvider> {
    let path =
        PathBuf::from(std::env::var_os("LSF_S3_TEST_INVENTORY").expect("owned test inventory"));
    fixture_at(config, key, path).await
}
pub async fn fixture_at(
    config: S3Config,
    key: String,
    inventory_path: PathBuf,
) -> Fixture<S3BlobProvider> {
    let mut ceiling = support::budget();
    ceiling.outbound_requests = 64;
    ceiling.blob_write_bytes = 16 * 1024 * 1024;
    ceiling.blob_read_bytes = 1024 * 1024;
    ceiling.wall_time_limit_millis = Some(30000);
    Fixture::with_provider(
        ceiling,
        ProviderPoolLimits {
            maximum_metadata_bytes: 32 * 1024 * 1024,
            ..ProviderPoolLimits::default()
        },
        S3_BLOB_PROFILE,
        move |path, pools| async move {
            let secret_root = path.join("secrets");
            std::fs::create_dir(&secret_root).unwrap();
            std::fs::set_permissions(&secret_root, std::fs::Permissions::from_mode(0o700)).unwrap();
            let secret_file = secret_root.join("s3-tuple");
            std::fs::write(&secret_file, key.as_bytes()).unwrap();
            std::fs::set_permissions(&secret_file, std::fs::Permissions::from_mode(0o600)).unwrap();
            let store = LocalSecretStore::open(
                pools.clone(),
                secret_root,
                SecretLimits::default(),
                vec![],
                Arc::new(SystemSecretClock),
            )
            .unwrap()
            .await
            .unwrap();
            let origin = config.transport.destinations[0].origin.clone();
            store
                .reload(
                    0,
                    ["tests", "other"]
                        .into_iter()
                        .map(|tenant| SecretSpec {
                            tenant: TenantId(tenant.into()),
                            reference: "s3-auth".into(),
                            source: SecretSource::File {
                                name: "s3-tuple".into(),
                            },
                            purpose: SecretPurpose::ProviderCredential {
                                provider_id: "blobs".into(),
                                origin: origin.clone(),
                            },
                            media_type: "text/plain".into(),
                            version: "1".into(),
                            expires_at_unix_millis: None,
                        })
                        .collect(),
                )
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
                                provider_id: "blobs".into(),
                                origin: origin.clone(),
                            },
                            "s3-auth".into(),
                        )
                        .unwrap()
                })
                .collect();
            let inventory = S3Inventory::open(&inventory_path, &pools, config).unwrap();
            let provider =
                S3BlobProvider::install(pools, "blobs", 1, 0, inventory, credentials).unwrap();
            let reference = provider.reference();
            (provider, reference)
        },
    )
    .await
}

/// A separate authorized tenant in the same catalog, broker and provider pool.
/// Its capsule, compiled plan/session and credential binding belong to the other
/// tenant; descriptive guest data cannot substitute that trusted authority.
pub async fn other_session(f: &Fixture<S3BlobProvider>) -> (CapabilitySession, Control) {
    use latent_artifacts::{
        ArtifactRepository, LifecycleScope, ManagedPublicationUpload, ReleaseActor,
        ReleaseActorKind, ReleaseMutationContext,
    };
    let mut artifact = packages::artifact(&packages::capsule_for("other"));
    artifact.manifest.metadata.tenant = Some(TenantId("other".into()));
    artifact.manifest.execution.resource_budget_ceiling = f.ceiling.clone();
    let release = artifact.descriptor.release_digest.clone();
    let receipt = f
        .catalog
        .publish_managed(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId("other".into())),
                actor: ReleaseActor {
                    subject: "operator".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: None,
            },
            ManagedPublicationUpload::Local(artifact),
            &mut |_| Ok(()),
        )
        .await
        .unwrap();
    let publication = f
        .catalog
        .execution_eligibility_selected(&release, Some(&receipt.publication.id))
        .unwrap()
        .unwrap();
    let provider = f.provider.reference();
    fixture::install(
        &f.policies,
        &publication,
        provider.configuration_digest(),
        S3_BLOB_PROFILE,
        f.ceiling.wall_time_limit_millis.unwrap(),
        "other",
    );
    let mut revision = f.revision.clone();
    revision.release = release;
    revision.target.tenant = TenantId("other".into());
    revision.target.contract = ContractId("other:local-blobs/api@1.0.0".into());
    revision.publication = Some(receipt.publication.id);
    let plan = f
        .broker
        .compile_plan(
            &revision,
            &[CapabilityBindingSpec {
                definition_digest: None,
                provider: &provider,
                imported_operations: &[
                    "create".into(),
                    "open".into(),
                    "write".into(),
                    "read".into(),
                    "seal".into(),
                ],
                policy_ids: &["p".into()],
                provider_binding_id: "binding",
                deployment_restriction_json: br#"{"operations":[]}"#,
            }],
            &publication,
            Instant::now() + Duration::from_secs(10),
        )
        .unwrap();
    let (mut request, control) = f.request("other-tenant", 0, 0);
    request.prepared = f.prepared_for(&revision).await;
    request.activation.principal.tenant = Some(TenantId("other".into()));
    request.activation.target = revision.target.clone();
    request.activation.resolved_revision = Some(revision);
    let session = f
        .broker
        .open_session(plan, &request, &control, &publication)
        .unwrap();
    (session, control)
}
