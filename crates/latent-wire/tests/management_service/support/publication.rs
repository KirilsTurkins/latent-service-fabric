use super::{artifact, Harness};
use latent_artifacts::{
    ArtifactRepository, LifecycleScope, ManagedPublicationUpload, ReleaseActor, ReleaseActorKind,
    ReleaseMutationContext, ReleaseOperationPrecondition,
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
    let published = harness
        .artifacts
        .publish_managed(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId(tenant.into())),
                actor: ReleaseActor {
                    subject: "fixture".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: variant.into(),
                    expected_generation: 0,
                }),
            },
            ManagedPublicationUpload::Local(artifact),
            &mut |_| Ok(()),
        )
        .await
        .unwrap();
    (
        proto::PublicationRef {
            id: published.publication.id.into_string(),
            tenant: tenant.into(),
        },
        published.release.descriptor.release_digest.clone(),
    )
}
