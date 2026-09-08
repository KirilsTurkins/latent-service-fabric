use std::collections::BTreeSet;

use latent_core::PlatformError;
use latent_scheduler::CellClass;

use super::{invalid, NodeConfig, IDENTIFIER_BYTES, JOURNAL_RECORD_BYTES, MIB};

pub(super) struct Capacity {
    pub cells: u32,
    pub reservations: u32,
    pub maximum_memory: u64,
}

pub(super) fn validate(config: &NodeConfig) -> Result<Capacity, PlatformError> {
    if config.format_version != 1 {
        return Err(invalid("formatVersion"));
    }
    if !config.data_directory.is_absolute()
        || config
            .data_directory
            .to_str()
            .is_none_or(|value| value.len() > 4096 || value.chars().any(char::is_control))
    {
        return Err(invalid("dataDirectory"));
    }
    identifier(&config.node_id, IDENTIFIER_BYTES, "nodeId")?;
    if !config.bind.ip().is_loopback() {
        return Err(invalid("bind"));
    }
    range(config.workers.runtime, 1, 32, "workers.runtime")?;
    range(config.workers.control, 1, 8, "workers.control")?;
    range(
        config.limits.maximum_connections,
        1,
        1024,
        "limits.maximumConnections",
    )?;
    range(
        config.limits.maximum_component_bytes,
        1,
        64 * MIB,
        "limits.maximumComponentBytes",
    )?;
    range(
        config.limits.maximum_payload_bytes,
        1,
        MIB,
        "limits.maximumPayloadBytes",
    )?;
    range64(
        config.execution.maximum_cpu_fuel,
        1,
        10_000_000_000,
        "execution.maximumCpuFuel",
    )?;
    range64(
        config.execution.maximum_wall_time_millis,
        2,
        300_000,
        "execution.maximumWallTimeMillis",
    )?;
    range64(
        config.execution.maximum_log_bytes,
        0,
        16 * 1024,
        "execution.maximumLogBytes",
    )?;
    range64(
        config.shutdown_grace_millis,
        1,
        60_000,
        "shutdownGraceMillis",
    )?;
    credentials(config)?;
    let capacity = cells(config)?;
    retained(config, &capacity)?;
    Ok(capacity)
}

fn cells(config: &NodeConfig) -> Result<Capacity, PlatformError> {
    range(config.cells.len(), 1, 5, "cells")?;
    let mut names = BTreeSet::new();
    let mut total = 0_u32;
    let mut queued = 0_u32;
    let mut memory = 0;
    for cell in &config.cells {
        if !names.insert(class(&cell.class)?) {
            return Err(invalid("cells.class"));
        }
        range64(u64::from(cell.capacity), 1, 64, "cells.capacity")?;
        range64(
            u64::from(cell.queue_capacity),
            1,
            1024,
            "cells.queueCapacity",
        )?;
        range64(
            cell.maximum_memory_bytes,
            64 * 1024,
            1024 * MIB as u64,
            "cells.maximumMemoryBytes",
        )?;
        total = total
            .checked_add(cell.capacity)
            .ok_or_else(|| invalid("cells.capacity"))?;
        queued = queued
            .checked_add(cell.queue_capacity)
            .ok_or_else(|| invalid("cells.queueCapacity"))?;
        memory = memory.max(cell.maximum_memory_bytes);
    }
    let reservations = total.checked_add(queued).ok_or_else(|| invalid("cells"))?;
    range64(u64::from(total), 1, 64, "cells.capacity")?;
    range64(u64::from(reservations), 1, 1024, "cells.queueCapacity")?;
    Ok(Capacity {
        cells: total,
        reservations,
        maximum_memory: memory,
    })
}

