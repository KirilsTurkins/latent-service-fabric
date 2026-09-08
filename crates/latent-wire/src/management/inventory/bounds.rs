use latent_core::Metadata;
use latent_node::NodeInventory;
use std::mem::size_of;
use tonic::Status;

use super::super::ManagementLimits;

pub(in crate::management) fn validate_inventory(
    value: &NodeInventory,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    let mut cost = Cost {
        used: size_of::<NodeInventory>(),
        limits,
    };
    cost.sequence(&value.cell_capacity, 5)?;
    cost.sequence(&value.cache_entries, limits.max_collection_entries)?;
    cost.sequence(&value.topology.entries, limits.max_collection_entries)?;
    cost.sequence(&value.health.reasons, limits.max_collection_entries)?;
    cost.sequence(&value.node.cpu_features, limits.max_collection_entries)?;
    cost.sequence(&value.node.trust_classes, limits.max_collection_entries)?;
    cost.string(&value.node.id.0, limits.max_id_bytes)?;
    for text in [
        &value.node.architecture,
        &value.node.operating_system,
        &value.node.endpoint,
        &value.node.identity,
    ]
    .into_iter()
    .chain(value.node.region.iter())
    .chain(value.node.zone.iter())
    .chain(value.node.cpu_features.iter())
    .chain(value.node.trust_classes.iter())
    .chain(value.health.reasons.iter())
    {
        cost.string(text, limits.max_string_bytes)?;
    }
    cost.metadata(&value.node.attributes)?;
    for cell in &value.cell_capacity {
        cost.string(&cell.class, limits.max_string_bytes)?;
        if cell.observation_available
            && (u64::from(cell.available) + u64::from(cell.active) + u64::from(cell.quarantined)
                != u64::from(cell.total)
                || cell.queue_depth > cell.queue_capacity
                || cell.queued_tenants > cell.queue_depth)
        {
            return Err(Status::internal("invalid node inventory"));
        }
    }
    for entry in &value.cache_entries {
        cost.string(&entry.key, limits.max_string_bytes)?;
        cost.string(&entry.release_digest.0, limits.max_id_bytes.max(71))?;
    }
    for entry in &value.topology.entries {
        cost.string(&entry.name, limits.max_string_bytes)?;
        cost.string(&entry.kind, limits.max_string_bytes)?;
        cost.metadata(&entry.attributes)?;
    }
    if value.retained_bytes > limits.max_response_bytes
        || [
            value.memory_pressure_milli,
            value.pressure.cpu_pressure_milli,
            value.pressure.memory_pressure_milli,
            value.pressure.queue_pressure_milli,
            value.pressure.cache_pressure_milli,
        ]
        .iter()
        .any(|value| *value > 1000)
    {
        return Err(Status::internal("invalid node inventory"));
    }
    Ok(())
}

struct Cost<'a> {
    used: usize,
    limits: &'a ManagementLimits,
}
impl Cost<'_> {
    fn charge(&mut self, count: usize, size: usize) -> Result<(), Status> {
        self.used = count
            .checked_mul(size)
            .and_then(|bytes| self.used.checked_add(bytes))
            .filter(|bytes| *bytes <= self.limits.max_response_bytes)
            .ok_or_else(exhausted)?;
        Ok(())
    }
    fn sequence<T>(&mut self, values: &Vec<T>, maximum: usize) -> Result<(), Status> {
        if values.len() > maximum {
            return Err(exhausted());
        }
        self.charge(values.capacity(), size_of::<T>())
    }
    fn string(&mut self, value: &String, maximum: usize) -> Result<(), Status> {
        if value.len() > maximum {
            return Err(exhausted());
        }
        self.charge(value.capacity(), 1)
    }
    fn metadata(&mut self, value: &Metadata) -> Result<(), Status> {
        if value.len() > self.limits.max_metadata_entries {
            return Err(exhausted());
        }
        self.charge(value.len(), 4096)?;
        let before = self.used;
        for (key, value) in value {
            self.string(key, self.limits.max_string_bytes)?;
            self.string(value, self.limits.max_string_bytes)?;
        }
        if self.used - before > self.limits.max_metadata_bytes {
            return Err(exhausted());
        }
        Ok(())
    }
}

fn exhausted() -> Status {
    Status::resource_exhausted("management inventory response exceeds configured limits")
}
