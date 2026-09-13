use super::super::super::{bounds, control_audit, proto, ManagementLimits, RequestBudget};
use super::super::{deployment_to_proto, validation as deployment_validation};
use super::validation;
use latent_artifacts::{ReleaseActorKind, ReleaseAuditAck};
use latent_control_store::deployment_operations::{
    DeploymentOperationAction, DeploymentOperationCommit, DeploymentOperationReceipt,
    DeploymentReadLease, PreparedDeploymentOperation, MAX_RECEIPT_BYTES,
};
use latent_core::{PlatformError, TenantId};
use latent_rollout::deployment_audit::MAX_AUDIT_RETAINED_BYTES;
use prost::Message;
use std::time::Instant;
use tonic::{metadata::MetadataMap, Response, Status};

pub(super) fn preflight(
    prepared: &PreparedDeploymentOperation,
    tenant: &TenantId,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    let mut budget = scratch(limits)?;
    control_audit::charge(&mut budget)?;
    charge(prepared.preview(), tenant, &mut budget, limits)?;
    let deployment = prepared
        .apply_result()
        .map(|value| {
            deployment_validation::domain(value, tenant, &mut budget, limits)?;
            deployment_to_proto(value)
                .map_err(|_| Status::internal("invalid managed deployment result"))
        })
        .transpose()?;
    let output = proto::ApplyDeploymentResponse {
        deployment,
        warnings: Vec::new(),
        audit_ack: Some(control_audit::maximum()),
        receipt: Some(receipt(prepared.preview().clone())),
        replayed: true,
        durability: proto::DeploymentDurability::Uncertain as i32,
    };
    check(&output, limits)?;
    // Delete's Empty response carries only a fixed set of prepaid ASCII headers.
    if prepared.apply_result().is_none() {
        budget.allocation::<u8>(1024)?;
        if limits.max_response_bytes < 1024 {
            return Err(bounds::exhausted());
        }
    }
    Ok(())
}

pub(super) fn scratch(limits: &ManagementLimits) -> Result<RequestBudget, Status> {
    let mut budget = RequestBudget::for_response::<proto::ApplyDeploymentResponse>(limits)?;
    budget.allocation::<u8>(MAX_AUDIT_RETAINED_BYTES)?;
    Ok(budget)
}

pub(super) fn rejection(failure: &PlatformError, limits: &ManagementLimits) -> Result<(), Status> {
    let mut budget = scratch(limits)?;
    control_audit::charge(&mut budget)?;
    budget.allocation::<u8>(256)?;
    let error = PlatformError {
        code: failure.code,
        message: String::new(),
        retryable: failure.retryable,
        details: Vec::new(),
    };
    let status = crate::management::errors::platform_status(error, limits);
    if status.message().len() + status.details().len() + 128 > limits.max_response_bytes {
        return Err(bounds::exhausted());
    }
    Ok(())
}

