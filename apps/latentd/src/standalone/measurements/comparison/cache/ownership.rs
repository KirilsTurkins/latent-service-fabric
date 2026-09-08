use latent_core::ReleaseDigest;
use latent_executor::ExecutionBackend;
use serde_json::json;

use super::{cold, direct, observation, sequence, Node, Result, State, Writer};

pub(super) async fn release(
    node: &Node,
    writer: &mut Writer,
    clock: cold::call::Clock,
    state: &mut State,
    key: usize,
    label: &str,
) -> Result<()> {
    let descriptor = state.descriptors[key]
        .as_ref()
        .ok_or("cache release descriptor absent")?
        .clone();
    let before = node.owner.backend.cache_accounting_snapshot();
    let started = clock.elapsed();
    state.direct.releases += 1;
    let result = node.owner.backend.release(descriptor.clone()).await;
    writer.sample(
        &json!({"kind":"explicit-release","label":label,"key":key.to_string(),
        "release_digest":descriptor.key.release.0,"prepared_handle":descriptor.opaque_handle,
        "started_nanos":started.to_string(),"finished_nanos":clock.elapsed().to_string(),
        "succeeded":result.is_ok(),"accounting_before":observation::decimal(&before)?,
        "accounting_after":observation::decimal(&node.owner.backend.cache_accounting_snapshot())?}),
    )?;
    result.map_err(super::super::super::platform)
}

#[expect(
    clippy::too_many_lines,
    reason = "The affine ready and active owners remain visible through every recorded lifetime transition."
)]
pub(super) async fn run(
    node: &mut Node,
    writer: &mut Writer,
    clock: cold::call::Clock,
    state: &mut State,
    releases: &[String],
) -> Result<()> {
    for key in 0..5 {
        release(node, writer, clock, state, key, "ownership-reset").await?;
    }
    observation::checkpoint(node, writer, clock, "ownership-empty", true)?;
    let helper = node
        .owner
        .factory
        .as_ref()
        .ok_or("cache node factory absent")?
        .create_backend_instance();
    let key = helper
        .preparation_key(&ReleaseDigest(releases[0].clone()))
        .map_err(super::super::super::platform)?;
    state.direct.readiness_acquisitions += 1;
    let first = helper
        .prepare_ready_from_repository(node.artifacts.clone(), key.clone())
        .await
        .map_err(super::super::super::platform)?;
    state.direct.readiness_acquisitions += 1;
    let held = helper
        .prepare_ready_from_repository(node.artifacts.clone(), key)
        .await
        .map_err(super::super::super::platform)?;
    if first.descriptor() != held.descriptor() {
        return Err("held readiness descriptors differ".into());
    }
    let descriptor = held.descriptor().clone();
    writer.sample(&json!({"kind":"direct-readiness","release_digest":descriptor.key.release.0,
        "prepared_handle":descriptor.opaque_handle,"owners":"2","direct_work":observation::decimal(&state.direct)?}))?;
    observation::checkpoint(node, writer, clock, "held-two-ready", false)?;
    state.direct.materializations += 1;
    let active = helper
        .materialize_ready(first)
        .map_err(super::super::super::platform)?;
    observation::checkpoint(node, writer, clock, "held-ready-and-active", false)?;
    state.events.export(node, writer, clock, "held-prepared")?;
    for key in 1..5 {
        sequence::invoke(
            node,
            writer,
            clock,
            "ownership-evict",
            key - 1,
            key,
            &releases[key as usize],
        )
        .await?;
    }
    observation::checkpoint(node, writer, clock, "evicted-held-ready-and-active", false)?;
    state.events.export(node, writer, clock, "held-evicted")?;
    state.direct.executions += 1;
    direct::execute(&helper, active, writer, clock).await?;
    observation::checkpoint(node, writer, clock, "evicted-held-ready", false)?;
    sequence::invoke(
        node,
        writer,
        clock,
        "ownership-recompile",
        0,
        0,
        &releases[0],
    )
    .await?;
    observation::checkpoint(node, writer, clock, "resident-new-and-evicted-old", false)?;
    drop(held);
    observation::checkpoint(node, writer, clock, "released-old-ready", true)?;
    let before = node.owner.backend.cache_accounting_snapshot();
    sequence::invoke(node, writer, clock, "ownership-invalid", 0, 5, &releases[5]).await?;
    cold::observation::drain(&node.owner.backend.preparation_observer(), clock).await?;
    let after = node.owner.backend.cache_accounting_snapshot();
    // Hits/misses/failures may change; only admitted residency costs must remain.
    writer.sample(&json!({"kind":"failed-refill-accounting","before":observation::decimal(&before)?,"after":observation::decimal(&after)?}))?;
    if before.resident.entries != after.resident.entries
        || before.resident.source_bytes != after.resident.source_bytes
        || before.resident.metadata_bytes != after.resident.metadata_bytes
        || before.resident.compiled_image_bytes != after.resident.compiled_image_bytes
    {
        return Err("failed surface refill changed cache residency".into());
    }
    sequence::invoke(node, writer, clock, "ownership-healthy", 0, 0, &releases[0]).await?;
    drop(helper);
    state
        .events
        .export(node, writer, clock, "ownership-complete")?;
    observation::checkpoint(node, writer, clock, "ownership-complete", true)
}
