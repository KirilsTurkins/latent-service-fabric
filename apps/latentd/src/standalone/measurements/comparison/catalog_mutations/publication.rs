use super::super::catalog::fixture;
use super::observation::{self, Counts, Operation};
use super::{Clock, Node, Plan, Result, Writer};
use latent_artifacts::ArtifactRepository;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use serde_json::json;
use sha2::{Digest, Sha256};

pub(super) async fn publish(
    node: &mut Node,
    writer: &mut Writer,
    counts: &mut Counts,
    plan: &Plan,
    clock: Clock,
) -> Result<()> {
    let codec = JsonManifestCodec::default();
    let end = plan.populated_size;
    for begin in (0..end).step_by(256) {
        super::sequence::deadline(plan, clock)?;
        let stop = (begin + 256).min(end);
        let first_ordinal = node.work.commands + 1;
        let started = clock.elapsed();
        let mut digest = Sha256::new();
        digest.update(b"lsf-catalog-publication-v1\0");
        let mut completed = 0_u32;
        let mut failure = None;
        for index in begin..stop {
            let artifact = fixture::artifact_for_shape(&node.fixture, &plan.shape, index);
            let expected = artifact.descriptor.clone();
            let capsule_digest = latent_artifacts::content_digest(
                &codec
                    .encode_capsule(&artifact.manifest)
                    .map_err(|_| "catalog publication capsule encoding")?,
            )
            .0;
            let deployment_digest = latent_artifacts::content_digest(
                &codec
                    .encode_deployment(&fixture::deployment_for_shape(
                        &node.fixture,
                        &plan.shape,
                        index,
                    ))
                    .map_err(|_| "catalog publication deployment encoding")?,
            )
            .0;
            counts.issued(node, Operation::Publish)?;
            let outcome = node.artifacts.publish(artifact).await;
            counts.returned(Operation::Publish, outcome.is_ok());
            match outcome {
                Ok(actual) => {
                    let row = json!({"index":index.to_string(),"descriptor":{"reference":actual.reference.0,
                        "release":actual.release_digest.0,"size":actual.size_bytes.to_string(),"media_type":actual.media_type},
                        "capsule_digest":capsule_digest,"deployment_digest":deployment_digest});
                    let bytes = serde_json::to_vec(&row)?;
                    digest.update((bytes.len() as u64).to_be_bytes());
                    digest.update(&bytes);
                    completed += 1;
                    if actual != expected {
                        failure = Some(
                            json!({"index":index.to_string(),"reason":"descriptor-mismatch","actual":row}),
                        );
                        break;
                    }
                }
                Err(error) => {
                    failure =
                        Some(json!({"index":index.to_string(),"error":observation::error(&error)}));
                    break;
                }
            }
        }
        writer.sample(&json!({"kind":"publication-chunk","first_ordinal":first_ordinal.to_string(),"last_ordinal":node.work.commands.to_string(),"first":begin.to_string(),"planned_count":(stop-begin).to_string(),
            "completed":completed.to_string(),"started_nanos":started.to_string(),"finished_nanos":clock.elapsed().to_string(),
            "digest":format!("sha256:{:x}",digest.finalize()),"failure":failure}))?;
        if failure.is_some() {
            return Err("catalog publication failed".into());
        }
    }
    Ok(())
}
