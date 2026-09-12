#[path = "../../../../latent-control-store/tests/admission/support.rs"]
mod authority;
#[path = "../../../tests/admission/component.rs"]
mod component;

use std::collections::BTreeMap;
use std::sync::atomic::Ordering;
use std::sync::{mpsc, Arc};
use std::task::{Context, Waker};
use std::time::Duration;

use latent_artifacts::{
    AdmissionAuthority, AdmissionStorageLimits, ArtifactDescriptor, ArtifactRepository,
    CapsuleArtifact, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
};
use latent_core::{ArtifactReference, ContractId, Metadata, TenantId};
use latent_executor::ExecutionBackend;
use latent_manifest::{ContractExport, JsonManifestCodec, ManifestCodec};

use crate::backend::preparation::ComponentIntegrity;
use crate::compiler::{Acquisition, Admission};
use crate::{WasmtimeComponentEngineFactory, WasmtimeConfig, WasmtimeHostServices};

fn artifact() -> CapsuleArtifact {
    let bytes = component::bytes();
    let release = latent_artifacts::content_digest(&bytes);
    let mut document: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../../examples/echo-contract/capsule.json"
    ))
    .unwrap();
    document["component"]["digest"] = release.0.clone().into();
    let mut manifest = JsonManifestCodec::default()
        .decode_capsule(&serde_json::to_vec(&document).unwrap())
        .unwrap();
    manifest.metadata.tenant = Some(TenantId("tests".to_owned()));
    manifest.metadata.name = "admission-unit".to_owned();
    manifest.world = ContractId("tests:admission/service@1.0.0".to_owned());
    manifest.exports = vec![ContractExport {
        contract: ContractId(component::CONTRACT.to_owned()),
    }];
    manifest.imports.clear();
    manifest.execution.resource_budget_ceiling.cpu_fuel = 1000;
    manifest.execution.resource_budget_ceiling.memory_bytes = 65536;
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://admission-unit".to_owned()),
            release_digest: release,
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: bytes.len() as u64,
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest,
        contracts: Vec::new(),
        component_bytes: bytes,
    }
}

async fn setup() -> (
    authority::Directory,
    Arc<authority::Authority>,
    Arc<DirectoryArtifactRepository>,
    WasmtimeComponentEngineFactory,
) {
    let artifact = artifact();
    let authority = authority::Authority::new(artifact.clone());
    let trusted: Arc<dyn AdmissionAuthority> = authority.clone();
    let directory = authority::Directory::new();
    let repository = Arc::new(
        DirectoryArtifactRepository::open_enforced(
            &directory.0,
            DirectoryArtifactRepositoryConfig::default(),
            AdmissionStorageLimits::default(),
            trusted.clone(),
        )
        .unwrap(),
    );
    repository
        .admit_package(
            &TenantId("tests".to_owned()),
            authority::upload(&artifact),
            &mut |_| Ok(()),
        )
        .await
        .unwrap();
    let config = WasmtimeConfig {
        compiler_workers: Some(1),
        maximum_concurrent_preparations: 3,
        ..WasmtimeConfig::default()
    };
    let factory = WasmtimeComponentEngineFactory::with_enforced_admission(
        config,
        WasmtimeHostServices::default(),
        trusted,
    )
    .unwrap();
    (directory, authority, repository, factory)
}

#[tokio::test(flavor = "current_thread")]
async fn checked_fallback_without_optimization_stamp_retains_eligibility_on_reuse() {
    let (_directory, authority, repository, factory) = setup().await;
    let backend = factory.create_backend_instance();
    backend.preparation_observer().enable();
    let artifact = artifact();
    let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
    let eligibility = repository
        .release_eligibility(&key.release)
        .unwrap()
        .unwrap();
    let job = backend.shared.preparation_observer.begin(&key.release);
    let runtime = backend
        .prepare_runtime_with_integrity(
            &artifact,
            &key,
            ComponentIntegrity::VerifiedBySource,
            Some(eligibility.clone()),
            &job,
        )
        .unwrap();
    assert!(runtime.authentication.is_none());
    assert_eq!(runtime.eligibility.as_ref(), Some(&eligibility));
    let again = backend
        .prepare_runtime_with_integrity(
            &artifact,
            &key,
            ComponentIntegrity::VerifiedBySource,
            Some(eligibility.clone()),
            &job,
        )
        .unwrap();
    assert!(Arc::ptr_eq(&runtime, &again));
    authority.state.active.store(false, Ordering::SeqCst);
    assert!(backend
        .shared
        .preparation_context
        .check_runtime(&runtime)
        .is_err());
    assert!(backend
        .prepare_runtime_with_integrity(
            &artifact,
            &key,
            ComponentIntegrity::VerifiedBySource,
            Some(eligibility),
            &job
        )
        .is_err());
    assert_eq!(backend.resource_snapshot().stores_created, 0);
}

