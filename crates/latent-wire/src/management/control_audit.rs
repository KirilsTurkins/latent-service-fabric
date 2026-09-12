//! Small, prepaid acknowledgement surface shared by mutation adapters.

use latent_artifacts::{ReleaseAuditAck, ReleaseAuditStatus};
use prost::Message;
use tonic::{metadata::MetadataMap, Response, Status};

use super::{bounds::exhausted, proto, ManagementLimits, RequestBudget};

pub(super) fn wire(value: ReleaseAuditAck) -> proto::AuditAck {
    proto::AuditAck {
        status: match value.status {
            ReleaseAuditStatus::Disabled => proto::AuditAckStatus::Disabled,
            ReleaseAuditStatus::Durable => proto::AuditAckStatus::Durable,
            ReleaseAuditStatus::OutcomeUnknown => proto::AuditAckStatus::OutcomeUnknown,
            ReleaseAuditStatus::AuditUnavailable => proto::AuditAckStatus::AuditUnavailable,
        } as i32,
        attempt_sequence: value.attempt_sequence,
    }
}

pub(super) fn maximum() -> proto::AuditAck {
    proto::AuditAck {
        status: proto::AuditAckStatus::OutcomeUnknown as i32,
        attempt_sequence: Some(u64::MAX),
    }
}

pub(super) fn charge(budget: &mut RequestBudget) -> Result<(), Status> {
    // The ack, encoder buffer and bounded two-field metadata projection coexist.
    // This is additional to the original operation/deployment response graph.
    budget.allocation::<proto::AuditAck>(1)?;
    budget.allocation::<u8>(128)
}

pub(super) fn operation_preflight(
    operation: &proto::ReleaseOperationReceipt,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    // Both supported lifecycle response wrappers contain field1=operation and
    // field2=ack. Count exact encoding without cloning the already charged DTO.
    let inner = operation.encoded_len();
    let ack = maximum().encoded_len();
    let length = 1
        + prost::encoding::encoded_len_varint(inner as u64)
        + inner
        + 1
        + prost::encoding::encoded_len_varint(ack as u64)
        + ack;
    if length > limits.max_response_bytes {
        return Err(exhausted());
    }
    Ok(())
}

pub(super) fn status(mut status: Status, ack: ReleaseAuditAck) -> Status {
    metadata(status.metadata_mut(), ack);
    status
}

pub(super) fn response<T>(mut response: Response<T>, ack: ReleaseAuditAck) -> Response<T> {
    metadata(response.metadata_mut(), ack);
    response
}

fn metadata(target: &mut MetadataMap, ack: ReleaseAuditAck) {
    if ack.status == ReleaseAuditStatus::Disabled {
        return;
    }
    let status = match ack.status {
        ReleaseAuditStatus::Disabled => "disabled",
        ReleaseAuditStatus::Durable => "durable",
        ReleaseAuditStatus::OutcomeUnknown => "outcome-unknown",
        ReleaseAuditStatus::AuditUnavailable => "audit-unavailable",
    };
    target.insert(
        "latent-audit-status",
        status.parse().expect("fixed ASCII audit status"),
    );
    if let Some(sequence) = ack.attempt_sequence {
        target.insert(
            "latent-audit-attempt",
            sequence.to_string().parse().expect("bounded u64 ASCII"),
        );
    }
}
