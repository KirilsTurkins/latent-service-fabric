use super::{model, FailureKind, RecoveryIdentity, RpcClient, RpcFailure};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::time::Instant;

pub(super) struct Context {
    pub recovery: RecoveryIdentity,
    pub deadline: Instant,
    pub record_id: Option<String>,
    pub record_kind: Option<i32>,
    pub deployment_id: Option<String>,
    pub page_size: usize,
    pub token_bytes: usize,
    pub maximum_request: usize,
    pub maximum_response: usize,
    pub recovery_read: bool,
}

pub(super) trait RequestProfile {
    const MAXIMUM_REQUEST: usize = 128 * 1024;
    const MAXIMUM_RESPONSE: usize = 1024 * 1024;

    fn recovery(&self) -> RecoveryIdentity {
        RecoveryIdentity::default()
    }

    fn validate(&self, context: &mut Context, tenant: &str) -> Result<(), RpcFailure>;
}

fn retained(identity: &str) -> Option<String> {
    (identity.len() <= 256).then(|| identity.into())
}

fn valid_id(identity: &str) -> bool {
    !identity.is_empty()
        && identity.len() <= 256
        && !identity
            .chars()
            .any(|value| value.is_control() || value.is_whitespace())
}

fn invalid() -> RpcFailure {
    RpcFailure::local(FailureKind::InvalidRequest)
}

pub(super) fn context<Request: RequestProfile>(
    request: &Request,
    client: &RpcClient,
    started: Instant,
    options: &model::CallOptions,
) -> Result<Context, RpcFailure> {
    let recovery = request.recovery();
    let prepare = || {
        let limits = client.limits();
        let timeout = match options.timeout_millis {
            Some(value) => {
                i64::try_from(value).map_err(|_| invalid())?;
                Duration::from_millis(value)
            }
            None => limits.rpc_timeout,
        };
        let deadline = started
            .checked_add(timeout)
            .ok_or_else(invalid)?
            .min(started + limits.rpc_timeout);
        if deadline <= Instant::now() {
            return Err(RpcFailure::local(FailureKind::Deadline));
        }
        let mut context = Context {
            recovery: recovery.clone(),
            deadline,
            record_id: None,
            record_kind: None,
            deployment_id: None,
            page_size: 0,
            token_bytes: 0,
            maximum_request: limits.maximum_request_bytes.min(Request::MAXIMUM_REQUEST),
            maximum_response: limits.maximum_response_bytes.min(Request::MAXIMUM_RESPONSE),
            recovery_read: false,
        };
        request.validate(&mut context, &client.inner.tenant.0)?;
        Ok(context)
    };
    prepare().map_err(|failure| failure.context(&recovery, false))
}

impl RequestProfile for model::InvokeRequest {
    const MAXIMUM_REQUEST: usize = 4 * 1024 * 1024;
    const MAXIMUM_RESPONSE: usize = 4 * 1024 * 1024;

    fn recovery(&self) -> RecoveryIdentity {
        RecoveryIdentity {
            activation_id: self.activation_id.as_deref().and_then(retained),
            operation_id: None,
        }
    }

    fn validate(&self, context: &mut Context, tenant: &str) -> Result<(), RpcFailure> {
        let target = self.target.as_ref().ok_or_else(invalid)?;
        if target.tenant != tenant
            || [
                &target.tenant,
                &target.service,
                &target.contract,
                &target.function,
            ]
            .iter()
            .any(|value| !valid_id(value))
            || [
                &self.activation_id,
                &self.root_activation_id,
                &self.parent_activation_id,
                &self.idempotency_key,
                &target.route,
            ]
            .into_iter()
            .flatten()
            .any(|value| !valid_id(value))
            || (self.parent_activation_id.is_some() && self.root_activation_id.is_none())
            || self.media_type.len() > 128
            || self.metadata.len() > 32
            || self
                .metadata
                .iter()
                .any(|(key, value)| key.len() > 128 || value.len() > 1024)
        {
            return Err(invalid());
        }
        if let Some(deadline) = self.deadline_unix_millis {
            let now = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| invalid())?;
            let remaining = Duration::from_millis(deadline)
                .checked_sub(now)
                .filter(|remaining| !remaining.is_zero())
                .ok_or_else(|| RpcFailure::local(FailureKind::Deadline))?;
            context.deadline = context
                .deadline
                .min(Instant::now() + remaining.min(Duration::from_mins(5)));
        }
        Ok(())
    }
}

impl RequestProfile for model::CancelRequest {
    fn recovery(&self) -> RecoveryIdentity {
        RecoveryIdentity {
            activation_id: retained(&self.activation_id),
            operation_id: None,
        }
    }

    fn validate(&self, _context: &mut Context, _tenant: &str) -> Result<(), RpcFailure> {
        if !valid_id(&self.activation_id) || self.reason.len() > 1024 {
            return Err(invalid());
        }
        Ok(())
    }
}

