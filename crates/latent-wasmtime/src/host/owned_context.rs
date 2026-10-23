//! Move validated context while keeping retained capacities inside its charge.

use latent_core::{ActivationBudget, ActivationId, BudgetProfile, Metadata, PlatformError};
use latent_executor::ExecutionRequest;

use super::ActivationHostContext;

impl ActivationHostContext {
    /// Reserve a conservative envelope before this ownership transformation.
    /// Original ingress backing and discarded request/import scaffolding remain
    /// outside this owner; later host-import/result copies have separate lives.
    pub(crate) fn from_request_accounted(
        request: ExecutionRequest,
        deadline_unix_millis: Option<u64>,
        budget: &ActivationBudget,
    ) -> Result<Self, PlatformError> {
        let memory = if matches!(
            budget.profile(),
            BudgetProfile::Phase3 | BudgetProfile::Phase4
        ) {
            Some(
                budget
                    .reserve_host_memory(retained_charge(&request)?)
                    .map_err(|error| error.to_platform_error())?,
            )
        } else {
            None
        };
        let mut context = Self::from_request(request, deadline_unix_millis);
        context._context_memory = memory;
        if let Some(memory) = &mut context._context_memory {
            // Actual retained context now exists. This is the declared finite
            // capacity envelope, including construction overlap, not exact RSS.
            // Attach before confirmation so unwind also destroys fields first.
            memory.confirm();
        }
        Ok(context)
    }

    /// The caller has already validated the borrowed request and captured its
    /// admitted ledger. The remaining request scaffolding is destroyed before
    /// this synchronous helper returns; no request owner enters the guest call.
    pub(crate) fn from_request(
        request: ExecutionRequest,
        deadline_unix_millis: Option<u64>,
    ) -> Self {
        let publication = super::web_identity::selected(&request).cloned();
        let activation = request.activation;
        let mut principal = activation.principal;
        compact(&mut principal.subject);
        if let Some(tenant) = &mut principal.tenant {
            compact(&mut tenant.0);
        }
        if let Some(service) = &mut principal.service {
            compact(&mut service.0);
        }
        principal.claims = metadata(principal.claims);

        Self::new(
            ActivationId(text(activation.activation_id.0)),
            ActivationId(text(activation.root_activation_id.0)),
            activation
                .parent_activation_id
                .map(|id| ActivationId(text(id.0))),
            principal,
            text(activation.trace.trace_id.0),
            text(activation.trace.span_id.0),
            activation.trace.trace_flags,
            metadata(activation.trace.baggage),
            deadline_unix_millis,
            metadata(super::web_identity::bind(activation.metadata, publication)),
        )
    }
}

/// Retained fields only; inline structures are already paid with HostState.
/// The existing 4096-byte per-entry envelope covers sparse BTreeMap nodes and
/// their bounded reconstruction. Each string includes the unchanged maximum
/// capacity postcondition and 64 bytes of conservative allocator bookkeeping.
fn retained_charge(request: &ExecutionRequest) -> Result<u64, PlatformError> {
    let activation = &request.activation;
    let mut bytes = 0_u64;
    for value in [
        &activation.activation_id.0,
        &activation.root_activation_id.0,
        &activation.principal.subject,
        &activation.trace.trace_id.0,
        &activation.trace.span_id.0,
    ] {
        add_string(&mut bytes, value.len())?;
    }
    for value in [
        activation.parent_activation_id.as_ref().map(|id| &id.0),
        activation.principal.tenant.as_ref().map(|id| &id.0),
        activation.principal.service.as_ref().map(|id| &id.0),
    ]
    .into_iter()
    .flatten()
    {
        add_string(&mut bytes, value.len())?;
    }
    for values in [
        &activation.principal.claims,
        &activation.trace.baggage,
        &activation.metadata,
    ] {
        for (key, value) in values {
            if std::ptr::eq(values, &activation.metadata) && key == super::web_identity::KEY {
                continue; // bind always removes the caller's reserved identity
            }
            add(&mut bytes, 4096)?;
            add_string(&mut bytes, key.len())?;
            add_string(&mut bytes, value.len())?;
        }
    }
    if let Some(publication) = super::web_identity::selected(request) {
        add(&mut bytes, 4096)?;
        add_string(&mut bytes, super::web_identity::KEY.len())?;
        add_string(&mut bytes, publication.as_str().len())?;
        // The authenticated PublicationId clone overlaps the destination String
        // during bind. Keep this finite allowance until actual context retirement.
        add_string(&mut bytes, publication.as_str().len())?;
    }
    Ok(bytes)
}

fn add_string(bytes: &mut u64, length: usize) -> Result<(), PlatformError> {
    let allowance = super::request_context::string_bytes(length)
        .and_then(|value| value.checked_add(64))
        .and_then(|value| u64::try_from(value).ok())
        .ok_or_else(exhausted)?;
    add(bytes, allowance)
}

fn add(bytes: &mut u64, amount: u64) -> Result<(), PlatformError> {
    *bytes = bytes.checked_add(amount).ok_or_else(exhausted)?;
    Ok(())
}

fn exhausted() -> PlatformError {
    crate::containment::platform_error(
        latent_core::PlatformErrorCode::ResourceExhausted,
        "activation host context memory limit",
        false,
    )
}

fn fits(value: &String) -> bool {
    // The unchanged validator charges 2 * (len + size_of::<String>()) per
    // string, in addition to the request/context structures and map-node
    // allowances. One moved backing buffer must fit that existing allowance.
    super::request_context::string_bytes(value.len())
        .is_some_and(|charged| value.capacity() <= charged)
}

fn text(mut value: String) -> String {
    compact(&mut value);
    value
}

fn compact(value: &mut String) {
    if !fits(value) {
        // Unlike shrink_to_fit, this gives the Rust-visible String a hard
        // capacity == len postcondition. Allocator usable size/RSS is separate.
        *value = std::mem::take(value).into_boxed_str().into_string();
    }
}

fn metadata(mut values: Metadata) -> Metadata {
    if values.is_empty() {
        // BTreeMap::remove can retain an allocated empty leaf. A zero-entry
        // bound must not transfer that hidden backing into the host context.
        return Metadata::new();
    }
    if values.keys().any(|key| !fits(key)) {
        // BTreeMap keys cannot be mutated in place. Rebuild only this unusual
        // map; moving ordinary keys/values preserves their backing buffers.
        values
            .into_iter()
            .map(|(key, value)| (text(key), text(value)))
            .collect()
    } else {
        for value in values.values_mut() {
            compact(value);
        }
        values
    }
}

#[cfg(test)]
mod tests;
