use super::super::proto;
use super::validation;
use latent_policy::capability as domain;
use prost::Message;
use std::time::Instant;
use tonic::{Response, Status};

pub(super) fn kind(kind: domain::RecordKind) -> i32 {
    match kind {
        domain::RecordKind::Policy => proto::CapabilityPolicyRecordKind::Policy as i32,
        domain::RecordKind::ProviderBinding => {
            proto::CapabilityPolicyRecordKind::ProviderBinding as i32
        }
    }
}
pub(super) fn operation(value: &domain::OperationReceipt) -> proto::CapabilityPolicyOperation {
    proto::CapabilityPolicyOperation {
        operation_id: value.operation_id.clone(),
        tenant: value.tenant.clone(),
        id: value.id.clone(),
        record_kind: kind(value.kind),
        generation: value.revision,
        content_digest: value.digest.clone(),
        revoked: value.revoked,
    }
}
pub(super) fn record(value: domain::RecordView) -> proto::Policy {
    let revoked = value.document.is_none();
    proto::Policy {
        metadata: Some(proto::ObjectMetadata {
            name: value.id.clone(),
            tenant: Some(value.tenant),
            namespace: None,
            labels: std::collections::HashMap::new(),
            annotations: std::collections::HashMap::new(),
        }),
        id: value.id,
        document: value.document.unwrap_or_default(),
        generation: value.revision,
        language: validation::language(value.kind).into(),
        record_kind: kind(value.kind),
        content_digest: value.digest,
        revoked,
    }
}
pub(super) fn applied(
    receipt: &domain::OperationReceipt,
    document: &str,
) -> proto::ApplyPolicyResponse {
    proto::ApplyPolicyResponse {
        policy: Some(record(domain::RecordView {
            tenant: receipt.tenant.clone(),
            id: receipt.id.clone(),
            kind: receipt.kind,
            revision: receipt.revision,
            digest: receipt.digest.clone(),
            document: Some(document.into()),
        })),
        receipt: Some(operation(receipt)),
    }
}
pub(super) fn finish<T: Message>(
    value: T,
    lease: domain::PolicyReadLease,
    maximum: usize,
    deadline: Instant,
) -> Result<Response<T>, Status> {
    validation::completed(deadline)?;
    if value.encoded_len() > maximum.min(super::MAX_RESPONSE_BYTES) {
        return Err(validation::platform(validation::too_large()));
    }
    let mut response = Response::new(value);
    response.extensions_mut().insert(lease);
    Ok(response)
}
