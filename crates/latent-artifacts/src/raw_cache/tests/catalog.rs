use super::*;
use crate::{
    ArtifactDescriptor, ArtifactRepository, CapsuleArtifact, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, ReleaseActor, ReleaseActorKind,
    ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPrecondition,
};
use latent_core::{ArtifactReference, Metadata, TenantId};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll, Waker};
fn ready<T>(mut operation: Pin<Box<dyn Future<Output = T> + Send + '_>>) -> T {
    match operation
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
    {
        Poll::Ready(value) => value,
        Poll::Pending => panic!("synchronous catalog control operation awaited"),
    }
}

fn artifact() -> CapsuleArtifact {
    let bytes = b"tiny trusted-local retained component".to_vec();
    let digest = crate::content_digest(&bytes);
    let mut manifest = JsonManifestCodec::default()
        .decode_capsule(include_bytes!(
            "../../../../../examples/echo-contract/capsule.json"
        ))
        .unwrap();
    manifest.component_digest = digest.clone();
    manifest.metadata.tenant = Some(TenantId("examples".into()));
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://cache-independence".into()),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".into(),
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

#[test]
fn raw_eviction_never_deletes_authoritative_content_or_restores_revoked_eligibility() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let repository = DirectoryArtifactRepository::open(
        root.base().join("catalog"),
        DirectoryArtifactRepositoryConfig::default(),
    )
    .unwrap();
    let artifact = artifact();
    let descriptor = ready(repository.publish(artifact.clone())).unwrap();
    let release = &descriptor.release_digest;
    let eligibility = repository.execution_eligibility(release).unwrap().unwrap();
    drop(put(&cache, &artifact.component_bytes));
    cache.reserve_reclaim(1).unwrap().run().unwrap();
    assert!(cache
        .try_pin(&blob(&artifact.component_bytes))
        .unwrap()
        .is_none());
    assert_eq!(ready(repository.fetch(release)).unwrap(), artifact);
    eligibility.check_current().unwrap();

    ready(repository.change_release_lifecycle(
        ReleaseMutationContext {
            scope: LifecycleScope::Tenant(TenantId("examples".into())),
            actor: ReleaseActor {
                subject: "cache-test-host".into(),
                kind: ReleaseActorKind::Host,
            },
            operation: Some(ReleaseOperationPrecondition {
                operation_id: "revoke-cache-independent".into(),
                expected_generation: 1,
            }),
        },
        release,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    ))
    .unwrap();
    let pin = put(&cache, &artifact.component_bytes);
    let bytes = pin
        .reserve_read(artifact.component_bytes.len() as u64)
        .unwrap()
        .read_verified()
        .unwrap();
    assert_eq!(bytes.as_bytes(), artifact.component_bytes.as_slice());
    assert!(eligibility.check_current().is_err());
    assert!(repository.execution_eligibility(release).is_err());
    assert!(ready(repository.fetch(release)).is_err());
    let retained = ready(repository.historical_execution_snapshot(release)).unwrap();
    assert_eq!(retained.metadata().descriptor(), &descriptor);
}
