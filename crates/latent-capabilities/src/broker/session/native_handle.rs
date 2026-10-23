//! Original handle row storage and the closed owned resource text graph.
use super::{HandleEntry, HandleEntryOwner};
use crate::broker::{capacity, invalid, token};
use latent_core::{ActivationBudget, HostMemoryReservation, PlatformError};
use latent_policy::capability::ResourceTarget;

const ALLOCATION_BOOKKEEPING: u64 = 64;

pub(super) struct Prepared {
    header: super::shared::Prepared<HandleEntry>,
    payload: Option<HostMemoryReservation>,
}

fn text_bytes(value: &str) -> Result<u64, PlatformError> {
    if value.is_empty() {
        Ok(0)
    } else {
        u64::try_from(value.len())
            .ok()
            .and_then(|bytes| bytes.checked_add(ALLOCATION_BOOKKEEPING))
            .ok_or_else(capacity)
    }
}

pub(in crate::broker) fn payload_bytes(
    operation: &str,
    resource: ResourceTarget<'_>,
) -> Result<u64, PlatformError> {
    // The original checked_text validation, without its allocation. The
    // policy decision has already validated every borrowed resource fact.
    if !token(operation) {
        return Err(invalid());
    }
    let mut bytes = text_bytes(operation)?;
    let mut add = |value: &str| -> Result<(), PlatformError> {
        bytes = bytes.checked_add(text_bytes(value)?).ok_or_else(capacity)?;
        Ok(())
    };
    match resource {
        ResourceTarget::Context | ResourceTarget::Clock | ResourceTarget::Random => {}
        ResourceTarget::Log { level } => add(level)?,
        ResourceTarget::Http {
            origin,
            method,
            path,
        } => {
            add(&origin.scheme)?;
            add(&origin.host)?;
            add(method)?;
            add(path)?;
        }
        ResourceTarget::Stream { endpoint } => add(&endpoint.host)?,
        ResourceTarget::Blob { namespace } => add(namespace)?,
        ResourceTarget::Secrets { reference } => add(reference)?,
        ResourceTarget::Events { subject } => add(subject)?,
        ResourceTarget::Telemetry { name } => add(name)?,
        ResourceTarget::Service {
            service,
            publication,
        } => {
            add(service)?;
            add(publication)?;
        }
        ResourceTarget::State {
            namespace,
            entity,
            recovery_scope,
            result_policy,
            ..
        } => {
            add(namespace)?;
            if let Some(entity) = entity {
                add(entity)?;
            }
            add(recovery_scope)?;
            add(result_policy)?;
        }
    }
    Ok(bytes)
}

impl Prepared {
    pub(super) fn reserve(
        budget: &ActivationBudget,
        operation: &str,
        resource: ResourceTarget<'_>,
    ) -> Result<Self, PlatformError> {
        let bytes = payload_bytes(operation, resource)?;
        // The logical 8192-byte metadata counter is separate. These are the
        // actual original Arc, private billing Arc and each owned text buffer.
        // Both reservations precede incarnation assignment and any copy.
        let header = HandleEntryOwner::reserve(budget)?;
        let payload = if budget.profile().supports_descendants() {
            Some(
                budget
                    .reserve_host_memory(bytes)
                    .map_err(|e| e.to_platform_error())?,
            )
        } else {
            None
        };
        Ok(Self { header, payload })
    }

    pub(super) fn allocate(self, mut row: HandleEntry) -> HandleEntryOwner {
        // Preparation already owns this capacity throughout construction.
        // The guard is last so every String drops before its refund; the
        // separate shared billing guard outlives the actual Arc header.
        row._native_owned = self.payload;
        if let Some(memory) = &mut row._native_owned {
            memory.confirm();
        }
        self.header.allocate(row)
    }
}

#[cfg(test)]
mod tests;
