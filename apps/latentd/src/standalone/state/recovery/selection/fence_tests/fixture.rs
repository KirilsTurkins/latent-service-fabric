//! Real signed selections and policy seals for the final writer fence only.
use super::super::super::{
    assets::SchemaEvidence,
    authority::{Authority, NativeProfile},
    catalog::Catalog,
    codecs::Codecs,
    profile::Profile,
    request::Action,
};
use super::super::{retain, RecoverySource};
use crate::standalone::{effects::ProtectedEffectClock, state::SignedFixture};
use latent_artifacts::{
    AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, PublicationRef, TransactionAssetProfile,
};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeCapacityLimits, NativeCapacityOwner,
        NativeReservationRequest,
    },
    ActivationClock, BudgetProfile, ClockSample, InvocationPrincipal, Metadata, PrincipalKind,
    StateNamespaceId, SystemActivationClock, TenantId,
};
use latent_manifest::{ManifestValidationProfile, RuntimeCompatibilityProfile};
use latent_policy::{
    capability::PolicyStore, capability::PolicyStoreLimits, supply_chain::SupplyChainAuthority,
};
use latent_state::{
    namespace::{
        compatibility::{ReviewedSchema, SchemaDeclaration, SchemaId},
        NamespaceQuota, NamespaceRecord,
    },
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner, ProtectedStoreStartupMemory},
    store_identity::{ExternalCheckpoint, StoreIdentity},
};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    os::unix::fs::PermissionsExt,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

#[path = "policy.rs"]
mod policy;
#[path = "write.rs"]
mod write;

pub(super) fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(5)
}

pub(super) struct Clock {
    wall: AtomicU64,
    monotonic: Instant,
}
impl Clock {
    pub fn regress(&self) {
        self.wall.store(0, Ordering::SeqCst);
    }
}
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(self.wall.load(Ordering::SeqCst), self.monotonic)
    }
    fn monotonic_now(&self) -> Instant {
        self.monotonic
    }
}

pub(super) struct Fixture {
    pub codecs: Arc<Codecs>,
    pub policy: Arc<PolicyStore>,
    pub sources: Vec<PublicationRef>,
    pub artifacts: Arc<DirectoryArtifactRepository>,
    pub native: NativeCapacityOwner,
    pub clock: Arc<Clock>,
    pub principal: InvocationPrincipal,
    pub profile: String,
    pub digest: String,
    pub store: Arc<ProtectedStoreOwner>,
    authority: Arc<SupplyChainAuthority>,
    signed: SignedFixture,
    root: tempfile::TempDir,
}

impl Fixture {
    pub async fn new(restore: bool) -> Self {
        Self::configured(restore, false).await
    }

    pub async fn expiring() -> Self {
        Self::configured(false, true).await
    }

    pub async fn for_restore_targets(targets: &[&ProtectedStoreConfig]) -> Self {
        Self::configured_with_targets(true, false, Some(targets)).await
    }

    async fn configured(restore: bool, short_policy: bool) -> Self {
        Self::configured_with_targets(restore, short_policy, None).await
    }

