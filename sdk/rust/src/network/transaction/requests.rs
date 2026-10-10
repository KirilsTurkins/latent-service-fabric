use super::{management, model, phase4, FailureKind, RpcClient, RpcFailure};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::time::Instant;

pub(super) struct Context {
    pub identity: model::RecoveryIdentity,
    pub association: phase4::Association,
    pub deadline: Instant,
    pub maximum_request: usize,
    pub maximum_response: usize,
}

impl Context {
    pub(super) fn transport_identity(&self) -> crate::network::RecoveryIdentity {
        crate::network::RecoveryIdentity {
            activation_id: self.identity.activation_id.clone(),
            operation_id: self.identity.operation_id.clone(),
        }
    }
}

pub(super) fn local_failure(
    error: phase4::ValidationError,
    identity: model::RecoveryIdentity,
) -> model::ClientFailure {
    model::ClientFailure {
        transport: Box::new(
            RpcFailure::local(if error == phase4::ValidationError::Capacity {
                FailureKind::Capacity
            } else {
                FailureKind::InvalidRequest
            })
            .into(),
        ),
        identity: Box::new(identity),
        observed: None,
    }
}

pub(super) fn identity(request: &phase4::Request) -> model::RecoveryIdentity {
    use phase4::Request;
    let mut result = model::RecoveryIdentity::default();
    if let Some(value) = dispatcher_original(request) {
        result.operation_id = Some(value.operation_id.clone());
        result.dispatcher_action = Some(model::DispatcherAction(value.action));
        result.dispatcher_expected_generation = value.expected_generation.map(Into::into);
    }
    management_identity(request, &mut result);
    let command = match request {
        Request::InvokeCommand(value) => {
            result.activation_id = value
                .invocation
                .as_ref()
                .and_then(|value| value.activation_id.clone());
            result.expected_versions = value
                .expected_versions
                .iter()
                .cloned()
                .map(Into::into)
                .collect();
            if let Some(retry) = &value.retry_attempt {
                result.retry_request_id = Some(retry.request_id.clone());
                result.expected_abort = retry.expected_abort.clone().map(Into::into);
                result.attempt_id = retry
                    .expected_abort
                    .as_ref()
                    .map(|fence| fence.attempt_id.clone());
            }
            value.command.as_ref()
        }
        Request::Query(value) => {
            result.namespace = value.namespace.clone().map(Into::into);
            result.activation_id = value
                .invocation
                .as_ref()
                .and_then(|value| value.activation_id.clone());
            None
        }
        Request::LookupCommand(value) => {
            result.attempt_id.clone_from(&value.attempt_id);
            result.authorization_publication =
                value.authorization_publication.clone().map(Into::into);
            value.command.as_ref()
        }
        Request::LookupCommit(value) => {
            result.receipt_id = Some(value.receipt_id.clone());
            result.authorization_publication =
                value.authorization_publication.clone().map(Into::into);
            value.command.as_ref()
        }
        Request::GetEffect(value) => {
            result.effect_id = Some(value.effect_id.clone());
            result.authorization_publication =
                value.authorization_publication.clone().map(Into::into);
            value.command.as_ref()
        }
        Request::PlanEffectMutation(value) => {
            result.operation_id = Some(value.operation_id.clone());
            result.expected_version = Some(value.expected_version.clone());
            result.expected_policy_digest = Some(value.expected_policy_digest.clone());
            result.effect_mutation = Some((**value).clone().into());
            value.effect.as_ref().and_then(|value| {
                result.effect_id = Some(value.effect_id.clone());
                result.authorization_publication =
                    value.authorization_publication.clone().map(Into::into);
                value.command.as_ref()
            })
        }
        Request::ListEffectHistory(value) => value.effect.as_ref().and_then(|value| {
            result.effect_id = Some(value.effect_id.clone());
            result.authorization_publication =
                value.authorization_publication.clone().map(Into::into);
            value.command.as_ref()
        }),
        Request::CancelCommand(value) => value.command.as_ref().and_then(|value| {
            result.attempt_id.clone_from(&value.attempt_id);
            result.authorization_publication =
                value.authorization_publication.clone().map(Into::into);
            value.command.as_ref()
        }),
        _ => None,
    };
    if let Some(command) = command {
        result.namespace = command.namespace.clone().map(Into::into);
        result.command = Some(command.clone().into());
    }
    result
}

