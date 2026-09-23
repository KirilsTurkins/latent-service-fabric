use super::{artifact, Harness};
use latent_artifacts::{
    ArtifactRepository, CapsuleArtifact, LifecycleScope, ManagedPublicationUpload, ReleaseActor,
    ReleaseActorKind, ReleaseMutationContext,
};
use latent_core::{ReleaseDigest, TenantId};
use latent_wire::management::proto;

pub(crate) async fn publish_variant(
    harness: &Harness,
    tenant: &str,
    variant: &str,
) -> (proto::PublicationRef, ReleaseDigest) {
    let mut artifact = artifact(tenant, "echo", "identical-executable");
    artifact.manifest.semantic_version = variant.into();
    publish_artifact(harness, artifact).await
}

pub(crate) async fn publish_artifact(
    harness: &Harness,
    artifact: CapsuleArtifact,
) -> (proto::PublicationRef, ReleaseDigest) {
    let tenant = artifact
        .manifest
        .metadata
        .tenant
        .as_ref()
        .unwrap()
        .0
        .clone();
    let published = harness
        .artifacts
        .publish_managed(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId(tenant.clone())),
                actor: ReleaseActor {
                    subject: "fixture".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: None,
            },
            ManagedPublicationUpload::Local(artifact),
            &mut |_| Ok(()),
        )
        .await
        .unwrap();
    (
        proto::PublicationRef {
            id: published.publication.id.into_string(),
            tenant,
        },
        published.release.descriptor.release_digest.clone(),
    )
}
