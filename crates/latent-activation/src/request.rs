//! Bounded normalization of trusted-local invocation requests.

#[cfg(test)]
mod tests;
mod validation;

use std::collections::hash_map::RandomState;
use std::hash::BuildHasher;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use latent_core::{
    ActivationId, IdempotencyKey, InvocationPrincipal, Metadata, Payload, PlatformError,
    PlatformErrorCode, ResourceBudget,
};
use latent_routing::InvocationTarget;

use crate::{ActivationEnvelope, TraceContext};

/// Input to the local manager. The principal comes from trusted embedding code;
/// request metadata and lineage are correlation data, never authority.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationRequest {
    pub activation_id: Option<ActivationId>,
    pub parent_activation_id: Option<ActivationId>,
    pub root_activation_id: Option<ActivationId>,
    pub principal: InvocationPrincipal,
    pub target: InvocationTarget,
    pub deadline_unix_millis: Option<u64>,
    pub priority: u8,
    pub trace: TraceContext,
    pub idempotency_key: Option<IdempotencyKey>,
    pub retry_attempt: u32,
    pub budget: ResourceBudget,
    pub metadata: Metadata,
    pub input: Payload,
    pub input_media_type: String,
}

impl ActivationRequest {
    /// Preserves explicit identity and caller data, but deliberately discards a
    /// pre-populated revision. The manager resolves a fresh trusted catalog pin.
    #[must_use]
    pub fn from_envelope(envelope: ActivationEnvelope) -> Self {
        Self {
            activation_id: Some(envelope.activation_id),
            parent_activation_id: envelope.parent_activation_id,
            root_activation_id: Some(envelope.root_activation_id),
            principal: envelope.principal,
            target: envelope.target,
            deadline_unix_millis: envelope.deadline_unix_millis,
            priority: envelope.priority,
            trace: envelope.trace,
            idempotency_key: envelope.idempotency_key,
            retry_attempt: envelope.retry_attempt,
            budget: envelope.budget,
            metadata: envelope.metadata,
            input: envelope.input,
            input_media_type: envelope.input_media_type,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ActivationRequestLimits {
    pub maximum_identifier_bytes: usize,
    /// Aggregate retained string capacities and conservative collection bookkeeping.
    pub maximum_context_bytes: usize,
    /// Retained payload allocation, including unused capacity in the owned input.
    pub maximum_input_bytes: usize,
}

impl Default for ActivationRequestLimits {
    fn default() -> Self {
        Self {
            maximum_identifier_bytes: 512,
            maximum_context_bytes: 1024 * 1024,
            maximum_input_bytes: 1024 * 1024,
        }
    }
}

/// Generates only absent activation IDs. Generated values must also fit the
/// configured identifier bound; IDs are not authentication credentials.
pub trait ActivationIdSource: Send + Sync {
    fn next_id(&self) -> Result<ActivationId, PlatformError>;
}

/// One process-local random namespace and a checked, monotonically increasing
/// counter. A manager retains one source, rather than creating one per call.
pub struct SystemActivationIdSource {
    namespace: u64,
    next: AtomicU64,
}

impl Default for SystemActivationIdSource {
    fn default() -> Self {
        Self {
            namespace: RandomState::new().hash_one(std::process::id()),
            next: AtomicU64::new(1),
        }
    }
}

impl ActivationIdSource for SystemActivationIdSource {
    fn next_id(&self) -> Result<ActivationId, PlatformError> {
        let sequence = self
            .next
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |next| {
                next.checked_add(1)
            })
            .map_err(|_| {
                error(
                    PlatformErrorCode::ResourceExhausted,
                    "activation-id-exhausted",
                )
            })?;
        Ok(ActivationId(format!(
            "activation-{:016x}-{sequence:016x}",
            self.namespace
        )))
    }
}

#[derive(Clone)]
pub struct ActivationRequestBuilder {
    limits: ActivationRequestLimits,
    ids: Arc<dyn ActivationIdSource>,
}

impl ActivationRequestBuilder {
    pub fn new(
        limits: ActivationRequestLimits,
        ids: Arc<dyn ActivationIdSource>,
    ) -> Result<Self, PlatformError> {
        if limits.maximum_identifier_bytes == 0
            || limits.maximum_context_bytes == 0
            || limits.maximum_input_bytes == 0
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-activation-request-limits",
            ));
        }
        Ok(Self { limits, ids })
    }

    #[must_use]
    pub fn limits(&self) -> ActivationRequestLimits {
        self.limits
    }

    pub fn build(&self, request: ActivationRequest) -> Result<ActivationEnvelope, PlatformError> {
        validation::validate(&request, self.limits)?;
        let activation_id = if let Some(id) = request.activation_id {
            id
        } else {
            let id = self.ids.next_id()?;
            validation::identifier(&id.0, self.limits.maximum_identifier_bytes)?;
            // The pre-validation reservation covers the generated spelling,
            // not arbitrary spare capacity returned by an embedding's source.
            ActivationId(id.0.into_boxed_str().into_string())
        };
        let root_activation_id = request
            .root_activation_id
            .unwrap_or_else(|| activation_id.clone());
        Ok(ActivationEnvelope {
            activation_id,
            parent_activation_id: request.parent_activation_id,
            root_activation_id,
            principal: request.principal,
            target: request.target,
            resolved_revision: None,
            deadline_unix_millis: request.deadline_unix_millis,
            priority: request.priority,
            trace: request.trace,
            idempotency_key: request.idempotency_key,
            retry_attempt: request.retry_attempt,
            budget: request.budget,
            metadata: request.metadata,
            input: request.input,
            input_media_type: request.input_media_type,
        })
    }
}

fn error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
