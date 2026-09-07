use super::boundary_error;
use latent_activation::TraceContext;
use latent_core::{Metadata, PlatformError, PlatformErrorCode, SpanId, TraceId};
use std::collections::hash_map::RandomState;
use std::hash::BuildHasher;
use std::sync::atomic::{AtomicU64, Ordering};

pub trait InvocationTraceSource: Send + Sync {
    fn next_trace(&self) -> Result<TraceContext, PlatformError>;
}

/// One random namespace and a checked sequence per node-owned source. These
/// correlation identifiers carry no authentication or authorization authority.
pub struct SystemInvocationTraceSource {
    namespace: u64,
    sequence: AtomicU64,
}
impl Default for SystemInvocationTraceSource {
    fn default() -> Self {
        Self {
            namespace: RandomState::new().hash_one(std::process::id()),
            sequence: AtomicU64::new(1),
        }
    }
}
impl InvocationTraceSource for SystemInvocationTraceSource {
    fn next_trace(&self) -> Result<TraceContext, PlatformError> {
        let sequence = self
            .sequence
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                value.checked_add(1)
            })
            .map_err(|_| {
                boundary_error(
                    PlatformErrorCode::ResourceExhausted,
                    "invocation trace namespace exhausted",
                )
            })?;
        Ok(TraceContext {
            trace_id: TraceId(format!("{:016x}{sequence:016x}", self.namespace)),
            span_id: SpanId(format!("{sequence:016x}")),
            trace_flags: 0,
            baggage: Metadata::new(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn default_ids_fit_short_caller_limits_and_exhaustion_cannot_reuse_a_trace() {
        let source = SystemInvocationTraceSource::default();
        let first = source.next_trace().unwrap();
        let second = source.next_trace().unwrap();
        assert_ne!(first.trace_id, second.trace_id);
        assert_eq!(first.trace_id.0.len(), 32);
        assert_eq!(first.span_id.0.len(), 16);
        assert!(first.baggage.is_empty());
        assert_eq!(first.trace_flags, 0);
        let limits = super::super::InvocationLimits {
            max_id_bytes: 16,
            ..Default::default()
        };
        super::super::authentication::validate_trace(&first, &limits).unwrap();
        let source = SystemInvocationTraceSource {
            namespace: 1,
            sequence: AtomicU64::new(u64::MAX - 1),
        };
        assert!(source.next_trace().is_ok());
        assert_eq!(
            source.next_trace().unwrap_err().code,
            PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(
            source.next_trace().unwrap_err().code,
            PlatformErrorCode::ResourceExhausted
        );
    }
}
