mod bounds;
mod owned;

use super::super::super::{errors::platform_status, RequestBudget};
use super::{conversion, proto, ManagementLimits};
use latent_artifacts::{ReleaseLifecycleStatus, ReleaseOperationReceipt};
use latent_core::{PlatformError, TenantId};
use prost::Message;
use tonic::Status;

pub(super) fn operation(
    value: &ReleaseOperationReceipt,
    tenant: &TenantId,
    limits: &ManagementLimits,
) -> Result<proto::ReleaseOperationReceipt, Status> {
    let mut ceiling = limits.clone();
    // Stored/encoded byte ceilings and the coexisting typed source/wire graph
    // are distinct budgets; valid maximum-length actor/scope fields need both.
    ceiling.max_response_bytes = ceiling.max_response_bytes.min(32 * 1024);
    let mut budget = RequestBudget::for_response::<proto::ReleaseOperationReceipt>(&ceiling)?;
    // Source allocations and the prospective owned wire graph coexist.
    bounds::receipt(value, tenant, &mut budget, &ceiling)?;
    bounds::receipt(value, tenant, &mut budget, &ceiling)?;
    let wire = owned::receipt(value);
    ceiling.max_response_bytes = limits.max_response_bytes.min(8192);
    encoded(&wire, &ceiling)?;
    Ok(wire)
}

pub(super) fn charge_operation(
    value: &ReleaseOperationReceipt,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    // Publication retains the repository receipt, the preflight's owned wire
    // receipt, and the copy inside the prepared publication response together.
    bounds::receipt(value, tenant, budget, limits)?;
    bounds::receipt(value, tenant, budget, limits)?;
    bounds::receipt(value, tenant, budget, limits)
}

pub(super) fn status(
    value: &ReleaseLifecycleStatus,
    tenant: &TenantId,
    limits: &ManagementLimits,
) -> Result<proto::ReleaseLifecycleStatus, Status> {
    let mut ceiling = limits.clone();
    ceiling.max_response_bytes = ceiling.max_response_bytes.min(16 * 1024);
    let mut budget = RequestBudget::for_response::<proto::ReleaseLifecycleStatus>(&ceiling)?;
    bounds::record(&value.record, tenant, &mut budget, &ceiling)?;
    bounds::record(&value.record, tenant, &mut budget, &ceiling)?;
    let wire = proto::ReleaseLifecycleStatus {
        record: Some(owned::record(&value.record)),
        eligibility: conversion::release_live_eligibility(value.eligibility),
        eligibility_reason: conversion::release_eligibility_reason(value.eligibility_reason),
    };
    ceiling.max_response_bytes = limits.max_response_bytes.min(4096);
    encoded(&wire, &ceiling)?;
    Ok(wire)
}

pub(super) fn encoded(value: &impl Message, limits: &ManagementLimits) -> Result<(), Status> {
    if value.encoded_len() > limits.max_response_bytes {
        return Err(Status::resource_exhausted(
            "release response exceeds configured limits",
        ));
    }
    Ok(())
}

/// Only fixed server fields plus the already bounded receipt enter this error.
/// Arbitrary source messages/details are never cloned or disclosed.
pub(super) fn failure(
    error: &PlatformError,
    receipt: &proto::ReleaseOperationReceipt,
    limits: &ManagementLimits,
) -> Result<Status, Status> {
    let plain = platform_status(
        PlatformError {
            code: error.code,
            message: String::new(),
            retryable: error.retryable,
            details: Vec::new(),
        },
        limits,
    );
    let mut fields = std::collections::HashMap::from([
        ("operation_id".to_owned(), receipt.operation_id.clone()),
        ("disposition".to_owned(), "rejected".to_owned()),
        ("reason".to_owned(), reason(receipt.reason)?.to_owned()),
    ]);
    if let Some(record) = &receipt.record {
        fields.insert("generation".to_owned(), record.generation.to_string());
    }
    let body = proto::PlatformError {
        code: error.code.wire_code().to_owned(),
        message: plain.message().to_owned(),
        retryable: error.retryable,
        detail_items: vec![proto::ErrorDetail {
            kind: "release-operation".to_owned(),
            fields,
        }],
    };
    let mut budget = RequestBudget::for_response::<proto::PlatformError>(limits)?;
    budget.string(&body.code, 64)?;
    budget.string(&body.message, 128)?;
    budget.sequence(&body.detail_items, 1)?;
    budget.string(&body.detail_items[0].kind, 64)?;
    // Hash-map capacity is bounded by its fixed construction above. Charge it
    // directly, without reserving an unrelated domain metadata destination.
    budget.allocation::<u8>(body.detail_items[0].fields.capacity() * 128)?;
    for (key, value) in &body.detail_items[0].fields {
        budget.string(key, 64)?;
        budget.string(value, 128)?;
    }
    encoded(&body, limits)?;
    Ok(Status::with_details(
        plain.code(),
        plain.message(),
        body.encode_to_vec().into(),
    ))
}

fn reason(value: i32) -> Result<&'static str, Status> {
    use proto::ReleaseLifecycleReason as R;
    Ok(match R::try_from(value) {
        Ok(R::Admitted) => "admitted",
        Ok(R::EvidenceRenewed) => "evidence-renewed",
        Ok(R::OperatorRevocation) => "operator-revocation",
        Ok(R::SecurityIncident) => "security-incident",
        Ok(R::CorruptContent) => "corrupt-content",
        Ok(R::Superseded) => "superseded",
        Ok(R::EndOfSupport) => "end-of-support",
        Ok(R::OperatorRetirement) => "operator-retirement",
        Ok(R::InvalidPackage) => "invalid-package",
        Ok(R::IntegrityMismatch) => "integrity-mismatch",
        Ok(R::IncompatibleContract) => "incompatible-contract",
        Ok(R::EvidenceRejected) => "evidence-rejected",
        Ok(R::PolicyDenied) => "policy-denied",
        Ok(R::ReleaseRevoked) => "release-revoked",
        Ok(R::ReleaseRetired) => "release-retired",
        Ok(R::GenerationConflict) => "generation-conflict",
        Ok(R::ContentConflict) => "content-conflict",
        _ => return Err(Status::internal("invalid release operation reason")),
    })
}
