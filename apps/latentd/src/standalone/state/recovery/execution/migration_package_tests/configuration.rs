use super::fixture::*;
use latent_artifacts::{
    AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, PublicationRef,
};
use latent_core::{BudgetProfile, ReleaseDigest};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidationProfile, RuntimeCompatibilityProfile,
};
use latent_policy::{capability::PolicyStoreLimits, supply_chain::SupplyChainAuthority};

pub(super) struct Packages {
    pub artifacts: Arc<DirectoryArtifactRepository>,
    pub authority: Arc<SupplyChainAuthority>,
    pub publications: Vec<(PublicationRef, ReleaseDigest)>,
}

pub(super) async fn packages(root: &std::path::Path, count: usize) -> Packages {
    assert!((1..=4).contains(&count));
    let signed = crate::standalone::state::SignedFixture::captured_java();
    let profile = ManifestValidationProfile::phase4(
        BudgetProfile::Phase4,
        latent_core::PHASE4_HOST_ABI_V1,
        &latent_manifest::phase4_host_abi_digest(),
    )
    .unwrap();
    let runtime = Arc::new(
        RuntimeCompatibilityProfile::new(
            "wasmtime",
            "48.0.6",
            "x86_64-unknown-linux-gnu",
            &["x86_64.sse2"],
            64 * 1024 * 1024,
            1_000_000_000,
        )
        .unwrap(),
    );
    let authority = Arc::new(
        SupplyChainAuthority::open_with_runtime_and_manifest_profile(
            &root.join("trust"),
            signed.approved(),
            signed.clock.clone(),
            5,
            runtime,
            profile,
        )
        .unwrap(),
    );
    let artifacts = Arc::new(
        DirectoryArtifactRepository::open_enforced(
            root.join("artifacts"),
            DirectoryArtifactRepositoryConfig {
                manifest_profile: profile,
                ..Default::default()
            },
            AdmissionStorageLimits::default(),
            authority.clone(),
        )
        .unwrap(),
    );
    let mut publications = Vec::new();
    for index in 0..count {
        let (input, observed) = super::package::input(&format!("captured-{index}"));
        let admitted = artifacts
            .admit_package(
                &TenantId("examples".into()),
                signed.captured_java_upload(input, observed),
                &mut |_| Ok(()),
            )
            .await
            .unwrap();
        assert_eq!(
            admitted.descriptor.release_digest.0,
            "sha256:05e8bbaa90168aa250d779431a317fcde8f785d93e511054e0d5facaaad5787d"
        );
        let publication = PublicationRef::package(
            LifecycleScope::Tenant(TenantId("examples".into())),
            admitted.package.as_ref().unwrap(),
        )
        .unwrap();
        assert!(!publications
            .iter()
            .any(|(prior, _): &(PublicationRef, ReleaseDigest)| prior.id == publication.id));
        publications.push((publication, admitted.descriptor.release_digest));
    }
    Packages {
        artifacts,
        authority,
        publications,
    }
}

pub(super) fn settings(root: &std::path::Path, store: ProtectedStoreConfig) -> StateSettings {
    StateSettings {
        create_if_missing: true,
        configuration_epoch: 1,
        store_identity: StoreIdentity::new("captured-migration-source".into()).unwrap(),
        startup_work_bytes: store.startup_memory_bytes(0).unwrap(),
        store,
        native: NativeCapacityLimits::default(),
        dispatcher: latent_effects::runtime::DispatcherConfig::default(),
        checkpoint_root: root.join("checkpoint"),
        startup_timeout: Duration::from_secs(5),
        operations: Vec::new(),
        tenant_quotas: vec![serde_json::from_value(json!({
            "tenant":"examples","limits":{"stateKeys":32,"stateBytes":65536,
            "tombstoneKeys":32,"tombstoneBytes":65536,"resultRows":32,"resultBytes":65536,
            "effectRows":32,"effectBytes":65536,"payloadBytes":65536,"recoveryBytes":65536,
            "metadataRows":128,"metadataBytes":1_048_576}
        }))
        .unwrap()],
    }
}