    #[expect(
        clippy::too_many_lines,
        reason = "One real signed subject pair, original native reservation, policy and protected writer constructs the final-fence controls"
    )]
    async fn configured_with_targets(
        restore: bool,
        short_policy: bool,
        targets: Option<&[&ProtectedStoreConfig]>,
    ) -> Self {
        let root = tempfile::tempdir().unwrap();
        let schema = SchemaId::from_definition(b"final-fence-test-schema").unwrap();
        let companion = serde_json::to_vec(
            &json!({"apiVersion":"latent.dev/v1","kind":"TransactionBinding",
            "capsule":"tests/packaging","deployment":"deployment","binding":"binding",
            "profile":latent_core::transaction_contract::PROFILE,
            "hostAbiDigest":latent_manifest::phase4_host_abi_digest(),"namespace":"orders",
            "stateSchema":schema.as_str(),"operations":[{"operation":"inspect","mode":"fresh-query",
                "inputFormat":"lsf-wit-values-v1","resultFormat":"lsf-wit-values-v1"}]}),
        )
        .unwrap();
        let mut signed = SignedFixture::transactional_with_companion(companion.clone(), false);
        signed.policy["tenants"]
            .as_array_mut()
            .unwrap()
            .push(json!({"tenant":"other","publishers":["publisher-a"]}));
        let manifest_profile = ManifestValidationProfile::phase4(
            BudgetProfile::Phase4,
            latent_core::PHASE4_HOST_ABI_V1,
            &latent_manifest::phase4_host_abi_digest(),
        )
        .unwrap();
        let runtime = Arc::new(
            RuntimeCompatibilityProfile::new(
                "wasmtime",
                "48.0.4",
                "x86_64-unknown-linux-gnu",
                &["x86_64.sse2"],
                64 * 1024 * 1024,
                100_000_000,
            )
            .unwrap(),
        );
        let authority = Arc::new(
            SupplyChainAuthority::open_with_runtime_and_manifest_profile(
                &root.path().join("trust"),
                signed.approved(),
                signed.clock.clone(),
                5,
                runtime,
                manifest_profile,
            )
            .unwrap(),
        );
        let artifacts = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                root.path().join("artifacts"),
                DirectoryArtifactRepositoryConfig {
                    manifest_profile,
                    ..Default::default()
                },
                AdmissionStorageLimits::default(),
                authority.clone(),
            )
            .unwrap(),
        );
        let uploads = [signed.upload(), signed.annotated_upload("secondary")];
        assert_ne!(uploads[0].manifest, uploads[1].manifest);
        assert_ne!(
            uploads[0].signatures[0].manifest,
            uploads[1].signatures[0].manifest
        );
        assert_ne!(
            uploads[0].provenance[0].manifest,
            uploads[1].provenance[0].manifest
        );
        let mut admitted = Vec::new();
        for upload in uploads {
            admitted.push(
                artifacts
                    .admit_package(&TenantId("tests".into()), upload, &mut |_| Ok(()))
                    .await
                    .unwrap(),
            );
        }
        assert_eq!(
            admitted[0].descriptor.release_digest,
            admitted[1].descriptor.release_digest
        );
        let sources = admitted
            .iter()
            .map(|row| {
                PublicationRef::package(
                    latent_artifacts::LifecycleScope::Tenant(TenantId("tests".into())),
                    row.package.as_ref().unwrap(),
                )
                .unwrap()
            })
            .collect::<Vec<_>>();
        assert_ne!(sources[0].id, sources[1].id);
        let policy = Arc::new(
            PolicyStore::open(
                &root.path().join("policy"),
                PolicyStoreLimits::default(),
                artifacts.lifecycle_authority(),
            )
            .unwrap(),
        );
        let mut config = ProtectedStoreConfig::bounded_linux(root.path().join("state"));
        std::fs::create_dir(&config.root).unwrap();
        std::fs::set_permissions(&config.root, std::fs::Permissions::from_mode(0o700)).unwrap();
        config.create_if_missing = true;
        config.engine.cache_bytes = 1024 * 1024;
        let native = NativeCapacityOwner::with_clock(
            NativeCapacityLimits::default(),
            Arc::new(SystemActivationClock),
        )
        .unwrap();
        let work_bytes = match targets {
            None => config.startup_memory_bytes(0).unwrap() + 9 * 1024 * 1024,
            Some(targets) => restore_target_work_bytes(&config, targets),
        };
        let original = Arc::new(
            native
                .reserve(
                    NativeAdmissionClass::Recovery,
                    NativeReservationRequest {
                        work_bytes,
                        response_bytes: 2 * 1024 * 1024,
                        ..Default::default()
                    },
                    deadline(),
                )
                .unwrap(),
        );
        let identity = StoreIdentity::new("native-recovery-fence".into()).unwrap();
        let store = Arc::new(
            ProtectedStoreOwner::start_bound_retained_validated_view_with_clock(
                config,
                identity.clone(),
                ProtectedStoreStartupMemory::new(&native, original.clone()).unwrap(),
                0,
                |_| Ok(()),
                Arc::new(SystemActivationClock),
            )
            .unwrap()
            .await
            .unwrap(),
        );
        let (profile, digest) = store.inspection_profile();
        let digest = format!("sha256:{:x}", latent_core::digest::HexDigest(digest));
        let principal = InvocationPrincipal {
            subject: "operator".into(),
            kind: PrincipalKind::Administrator,
            tenant: Some(TenantId("tests".into())),
            service: None,
            claims: Metadata::new(),
        };
        policy::install(
            &policy,
            &principal,
            sources[0].id.as_str(),
            profile,
            &digest,
            short_policy,
        );
        let mut schemas = Vec::new();
        for (index, row) in admitted.iter().enumerate() {
            let asset = artifacts
                .capture_selected_transaction_asset_profile(
                    &TenantId("tests".into()),
                    &row.descriptor.release_digest,
                    &sources[index].id,
                    &native,
                    original.clone(),
                    TransactionAssetProfile::Compact,
                )
                .unwrap();
            assert!(asset.get().is_from_reservation(&original));
            let input = crate::config::state::OperationSettings {
                tenant: TenantId("tests".into()),
                component: row.descriptor.release_digest.clone(),
                publication: sources[index].id.clone(),
                contract: "tests:packaging/api@1.0.0".into(),
                function: "inspect".into(),
                deployment: "deployment".into(),
                route: None,
                binding: "binding".into(),
                companion_digest: asset.get().asset_digest().to_string(),
                incarnation: 1,
                result_policy: "visibility-v1".into(),
                policies: vec!["native".into()],
                entity: None,
                deferred_http: None,
            };
            let operation =
                retain(input, asset, native.clone(), original.clone(), index == 0).unwrap();
            schemas.push(evidence(operation, &schema, &companion));
        }
        let catalog = Catalog {
            selected: 0,
            schemas,
            effects: Vec::new(),
            artifacts: Vec::new(),
            formats: Vec::new(),
        };
        let clock = Arc::new(Clock {
            wall: AtomicU64::new(1_100_000),
            monotonic: Instant::now(),
        });
        let protected_clock =
            ProtectedEffectClock::admit(clock.clone(), authority.clone(), None).unwrap();
        let namespace = NamespaceRecord::create(
            TenantId("tests".into()),
            StateNamespaceId("orders".into()),
            schema.as_str().into(),
            NamespaceQuota::default(),
        )
        .unwrap();
        let action = if restore {
            restore_action(root.path())
        } else {
            let observed = latent_state::recovery::namespace_resume::NamespaceRecoveryView {
                history: latent_state::namespace::history::NamespaceHistory::initial(&namespace),
                namespace: namespace.clone(),
                guard: None,
            };
            Action::Resume {
                operation_id: "original-resume".into(),
                expected_view: observed.view_token().unwrap(),
            }
        };
        let auth = Authority::retain(
            policy.clone(),
            catalog.primary(),
            &principal,
            &action,
            protected_clock,
            original.original_deadline(),
            &NativeProfile {
                profile,
                digest: &digest,
                epoch: 1,
            },
        )
        .unwrap();
        let checkpoint = ExternalCheckpoint::initial(identity.clone(), 1, 1, 1_100_000).unwrap();
        let metadata = original
            .reserve_buffer(NativeBufferClass::Work, 1024 * 1024)
            .unwrap();
        let codecs = Arc::new(Codecs {
            catalog,
            authority: auth,
            action,
            runtime: [1; 32],
            review: [2; 32],
            namespace,
            identity,
            quotas: Vec::new(),
            checkpoint,
            original,
            _metadata: metadata,
        });
        Self {
            codecs,
            policy,
            sources,
            artifacts,
            native,
            clock,
            principal,
            profile: profile.into(),
            digest,
            store,
            authority,
            signed,
            root,
        }
    }

    pub async fn finish(self) {
        let Self {
            codecs,
            policy,
            sources,
            artifacts,
            native,
            clock,
            principal,
            profile,
            digest,
            store,
            authority,
            signed,
            root,
        } = self;
        store.close();
        let cutoff = deadline();
        let retired = store
            .drain_async(cutoff, tokio::time::sleep_until(cutoff.into()))
            .unwrap()
            .await;
        assert!(retired.clean && retired.snapshot.physically_retired());
        assert!(store.reap_retired_threads().unwrap() > 0);
        assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
        drop(store);
        drop(codecs);
        assert_eq!(policy.retained_read_owners(), 0);
        assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
        assert_eq!(native.snapshot().unwrap().recovery.bytes, 0);
        drop((
            policy, sources, artifacts, clock, principal, profile, digest, authority, signed, root,
        ));
    }
}

