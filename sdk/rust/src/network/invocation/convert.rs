use super::{FailureKind, RpcFailure};
use crate::{
    DeclaredInvocationError, InvocationOutcome, InvocationReceipt, InvokeRequest, InvokeResponse,
    PlatformInvocationFailure,
};
use latent_core::{
    ActivationId, BudgetConsumption, DeclaredError, ReleaseDigest, RevisionId, RouteGeneration,
};
use latent_rpc::{invocation::v1 as proto, platform_error::TryIntoDomainPlatformError};

pub(super) fn request_bounds(request: &InvokeRequest, maximum: usize) -> Result<(), RpcFailure> {
    let options = &request.options;
    if request.payload.len() > maximum
        || request.media_type.len() > 128
        || options.metadata.len() > 32
        || options
            .metadata
            .iter()
            .any(|(key, value)| key.len() > 128 || value.len() > 1024)
        || [
            &request.target.tenant.0,
            &request.target.service.0,
            &request.target.contract.0,
            &request.target.function.0,
        ]
        .iter()
        .any(|value| value.len() > 256)
        || request
            .target
            .route
            .as_ref()
            .is_some_and(|route| route.len() > 256)
        || [
            &request.activation_id,
            &request.root_activation_id,
            &request.parent_activation_id,
        ]
        .into_iter()
        .flatten()
        .any(|id| id.0.len() > 256)
        || options
            .idempotency_key
            .as_ref()
            .is_some_and(|key| key.0.len() > 256)
    {
        return Err(RpcFailure::local(FailureKind::InvalidRequest));
    }
    Ok(())
}

pub(super) fn request(value: InvokeRequest) -> proto::InvokeRequest {
    let budget = value.options.budget;
    proto::InvokeRequest {
        activation_id: value.activation_id.map(|id| id.0),
        root_activation_id: value.root_activation_id.map(|id| id.0),
        parent_activation_id: value.parent_activation_id.map(|id| id.0),
        target: Some(proto::InvocationTarget {
            tenant: value.target.tenant.0,
            service: value.target.service.0,
            contract: value.target.contract.0,
            function: value.target.function.0,
            route: value.target.route,
        }),
        payload: value.payload,
        media_type: value.media_type,
        deadline_unix_millis: value.options.deadline_unix_millis,
        priority: u32::from(value.options.priority),
        idempotency_key: value.options.idempotency_key.map(|key| key.0),
        metadata: value.options.metadata.into_iter().collect(),
        budget: Some(proto::ResourceBudget {
            cpu_fuel: budget.cpu_fuel,
            memory_bytes: budget.memory_bytes,
            wall_time_limit_millis: budget.wall_time_limit_millis,
            child_calls: budget.child_calls,
            outbound_requests: budget.outbound_requests,
            state_read_bytes: budget.state_read_bytes,
            state_write_bytes: budget.state_write_bytes,
            blob_read_bytes: budget.blob_read_bytes,
            blob_write_bytes: budget.blob_write_bytes,
            log_bytes: budget.log_bytes,
            effect_count: budget.effect_count,
        }),
    }
}

pub(super) fn outcome(value: proto::InvokeResponse) -> Result<InvocationOutcome, RpcFailure> {
    valid_id(&value.activation_id)?;
    match (
        value.revision_id.is_empty(),
        value.release_digest.is_empty(),
    ) {
        (true, true)
            if value.route_generation == 0
                && value.publication_id.is_none()
                && matches!(
                    value.result,
                    Some(proto::invoke_response::Result::PlatformFailure(_))
                ) => {}
        (false, false) => {
            valid_id(&value.revision_id)?;
            valid_id(&value.release_digest)?;
        }
        _ => return Err(invalid()),
    }
    if let Some(id) = &value.publication_id {
        id.parse::<latent_core::PublicationId>()
            .map_err(|_| invalid())?;
    }
    let receipt = InvocationReceipt {
        activation_id: ActivationId(value.activation_id),
        revision_id: RevisionId(value.revision_id),
        release_digest: ReleaseDigest(value.release_digest),
        publication_id: value
            .publication_id
            .map(|id| id.parse())
            .transpose()
            .map_err(|_| invalid())?,
        route_generation: RouteGeneration(value.route_generation),
        consumption: consumption(value.consumption.ok_or_else(invalid)?),
    };
    match value.result.ok_or_else(invalid)? {
        proto::invoke_response::Result::Success(success) => {
            Ok(InvocationOutcome::Succeeded(InvokeResponse {
                activation_id: receipt.activation_id,
                revision_id: receipt.revision_id,
                release_digest: receipt.release_digest,
                publication_id: receipt.publication_id,
                route_generation: receipt.route_generation,
                consumption: receipt.consumption,
                payload: success.payload,
                media_type: success.media_type,
                committed_state_version: success.committed_state_version,
                effect_ids: success.effect_ids,
                metadata: success.metadata.into_iter().collect(),
            }))
        }
        proto::invoke_response::Result::DeclaredError(error) => {
            Ok(InvocationOutcome::DeclaredError(DeclaredInvocationError {
                receipt,
                error: declared(error),
            }))
        }
        proto::invoke_response::Result::PlatformFailure(error) => Ok(
            InvocationOutcome::PlatformFailure(PlatformInvocationFailure {
                receipt,
                error: error.try_into_domain().map_err(|error| {
                    RpcFailure::unsupported("platform_error.code", error.code())
                })?,
            }),
        ),
    }
}

pub(super) fn consumption(value: proto::BudgetConsumption) -> BudgetConsumption {
    BudgetConsumption {
        cpu_fuel: value.cpu_fuel,
        peak_memory_bytes: value.peak_memory_bytes,
        wall_time_micros: value.wall_time_micros,
        child_calls: value.child_calls,
        outbound_requests: value.outbound_requests,
        state_read_bytes: value.state_read_bytes,
        state_write_bytes: value.state_write_bytes,
        blob_read_bytes: value.blob_read_bytes,
        blob_write_bytes: value.blob_write_bytes,
        log_bytes: value.log_bytes,
        effect_count: value.effect_count,
    }
}

pub(super) fn declared(value: proto::DeclaredError) -> DeclaredError {
    DeclaredError {
        code: value.code,
        message: value.message,
        payload: value.payload,
        media_type: value.media_type,
        metadata: value.metadata.into_iter().collect(),
    }
}

pub(super) fn valid_id(value: &str) -> Result<(), RpcFailure> {
    if value.is_empty()
        || value.len() > 256
        || value
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
    {
        return Err(invalid());
    }
    Ok(())
}

pub(super) fn invalid() -> RpcFailure {
    RpcFailure::local(FailureKind::InvalidResponse)
}
