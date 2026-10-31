use latent_artifacts::*;
use latent_core::{
    ArtifactReference, ContractId, FunctionId, InterfaceId, Metadata, PlatformError, TenantId,
};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidator, Phase1ManifestValidator,
};
use std::{
    fs,
    future::Future,
    path::{Path, PathBuf},
    pin::Pin,
    sync::atomic::{AtomicU64, Ordering},
    task::{Context, Poll, Waker},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

pub const TIMEOUT: Duration = Duration::from_secs(30);
const PLACEHOLDER_DIGEST: &str =
    "sha256:1111111111111111111111111111111111111111111111111111111111111111";
static NEXT: AtomicU64 = AtomicU64::new(0);
pub struct Root(PathBuf);
impl Root {
    pub fn new() -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "lsf-native-retention-{}-{nonce}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::SeqCst)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    pub fn path(&self) -> &Path {
        &self.0
    }
    pub fn open(&self) -> DirectoryArtifactRepository {
        DirectoryArtifactRepository::open(self.path(), DirectoryArtifactRepositoryConfig::default())
            .unwrap()
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
pub fn block_on<T>(mut future: Pin<Box<dyn Future<Output = T> + Send + '_>>) -> T {
    let mut context = Context::from_waker(Waker::noop());
    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(value) => return value,
            Poll::Pending => std::thread::yield_now(),
        }
    }
}
pub fn scope() -> LifecycleScope {
    LifecycleScope::Tenant(TenantId("examples".into()))
}
pub fn context(id: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: scope(),
        actor: ReleaseActor {
            subject: "authenticated-native-test-admin".into(),
            kind: ReleaseActorKind::Administrator,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: id.into(),
            expected_generation: generation,
        }),
    }
}
pub fn publish(repo: &DirectoryArtifactRepository, label: &str) -> PublicationRef {
    block_on(repo.publish_managed(
        context(&format!("publish-{label}"), 0),
        ManagedPublicationUpload::Local(artifact(label, b"shared native component")),
        &mut |_| Ok(()),
    ))
    .unwrap()
    .publication
}
pub fn snapshot(
    repo: &DirectoryArtifactRepository,
    publications: &[PublicationRef],
) -> PublicationRetentionSnapshot {
    repo.publication_retention_snapshot(&scope(), publications, TIMEOUT)
        .unwrap()
}
pub fn request(
    repo: &DirectoryArtifactRepository,
    publications: &[PublicationRef],
    id: &str,
    action: PublicationRetentionAction,
) -> PublicationRetentionRequest {
    let selected = snapshot(repo, publications);
    // Avoid in-place collect reusing the larger selection allocation, which
    // would retain capacity above the request's exact 32-target memory bound.
    let mut targets = Vec::with_capacity(selected.selections.len());
    for selection in selected.selections {
        targets.push(selection.target);
    }
    PublicationRetentionRequest {
        scope: scope(),
        actor: context("unused", 0).actor,
        operation_id: id.into(),
        expected_catalog_fence: selected.catalog_fence,
        action,
        targets,
    }
}
pub fn mutate(
    repo: &DirectoryArtifactRepository,
    request: PublicationRetentionRequest,
) -> Result<PublicationRetentionResult, PlatformError> {
    repo.change_publication_retention(&request, TIMEOUT, &mut |_| Ok(()))
}
pub fn retire(repo: &DirectoryArtifactRepository, publication: &PublicationRef) {
    repo.change_publication_lifecycle(
        context("retire", 1),
        publication,
        ReleaseLifecycleAction::Retire,
        ReleaseLifecycleReason::OperatorRetirement,
        &mut |_| Ok(()),
    )
    .unwrap();
}
pub fn artifact(name: &str, bytes: &[u8]) -> CapsuleArtifact {
    let release = latent_artifacts::content_digest(bytes);
    // Keep the example's name, tenant, world and exports in the same scope.
    let manifest_source = include_str!("../../../../examples/echo-contract/capsule.json")
        .replace(PLACEHOLDER_DIGEST, &release.0);
    let manifest = JsonManifestCodec::default()
        .decode_capsule(manifest_source.as_bytes())
        .expect("test capsule must decode");
    Phase1ManifestValidator::new()
        .validate_capsule(&manifest)
        .expect("test capsule must satisfy semantic validation");
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://tests/{name}")),
            release_digest: release,
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: u64::try_from(bytes.len()).expect("test component length must fit u64"),
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest,
        contracts: vec![contract_fixture()],
        component_bytes: bytes.to_vec(),
    }
}

fn contract_fixture() -> ContractDescriptor {
    let mut attributes = Metadata::new();
    attributes.insert("latent.dev/test".to_owned(), "catalog".to_owned());
    ContractDescriptor {
        id: ContractId("tests:catalog/api@0.1.0".to_owned()),
        package_name: "tests:catalog".to_owned(),
        semantic_version: "0.1.0".to_owned(),
        interfaces: vec![InterfaceDescriptor {
            id: InterfaceId("tests:catalog/api@0.1.0".to_owned()),
            functions: vec![FunctionDescriptor {
                id: FunctionId("round-trip".to_owned()),
                name: "round-trip".to_owned(),
                asynchronous: true,
                parameters: vec![FieldDescriptor {
                    name: "input".to_owned(),
                    value_type: ValueType::List(Box::new(ValueType::Option(Box::new(
                        ValueType::String,
                    )))),
                    documentation: Some("input field".to_owned()),
                }],
                results: vec![FieldDescriptor {
                    name: "output".to_owned(),
                    value_type: ValueType::Result {
                        ok: Some(Box::new(ValueType::Bytes)),
                        error: Some(Box::new(ValueType::Record("failure".to_owned()))),
                    },
                    documentation: None,
                }],
                documentation: Some("round-trip function".to_owned()),
                attributes,
            }],
            documentation: Some("catalog test interface".to_owned()),
            digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                .to_owned(),
        }],
        dependencies: vec![ContractId("latent:context/context@0.1.0".to_owned())],
        digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            .to_owned(),
    }
}
