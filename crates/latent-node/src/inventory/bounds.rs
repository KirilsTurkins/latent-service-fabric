use std::mem::size_of;

use latent_artifacts::CacheEntryDescriptor;
use latent_core::{Metadata, PlatformError};

use super::{
    exhausted, invalid, NodeDescriptor, NodeInventory, NodeTopologyEntry, StandaloneInventoryConfig,
};

const MAXIMUM_COLLECTION_ENTRIES: usize = 32;

pub(super) fn config(config: &StandaloneInventoryConfig) -> Result<(), PlatformError> {
    if config.cell_classes.is_empty()
        || config.cell_classes.len() > 5
        || config.cell_classes.capacity() > 5
        || config.maximum_cache_descriptors > 32
        || config.maximum_topology_entries == 0
        || config.maximum_topology_entries > 64
        || config.maximum_snapshot_bytes == 0
        || config.maximum_snapshot_bytes > 4 * 1024 * 1024
        || config.maximum_string_bytes == 0
        || config.maximum_string_bytes > 4096
        || config.maximum_load_age.is_zero()
    {
        return Err(invalid("invalid-inventory-limits"));
    }
    for (index, class) in config.cell_classes.iter().enumerate() {
        if config.cell_classes[..index].contains(class) {
            return Err(invalid("duplicate-inventory-cell-class"));
        }
    }
    Ok(())
}

pub(super) struct Cost {
    maximum: usize,
    remaining: usize,
    string_maximum: usize,
}

impl Cost {
    pub fn new(config: &StandaloneInventoryConfig) -> Result<Self, PlatformError> {
        let mut cost = Self {
            maximum: config.maximum_snapshot_bytes,
            remaining: config.maximum_snapshot_bytes,
            string_maximum: config.maximum_string_bytes,
        };
        // Includes the DTO and fixed reporter bookkeeping, plus the bounded
        // health reasons (at most16 fixed strings, each under64 bytes).
        cost.charge(size_of::<NodeInventory>() + 4096)?;
        Ok(cost)
    }

    pub fn charge(&mut self, bytes: usize) -> Result<(), PlatformError> {
        self.remaining = self.remaining.checked_sub(bytes).ok_or_else(exhausted)?;
        Ok(())
    }

    pub fn used(&self) -> usize {
        self.maximum - self.remaining
    }

    fn string(&mut self, value: &String) -> Result<(), PlatformError> {
        if value.capacity() > self.string_maximum {
            return Err(exhausted());
        }
        self.charge(value.capacity())
    }

    fn strings(&mut self, values: &Vec<String>) -> Result<(), PlatformError> {
        if values.capacity() > MAXIMUM_COLLECTION_ENTRIES {
            return Err(exhausted());
        }
        self.charge(
            values
                .capacity()
                .checked_mul(size_of::<String>())
                .ok_or_else(exhausted)?,
        )?;
        for value in values {
            self.string(value)?;
        }
        Ok(())
    }

    fn metadata(&mut self, metadata: &Metadata) -> Result<(), PlatformError> {
        if metadata.len() > MAXIMUM_COLLECTION_ENTRIES {
            return Err(exhausted());
        }
        // An emptied owned map can retain a leaf root. The fixed allowance plus
        // one KiB per entry covers that root and sparse string/string nodes.
        self.charge(
            metadata
                .len()
                .checked_add(1)
                .and_then(|entries| entries.checked_mul(1024))
                .ok_or_else(exhausted)?,
        )?;
        for (key, value) in metadata {
            self.string(key)?;
            self.string(value)?;
        }
        Ok(())
    }

    pub fn node(&mut self, node: &NodeDescriptor) -> Result<(), PlatformError> {
        self.charge(size_of::<NodeDescriptor>())?;
        for value in [
            &node.id.0,
            &node.architecture,
            &node.operating_system,
            &node.endpoint,
            &node.identity,
        ] {
            if value.is_empty() {
                return Err(invalid("invalid-inventory-node-descriptor"));
            }
            self.string(value)?;
        }
        for value in [node.region.as_ref(), node.zone.as_ref()]
            .into_iter()
            .flatten()
        {
            self.string(value)?;
        }
        self.strings(&node.cpu_features)?;
        self.strings(&node.trust_classes)?;
        self.metadata(&node.attributes)
    }

    pub fn cache_entry(&mut self, entry: &CacheEntryDescriptor) -> Result<(), PlatformError> {
        // The reporter charged the bounded Vec capacity before source selection.
        self.string(&entry.key)?;
        self.string(&entry.release_digest.0)
    }

    pub fn topology(&mut self, entry: &NodeTopologyEntry) -> Result<(), PlatformError> {
        self.string(&entry.name)?;
        self.string(&entry.kind)?;
        self.metadata(&entry.attributes)
    }
}
