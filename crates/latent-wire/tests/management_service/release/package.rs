use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

use latent_artifacts::{
    ArtifactCatalogEntry, ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository,
    CapsuleArtifact, PackageAdmissionUpload,
};
use latent_core::{BoxFuture, PlatformError, PublisherId, ReleaseDigest, ServiceId, TenantId};
use tonic::{Code, Request};

use super::{artifact, proto, publish, Harness, ManagementLimits};

struct PublicationOwner {
    summary: ArtifactCatalogEntry,
    commits: AtomicUsize,
}

impl PublicationOwner {
    fn new() -> Self {
        let artifact = artifact("acme", "echo", "package-wire-publication");
        let mut descriptor = artifact.descriptor;
        descriptor.publisher = Some(PublisherId("verified-publisher".to_owned()));
        Self {
            summary: ArtifactCatalogEntry {
                descriptor,
                tenant: artifact.manifest.metadata.tenant,
                service: ServiceId(artifact.manifest.metadata.name),
                semantic_version: artifact.manifest.semantic_version,
                world: artifact.manifest.world,
            },
            commits: AtomicUsize::new(0),
        }
    }
}

// This fixture tests the authenticated wire handoff and reject-only preflight;
// cryptographic admission and durable commits are exercised by their real owners.
impl ArtifactRepository for PublicationOwner {
    fn admit_package<'a>(
        &'a self,
        tenant: &'a TenantId,
        upload: PackageAdmissionUpload,
        preflight: &'a mut (dyn FnMut(&ArtifactCatalogEntry) -> Result<(), PlatformError> + Send),
    ) -> BoxFuture<'a, Result<ArtifactCatalogEntry, PlatformError>> {
        Box::pin(async move {
            assert_eq!(tenant.0, "acme");
            assert_eq!(upload.manifest, b"{\"exact\":true}");
            assert_eq!(upload.layers, vec![("component.wasm".to_owned(), vec![0])]);
            preflight(&self.summary)?;
            self.commits.fetch_add(1, Ordering::SeqCst);
            Ok(self.summary.clone())
        })
    }
    fn resolve<'a>(
        &'a self,
        _: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        panic!("not called")
    }
    fn fetch<'a>(
        &'a self,
        _: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        panic!("not called")
    }
    fn publish(
        &self,
        _: CapsuleArtifact,
    ) -> BoxFuture<'_, Result<ArtifactDescriptor, PlatformError>> {
        panic!("raw publication must not be called")
    }
    fn list<'a>(
        &'a self,
        _: Option<&'a ReleaseDigest>,
        _: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        panic!("not called")
    }
}

fn upload() -> proto::PublishReleaseRequest {
    proto::PublishReleaseRequest {
        package: Some(proto::PackageAdmissionUpload {
            manifest: br#"{"exact":true}"#.to_vec(),
            configuration: b"{}".to_vec(),
            layers: vec![proto::PackageAdmissionLayer {
                path: "component.wasm".to_owned(),
                data: vec![0],
            }],
            ..proto::PackageAdmissionUpload::default()
        }),
        ..proto::PublishReleaseRequest::default()
    }
}

#[tokio::test]
async fn authenticated_package_handoff_derives_the_receipt_from_the_repository() {
    let owner = Arc::new(PublicationOwner::new());
    let harness = Harness::with_artifacts(ManagementLimits::default(), Some(owner.clone())).await;
    assert_eq!(
        harness
            .releases_client()
            .publish_release(Request::new(upload()))
            .await
            .unwrap_err()
            .code(),
        Code::Unauthenticated
    );
    assert_eq!(
        publish(&harness, "caller", upload())
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    assert_eq!(owner.commits.load(Ordering::SeqCst), 0);
    let receipt = publish(&harness, "alice", upload()).await.unwrap();
    assert_eq!(receipt.publisher, "verified-publisher");
    assert_eq!(receipt.tenant.as_deref(), Some("acme"));
    assert!(receipt.admitted);
    assert_eq!(owner.commits.load(Ordering::SeqCst), 1);
    harness.shutdown().await;
}

#[tokio::test]
async fn package_response_budget_rejection_precedes_any_commit() {
    let mut owner = PublicationOwner::new();
    owner
        .summary
        .descriptor
        .annotations
        .insert("description".to_owned(), "x".repeat(600));
    let owner = Arc::new(owner);
    let limits = ManagementLimits {
        max_response_bytes: 512,
        max_metadata_bytes: 512,
        max_string_bytes: 512,
        max_page_token_bytes: 512,
        max_collection_entries: 512,
        max_route_services: 512,
        max_route_revisions: 512,
        ..ManagementLimits::default()
    };
    let harness = Harness::with_artifacts(limits, Some(owner.clone())).await;
    assert_eq!(
        publish(&harness, "alice", upload())
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    assert_eq!(owner.commits.load(Ordering::SeqCst), 0);
    harness.shutdown().await;
}
