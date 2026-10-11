//! Real signed capture and protected startup ownership, without guest qualification.
use super::*;
use crate::standalone::state::{kernel::tests::Fixture as KernelFixture, AdapterClock};
use latent_artifacts::{
    AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepositoryConfig,
};
use latent_core::{BudgetProfile, TenantId};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidationProfile, RuntimeCompatibilityProfile,
    TransactionOperationMode,
};
use latent_policy::{
    capability::{MutationRequest, PolicyStoreLimits, RecordKind},
    supply_chain::SupplyChainAuthority,
};
use latent_rpc::{control::v1 as c, phase4 as contract, transaction::v1 as t};
use latent_wire::invocation::AuthenticatedInvocationContext;
use serde_json::json;
use std::time::{Duration, Instant};

// Reuse the existing actual package, signature, provenance and trust fixture.
mod http;
#[path = "../../../../../../crates/latent-policy/src/supply_chain/tests/support.rs"]
#[allow(
    unused_imports,
    clippy::too_many_lines,
    reason = "Reuse the upstream signed fixture including its separately ignored exporters"
)]
mod signed;

fn declaration() -> Vec<u8> {
    serde_json::to_vec(&json!({"apiVersion":"latent.dev/v1","kind":"TransactionBinding",
        "capsule":"tests/packaging","deployment":"deployment","binding":"binding",
        "profile":latent_core::transaction_contract::PROFILE,"hostAbiDigest":latent_manifest::phase4_host_abi_digest(),
        "namespace":"orders","stateSchema":format!("sha256:{}","1".repeat(64)),"operations":[
            {"operation":"inspect","mode":"fresh-query","inputFormat":"lsf-wit-values-v1","resultFormat":"lsf-wit-values-v1"},
            {"operation":"uninstalled","mode":"fresh-query","inputFormat":"lsf-wit-values-v1","resultFormat":"lsf-wit-values-v1"}]})).unwrap()
}

struct Setup {
    fixture: KernelFixture,
    services: InstalledStateServices,
    policy: Arc<PolicyStore>,
    kernel: StateKernel,
    effects: EffectRuntime,
    owners: Arc<TransactionAdmissionOwners>,
}
impl Setup {
    async fn new() -> Self {
        Self::with_http_document(None).await
    }

    async fn with_http_document(document: Option<Vec<u8>>) -> Self {
        Self::configured(document, false).await
    }

