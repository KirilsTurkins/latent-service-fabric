use latent_activation::TraceContext;
use latent_core::{
    ActivationPhase, ActivationTerminalState, CancelDisposition, Metadata, SpanId, TraceId,
};

use crate::{
    ActivationCleanupDisposition, ActivationObservationContext, ActivationObservationKind,
    LogSeverity,
};

pub(super) fn bounded(value: &str, maximum: usize) -> String {
    let mut end = value.len().min(maximum);
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    value[..end].to_owned()
}

pub(super) fn attributes(context: &ActivationObservationContext, maximum: usize) -> Metadata {
    let mut result = Metadata::from([
        (
            "activation_id".to_owned(),
            bounded(&context.activation_id.0, maximum),
        ),
        (
            "root_activation_id".to_owned(),
            bounded(&context.root_activation_id.0, maximum),
        ),
        ("tenant".to_owned(), bounded(&context.tenant.0, maximum)),
        ("service".to_owned(), bounded(&context.service.0, maximum)),
        ("contract".to_owned(), bounded(&context.contract.0, maximum)),
        ("function".to_owned(), bounded(&context.function.0, maximum)),
    ]);
    for (key, value) in [
        (
            "parent_activation_id",
            context
                .parent_activation_id
                .as_ref()
                .map(|id| id.0.as_str()),
        ),
        ("release", context.release.as_ref().map(|id| id.0.as_str())),
        (
            "revision",
            context.revision.as_ref().map(|id| id.0.as_str()),
        ),
    ] {
        if let Some(value) = value {
            result.insert(key.to_owned(), bounded(value, maximum));
        }
    }
    if let Some(generation) = context.route_generation {
        result.insert("route_generation".to_owned(), generation.0.to_string());
    }
    result
}

pub(super) fn trace(context: &ActivationObservationContext, maximum: usize) -> TraceContext {
    TraceContext {
        trace_id: TraceId(bounded(&context.trace_id.0, maximum)),
        span_id: SpanId(bounded(&context.span_id.0, maximum)),
        trace_flags: context.trace_flags,
        baggage: Metadata::new(),
    }
}

pub(super) fn stage(kind: &ActivationObservationKind) -> &'static str {
    match kind {
        ActivationObservationKind::Received => "receipt",
        ActivationObservationKind::Phase { phase, .. } => match phase {
            ActivationPhase::Received => "receipt",
            ActivationPhase::Resolved => "resolution",
            ActivationPhase::Admitted => "admission",
            ActivationPhase::Queued => "queueing",
            ActivationPhase::Materializing => "materialization",
            _ => "execution",
        },
        ActivationObservationKind::AdmittedGrant(_) => "admission",
        ActivationObservationKind::Cancellation(_) => "cancellation",
        ActivationObservationKind::Cleanup(_) => "cleanup",
        ActivationObservationKind::Terminal(_) => "completion",
    }
}

pub(super) fn severity(value: LogSeverity) -> &'static str {
    match value {
        LogSeverity::Trace => "trace",
        LogSeverity::Debug => "debug",
        LogSeverity::Info => "info",
        LogSeverity::Warn => "warn",
        LogSeverity::Error => "error",
        LogSeverity::Fatal => "fatal",
    }
}

pub(super) fn terminal(value: ActivationTerminalState) -> &'static str {
    match value {
        ActivationTerminalState::Completed => "completed",
        ActivationTerminalState::Rejected => "rejected",
        ActivationTerminalState::Cancelled => "cancelled",
        ActivationTerminalState::DeadlineExceeded => "deadline_exceeded",
        ActivationTerminalState::ResourceExhausted => "resource_exhausted",
        ActivationTerminalState::GuestTrap => "guest_trap",
        ActivationTerminalState::StateConflict => "state_conflict",
        ActivationTerminalState::DependencyFailed => "dependency_failed",
        ActivationTerminalState::PlatformFailed => "platform_failed",
        _ => "unknown",
    }
}

pub(super) fn cancellation(value: CancelDisposition) -> &'static str {
    match value {
        CancelDisposition::Accepted => "accepted",
        CancelDisposition::AlreadyTerminal(_) => "already_terminal",
        CancelDisposition::NotFound => "not_found",
    }
}

pub(super) fn cleanup(value: ActivationCleanupDisposition) -> &'static str {
    match value {
        ActivationCleanupDisposition::NoCell => "no_cell",
        ActivationCleanupDisposition::Released => "released",
        ActivationCleanupDisposition::Quarantined => "quarantined",
        ActivationCleanupDisposition::ReclaimedBeforeExecution => "reclaimed_before_execution",
        ActivationCleanupDisposition::Abandoned => "abandoned",
        ActivationCleanupDisposition::Failed => "failed",
    }
}