#[tokio::test(flavor = "current_thread")]
async fn queued_source_is_rechecked_before_compilation_and_all_waiters_release() {
    let (_directory, authority, repository, factory) = setup().await;
    let backend = factory.create_backend_instance();
    backend.preparation_observer().enable();
    let pool = backend.shared.compiler.as_ref().unwrap();
    let Acquisition::Waiting {
        future: blocker,
        owner: true,
    } = pool
        .acquire(Admission {
            identity: None,
            handle: "test-owned-blocker".to_owned(),
            source_bytes: 1,
            metadata_bytes: 1,
            document_bytes: 0,
        })
        .unwrap()
    else {
        panic!("fresh blocker");
    };
    let (started_send, started) = mpsc::sync_channel(1);
    let (release, released) = mpsc::sync_channel(1);
    blocker
        .start(move |reservation| {
            Box::new(move |_| {
                let _reservation = reservation;
                started_send.send(()).unwrap();
                let _ = released.recv_timeout(Duration::from_secs(5));
                Err(super::denied("test-blocker-complete"))
            })
        })
        .unwrap();
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    let key = factory.preparation_key(artifact().descriptor.release_digest);
    let mut first = backend.prepare_ready_from_repository(repository.clone(), key.clone());
    let mut second = backend.prepare_ready_from_repository(repository, key);
    assert!(first
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert!(second
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    authority.state.active.store(false, Ordering::SeqCst);
    release.send(()).unwrap();
    assert!(tokio::time::timeout(Duration::from_secs(5), first)
        .await
        .unwrap()
        .is_err());
    assert!(tokio::time::timeout(Duration::from_secs(5), second)
        .await
        .unwrap()
        .is_err());
    assert!(blocker.await.is_err());
    factory.quiesce_compiler().await.unwrap();
    let snapshot = backend.shared.preparation_observer.snapshot();
    let counts: BTreeMap<_, _> = snapshot
        .stages
        .iter()
        .map(|stage| (stage.stage.name(), stage.started))
        .collect();
    assert_eq!(counts["component_new"], 0);
    assert_eq!(backend.compiler_snapshot().reserved_document_bytes, 0);
    assert_eq!(backend.compiler_snapshot().ready_preparations, 0);
    assert_eq!(backend.cache_snapshot().preparing, 0);
}

#[test]
fn explicit_host_requirements_reject_before_component_compilation() {
    let factory = WasmtimeComponentEngineFactory::new(WasmtimeConfig::default()).unwrap();
    let backend = factory.create_backend_instance();
    backend.preparation_observer().enable();
    let mut value = artifact();
    value.manifest.runtime_requirements.target_triples = vec!["unknown-vendor-none".into()];
    let key = factory.preparation_key(value.descriptor.release_digest.clone());
    let job = backend.shared.preparation_observer.begin(&key.release);
    let failure = backend
        .prepare_runtime_with_integrity(&value, &key, ComponentIntegrity::Verify, None, &job)
        .err()
        .unwrap();
    assert_eq!(
        failure.code,
        latent_core::PlatformErrorCode::IncompatibleContract
    );
    assert_eq!(failure.message, "runtime-target-incompatible");
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    assert!(!backend
        .preparation_observer()
        .snapshot()
        .recent_stages
        .iter()
        .any(|entry| entry.stage == crate::PreparationStage::ComponentNew));
}

#[test]
fn declared_host_requirements_change_metadata_identity_without_changing_component() {
    let factory = WasmtimeComponentEngineFactory::new(WasmtimeConfig::default()).unwrap();
    let backend = factory.create_backend_instance();
    let mut value = artifact();
    let original = backend
        .shared
        .preparation_context
        .metadata_identity(&value)
        .unwrap()
        .digest;
    value.manifest.runtime_requirements.runtime = Some(latent_manifest::RuntimeRequirement {
        engine: "wasmtime".into(),
        minimum_version: "47.0.3".into(),
    });
    backend
        .shared
        .preparation_context
        .validate_manifest(&value)
        .unwrap();
    assert_ne!(
        original,
        backend
            .shared
            .preparation_context
            .metadata_identity(&value)
            .unwrap()
            .digest
    );
    assert!(factory
        .profile()
        .configuration
        .contains_key("runtime-compatibility-digest"));
}