    #[expect(
        clippy::too_many_lines,
        reason = "The real signed fixture composes each independent original owner before admission"
    )]
    async fn configured(document: Option<Vec<u8>>, executable: bool) -> Self {
        let mut fixture = KernelFixture::new();
        let companion = declaration();
        let signed = match document {
            Some(document) => {
                signed::Fixture::transactional_with_http_companion(companion.clone(), document)
            }
            None if executable => {
                signed::Fixture::transactional_executable_with_companion(companion.clone())
            }
            None => signed::Fixture::transactional_with_companion(companion.clone(), false),
        };
        let profile = ManifestValidationProfile::phase4(
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
        fixture.authority = Arc::new(
            SupplyChainAuthority::open_with_runtime_and_manifest_profile(
                &fixture.root().join("signed-authority"),
                signed.approved(),
                signed.clock.clone(),
                5,
                runtime.clone(),
                profile,
            )
            .unwrap(),
        );
        let artifacts = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                fixture.root().join("signed-catalog"),
                DirectoryArtifactRepositoryConfig {
                    manifest_profile: profile,
                    ..Default::default()
                },
                AdmissionStorageLimits::default(),
                fixture.authority.clone(),
            )
            .unwrap(),
        );
        let upload = signed.upload();
        let configuration: serde_json::Value =
            serde_json::from_slice(&upload.configuration).unwrap();
        let component =
            latent_core::ReleaseDigest(configuration["componentDigest"].as_str().unwrap().into());
        let publication = latent_artifacts::PublicationRef::package(
            latent_artifacts::LifecycleScope::Tenant(TenantId("tests".into())),
            &latent_artifacts::package::package_digest(&upload.manifest),
        )
        .unwrap()
        .id;
        let mut input = crate::config::state::tests::input();
        input["createIfMissing"] = true.into();
        input["startupTimeoutMillis"] = 20_000.into();
        input["checkpointRoot"] = json!(fixture.settings.checkpoint_root);
        input["tenantQuotas"][0]["tenant"] = "tests".into();
        let operation = &mut input["operations"][0];
        operation["tenant"] = "tests".into();
        operation["componentDigest"] = component.0.clone().into();
        operation["publication"] = publication.as_str().into();
        operation["contract"] = "tests:packaging/api@1.0.0".into();
        operation["function"] = "inspect".into();
        operation["deployment"] = "deployment".into();
        operation["binding"] = "binding".into();
        operation["companionDigest"] = latent_artifacts::package::artifact_blob_digest(&companion)
            .to_string()
            .into();
        operation["statePolicies"] = json!(["state"]);
        fixture.settings =
            crate::config::state::derive(&serde_json::from_value(input).unwrap(), fixture.root())
                .unwrap();
        let bootstrap = fixture.bootstrap();
        artifacts
            .lifecycle_authority()
            .install_rejection_observer(bootstrap.authority.rejection_observer())
            .unwrap();
        let admitted = artifacts
            .admit_package(&TenantId("tests".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
        assert_eq!(admitted.publication.as_ref(), Some(&publication));
        assert_eq!(admitted.descriptor.release_digest, component);
        let policy = Arc::new(
            PolicyStore::open(
                &fixture.root().join("installed-policy"),
                PolicyStoreLimits::default(),
                artifacts.lifecycle_authority(),
            )
            .unwrap(),
        );
        policy
            .install_rejection_observer(bootstrap.authority.rejection_observer())
            .unwrap();
        install_policy(&policy, &fixture.settings, &publication);
        let deployments = Arc::new(
            DirectoryDeploymentRepository::open_with_catalog(
                fixture.root().join("installed-deployments"),
                artifacts.clone(),
                latent_control_store::DirectoryDeploymentRepositoryConfig {
                    manifest_profile: profile,
                    ..Default::default()
                },
                artifacts.lifecycle_authority(),
                runtime,
            )
            .await
            .unwrap(),
        );
        let mut deployment: serde_json::Value = serde_json::from_str(include_str!("../../../../../../crates/latent-manifest/tests/fixtures/valid-deployment-v1alpha1.json")).unwrap();
        deployment["metadata"]["tenant"] = "tests".into();
        deployment["metadata"]["name"] = "deployment".into();
        deployment["spec"]["service"] = "tests/packaging".into();
        deployment["spec"]["release"] = component.0.clone().into();
        deployment["spec"]["publication"] = publication.as_str().into();
        let metadata = artifacts
            .fetch_verified_metadata_selected(&component, Some(&publication))
            .await
            .unwrap();
        let capsule: serde_json::Value = serde_json::from_slice(
            &JsonManifestCodec::default()
                .encode_capsule(metadata.manifest())
                .unwrap(),
        )
        .unwrap();
        deployment["spec"]["resources"] = capsule["execution"]["limits"].clone();
        deployment["spec"]["grants"] = json!([{"capability":latent_capabilities::namespace::STATE_CONTRACT,"policy":"state","operations":["acquire-query"]}]);
        if executable {
            deployment["spec"]["grants"][0]["operations"] =
                json!(["acquire-query", "query-info", "read-result"]);
        }
        let manifest = JsonManifestCodec::default()
            .decode_deployment(&serde_json::to_vec(&deployment).unwrap())
            .unwrap();
        deployments.apply(manifest).await.unwrap();
        let (kernel, effects) = StateKernel::start(
            bootstrap,
            &fixture.settings,
            fixture.authority.clone(),
            Vec::new(),
            &AdapterClock::default(),
            tokio::runtime::Handle::current(),
        )
        .await
        .unwrap();
        let owners = kernel
            .admission_owners(Arc::clone(&policy), &effects)
            .unwrap();
        let services = InstalledStateServices {
            artifacts,
            deployments,
            clock: fixture.clock.clone(),
            audit: None,
            http: super::super::InstalledHttpEffects::empty(),
        };
        Self {
            fixture,
            services,
            policy,
            kernel,
            effects,
            owners,
        }
    }
    fn services(&self) -> InstalledStateServices {
        InstalledStateServices {
            artifacts: Arc::clone(&self.services.artifacts),
            deployments: Arc::clone(&self.services.deployments),
            clock: Arc::clone(&self.services.clock),
            audit: None,
            http: super::super::InstalledHttpEffects::empty(),
        }
    }
    async fn finish(mut self) {
        let deadline = self.fixture.clock.monotonic_now() + Duration::from_secs(20);
        drop(self.owners);
        assert!(self.effects.shutdown(deadline).await.unwrap().clean);
        drop(self.effects);
        assert!(self.kernel.shutdown(deadline).await.unwrap().clean);
    }
}

