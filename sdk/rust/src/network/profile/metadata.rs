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
) -> (Option<model::AuditAck>, Option<String>, Option<u64>) {
    let Some(value) = value else {
        return (None, None, None);
    };
    let status = match value.status.as_str() {
        "durable" => Some(model::AuditAckStatus::DURABLE),
        "outcome-unknown" => Some(model::AuditAckStatus::OUTCOME_UNKNOWN),
        "audit-unavailable" => Some(model::AuditAckStatus::AUDIT_UNAVAILABLE),
        "disabled" => Some(model::AuditAckStatus::DISABLED),
        _ => None,
    };
    (
        status.map(|status| model::AuditAck {
            status,
            attempt_sequence: value.attempt_sequence,
        }),
        Some(value.status),
        value.attempt_sequence,
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
        let (audit_ack, mut audit_status, audit_attempt_sequence) = audit(value.audit);
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
            audit_attempt_sequence,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn raw_audit_sequence_survives_without_any_invented_acknowledgement() {
        assert_eq!(audit(None), (None, None, None));
        for sequence in [None, Some(0), Some(u64::MAX)] {
            let (acknowledgement, status, attempt) = audit(Some(AuditAcknowledgement {
                status: "future-state".into(),
                attempt_sequence: sequence,
            }));
            assert!(acknowledgement.is_none());
            assert_eq!(status.as_deref(), Some("future-state"));
            assert_eq!(attempt, sequence);
            let failure: model::ClientFailure = RpcFailure {
                kind: FailureKind::Connection,
                grpc_code: Some(14),
                platform: None,
                dispatched: true,
                outcome_known: false,
                recovery: RecoveryIdentity::default(),
                audit: Some(AuditAcknowledgement {
                    status: "future-state".into(),
                    attempt_sequence: sequence,
                }),
                unsupported: None,
            }
            .into();
            assert!(failure.audit_ack.is_none());
            assert_eq!(failure.audit_status.as_deref(), Some("future-state"));
            assert_eq!(failure.audit_attempt_sequence, sequence);
        }
        let (acknowledgement, status, attempt) = audit(Some(AuditAcknowledgement {
            status: "durable".into(),
            attempt_sequence: Some(u64::MAX),
        }));
        assert_eq!(
            acknowledgement.unwrap().status,
            model::AuditAckStatus::DURABLE
        );
        assert_eq!(status.as_deref(), Some("durable"));
        assert_eq!(attempt, Some(u64::MAX));
    }
}
