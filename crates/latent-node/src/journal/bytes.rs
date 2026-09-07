//! Conservative retained allocation costs, checked before cloning payloads.

use std::mem::size_of;

use latent_activation::{ActivationEvent, ActivationOutcome};
use latent_core::{ActivationId, Metadata, PlatformError, TenantId};

use super::{capacity, state::Record, MAXIMUM_EVENTS};

pub(super) fn base(id: &ActivationId, tenant: &TenantId) -> Result<usize, PlatformError> {
    // Covers sparse key/pointer index nodes, owner/queue keys, one heap-allocated
    // record, all seven event slots, and every retained copy of its ID. Records
    // must stay boxed so unused B-tree slots do not reserve inline outcomes.
    4096_usize
        .checked_add(size_of::<Record>())
        .and_then(|bytes| bytes.checked_add(MAXIMUM_EVENTS * size_of::<ActivationEvent>()))
        .and_then(|bytes| {
            id.0.len()
                .checked_mul(12)
                .and_then(|ids| bytes.checked_add(ids))
        })
        .and_then(|bytes| bytes.checked_add(tenant.0.len()))
        .ok_or_else(capacity)
}

pub(super) fn metadata(metadata: &Metadata, maximum: usize) -> Result<usize, PlatformError> {
    let mut cost = Cost::new(maximum);
    cost.metadata(metadata)?;
    Ok(cost.used())
}

pub(super) fn outcome(outcome: &ActivationOutcome, maximum: usize) -> Result<usize, PlatformError> {
    let mut cost = Cost::new(maximum);
    cost.charge(256)?;
    match outcome {
        ActivationOutcome::Succeeded(success) => {
            if let Some(version) = &success.committed_state_version {
                cost.string(version)?;
            }
            cost.charge(
                success
                    .effect_ids
                    .len()
                    .checked_mul(size_of::<String>())
                    .ok_or_else(capacity)?,
            )?;
            for effect in &success.effect_ids {
                cost.string(effect)?;
            }
            cost.metadata(&success.metadata)?;
        }
        ActivationOutcome::DeclaredError { error, .. } => {
            for value in [&error.code, &error.message, &error.media_type] {
                cost.string(value)?;
            }
            cost.charge(error.payload.len())?;
            cost.metadata(&error.metadata)?;
        }
        ActivationOutcome::Failed { error, .. } => {
            cost.string(&error.message)?;
            cost.charge(error.details.len().checked_mul(128).ok_or_else(capacity)?)?;
            for detail in &error.details {
                cost.string(&detail.kind)?;
                cost.metadata(&detail.fields)?;
            }
        }
    }
    Ok(cost.used())
}

struct Cost {
    remaining: usize,
    maximum: usize,
}
impl Cost {
    fn new(maximum: usize) -> Self {
        Self {
            maximum,
            remaining: maximum,
        }
    }
    fn charge(&mut self, bytes: usize) -> Result<(), PlatformError> {
        self.remaining = self.remaining.checked_sub(bytes).ok_or_else(capacity)?;
        Ok(())
    }
    fn string(&mut self, value: &str) -> Result<(), PlatformError> {
        self.charge(size_of::<String>())?;
        self.charge(value.len())
    }
    fn metadata(&mut self, metadata: &Metadata) -> Result<(), PlatformError> {
        // One KiB per entry bounds sparse string-to-string B-tree nodes too.
        self.charge(metadata.len().checked_mul(1024).ok_or_else(capacity)?)?;
        for (key, value) in metadata {
            self.string(key)?;
            self.string(value)?;
        }
        Ok(())
    }
    fn used(&self) -> usize {
        self.maximum - self.remaining
    }
}