pub(super) fn charge(
    value: &DeploymentOperationReceipt,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    if &value.tenant != tenant {
        return Err(Status::internal("deployment receipt scope mismatch"));
    }
    budget.allocation::<proto::DeploymentOperationReceipt>(1)?;
    budget.allocation::<proto::ReleaseActor>(1)?;
    for text in [&value.tenant.0, &value.deployment_id.0] {
        budget.string(text, limits.max_id_bytes)?;
    }
    budget.string(&value.actor.subject, 512)?;
    budget.string(&value.operation_id, 128)?;
    budget.string(&value.component.0, 71)?;
    budget.allocation::<u8>(3 * 71 + MAX_RECEIPT_BYTES)?;
    value
        .canonical_bytes()
        .map_err(|_| Status::internal("invalid deployment operation receipt"))?;
    Ok(())
}
pub(super) fn receipt(value: DeploymentOperationReceipt) -> proto::DeploymentOperationReceipt {
    proto::DeploymentOperationReceipt {
        format_version: value.format_version,
        tenant: value.tenant.0,
        actor: Some(proto::ReleaseActor {
            subject: value.actor.subject,
            kind: actor(value.actor.kind),
        }),
        operation_id: value.operation_id,
        action: match value.action {
            DeploymentOperationAction::Apply => proto::DeploymentOperationAction::Apply,
            DeploymentOperationAction::Delete => proto::DeploymentOperationAction::Delete,
        } as i32,
        deployment_id: value.deployment_id.0,
        request_digest: value.request_digest.into_string(),
        expected_state_version: value.expected_state_version,
        expected_generation: value.expected_generation,
        object_generation: value.object_generation,
        route_generation: value.route_generation.0,
        state_version: value.state_version,
        manifest_digest: value.manifest_digest.into_string(),
        component_digest: value.component.0,
        completed_at_unix_millis: value.completed_at_unix_millis,
        receipt_digest: value.receipt_digest.into_string(),
    }
}
fn actor(kind: ReleaseActorKind) -> i32 {
    (match kind {
        ReleaseActorKind::User => proto::ReleaseActorKind::User,
        ReleaseActorKind::Service => proto::ReleaseActorKind::Service,
        ReleaseActorKind::Node => proto::ReleaseActorKind::Node,
        ReleaseActorKind::Trigger => proto::ReleaseActorKind::Trigger,
        ReleaseActorKind::Administrator => proto::ReleaseActorKind::Administrator,
        ReleaseActorKind::Anonymous => proto::ReleaseActorKind::Anonymous,
        ReleaseActorKind::Host => proto::ReleaseActorKind::Host,
    }) as i32
}
pub(super) fn durability(confirmed: bool) -> i32 {
    (if confirmed {
        proto::DeploymentDurability::Confirmed
    } else {
        proto::DeploymentDurability::Uncertain
    }) as i32
}
pub(super) fn apply(
    value: DeploymentOperationCommit,
    ack: ReleaseAuditAck,
    limits: &ManagementLimits,
) -> Result<proto::ApplyDeploymentResponse, Status> {
    let deployment = value
        .deployment
        .ok_or_else(|| Status::internal("managed apply result missing"))?;
    let output = proto::ApplyDeploymentResponse {
        deployment: Some(
            deployment_to_proto(&deployment)
                .map_err(|_| Status::internal("invalid managed apply result"))?,
        ),
        warnings: Vec::new(),
        audit_ack: Some(control_audit::wire(ack)),
        receipt: Some(receipt(value.receipt)),
        replayed: value.replayed,
        durability: durability(value.durability.is_ok()),
    };
    check(&output, limits)?;
    Ok(output)
}
pub(super) fn delete_metadata(
    target: &mut MetadataMap,
    value: &DeploymentOperationCommit,
) -> Result<(), Status> {
    target.insert_bin(
        "latent-deployment-operation-bin",
        tonic::metadata::MetadataValue::from_bytes(value.receipt.operation_id.as_bytes()),
    );
    for (name, text) in [
        (
            "latent-deployment-request",
            value.receipt.request_digest.as_str(),
        ),
        (
            "latent-deployment-receipt",
            value.receipt.receipt_digest.as_str(),
        ),
        (
            "latent-deployment-replayed",
            if value.replayed { "true" } else { "false" },
        ),
        (
            "latent-deployment-durability",
            if value.durability.is_ok() {
                "confirmed"
            } else {
                "uncertain"
            },
        ),
    ] {
        target.insert(
            name,
            text.parse()
                .map_err(|_| Status::internal("invalid deployment receipt metadata"))?,
        );
    }
    Ok(())
}
fn check<T: Message>(value: &T, limits: &ManagementLimits) -> Result<(), Status> {
    if value.encoded_len() > limits.max_response_bytes {
        Err(bounds::exhausted())
    } else {
        Ok(())
    }
}
pub(super) fn finish<T: Message>(
    output: T,
    lease: DeploymentReadLease,
    limits: &ManagementLimits,
    deadline: Instant,
) -> Result<Response<T>, Status> {
    let pending = Pending { output, lease };
    check(&pending.output, limits)?;
    validation::completed(deadline)?;
    let Pending { output, lease } = pending;
    let mut response = Response::new(output);
    response.extensions_mut().insert(lease);
    Ok(response)
}
struct Pending<T> {
    output: T,
    lease: DeploymentReadLease,
}
