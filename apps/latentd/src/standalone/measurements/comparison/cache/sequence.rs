use latent_core::ReleaseDigest;
use latent_executor::ExecutionBackend;

use super::{cold, Node, Result, State, Writer};

pub(super) struct Sequence<'a> {
    pub phase: &'a str,
    pub keys: &'a [u32],
    pub count: u32,
}

pub(super) async fn run(
    node: &mut Node,
    writer: &mut Writer,
    clock: cold::call::Clock,
    state: &mut State,
    releases: &[String],
    sequence: Sequence<'_>,
) -> Result<()> {
    for index in 0..sequence.count {
        let key = sequence.keys[index as usize % sequence.keys.len()];
        invoke(
            node,
            writer,
            clock,
            sequence.phase,
            index,
            key,
            &releases[key as usize],
        )
        .await?;
        let preparation = node
            .owner
            .backend
            .preparation_key(&ReleaseDigest(releases[key as usize].clone()))
            .map_err(super::super::super::platform)?;
        state.descriptors[key as usize] = Some(
            node.owner
                .backend
                .cached_preparation(&preparation)
                .ok_or("successful sequential cache resident missing")?,
        );
        if (index + 1) % 16 == 0 || index + 1 == sequence.count {
            state.events.export(node, writer, clock, sequence.phase)?;
        }
    }
    Ok(())
}

pub(super) async fn invoke(
    node: &mut Node,
    writer: &mut Writer,
    clock: cold::call::Clock,
    phase: &str,
    index: u32,
    key: u32,
    release: &str,
) -> Result<()> {
    node.command(true)?;
    node.command(false)?;
    let mut row = cold::call::invoke_at_generation(
        node.channel(),
        clock,
        cold::call::InvokeOptions {
            phase: phase.into(),
            index,
            key,
            scheduled: clock.elapsed(),
            id: format!("cache-{phase}-{index:04}"),
            release: release.into(),
            overload: false,
        },
        6,
    )
    .await?;
    cold::call::retain(node.channel(), clock, &mut row).await?;
    let expected = if key == 5 {
        row["outcome"] == "platform-failure" && row["response"]["code"] == "incompatible-contract"
    } else {
        row["outcome"] == "success"
    };
    let valid = cold::schedule::record(node, writer, row)?;
    if !valid || !expected {
        return Err("cache sequential outcome or retention mismatch".into());
    }
    Ok(())
}
