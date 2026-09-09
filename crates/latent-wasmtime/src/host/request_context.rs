//! Borrowed allocation accounting before copying activation-owned host context.

use std::mem::size_of;

use latent_core::{Metadata, PlatformError, PlatformErrorCode};
use latent_executor::ExecutionRequest;

use super::ActivationHostContext;
use crate::containment::platform_error;
use crate::InvocationContextCharge;

// Covers sparse BTreeMap nodes, map entry/string storage, and the owned copy.
// Payload bytes are charged separately by the generic value codec.
const MAP_ENTRY_BYTES: usize = 4096;
const IMPORT_ENTRY_BYTES: usize = 256;

pub(crate) fn validate_request_context(
    request: &ExecutionRequest,
    maximum_bytes: usize,
) -> Result<(), PlatformError> {
    context_charge(request, maximum_bytes).map(|_| ())
}

pub(crate) fn context_charge(
    request: &ExecutionRequest,
    maximum_bytes: usize,
) -> Result<InvocationContextCharge, PlatformError> {
    let mut budget = ContextBudget(maximum_bytes);
    budget.charge(size_of::<ExecutionRequest>() + size_of::<ActivationHostContext>())?;
    let activation = &request.activation;
    for value in [
        activation.activation_id.0.as_str(),
        activation.root_activation_id.0.as_str(),
        activation.principal.subject.as_str(),
        activation.trace.trace_id.0.as_str(),
        activation.trace.span_id.0.as_str(),
        activation.input_media_type.as_str(),
    ] {
        budget.string(value)?;
    }
    for value in [
        activation
            .parent_activation_id
            .as_ref()
            .map(|id| id.0.as_str()),
        activation.principal.tenant.as_ref().map(|id| id.0.as_str()),
        activation
            .principal
            .service
            .as_ref()
            .map(|id| id.0.as_str()),
        activation.idempotency_key.as_ref().map(|id| id.0.as_str()),
    ]
    .into_iter()
    .flatten()
    {
        budget.string(value)?;
    }
    for metadata in [
        &activation.principal.claims,
        &activation.trace.baggage,
        &activation.metadata,
        &request.prepared.metadata,
        &request.cell.metadata,
    ] {
        budget.metadata(metadata)?;
    }
    charge_target(
        &mut budget,
        &activation.target.tenant.0,
        &activation.target.service.0,
        &activation.target.contract.0,
        &activation.target.function.0,
        activation.target.route.as_deref(),
    )?;
    if let Some(revision) = &activation.resolved_revision {
        charge_target(
            &mut budget,
            &revision.target.tenant.0,
            &revision.target.service.0,
            &revision.target.contract.0,
            &revision.target.function.0,
            revision.target.route.as_deref(),
        )?;
        budget.string(&revision.revision.0)?;
        budget.string(&revision.release.0)?;
        budget.metadata(&revision.attributes)?;
    }
    for value in [
        request.prepared.backend.as_str(),
        request.prepared.opaque_handle.as_str(),
        request.prepared.key.release.0.as_str(),
        request.prepared.key.engine_version.as_str(),
        request.prepared.key.engine_configuration_digest.as_str(),
        request.prepared.key.target_triple.as_str(),
        request.prepared.key.cpu_feature_set.as_str(),
        request.cell.id.0.as_str(),
        request.cell.class.as_str(),
    ] {
        budget.string(value)?;
    }
    budget.collection(request.imports.len(), IMPORT_ENTRY_BYTES)?;
    for import in &request.imports {
        budget.string(&import.capability.0)?;
        budget.string(&import.contract)?;
        budget.string(&import.opaque_handle)?;
    }
    Ok(InvocationContextCharge {
        maximum_bytes,
        charged_bytes: maximum_bytes - budget.0,
        remaining_bytes: budget.0,
    })
}

fn charge_target(
    budget: &mut ContextBudget,
    tenant: &str,
    service: &str,
    contract: &str,
    function: &str,
    route: Option<&str>,
) -> Result<(), PlatformError> {
    for value in [tenant, service, contract, function] {
        budget.string(value)?;
    }
    if let Some(route) = route {
        budget.string(route)?;
    }
    Ok(())
}

struct ContextBudget(usize);

impl ContextBudget {
    fn charge(&mut self, bytes: usize) -> Result<(), PlatformError> {
        self.0 = self.0.checked_sub(bytes).ok_or_else(exhausted)?;
        Ok(())
    }

    fn collection(&mut self, count: usize, entry_bytes: usize) -> Result<(), PlatformError> {
        self.charge(count.checked_mul(entry_bytes).ok_or_else(exhausted)?)
    }

    fn string(&mut self, value: &str) -> Result<(), PlatformError> {
        let bytes = value
            .len()
            .checked_add(size_of::<String>())
            .and_then(|bytes| bytes.checked_mul(2))
            .ok_or_else(exhausted)?;
        self.charge(bytes)
    }

    fn metadata(&mut self, metadata: &Metadata) -> Result<(), PlatformError> {
        // Check entry count before walking keys or allocating any owned values.
        self.collection(metadata.len(), MAP_ENTRY_BYTES)?;
        for (name, value) in metadata {
            self.string(name)?;
            self.string(value)?;
        }
        Ok(())
    }
}

fn exhausted() -> PlatformError {
    platform_error(
        PlatformErrorCode::ResourceExhausted,
        "activation context exceeds configured byte limit",
        false,
    )
}

#[cfg(test)]
mod tests;
