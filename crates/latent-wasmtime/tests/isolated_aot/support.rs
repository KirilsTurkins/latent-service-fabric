use std::fs;
use std::future::Future;
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, OnceLock};
use std::task::{Context, Poll, Waker};
use std::time::{SystemTime, UNIX_EPOCH};

use latent_artifacts::{
    content_digest, ArtifactDescriptor, ArtifactRepository, CapsuleArtifact,
    DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig, LifecycleScope,
    OwnedArtifactPreparationSource, ReleaseActor, ReleaseActorKind, ReleaseLifecycleAction,
    ReleaseLifecycleReason, ReleaseMutationContext, ReleaseOperationPrecondition,
};
use latent_core::{ArtifactReference, ContractId, Metadata, ReleaseDigest, TenantId};
use latent_manifest::{ContractExport, JsonManifestCodec, ManifestCodec};
use latent_wasmtime::{
    AotProcessLimits, IsolatedAotCompiler, TrustedAotCompilerAuthority, ValidatedAotProfile,
    WasmtimeConfig,
};
use zeroize::Zeroizing;

#[path = "diagnostics.rs"]
#[allow(dead_code, reason = "shared with the custom supervisor harness")]
pub mod diagnostics;
#[path = "prepared.rs"]
pub mod prepared;

pub const OUTPUT_BYTES: usize = 1024 * 1024;
pub const COMPILER_NAME: &str = "isolated-aot-fixture";
const KEY: [u8; 32] = [37; 32];

pub struct Directory(PathBuf);
impl Directory {
    pub fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "lsf-isolated-aot-{}-{timestamp}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    #[allow(
        dead_code,
        reason = "only the separate supervisor harness needs marker paths"
    )]
    pub fn path(&self) -> &Path {
        &self.0
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _stage = diagnostics::Span::new("fixture-teardown");
        fs::remove_dir_all(&self.0).expect("remove owned AOT fixture directory");
    }
}

pub struct Fixture {
    pub repository: Arc<DirectoryArtifactRepository>,
    pub artifact: CapsuleArtifact,
    directory: Directory,
}
impl Fixture {
    pub fn tiny() -> Self {
        Self::new(super::component::bytes())
    }
    pub fn new(bytes: Vec<u8>) -> Self {
        let _stage = diagnostics::Span::new("fixture-creation");
        let directory = Directory::new();
        let repository = Arc::new(
            DirectoryArtifactRepository::open(
                &directory.0,
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        );
        let release = content_digest(&bytes);
        let mut manifest = JsonManifestCodec::default()
            .decode_capsule(include_bytes!(
                "../../../../examples/echo-contract/capsule.json"
            ))
            .unwrap();
        manifest.component_digest = release.clone();
        manifest.metadata.name = "tests/isolated-aot".into();
        manifest.metadata.tenant = Some(TenantId("tests".into()));
        manifest.world = ContractId("tests:admission/service@1.0.0".into());
        manifest.minimum_fabric_version = "0.1.0-alpha.0".into();
        manifest.imports.clear();
        manifest.exports = vec![ContractExport {
            contract: ContractId(super::component::CONTRACT.into()),
        }];
        let artifact = CapsuleArtifact {
            descriptor: ArtifactDescriptor {
                reference: ArtifactReference("local://isolated-aot-fixture".into()),
                release_digest: release,
                media_type: "application/vnd.wasm.component.v1+wasm".into(),
                size_bytes: bytes.len() as u64,
                publisher: None,
                layers: Vec::new(),
                annotations: Metadata::new(),
            },
            manifest,
            contracts: Vec::new(),
            component_bytes: bytes,
        };
        ready(repository.publish(artifact.clone())).unwrap();
        Self {
            repository,
            artifact,
            directory,
        }
    }
    pub fn release(&self) -> &ReleaseDigest {
        &self.artifact.descriptor.release_digest
    }
    pub fn source(&self) -> OwnedArtifactPreparationSource {
        Arc::clone(&self.repository)
            .owned_preparation_source()
            .unwrap()
    }
    pub fn component_path(&self) -> PathBuf {
        let publication = ready(
            self.repository
                .get_catalog_entry(&TenantId("tests".into()), self.release()),
        )
        .unwrap()
        .unwrap()
        .publication
        .unwrap();
        self.directory
            .0
            .join("publications")
            .join(publication.hex())
            .join("component.wasm")
    }
    pub fn revoke(&self) {
        ready(self.repository.change_release_lifecycle(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId("tests".into())),
                actor: ReleaseActor {
                    subject: "aot-test-host".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: "revoke-aot-fixture".into(),
                    expected_generation: 1,
                }),
            },
            self.release(),
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        ))
        .unwrap();
    }
}

pub fn limits() -> AotProcessLimits {
    let mut limits = AotProcessLimits::default();
    limits.compiler.maximum_output_bytes = OUTPUT_BYTES;
    limits.resources.maximum_jobs = 1;
    limits.resources.maximum_outputs = 1;
    limits.resources.maximum_native_bytes = OUTPUT_BYTES;
    limits.resources.maximum_input_bytes = 4096;
    limits.resources.maximum_document_bytes = 2 * 1024 * 1024;
    limits.maximum_component_bytes = 4096;
    limits.maximum_metadata_bytes = 64 * 1024;
    limits.maximum_document_bytes = 64 * 1024;
    limits
}

pub fn authority(limits: AotProcessLimits) -> TrustedAotCompilerAuthority {
    TrustedAotCompilerAuthority::new(COMPILER_NAME, Zeroizing::new(KEY), limits.compiler).unwrap()
}

fn selected() -> &'static prepared::Executable {
    static INPUT: OnceLock<prepared::Executable> = OnceLock::new();
    INPUT.get_or_init(|| {
        prepared::select(
            "compiler",
            Path::new(env!("CARGO_BIN_EXE_latent-aot-compiler")),
        )
    })
}

pub fn executable() -> &'static Path {
    &selected().path
}
pub fn executable_digest() -> [u8; 32] {
    selected().digest
}

pub fn compiler(limits: AotProcessLimits) -> IsolatedAotCompiler {
    let executable = selected();
    let profile = {
        let _stage = diagnostics::Span::new("engine-profile");
        ValidatedAotProfile::from_config(&WasmtimeConfig::default(), limits.compiler).unwrap()
    };
    let _stage = diagnostics::Span::new("compiler-construction-and-verification");
    IsolatedAotCompiler::new(
        &executable.path,
        executable.digest,
        profile,
        authority(limits),
        limits,
    )
    .unwrap()
}

fn ready<T>(mut operation: Pin<Box<dyn Future<Output = T> + Send + '_>>) -> T {
    match operation
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
    {
        Poll::Ready(value) => value,
        Poll::Pending => panic!("synchronous directory operation unexpectedly awaited"),
    }
}