fn install_policy(
    policy: &PolicyStore,
    settings: &StateSettings,
    publication: &latent_core::PublicationId,
) {
    let (profile, digest) = settings.store.inspection_profile().unwrap();
    let caller = latent_capabilities::namespace::CallerScope::derive(
        &operator(),
        &RecoverySelection::OriginalCaller,
    )
    .unwrap();
    for (kind, id, value) in [
        (
            RecordKind::Policy,
            "state",
            json!({"formatVersion":1,"tenant":"tests","rules":[{"id":"operator","effect":"allow",
            "principals":[{"kind":"administrator","subject":"operator"}],"services":["tests/packaging"],"publications":[publication.as_str()],
            "capability":latent_capabilities::namespace::STATE_CONTRACT,"operations":["namespace-create","namespace-inspect"],
            "resources":{"kind":"state","scopes":[{"namespace":"orders","incarnation":1,"entity":null,"recoveryKind":caller.kind, "recoveryScope":caller.scope,"resultPolicy":"owner"}]},
            "ceiling":{"operations":16,"inputBytes":2_097_152,"outputBytes":2_097_152,"wallTimeMillis":10_000}}]}),
        ),
        (
            RecordKind::ProviderBinding,
            "binding",
            json!({"formatVersion":1,"tenant":"tests","capability":latent_capabilities::namespace::STATE_CONTRACT,
            "providerProfile":profile,"configurationDigest":format!("sha256:{:x}", latent_core::digest::HexDigest(digest)),
            "configurationEpoch":1,"restriction":{"operations":[]}}),
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
            .unwrap();
    }
}

fn operator() -> latent_core::InvocationPrincipal {
    latent_core::InvocationPrincipal {
        subject: "operator".into(),
        kind: latent_core::PrincipalKind::Administrator,
        tenant: Some(TenantId("tests".into())),
        service: None,
        claims: latent_core::Metadata::new(),
    }
}

#[tokio::test]
async fn signed_http_document_capture_keeps_original_native_owner_and_refuses_oversize() {
    for size in [8192, 8193] {
        let bytes = vec![b' '; size];
        let setup = Setup::with_http_document(Some(bytes.clone())).await;
        let original = Arc::new(
            setup
                .kernel
                .native
                .reserve(
                    NativeAdmissionClass::Recovery,
                    NativeReservationRequest {
                        request_bytes: state::INSTALLATION_CAPTURE_REQUEST_BYTES,
                        work_bytes: state::INSTALLATION_CAPTURE_WORK_BYTES,
                        response_bytes: TRANSACTION_ASSET_RESPONSE_BYTES,
                    },
                    setup.kernel.original_deadline().unwrap(),
                )
                .unwrap(),
        );
        let operation = setup.fixture.settings.operations[0].clone();
        let artifacts = setup.services.artifacts.clone();
        let native = setup.kernel.native.clone();
        let worker_original = original.clone();
        let captured = setup
            .kernel
            .store
            .with_store_retaining(
                StoreIoKind::RecoveryRead,
                state::INSTALLATION_CAPTURE_REQUEST_BYTES
                    + state::INSTALLATION_CAPTURE_WORK_BYTES
                    + TRANSACTION_ASSET_RESPONSE_BYTES,
                original.clone(),
                move |_| {
                    Ok(artifacts.capture_selected_transaction_asset(
                        &operation.tenant,
                        &operation.component,
                        &operation.publication,
                        &native,
                        worker_original,
                    ))
                },
            )
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        if size == 8192 {
            let captured = captured.unwrap();
            assert!(captured.get().is_from_reservation(&original));
            let (digest, actual) = captured.get().deferred_http_requirements().unwrap();
            assert_eq!(actual, bytes);
            assert_eq!(
                *digest,
                latent_artifacts::package::artifact_blob_digest(&bytes)
            );
            assert!(setup.kernel.native.snapshot().unwrap().recovery.bytes > 2 * 1024 * 1024);
            drop(captured);
        } else {
            assert!(captured.is_err());
        }
        drop(original);
        assert_eq!(setup.kernel.native.snapshot().unwrap().recovery.slots, 1);
        setup.finish().await;
    }
}

#[tokio::test]
async fn signed_installed_targets_require_actual_namespace_and_keep_resident_source_charges() {
    let setup = Setup::new().await;
    let loaded = load(
        &setup.kernel,
        &setup.fixture.settings,
        &setup.owners,
        Arc::clone(&setup.policy),
        setup.services(),
        &setup.effects,
    )
    .await
    .unwrap();
    assert!(loaded.installations.is_empty());
    assert_eq!(setup.kernel.native.snapshot().unwrap().recovery.slots, 2);
    let namespace = c::InspectNamespaceRequest {
        profile: Some(contract::current_profile()),
        namespace: Some(t::NamespaceSelector {
            tenant: "tests".into(),
            namespace: "orders".into(),
            incarnation: "1".into(),
        }),
        authorization_publication: Some(c::PublicationRef {
            tenant: "tests".into(),
            id: setup.fixture.settings.operations[0]
                .publication
                .as_str()
                .into(),
        }),
    };
    let quota = policy::maximum_quota(
        &setup.fixture.settings,
        &setup.fixture.settings.operations[0],
    )
    .unwrap();
    let created = loaded
        .management
        .as_ref()
        .unwrap()
        .execute_state(
            AuthenticatedInvocationContext::new(operator()),
            c::MutateNamespaceRequest {
                namespace: Some(namespace),
                mutation: c::NamespaceMutationKind::Create as i32,
                operation_id: "actual-create".into(),
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
    drop(created);
    drop(loaded);
    let loaded = load(
        &setup.kernel,
        &setup.fixture.settings,
        &setup.owners,
        Arc::clone(&setup.policy),
        setup.services(),
        &setup.effects,
    )
    .await
    .unwrap();
    assert_eq!(loaded.installations.len(), 1);
    let operation = &setup.fixture.settings.operations[0];
    let mut target = InvocationTarget {
        tenant: operation.tenant.clone(),
        service: ServiceId("tests/packaging".into()),
        contract: ContractId(operation.contract.clone()),
        function: FunctionId(operation.function.clone()),
        route: None,
    };
    assert!(loaded.installations[0]
        .operation_for(&target, "orders", TransactionOperationMode::FreshQuery)
        .is_some());
    target.function = FunctionId("uninstalled".into());
    assert!(loaded.installations[0]
        .operation_for(&target, "orders", TransactionOperationMode::FreshQuery)
        .is_none());
    assert_eq!(setup.kernel.native.snapshot().unwrap().ordinary.slots, 0);
    drop(loaded);
    assert_eq!(setup.kernel.native.snapshot().unwrap().recovery.slots, 1);
    setup.finish().await;
}
