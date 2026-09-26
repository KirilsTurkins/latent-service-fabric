use super::super::{bounds, control_audit, proto, ManagementServiceAdapter};
use super::{conversion, validation};
use latent_artifacts::ReleaseAuditAck;
use latent_control_store::http_routes::{
    PreparedTriggerOperation, TriggerOperationCommit, TriggerReadLease,
};
use prost::Message;
use std::time::Instant;
use tonic::{
    metadata::{MetadataMap, MetadataValue},
    Response, Status,
};

pub(super) fn durability(confirmed: bool) -> i32 {
    if confirmed {
        proto::TriggerDurability::Confirmed as i32
    } else {
        proto::TriggerDurability::Uncertain as i32
    }
}
fn check<T: Message>(
    adapter: &ManagementServiceAdapter,
    value: &T,
    scratch: usize,
) -> Result<(), Status> {
    if value
        .encoded_len()
        .saturating_mul(4)
        .saturating_add(4096)
        .saturating_add(scratch)
        > adapter.limits.max_response_bytes
    {
        return Err(bounds::exhausted());
    }
    Ok(())
}
pub(super) fn preflight(
    adapter: &ManagementServiceAdapter,
    prepared: &PreparedTriggerOperation,
) -> Result<(), Status> {
    let output = proto::ApplyTriggerResponse {
        trigger: prepared.trigger().cloned().map(conversion::trigger),
        warnings: Vec::new(),
        receipt: Some(conversion::receipt(prepared.preview().clone())),
        replayed: true,
        durability: durability(false),
        audit_ack: Some(control_audit::maximum()),
    };
    check(
        adapter,
        &output,
        latent_rollout::trigger_audit::MAX_AUDIT_RETAINED_BYTES,
    )
}
pub(super) fn apply(
    value: TriggerOperationCommit,
    ack: ReleaseAuditAck,
) -> Result<proto::ApplyTriggerResponse, Status> {
    Ok(proto::ApplyTriggerResponse {
        trigger: Some(conversion::trigger(
            value
                .trigger
                .ok_or_else(|| Status::internal("HTTP trigger result missing"))?,
        )),
        warnings: Vec::new(),
        receipt: Some(conversion::receipt(value.receipt)),
        replayed: value.replayed,
        durability: durability(value.durability.is_ok()),
        audit_ack: Some(control_audit::wire(ack)),
    })
}
pub(super) fn finish<T: Message>(
    adapter: &ManagementServiceAdapter,
    value: T,
    lease: TriggerReadLease,
    expires: Instant,
) -> Result<Response<T>, Status> {
    check(adapter, &value, 0)?;
    validation::completed(expires)?;
    let mut response = Response::new(value);
    response.extensions_mut().insert(lease);
    Ok(response)
}
pub(super) fn delete_metadata(metadata: &mut MetadataMap, value: &TriggerOperationCommit) {
    metadata.insert_bin(
        "latent-trigger-operation-bin",
        MetadataValue::from_bytes(value.receipt.operation_id.as_bytes()),
    );
    for (name, value) in [
        (
            "latent-trigger-receipt",
            value.receipt.receipt_digest.clone(),
        ),
        (
            "latent-trigger-state",
            value.receipt.state_version.to_string(),
        ),
        (
            "latent-trigger-generation",
            value.receipt.object_generation.to_string(),
        ),
        ("latent-trigger-replayed", value.replayed.to_string()),
        (
            "latent-trigger-durability",
            if value.durability.is_ok() {
                "confirmed"
            } else {
                "uncertain"
            }
            .to_owned(),
        ),
    ] {
        metadata.insert(
            name,
            value
                .parse()
                .expect("bounded ASCII trigger receipt metadata"),
        );
    }
}
