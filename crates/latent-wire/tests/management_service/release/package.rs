use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

use latent_artifacts::{
    ArtifactCatalogEntry, ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository,
    CapsuleArtifact, ManagedPublicationReceipt, ManagedPublicationUpload, ReleaseLifecycleAction,
    ReleaseLifecycleReason, ReleaseLifecycleRecord, ReleaseLifecycleState, ReleaseMutationContext,
    ReleaseOperationDisposition, ReleaseOperationPreview, ReleaseOperationReceipt,
};
use latent_core::{BoxFuture, PlatformError, PublisherId, ReleaseDigest, ServiceId};
use tonic::{Code, Request};

use super::{artifact, proto, publish, Harness, ManagementLimits};

struct PublicationOwner {
    summary: ArtifactCatalogEntry,
    commits: AtomicUsize,
    reject: bool,
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
            reject: false,
        }
    }
}

// This fixture tests the authenticated wire handoff and reject-only preflight;
// cryptographic admission and durable commits are exercised by their real owners.
impl ArtifactRepository for PublicationOwner {
    fn publish_managed<'a>(
        &'a self,
        context: ReleaseMutationContext,
        upload: ManagedPublicationUpload,
        preflight: &'a mut (dyn for<'p> FnMut(ReleaseOperationPreview<'p>) -> Result<(), PlatformError>
                     + Send),
    ) -> BoxFuture<'a, Result<ManagedPublicationReceipt, PlatformError>> {
        Box::pin(async move {
            assert_eq!(context.scope.tenant().unwrap().0, "acme");
            assert_eq!(context.actor.subject, "alice");
            let ManagedPublicationUpload::Package(upload) = upload else {
                panic!("expected package");
            };
            assert_eq!(upload.manifest, b"{\"exact\":true}");
            assert_eq!(upload.layers, vec![("component.wasm".to_owned(), vec![0])]);
            let package = latent_artifacts::package::package_digest(&upload.manifest);
            let operation_id = context
                .operation
                .as_ref()
                .map_or_else(|| "server-attempt".to_owned(), |v| v.operation_id.clone());
            let record = ReleaseLifecycleRecord {
                scope: context.scope.clone(),
                release: self.summary.descriptor.release_digest.clone(),
                package: Some(package.clone()),
                state: ReleaseLifecycleState::Admitted,
                generation: 1,
                actor: context.actor.clone(),
                reason: ReleaseLifecycleReason::Admitted,
                operation_id: operation_id.clone(),
                policy: None,
                observed_at_unix_millis: None,
                evidence_revision_digest: None,
            };
            let receipt = ReleaseOperationReceipt {
                operation_id: operation_id.clone(),
                request_digest: latent_artifacts::package::artifact_blob_digest(b"bounded-request"),
                scope: context.scope,
                actor: context.actor,
                action: ReleaseLifecycleAction::Publish,
                disposition: if self.reject {
                    ReleaseOperationDisposition::Rejected
                } else {
                    ReleaseOperationDisposition::Committed
                },
                reason: if self.reject {
                    ReleaseLifecycleReason::InvalidPackage
                } else {
                    ReleaseLifecycleReason::Admitted
                },
                component_digest: (!self.reject).then(|| record.release.clone()),
                package_manifest_digest: Some(package.as_str().parse().unwrap()),
                expected_generation: context.operation.map(|v| v.expected_generation),
                record: (!self.reject).then_some(record),
                policy: None,
                observed_at_unix_millis: None,
            };
            let failure = PlatformError {
                code: latent_core::PlatformErrorCode::AdmissionRejected,
                message: "private failed input".to_owned(),
                retryable: false,
                details: vec![latent_core::ErrorDetail {
                    kind: "release-operation".to_owned(),
                    fields: latent_core::Metadata::from([
                        ("operation_id".to_owned(), operation_id),
                        ("disposition".to_owned(), "rejected".to_owned()),
                        ("reason".to_owned(), "invalid-package".to_owned()),
                    ]),
                }],
            };
            preflight(ReleaseOperationPreview {
                replay: false,
                receipt: &receipt,
                release: (!self.reject).then_some(&self.summary),
                failure: self.reject.then_some(&failure),
            })?;
            self.commits.fetch_add(1, Ordering::SeqCst);
            if self.reject {
                return Err(failure);
            }
            Ok(ManagedPublicationReceipt {
                release: self.summary.clone(),
                operation: receipt,
            })
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

#[tokio::test]
async fn rejected_publication_preflights_its_operation_receipt_before_persistence() {
    for (maximum, expected_commits) in [(512, 0), (4 * 1024 * 1024, 1)] {
        let mut owner = PublicationOwner::new();
        owner.reject = true;
        let owner = Arc::new(owner);
        let limits = ManagementLimits {
            max_response_bytes: maximum,
            max_metadata_bytes: maximum.min(32768),
            max_string_bytes: maximum.min(4096),
            max_page_token_bytes: maximum.min(8192),
            max_collection_entries: maximum.min(1024),
            max_route_services: maximum.min(1024),
            max_route_revisions: maximum.min(4096),
            ..ManagementLimits::default()
        };
        let harness = Harness::with_artifacts(limits, Some(owner.clone())).await;
        let status = publish(&harness, "alice", upload()).await.unwrap_err();
        assert_eq!(status.code(), Code::ResourceExhausted);
        assert_eq!(owner.commits.load(Ordering::SeqCst), expected_commits);
        assert!(!format!("{status:?}").contains("private failed input"));
        if expected_commits == 1 {
            use prost::Message;
            let error = proto::PlatformError::decode(status.details()).unwrap();
            assert_eq!(
                error.detail_items[0].fields["operation_id"],
                "server-attempt"
            );
            assert_eq!(error.detail_items[0].fields["disposition"], "rejected");
        }
        harness.shutdown().await;
    }
}
