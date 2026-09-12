//! Injected trusted host authority for ownership/race tests, not a crypto verifier.
#![allow(dead_code)]

use std::any::Any;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use latent_artifacts::package;
use latent_artifacts::{
    encode_contract_metadata, AdmissionAuthority, AdmissionBinding, AdmissionGrant,
    AdmissionRecheck, CapsuleArtifact, ContractMetadataLimits, PackageAdmissionUpload,
    VerifiedAdmission,
};
use latent_core::{PlatformError, PlatformErrorCode, PublisherId, TenantId};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidator, Phase1ManifestValidator,
};

pub struct Directory(pub PathBuf);
impl Directory {
    pub fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "lsf-admission-race-{}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

pub struct State {
    pub active: AtomicBool,
    pub now: AtomicU64,
    pub until: AtomicU64,
    pub fence: Mutex<()>,
    pub started: AtomicU64,
    pub revoke_after_fence: AtomicBool,
}
impl State {
    fn check(&self) -> Result<(), PlatformError> {
        if !self.active.load(Ordering::SeqCst) {
            return Err(denied("fixture-revoked"));
        }
        if self.now.load(Ordering::SeqCst) >= self.until.load(Ordering::SeqCst) {
            return Err(denied("fixture-expired"));
        }
        Ok(())
    }
}

pub struct Authority {
    pub state: Arc<State>,
    artifacts: Vec<CapsuleArtifact>,
}
impl Authority {
    pub fn new(artifact: CapsuleArtifact) -> Arc<Self> {
        Self::new_many(vec![artifact])
    }
    pub fn new_many(artifacts: Vec<CapsuleArtifact>) -> Arc<Self> {
        Arc::new(Self {
            artifacts,
            state: Arc::new(State {
                active: AtomicBool::new(true),
                now: AtomicU64::new(100),
                until: AtomicU64::new(200),
                fence: Mutex::new(()),
                started: AtomicU64::new(0),
                revoke_after_fence: AtomicBool::new(false),
            }),
        })
    }
}
struct Grant {
    binding: AdmissionBinding,
    state: Arc<State>,
}
struct Checker<'a>(&'a Grant);
impl AdmissionRecheck for Checker<'_> {
    fn check(&self) -> Result<(), PlatformError> {
        self.0.state.check()
    }
    fn check_grant(&self, grant: &dyn AdmissionGrant) -> Result<(), PlatformError> {
        let grant = grant
            .as_any()
            .downcast_ref::<Grant>()
            .ok_or_else(|| denied("fixture-owner"))?;
        if !Arc::ptr_eq(&grant.state, &self.0.state) {
            return Err(denied("fixture-owner"));
        }
        grant.state.check()
    }
}
impl AdmissionGrant for Grant {
    fn as_any(&self) -> &dyn Any {
        self
    }
    fn binding(&self) -> &AdmissionBinding {
        &self.binding
    }
    fn retained_bytes(&self) -> usize {
        2048
    }
    fn check_current(&self) -> Result<(), PlatformError> {
        let _guard = self
            .state
            .fence
            .try_lock()
            .map_err(|_| denied("fixture-busy"))?;
        self.state.check()
    }
    fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let _guard = self
            .state
            .fence
            .try_lock()
            .map_err(|_| denied("fixture-busy"))?;
        self.state.check()?;
        self.state.started.fetch_add(1, Ordering::SeqCst);
        let outcome = action(&Checker(self));
        if self.state.revoke_after_fence.swap(false, Ordering::SeqCst) {
            self.state.active.store(false, Ordering::SeqCst);
        }
        outcome
    }
}
impl AdmissionAuthority for Authority {
    fn verify(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        self.state.check()?;
        let layout = package::inspect_package(
            &upload.manifest,
            &upload.configuration,
            package::PackageLimits::default(),
        )?;
        let release = layout
            .component_release()
            .ok_or_else(|| denied("fixture-kind"))?;
        let artifact = self
            .artifacts
            .iter()
            .find(|artifact| artifact.descriptor.release_digest == release)
            .ok_or_else(|| denied("fixture-release"))?;
        if artifact.manifest.metadata.tenant.as_ref() != Some(tenant) {
            return Err(denied("fixture-tenant"));
        }
        let mut artifact = artifact.clone();
        // The trusted injected verifier, rather than the uploaded descriptor,
        // supplies the authenticated publisher association retained by storage.
        artifact.descriptor.publisher = Some(PublisherId("fixture-publisher".to_owned()));
        let binding = AdmissionBinding {
            tenant: tenant.clone(),
            package: package::package_digest(&upload.manifest),
            release: artifact.descriptor.release_digest.clone(),
            receipt: b"trusted-test-receipt".to_vec(),
        };
        Ok(VerifiedAdmission {
            artifact,
            upload,
            grant: Arc::new(Grant {
                binding,
                state: Arc::clone(&self.state),
            }),
        })
    }
    fn recover(
        &self,
        binding: &AdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        let verified = self.verify(&binding.tenant, upload)?;
        if verified.grant.binding() != binding {
            return Err(denied("fixture-binding"));
        }
        Ok(verified)
    }
}