pub(super) fn operation(
    publication: &PublicationRef,
    component: &ReleaseDigest,
) -> OperationSettings {
    OperationSettings {
        tenant: TenantId("examples".into()),
        component: component.clone(),
        publication: publication.id.clone(),
        contract: "examples:transactional-aggregate/api@1.0.0".into(),
        function: "update".into(),
        deployment: "transaction-java-aggregate".into(),
        route: None,
        binding: "transaction-java-aggregate".into(),
        companion_digest: "sha256:e5719a610fb20811a402aed0531d13d71547978104048d9e275ae7b7ae061c49"
            .into(),
        incarnation: 1,
        result_policy: "visibility-v1".into(),
        policies: vec!["native".into()],
        entity: None,
        deferred_http: Some(crate::config::state::DeferredHttpConfig {
            requirements_digest:
                "sha256:4b4e375e4834be64784c71da140da42540bd901d8bc33a8ff813a9a2e18c6f1b".into(),
            provider_id: "metadata-only".into(),
            provider_incarnation: "1".repeat(64),
            credential_reference: "not-opened".into(),
            staging_binding: "metadata-only".into(),
            staging_policies: vec!["native".into()],
            dispatch_binding: "metadata-only".into(),
            dispatch_policies: vec!["native".into()],
            dispatch_authority: None,
        }),
    }
}

pub(super) fn deployment(input: &OperationSettings) -> latent_manifest::DeploymentManifest {
    let mut value: serde_json::Value = serde_json::from_slice(include_bytes!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../examples/echo-contract/deployment.json"
    )))
    .unwrap();
    value["metadata"] = json!({"name":input.deployment,"tenant":input.tenant.0});
    value["spec"]["service"] = "examples/transaction-java-aggregate".into();
    value["spec"]["release"] = input.component.0.clone().into();
    value["spec"]["publication"] = input.publication.as_str().into();
    value["spec"]["grants"] =
        json!([{"capability":latent_capabilities::namespace::STATE_CONTRACT,"policy":"native"}]);
    JsonManifestCodec::default()
        .decode_deployment(&serde_json::to_vec(&value).unwrap())
        .unwrap()
}

pub(super) fn policy(root: &std::path::Path, packages: &Packages) -> Arc<PolicyStore> {
    Arc::new(
        PolicyStore::open(
            &root.join("policy"),
            PolicyStoreLimits::default(),
            packages.artifacts.lifecycle_authority(),
        )
        .unwrap(),
    )
}

pub(super) fn work_bytes(source: &ProtectedStoreConfig, root: &std::path::Path) -> u64 {
    let metadata = 1024 * 1024;
    let operational = source
        .io
        .resident_bytes
        .checked_add(metadata)
        .and_then(|bytes| bytes.checked_add(8 * 1024 * 1024))
        .unwrap();
    let mut work = source.startup_memory_bytes(0).unwrap().max(operational);
    let mut targets = Vec::new();
    for name in ["installed.snapshot", "old.snapshot"] {
        let mut target = source.clone();
        target.root = root.join(format!("restored-{name}"));
        let initializing = target
            .startup_memory_bytes(0)
            .unwrap()
            .checked_add(source.io.resident_bytes)
            .and_then(|bytes| bytes.checked_add(metadata))
            .unwrap();
        let reading = source
            .io
            .resident_bytes
            .checked_add(target.io.resident_bytes)
            .and_then(|bytes| bytes.checked_add(metadata))
            .and_then(|bytes| bytes.checked_add(8 * 1024 * 1024))
            .unwrap();
        work = work.max(initializing).max(reading);
        targets.push(json!({"rootCapacity":target.root.capacity(),
            "startupBytes":target.startup_memory_bytes(0).unwrap(),
            "residentBytes":target.io.resident_bytes,
            "initializationOverlapBytes":initializing,"readingOverlapBytes":reading}));
    }
    eprintln!(
        "migration-package-work: {}",
        json!({
            "sourceRootCapacity":source.root.capacity(),"sourceStartupBytes":source.startup_memory_bytes(0).unwrap(),
            "sourceResidentBytes":source.io.resident_bytes,"metadataBytes":metadata,
            "operationalOverlapBytes":operational,"targets":targets,"workBytes":work,
        })
    );
    work
}
