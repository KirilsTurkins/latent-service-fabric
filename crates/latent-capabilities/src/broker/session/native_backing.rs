//! The closed allocations made by open_session, on its original budget.
use super::{HandleEntry, SessionCore, SessionCoreOwner, Stats, StatsOwner};
use crate::broker::{capacity, invalid, token};
use latent_core::{ActivationBudget, HostMemoryReservation, PlatformError};
use latent_executor::ExecutionRequest;
use std::{alloc::Layout, sync::Arc};

const ALLOCATION_BOOKKEEPING: usize = 64;

pub(super) struct Prepared {
    pub core: super::shared::Prepared<SessionCore>,
    pub stats: super::shared::Prepared<Stats>,
    pub core_payload: Option<HostMemoryReservation>,
    pub stats_payload: Option<HostMemoryReservation>,
}

fn string_bytes(value: &str) -> Result<usize, PlatformError> {
    if value.is_empty() {
        Ok(0)
    } else {
        value
            .len()
            .checked_add(ALLOCATION_BOOKKEEPING)
            .ok_or_else(capacity)
    }
}

pub(in crate::broker) fn payload_bytes(
    request: &ExecutionRequest,
    tenant: &str,
    slots: usize,
) -> Result<(u64, u64), PlatformError> {
    // These are precisely the four original checked_text inputs. Validation
    // copies no text and runs after the original authority/metadata admission.
    for value in [
        Some(request.activation.activation_id.0.as_str()),
        Some(request.activation.root_activation_id.0.as_str()),
        request
            .activation
            .parent_activation_id
            .as_ref()
            .map(|id| id.0.as_str()),
        Some(request.activation.principal.subject.as_str()),
    ]
    .into_iter()
    .flatten()
    {
        if !token(value) {
            return Err(invalid());
        }
    }
    let mut core = Layout::array::<Option<Arc<HandleEntry>>>(slots)
        .map_err(|_| capacity())?
        .size()
        .checked_add(ALLOCATION_BOOKKEEPING)
        .ok_or_else(capacity)?;
    for value in [
        Some(request.activation.activation_id.0.as_str()),
        Some(request.activation.root_activation_id.0.as_str()),
        request
            .activation
            .parent_activation_id
            .as_ref()
            .map(|id| id.0.as_str()),
        Some(request.activation.principal.subject.as_str()),
        request
            .activation
            .principal
            .tenant
            .as_ref()
            .map(|id| id.0.as_str()),
        request
            .activation
            .principal
            .service
            .as_ref()
            .map(|id| id.0.as_str()),
    ]
    .into_iter()
    .flatten()
    {
        core = core
            .checked_add(string_bytes(value)?)
            .ok_or_else(capacity)?;
    }
    Ok((
        u64::try_from(core).map_err(|_| capacity())?,
        u64::try_from(string_bytes(tenant)?).map_err(|_| capacity())?,
    ))
}

impl Prepared {
    pub(super) fn reserve(
        budget: &ActivationBudget,
        request: &ExecutionRequest,
        tenant: &str,
        slots: usize,
    ) -> Result<Self, PlatformError> {
        let (core_bytes, stats_bytes) = payload_bytes(request, tenant, slots)?;
        let core = SessionCoreOwner::reserve(budget)?;
        let stats = StatsOwner::reserve(budget)?;
        let (core_payload, stats_payload) = if budget.profile().supports_descendants() {
            (
                Some(
                    budget
                        .reserve_host_memory(core_bytes)
                        .map_err(|failure| failure.to_platform_error())?,
                ),
                Some(
                    budget
                        .reserve_host_memory(stats_bytes)
                        .map_err(|failure| failure.to_platform_error())?,
                ),
            )
        } else {
            (None, None)
        };
        Ok(Self {
            core,
            stats,
            core_payload,
            stats_payload,
        })
    }
}