fn restore_target_work_bytes(
    source: &ProtectedStoreConfig,
    targets: &[&ProtectedStoreConfig],
) -> u64 {
    let original = source.startup_memory_bytes(0).unwrap() + 9 * 1024 * 1024;
    targets.iter().fold(original, |bytes, target| {
        let initializing = target
            .startup_memory_bytes(0)
            .unwrap()
            .checked_add(source.io.resident_bytes)
            .and_then(|value| value.checked_add(1024 * 1024))
            .unwrap();
        let reading = source
            .io
            .resident_bytes
            .checked_add(target.io.resident_bytes)
            .and_then(|value| value.checked_add(1024 * 1024))
            .and_then(|value| value.checked_add(8 * 1024 * 1024))
            .unwrap();
        bytes.max(initializing).max(reading)
    })
}

fn evidence(operation: Arc<RecoverySource>, schema: &SchemaId, companion: &[u8]) -> SchemaEvidence {
    let package = operation.publication().package().unwrap().as_str();
    let package_digest = super::super::super::assets::digest_bytes(package).unwrap();
    let declaration = SchemaDeclaration {
        package_digest,
        readers: vec![schema.clone()],
        writers: vec![schema.clone()],
    };
    let proof: [u8; 32] = Sha256::digest(companion).into();
    let schema = ReviewedSchema::accept_with(
        declaration,
        package_digest,
        proof,
        |actual, _, actual_proof| {
            assert_eq!(actual.package_digest, package_digest);
            assert_eq!(actual_proof, proof);
            Ok(())
        },
    )
    .unwrap();
    // This descriptor reaches the real final fence only. It neither claims an
    // installed Java codec nor invokes the production native decoder closure.
    SchemaEvidence {
        operation,
        schema,
        profile: Profile::Legacy,
        artifacts: Vec::new(),
    }
}

fn restore_action(root: &std::path::Path) -> Action {
    use super::super::super::request::File;
    Action::Restore {
        file: File {
            root: root.into(),
            name: "snapshot".into(),
        },
        destination_root: root.join("restored"),
        operation_id: "restore".into(),
        snapshot_digest: format!("sha256:{}", "1".repeat(64)),
        manifest_digest: format!("sha256:{}", "2".repeat(64)),
        destination_checkpoint_root: root.join("restored-checkpoint"),
        window_acknowledgement: format!("sha256:{}", "3".repeat(64)),
        destination_store_identity: None,
    }
}