fn retained(config: &NodeConfig, capacity: &Capacity) -> Result<(), PlatformError> {
    range(config.cache.entries, 1, 4096, "cache.entries")?;
    range(
        config.cache.source_bytes,
        config.limits.maximum_component_bytes,
        1024 * MIB,
        "cache.sourceBytes",
    )?;
    range(
        config.cache.metadata_bytes,
        MIB,
        1024 * MIB,
        "cache.metadataBytes",
    )?;
    range(
        config.cache.compiled_image_bytes,
        1,
        1024 * MIB,
        "cache.compiledImageBytes",
    )?;
    range(
        config.cache.preparations,
        1,
        (capacity.cells as usize).min(config.workers.control),
        "cache.preparations",
    )?;
    range(
        config.catalogs.release_entries,
        1,
        100_000,
        "catalogs.releaseEntries",
    )?;
    range(
        config.catalogs.deployments,
        1,
        100_000,
        "catalogs.deployments",
    )?;
    range(
        config.catalogs.release_index_bytes,
        MIB,
        1024 * MIB,
        "catalogs.releaseIndexBytes",
    )?;
    range(
        config.catalogs.deployment_state_bytes,
        MIB,
        1024 * MIB,
        "catalogs.deploymentStateBytes",
    )?;
    range(
        config.retention.terminal_entries,
        1,
        100_000,
        "retention.terminalEntries",
    )?;
    range64(
        config.retention.terminal_ttl_millis,
        1,
        86_400_000,
        "retention.terminalTtlMillis",
    )?;
    let required = (capacity.reservations as usize)
        .checked_mul(JOURNAL_RECORD_BYTES)
        .ok_or_else(|| invalid("retention.bytes"))?;
    range(
        config.retention.bytes,
        required,
        1024 * MIB,
        "retention.bytes",
    )?;
    range(
        config.telemetry.queue_entries,
        1,
        4096,
        "telemetry.queueEntries",
    )?;
    range(
        config.telemetry.retained_entries,
        1,
        65_536,
        "telemetry.retainedEntries",
    )?;
    range(
        config.telemetry.retained_bytes,
        64 * 1024,
        256 * MIB,
        "telemetry.retainedBytes",
    )
}

fn credentials(config: &NodeConfig) -> Result<(), PlatformError> {
    range(config.credentials.len(), 1, 64, "credentials")?;
    let mut tokens = BTreeSet::new();
    for credential in &config.credentials {
        let token = &credential.token;
        if !(32..=256).contains(&token.len())
            || !token
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
            || !tokens.insert(token.as_str())
        {
            return Err(invalid("credentials.token"));
        }
        identifier(&credential.subject, IDENTIFIER_BYTES, "credentials.subject")?;
        let tenant = &credential.tenant;
        if tenant.is_empty()
            || tenant.len() > 128
            || !tenant
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
            || !tenant.as_bytes()[0].is_ascii_alphanumeric()
            || !tenant.as_bytes()[tenant.len() - 1].is_ascii_alphanumeric()
        {
            return Err(invalid("credentials.tenant"));
        }
    }
    Ok(())
}

fn identifier(value: &str, maximum: usize, field: &'static str) -> Result<(), PlatformError> {
    if value.is_empty()
        || value.len() > maximum
        || !value.is_ascii()
        || value
            .bytes()
            .any(|byte| byte.is_ascii_control() || byte.is_ascii_whitespace())
    {
        return Err(invalid(field));
    }
    Ok(())
}

fn range(
    value: usize,
    minimum: usize,
    maximum: usize,
    field: &'static str,
) -> Result<(), PlatformError> {
    if !(minimum..=maximum).contains(&value) {
        return Err(invalid(field));
    }
    Ok(())
}

fn range64(
    value: u64,
    minimum: u64,
    maximum: u64,
    field: &'static str,
) -> Result<(), PlatformError> {
    if !(minimum..=maximum).contains(&value) {
        return Err(invalid(field));
    }
    Ok(())
}

pub(super) fn class(name: &str) -> Result<CellClass, PlatformError> {
    match name {
        "tiny" => Ok(CellClass::Tiny),
        "small" => Ok(CellClass::Small),
        "standard" => Ok(CellClass::Standard),
        "large" => Ok(CellClass::Large),
        "extra-large" => Ok(CellClass::ExtraLarge),
        _ => Err(invalid("cells.class")),
    }
}
