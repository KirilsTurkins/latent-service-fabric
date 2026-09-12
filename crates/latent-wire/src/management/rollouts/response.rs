use super::super::{bounds, control_audit, RequestBudget};
use super::{conversion, proto, validation, ManagementLimits};
use latent_control_store::rollouts::RolloutOperationReceipt;
use latent_core::TenantId;
use latent_rollout::{MutationPreview, ResponseLease};
use prost::Message;
use std::time::Instant;
use tonic::{Response, Status};

pub(super) fn scope(receipt: &RolloutOperationReceipt, tenant: &TenantId) -> Result<(), Status> {
    if &receipt.tenant != tenant {
        return Err(Status::internal("rollout response scope mismatch"));
    }
    Ok(())
}

pub(super) fn preflight(
    preview: MutationPreview<'_>,
    tenant: &str,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    if preview.receipt.tenant.0 != tenant {
        return Err(Status::internal("rollout response scope mismatch"));
    }
    let mut budget = RequestBudget::for_response::<proto::StartRolloutResponse>(limits)?;
    budget.allocation::<proto::RolloutOperationReceipt>(1)?;
    budget.allocation::<proto::ReleaseActor>(1)?;
    for value in [
        &preview.receipt.rollout_id.0,
        &preview.receipt.tenant.0,
        &preview.receipt.operation_id,
        &preview.receipt.actor.subject,
    ] {
        budget.string(value, 512)?;
    }
    budget.allocation::<u8>(3 * 71)?;
    control_audit::charge(&mut budget)?;
    if preview.receipt.canary_decision.is_some() {
        super::canary::charge_decision(&mut budget)?;
    }
    if preview.observation.is_some() {
        budget.allocation::<proto::RolloutObservation>(1)?;
    }
    let output = proto::StartRolloutResponse {
        receipt: Some(conversion::receipt(preview.receipt.clone())),
        audit_ack: Some(control_audit::wire(preview.audit_ack)),
        // Reserve the encoded true flag even for a fresh operation.
        replayed: true,
        durability: proto::RolloutDurability::Uncertain as i32,
        observation: preview.observation.map(super::canary::observation),
    };
    if output.encoded_len() > limits.max_response_bytes {
        return Err(bounds::exhausted());
    }
    Ok(())
}

pub(super) fn finish<T: Message>(
    output: T,
    lease: ResponseLease,
    limits: &ManagementLimits,
    deadline: Instant,
) -> Result<Response<T>, Status> {
    // Keep payload destruction ahead of permit refund on either rejection.
    // Separate function arguments would otherwise drop in reverse order.
    let pending = PendingResponse { output, lease };
    if pending.output.encoded_len() > limits.max_response_bytes {
        return Err(bounds::exhausted());
    }
    validation::completed(deadline)?;
    let PendingResponse { output, lease } = pending;
    let mut response = Response::new(output);
    response.extensions_mut().insert(lease);
    Ok(response)
}

struct PendingResponse<T> {
    output: T,
    lease: ResponseLease,
}