/// Only package layout/integrity is under test here. The trusted fixture authority
/// deliberately supplies admission; production supply-chain tests own semantics/crypto.
pub fn upload(artifact: &CapsuleArtifact) -> PackageAdmissionUpload {
    Phase1ManifestValidator
        .validate_capsule(&artifact.manifest)
        .expect("admission fixtures must satisfy every capsule manifest rule");
    let raw = [
        (
            "capsule.json",
            package::LayerRole::CapsuleManifest,
            package::CAPSULE_MANIFEST_MEDIA_TYPE,
            JsonManifestCodec::default()
                .encode_capsule(&artifact.manifest)
                .unwrap(),
        ),
        (
            "component.wasm",
            package::LayerRole::Component,
            package::COMPONENT_MEDIA_TYPE,
            artifact.component_bytes.clone(),
        ),
        (
            "contracts.json",
            package::LayerRole::Contracts,
            package::CONTRACTS_MEDIA_TYPE,
            encode_contract_metadata(&artifact.contracts, ContractMetadataLimits::default())
                .unwrap(),
        ),
        (
            "wit-lock.json",
            package::LayerRole::WitLock,
            package::WIT_LOCK_MEDIA_TYPE,
            b"{}".to_vec(),
        ),
    ];
    let layers = raw
        .iter()
        .map(|(path, role, media, bytes)| package::PackageLayer {
            path: (*path).to_owned(),
            role: *role,
            media_type: (*media).to_owned(),
            digest: package::artifact_blob_digest(bytes),
            size: bytes.len() as u64,
        })
        .collect::<Vec<_>>();
    let config = package::PackageConfig {
        format_version: 1,
        kind: package::PackageKind::Capsule,
        name: artifact.manifest.metadata.name.clone(),
        version: artifact.manifest.semantic_version.clone(),
        entrypoint: "component.wasm".to_owned(),
        component_digest: Some(package::artifact_blob_digest(&artifact.component_bytes)),
        layers: layers.clone(),
        annotations: BTreeMap::new(),
    };
    let configuration = package::encode_config(&config, package::PackageLimits::default()).unwrap();
    let manifest = package::PackageManifest {
        schema_version: 2,
        media_type: package::OCI_MANIFEST_MEDIA_TYPE.to_owned(),
        artifact_type: config.kind.artifact_type().to_owned(),
        config: package::ArtifactDescriptor {
            media_type: package::PACKAGE_CONFIG_MEDIA_TYPE.to_owned(),
            digest: package::artifact_blob_digest(&configuration),
            size: configuration.len() as u64,
            annotations: None,
        },
        layers: layers
            .into_iter()
            .map(|layer| package::ArtifactDescriptor {
                media_type: layer.media_type,
                digest: layer.digest,
                size: layer.size,
                annotations: Some(BTreeMap::from([
                    (package::LAYER_PATH_ANNOTATION.to_owned(), layer.path),
                    (
                        package::LAYER_ROLE_ANNOTATION.to_owned(),
                        layer.role.as_str().to_owned(),
                    ),
                ])),
            })
            .collect(),
        annotations: BTreeMap::new(),
    };
    PackageAdmissionUpload {
        manifest: package::encode_manifest(&manifest, package::PackageLimits::default()).unwrap(),
        configuration,
        layers: raw
            .into_iter()
            .map(|(path, _, _, bytes)| (path.to_owned(), bytes))
            .collect(),
        signatures: Vec::new(),
        provenance: Vec::new(),
        sboms: Vec::new(),
    }
}

fn denied(message: &'static str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::PermissionDenied,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
