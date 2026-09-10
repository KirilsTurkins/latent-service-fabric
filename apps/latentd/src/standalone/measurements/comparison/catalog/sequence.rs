use latent_artifacts::ArtifactRepository;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_routing::RouteResolver;
use serde_json::json;
use sha2::{Digest, Sha256};

use super::observation::{self, Counts, Operation};
use super::{fixture, frames, proofs, resolve, Clock, Node, Plan, Result, Writer};

pub(super) async fn run(
    node: &mut Node,
    writer: &mut Writer,
    counts: &mut Counts,
    plan: &Plan,
    clock: Clock,
) -> Result<()> {
    if plan.mode == "reopen" {
        observation::checkpoint(node, writer, clock, "reopened-idle", plan.count(), false)?;
        proofs::reopen(node, writer, counts, plan, plan.count(), clock)?;
        observation::checkpoint(
            node,
            writer,
            clock,
            "reopened-output-released",
            plan.count(),
            false,
        )?;
        return Ok(());
    }
    observation::checkpoint(node, writer, clock, "empty", 0, false)?;
    let mut previous = 0;
    let scales = if plan.mode == "allocation" {
        &[16][..]
    } else {
        plan.scales()
    };
    for &count in scales {
        deadline(plan, clock)?;
        publish(node, writer, counts, plan, previous, count, clock).await?;
        // No desired-state request or oracle table exists at this checkpoint.
        observation::checkpoint(node, writer, clock, "artifact-only", count, false)?;
        let deployments = (previous..count)
            .map(|index| fixture::deployment(&node.fixture, plan, index))
            .collect();
        let before = node.deployments.generation();
        let verification = observation::verification(node)?;
        counts.issued(node, Operation::Apply)?;
        let started = clock.elapsed();
        let outcome = node.deployments.apply_many(deployments).await;
        let finished = clock.elapsed();
        counts.returned(Operation::Apply, outcome.is_ok());
        let result = match &outcome {
            Ok(generation) => json!({"generation":generation.0.to_string()}),
            Err(error) => json!({"error":observation::error(error)}),
        };
        writer.sample(&json!({"kind":"apply","mode":"growth","first":previous.to_string(),"count":(count-previous).to_string(),
            "generation_before":before.0.to_string(),"started_nanos":started.to_string(),"finished_nanos":finished.to_string(),
            "verification_before":verification,"verification_after":observation::verification(node)?,"result":result}))?;
        let generation = outcome.map_err(super::super::super::platform)?;
        if generation.0
            != before
                .0
                .checked_add(1)
                .ok_or("catalog generation overflow")?
        {
            return Err("catalog apply generation mismatch".into());
        }
        observation::checkpoint(node, writer, clock, "post-publication-idle", count, false)?;
        if plan.mode == "allocation" {
            frames::run(node, writer, counts, plan, count, clock)?;
        } else {
            resolve::normal(node, writer, counts, plan, count, clock)?;
        }
        observation::checkpoint(
            node,
            writer,
            clock,
            "after-resolver-output-drop",
            count,
            false,
        )?;
        previous = count;
    }
    if plan.mode == "initial" {
        proofs::update(node, writer, counts, plan, plan.count(), clock).await?;
    }
    Ok(())
}

async fn publish(
    node: &mut Node,
    writer: &mut Writer,
    counts: &mut Counts,
    plan: &Plan,
    first: u32,
    end: u32,
    clock: Clock,
) -> Result<()> {
    let codec = JsonManifestCodec::default();
    for begin in (first..end).step_by(256) {
        deadline(plan, clock)?;
        let stop = (begin + 256).min(end);
        let started = clock.elapsed();
        let mut digest = Sha256::new();
        digest.update(b"lsf-catalog-publication-v1\0");
        let mut completed = 0_u32;
        let mut failure = None;
        for index in begin..stop {
            let artifact = fixture::artifact(&node.fixture, plan, index);
            let expected = artifact.descriptor.clone();
            let capsule_digest = latent_artifacts::content_digest(
                &codec
                    .encode_capsule(&artifact.manifest)
                    .map_err(|_| "catalog publication capsule encoding")?,
            )
            .0;
            let deployment_digest = latent_artifacts::content_digest(
                &codec
                    .encode_deployment(&fixture::deployment(&node.fixture, plan, index))
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
        writer.sample(&json!({"kind":"publication-chunk","first":begin.to_string(),"planned_count":(stop-begin).to_string(),
            "completed":completed.to_string(),"started_nanos":started.to_string(),"finished_nanos":clock.elapsed().to_string(),
            "digest":format!("sha256:{:x}",digest.finalize()),"failure":failure}))?;
        if failure.is_some() {
            return Err("catalog publication failed".into());
        }
    }
    Ok(())
}

fn deadline(plan: &Plan, clock: Clock) -> Result<()> {
    if clock.elapsed() >= u128::from(plan.seconds()) * 1_000_000_000 {
        return Err("catalog source deadline reached".into());
    }
    Ok(())
}
