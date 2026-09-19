use super::{model, AuditAcknowledgement, FailureKind, RecoveryIdentity, RpcFailure};

impl From<RecoveryIdentity> for model::RequestIdentity {
    fn from(value: RecoveryIdentity) -> Self {
        Self {
            activation_id: value.activation_id,
            operation_id: value.operation_id,
        }
    }
}

pub(super) fn audit(
    value: Option<AuditAcknowledgement>,
) -> (Option<model::AuditAck>, Option<String>) {
    let Some(value) = value else {
        return (None, None);
    };
    let status = match value.status.as_str() {
        "durable" => model::AuditAckStatus::DURABLE,
        "outcome-unknown" => model::AuditAckStatus::OUTCOME_UNKNOWN,
        "audit-unavailable" => model::AuditAckStatus::AUDIT_UNAVAILABLE,
        "disabled" => model::AuditAckStatus::DISABLED,
        _ => model::AuditAckStatus::UNSPECIFIED,
    };
    (
        Some(model::AuditAck {
            status,
            attempt_sequence: value.attempt_sequence,
        }),
        Some(value.status),
    )
}

impl From<RpcFailure> for model::ClientFailure {
    fn from(value: RpcFailure) -> Self {
        let category = match value.kind {
            FailureKind::InvalidConfiguration | FailureKind::InvalidRequest => {
                model::FailureCategory::INVALID_REQUEST
            }
            FailureKind::Capacity => model::FailureCategory::LIMIT,
            FailureKind::Deadline => model::FailureCategory::DEADLINE,
            FailureKind::Closed => model::FailureCategory::LOCAL_CANCELLED,
            FailureKind::InvalidResponse => model::FailureCategory::DECODE,
            FailureKind::Rejected => model::FailureCategory::RPC,
            FailureKind::Connection if value.grpc_code.is_some() => model::FailureCategory::RPC,
            FailureKind::Connection => model::FailureCategory::TRANSPORT,
        };
        let message = value.to_string();
        let (audit_ack, mut audit_status) = audit(value.audit);
        let unsupported_wire_value = value.unsupported.map(|raw| model::UnsupportedWireValue {
            field: raw.field.into(),
            value: raw.value,
        });
        if audit_status.is_none() {
            audit_status = unsupported_wire_value
                .as_ref()
                .filter(|raw| raw.field == "audit.status")
                .map(|raw| raw.value.clone());
        }
        Self {
            category,
            message,
            grpc_status: value.grpc_code,
            platform_error: value
                .platform
                .map(|error| latent_rpc::control::v1::PlatformError::from(*error).into()),
            dispatched: value.dispatched,
            outcome: if !value.dispatched {
                model::OutcomeKnowledge::NOT_DISPATCHED
            } else if value.outcome_known {
                model::OutcomeKnowledge::OBSERVED
            } else {
                model::OutcomeKnowledge::UNKNOWN
            },
            identity: value.recovery.into(),
            audit_ack,
            audit_status,
            unsupported_wire_value,
        }
    }
}
