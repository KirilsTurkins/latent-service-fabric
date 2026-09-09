//! Move validated context while keeping retained capacities inside its charge.

use latent_core::{ActivationId, Metadata};
use latent_executor::ExecutionRequest;

use super::ActivationHostContext;

impl ActivationHostContext {
    /// The caller has already validated the borrowed request and captured its
    /// admitted ledger. The remaining request scaffolding is destroyed before
    /// this synchronous helper returns; no request owner enters the guest call.
    pub(crate) fn from_request(
        request: ExecutionRequest,
        deadline_unix_millis: Option<u64>,
    ) -> Self {
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
            metadata(activation.metadata),
        )
    }
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