fn management_identity(request: &phase4::Request, result: &mut model::RecoveryIdentity) {
    use phase4::Request;
    let inspect = match request {
        Request::InspectNamespace(value) => Some(&**value),
        Request::MutateNamespace(value) => {
            result.operation_id = Some(value.operation_id.clone());
            result.expected_generation = value.expected_generation;
            value.namespace.as_ref()
        }
        Request::SelectEntity(value) => value.namespace.as_ref(),
        Request::MutateState(value) => {
            result.operation_id = Some(value.operation_id.clone());
            result.expected_version = Some(value.expected_version.clone());
            result.expected_policy_digest = Some(value.expected_policy_digest.clone());
            result.effect_plan = value.effect_plan.clone().map(Into::into);
            value.namespace.as_ref()
        }
        Request::GetStateOperationReceipt(value) => {
            result.operation_id = Some(value.operation_id.clone());
            result.effect_plan = value.original_effect_plan.clone().map(Into::into);
            value.namespace.as_ref()
        }
        _ => None,
    };
    if let Some(inspect) = inspect {
        result.namespace = inspect.namespace.clone().map(Into::into);
        result.authorization_publication =
            inspect.authorization_publication.clone().map(Into::into);
    }
    if let Some(original) = result
        .effect_plan
        .as_ref()
        .and_then(|value| value.original.as_ref())
    {
        result.effect_mutation = Some(original.clone());
        result.expected_version = Some(original.expected_version.clone());
        result.expected_policy_digest = Some(original.expected_policy_digest.clone());
        result.effect_id = original
            .effect
            .as_ref()
            .map(|effect| effect.effect_id.clone());
    }
}

fn dispatcher_original(
    request: &phase4::Request,
) -> Option<&super::control::ControlDispatcherRequest> {
    match request {
        phase4::Request::ControlDispatcher(value) => Some(value),
        phase4::Request::GetDispatcherOperation(value) => value.original.as_ref(),
        _ => None,
    }
}

pub(super) fn prepare(
    request: &phase4::Request,
    client: &RpcClient,
    started: Instant,
    options: &management::CallOptions,
) -> Result<Context, model::ClientFailure> {
    request.validate().map_err(|error| {
        // A representable original node-control precondition remains available
        // when its successor cannot be represented. This data grants no rights.
        let bounded = dispatcher_original(request).filter(|value| {
            value.operation_id.len() <= 256
                && !value.operation_id.is_empty()
                && !value.operation_id.chars().any(char::is_control)
                && matches!(value.action, 1 | 2)
                && value
                    .expected_generation
                    .as_ref()
                    .is_some_and(|generation| generation.owner_epoch > 0 && generation.revision > 0)
        });
        local_failure(
            error,
            if bounded.is_some() {
                identity(request)
            } else {
                model::RecoveryIdentity::default()
            },
        )
    })?;
    let identity = identity(request);
    let operation = || {
        if !request.is_node_management() && request.tenant() != Some(client.inner.tenant.0.as_str())
        {
            return Err(RpcFailure::local(FailureKind::InvalidRequest));
        }
        let limits = client.limits();
        if request.encoded_len() > limits.maximum_request_bytes {
            return Err(RpcFailure::local(FailureKind::Capacity));
        }
        let timeout = options
            .timeout_millis
            .map_or(limits.rpc_timeout, Duration::from_millis);
        let mut deadline = started
            .checked_add(timeout)
            .ok_or_else(|| RpcFailure::local(FailureKind::InvalidRequest))?
            .min(started + limits.rpc_timeout);
        let invocation = match request {
            phase4::Request::InvokeCommand(value) => value.invocation.as_ref(),
            phase4::Request::Query(value) => value.invocation.as_ref(),
            _ => None,
        };
        if let Some(wall) = invocation.and_then(|value| value.deadline_unix_millis) {
            let elapsed = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| RpcFailure::local(FailureKind::InvalidRequest))?;
            let remaining = Duration::from_millis(wall)
                .checked_sub(elapsed)
                .ok_or_else(|| RpcFailure::local(FailureKind::Deadline))?;
            let wall_deadline = Instant::now()
                .checked_add(remaining)
                .ok_or_else(|| RpcFailure::local(FailureKind::InvalidRequest))?;
            deadline = deadline.min(wall_deadline);
        }
        if deadline <= Instant::now() {
            return Err(RpcFailure::local(FailureKind::Deadline));
        }
        Ok(Context {
            identity: identity.clone(),
            association: request.association(),
            deadline,
            maximum_request: limits.maximum_request_bytes.min(phase4::MAX_REQUEST_BYTES),
            maximum_response: limits
                .maximum_response_bytes
                .min(phase4::MAX_RESPONSE_BYTES),
        })
    };
    operation().map_err(|error| model::ClientFailure {
        transport: Box::new(error.into()),
        identity: Box::new(identity),
        observed: None,
    })
}
