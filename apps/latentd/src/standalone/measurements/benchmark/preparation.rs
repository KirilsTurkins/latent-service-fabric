use std::time::Instant;

use latent_artifacts::{ArtifactRepository, CapsuleArtifact};
use latent_executor::{ExecutionBackend, PreparationKey, PreparedComponent};
use latent_wasmtime::PreparedCacheSnapshot;
use serde_json::{json, Value};

use super::{execute, platform, write_call, Case, MeasurementNode, MeasurementWriter, Result};

pub(super) async fn initial(node: &MeasurementNode, writer: &mut MeasurementWriter) -> Result<()> {
    let backend = &node.node.backend;
    let fixture = &node.fixtures.echo;
    drop(published(node, fixture).await?);
    let key = backend
        .preparation_key(&fixture.artifact.descriptor.release_digest)
        .map_err(platform)?;
    let before = backend.cache_snapshot();
    let started = Instant::now();
    let _prepared = prepare(node, &key).await?;
    let elapsed = started.elapsed().as_micros();
    let after = backend.cache_snapshot();
    if before.entries != 0 || before.misses != 0 || after.entries != 1 || after.misses != 1 {
        return Err("initial preparation did not use an empty engine cache".into());
    }
    writer.write(
        "benchmark-prepare",
        &json!({"sample":"0","operation":"initial","elapsed_micros":elapsed.to_string(),
        "scope":"repository-acquisition-including-verified-refill",
        "cache_before":cache(&before),"cache_after":cache(&after)}),
    )?;
    Ok(())
}

pub(super) async fn pair(
    node: &MeasurementNode,
    writer: &mut MeasurementWriter,
    index: u32,
) -> Result<()> {
    let backend = &node.node.backend;
    let fixture = &node.fixtures.echo;
    drop(published(node, fixture).await?);
    let key = backend
        .preparation_key(&fixture.artifact.descriptor.release_digest)
        .map_err(platform)?;
    let descriptor = prepare(node, &key).await?;
    backend.release(descriptor).await.map_err(platform)?;
    let before = backend.cache_snapshot();
    let started = Instant::now();
    let cold = prepare(node, &key).await?;
    let elapsed = started.elapsed().as_micros();
    let after = backend.cache_snapshot();
    if after.misses != before.misses + 1 || after.entries != before.entries + 1 {
        return Err("cold preparation did not compile".into());
    }
    writer.write(
        "benchmark-prepare",
        &json!({"sample":index.to_string(),"operation":"cold","elapsed_micros":elapsed.to_string(),
        "scope":"repository-acquisition-including-verified-refill",
        "cache_before":cache(&before),"cache_after":cache(&after)}),
    )?;
    let first = execute(node, Case::FirstEcho, &format!("bench-first-{index}")).await?;
    require_reuse(node, &after)?;
    write_call(writer, "cold_first_rpc", index, &first)?;
    let before = backend.cache_snapshot();
    let started = Instant::now();
    let hit = prepare(node, &key).await?;
    let elapsed = started.elapsed().as_micros();
    let after = backend.cache_snapshot();
    if cold != hit || after.hits != before.hits + 1 || after.misses != before.misses {
        return Err("cache preparation did not reuse identity".into());
    }
    writer.write("benchmark-prepare",&json!({"sample":index.to_string(),"operation":"cache_hit","elapsed_micros":elapsed.to_string(),
        "scope":"repository-acquisition-including-verified-refill",
        "cache_before":cache(&before),"cache_after":cache(&after)}))?;
    let warm = execute(node, Case::Echo, &format!("bench-hit-{index}")).await?;
    require_reuse(node, &after)?;
    write_call(writer, "warm_rpc", index, &warm)
}

pub(super) async fn prewarm_failures(node: &MeasurementNode) -> Result<()> {
    let backend = &node.node.backend;
    for fixture in [&node.fixtures.generic, &node.fixtures.capabilities] {
        let artifact = published(node, fixture).await?;
        let key = backend
            .preparation_key(&artifact.descriptor.release_digest)
            .map_err(platform)?;
        drop(
            backend
                .prepare_from_repository(node.artifacts.as_ref(), &key)
                .await
                .map_err(platform)?,
        );
    }
    let cache = backend.cache_snapshot();
    if cache.entries != 3 || cache.misses != 3 || cache.evictions != 0 {
        return Err("benchmark prewarm did not retain exactly three published identities".into());
    }
    Ok(())
}

async fn prepare(node: &MeasurementNode, key: &PreparationKey) -> Result<PreparedComponent> {
    let activation = node
        .node
        .backend
        .prepare_from_repository(node.artifacts.as_ref(), key)
        .await
        .map_err(platform)?;
    let descriptor = activation.prepared.descriptor().clone();
    drop(activation);
    Ok(descriptor)
}

pub(super) fn require_reuse(node: &MeasurementNode, before: &PreparedCacheSnapshot) -> Result<()> {
    let after = node.node.backend.cache_snapshot();
    if after.hits != before.hits + 1
        || after.misses != before.misses
        || after.entries != before.entries
    {
        return Err("RPC did not reuse the prepared published identity".into());
    }
    Ok(())
}

async fn published(
    node: &MeasurementNode,
    fixture: &super::super::fixtures::Fixture,
) -> Result<CapsuleArtifact> {
    // Management creates the stored descriptor. Its reference participates in
    // preparation identity, so the caller's pre-publication descriptor cannot
    // substitute for it. This fixture oracle is outside preparation timings;
    // actual repository acquisition (including verified refill) is timed.
    let artifact = node
        .artifacts
        .fetch(&fixture.artifact.descriptor.release_digest)
        .await
        .map_err(platform)?;
    if artifact.descriptor.release_digest != fixture.artifact.descriptor.release_digest
        || artifact.manifest != fixture.artifact.manifest
        || artifact.contracts != fixture.artifact.contracts
        || artifact.component_bytes != fixture.artifact.component_bytes
    {
        return Err("published preparation inputs differ from recorded fixture".into());
    }
    Ok(artifact)
}

fn cache(value: &PreparedCacheSnapshot) -> Value {
    json!({"entries":value.entries.to_string(),"hits":value.hits.to_string(),"misses":value.misses.to_string(),
        "preparing":value.preparing.to_string(),"source_bytes":value.source_bytes.to_string(),
        "compiled_image_bytes":value.compiled_image_bytes.to_string()})
}