impl RequestProfile for model::GetActivationRequest {
    fn recovery(&self) -> RecoveryIdentity {
        RecoveryIdentity {
            activation_id: retained(&self.activation_id),
            operation_id: None,
        }
    }

    fn validate(&self, context: &mut Context, _tenant: &str) -> Result<(), RpcFailure> {
        context.recovery_read = true;
        if !valid_id(&self.activation_id) {
            return Err(invalid());
        }
        Ok(())
    }
}

impl RequestProfile for model::GetPolicyRequest {
    fn validate(&self, context: &mut Context, _tenant: &str) -> Result<(), RpcFailure> {
        if !valid_id(&self.id) {
            return Err(invalid());
        }
        context.record_id = Some(self.id.clone());
        context.record_kind = Some(self.record_kind.0);
        Ok(())
    }
}

fn page(value: Option<&model::PageRequest>, capability: bool) -> Result<usize, RpcFailure> {
    let Some(page) = value else {
        return if capability { Ok(128) } else { Err(invalid()) };
    };
    let maximum = if capability { 128 } else { 32 };
    let token_limit = if capability { 160 } else { 117 };
    if page.page_size > maximum
        || (!capability && page.page_size == 0)
        || page
            .page_token
            .as_ref()
            .is_some_and(|token| token.is_empty() || token.len() > token_limit)
    {
        return Err(invalid());
    }
    Ok(if page.page_size == 0 {
        128
    } else {
        page.page_size as usize
    })
}

impl RequestProfile for model::ListPoliciesRequest {
    fn validate(&self, context: &mut Context, _tenant: &str) -> Result<(), RpcFailure> {
        context.page_size = page(self.page.as_ref(), false)?;
        context.token_bytes = 117;
        context.record_kind = Some(self.record_kind.0);
        Ok(())
    }
}

impl RequestProfile for model::ListCapabilitiesRequest {
    const MAXIMUM_REQUEST: usize = 8 * 1024;
    const MAXIMUM_RESPONSE: usize = 128 * 1024;

    fn validate(&self, context: &mut Context, _tenant: &str) -> Result<(), RpcFailure> {
        if !valid_id(&self.deployment_id)
            || [&self.contract_prefix, &self.provider]
                .into_iter()
                .flatten()
                .any(|value| value.is_empty() || !value.is_ascii() || value.len() > 128)
        {
            return Err(invalid());
        }
        context.page_size = page(self.page.as_ref(), true)?;
        context.token_bytes = 160;
        context.deployment_id = Some(self.deployment_id.clone());
        Ok(())
    }
}

impl RequestProfile for model::ApplyPolicyRequest {
    fn recovery(&self) -> RecoveryIdentity {
        RecoveryIdentity {
            activation_id: None,
            operation_id: retained(&self.operation_id),
        }
    }

    fn validate(&self, context: &mut Context, tenant: &str) -> Result<(), RpcFailure> {
        let policy = self.policy.as_ref().ok_or_else(invalid)?;
        if policy.document.len() > context.maximum_request
            || policy.language.len() > 128
            || policy.content_digest.len() > 256
            || policy.metadata.as_ref().is_some_and(|metadata| {
                metadata.name.len() > 256
                    || metadata
                        .namespace
                        .as_ref()
                        .is_some_and(|value| value.len() > 256)
                    || metadata
                        .tenant
                        .as_ref()
                        .is_some_and(|value| value.len() > 256)
                    || metadata.labels.len() > 32
                    || metadata.annotations.len() > 32
                    || metadata
                        .labels
                        .iter()
                        .chain(metadata.annotations.iter())
                        .any(|(key, value)| key.len() > 128 || value.len() > 1024)
            })
        {
            return Err(RpcFailure::local(FailureKind::Capacity));
        }
        if self.expected_generation.is_none()
            || !valid_id(&self.operation_id)
            || !valid_id(&policy.id)
            || policy
                .metadata
                .as_ref()
                .and_then(|metadata| metadata.tenant.as_deref())
                .is_some_and(|value| value != tenant)
        {
            return Err(invalid());
        }
        context.record_id = Some(policy.id.clone());
        context.record_kind = Some(policy.record_kind.0);
        Ok(())
    }
}

impl RequestProfile for model::GetPolicyOperationRequest {
    fn recovery(&self) -> RecoveryIdentity {
        RecoveryIdentity {
            activation_id: None,
            operation_id: retained(&self.operation_id),
        }
    }

    fn validate(&self, context: &mut Context, _tenant: &str) -> Result<(), RpcFailure> {
        context.recovery_read = true;
        if !valid_id(&self.operation_id) {
            return Err(invalid());
        }
        Ok(())
    }
}
