use super::{requests::Context, FailureKind, RpcFailure};
use latent_core::PlatformErrorCode;
use latent_rpc::{control::v1 as control, invocation::v1 as invocation};

pub(super) trait ResponseProfile {
    fn activation_id(&self) -> Option<&str> {
        None
    }
    fn validate(&self, context: &Context, tenant: &str) -> Result<bool, RpcFailure>;
}

fn invalid() -> RpcFailure {
    RpcFailure::local(FailureKind::InvalidResponse)
}

pub(super) fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && !value
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
}

fn publication(value: Option<&str>) -> Result<(), RpcFailure> {
    if value.is_some_and(|value| value.parse::<latent_core::PublicationId>().is_err()) {
        return Err(invalid());
    }
    Ok(())
}

fn platform(value: &invocation::PlatformError) -> Result<PlatformErrorCode, RpcFailure> {
    if value.code.len() > 64
        || value.message.len() > 4096
        || value.detail_items.len() > 16
        || value.detail_items.iter().any(|detail| {
            detail.kind.len() > 128
                || detail.fields.len() > 32
                || detail
                    .fields
                    .iter()
                    .any(|(key, value)| key.len() > 128 || value.len() > 1024)
        })
    {
        return Err(invalid());
    }
    PlatformErrorCode::from_wire_code(&value.code)
        .ok_or_else(|| RpcFailure::unsupported("platform_error.code", &value.code))
}

fn terminal(value: &str) -> Result<(), RpcFailure> {
    if !matches!(
        value,
        "completed"
            | "rejected"
            | "cancelled"
            | "deadline_exceeded"
            | "resource_exhausted"
            | "guest_trap"
            | "state_conflict"
            | "dependency_failed"
            | "platform_failed"
    ) {
        return Err(RpcFailure::unsupported("activation.terminal_state", value));
    }
    Ok(())
}

impl ResponseProfile for invocation::InvokeResponse {
    fn activation_id(&self) -> Option<&str> {
        Some(&self.activation_id)
    }

    fn validate(&self, context: &Context, _tenant: &str) -> Result<bool, RpcFailure> {
        if !valid_id(&self.activation_id)
            || context
                .recovery
                .activation_id
                .as_ref()
                .is_some_and(|identity| identity != &self.activation_id)
            || self.consumption.is_none()
        {
            return Err(invalid());
        }
        let outcome = self.result.as_ref().ok_or_else(invalid)?;
        match (self.revision_id.is_empty(), self.release_digest.is_empty()) {
            (true, true)
                if self.route_generation == 0
                    && self.publication_id.is_none()
                    && matches!(
                        outcome,
                        invocation::invoke_response::Result::PlatformFailure(_)
                    ) => {}
            (false, false) if valid_id(&self.revision_id) && valid_id(&self.release_digest) => {}
            _ => return Err(invalid()),
        }
        publication(self.publication_id.as_deref())?;
        if let invocation::invoke_response::Result::PlatformFailure(error) = outcome {
            platform(error)?;
        }
        Ok(true)
    }
}

impl ResponseProfile for invocation::CancelResponse {
    fn validate(&self, _context: &Context, _tenant: &str) -> Result<bool, RpcFailure> {
        match (self.disposition, self.terminal_state.as_deref()) {
            (1 | 3, None) => {}
            (2, Some(value)) => terminal(value)?,
            (0..=3, _) => return Err(invalid()),
            _ => {}
        }
        Ok(true)
    }
}

impl ResponseProfile for invocation::ActivationStatus {
    fn activation_id(&self) -> Option<&str> {
        Some(&self.activation_id)
    }

    fn validate(&self, context: &Context, _tenant: &str) -> Result<bool, RpcFailure> {
        if !valid_id(&self.activation_id)
            || context.recovery.activation_id.as_deref() != Some(&self.activation_id)
        {
            return Err(invalid());
        }
        if !matches!(
            self.phase.as_str(),
            "received"
                | "resolved"
                | "admitted"
                | "queued"
                | "materializing"
                | "running"
                | "suspended"
                | "preparing_commit"
                | "committed"
                | "effects_pending"
        ) {
            return Err(RpcFailure::unsupported("activation.phase", &self.phase));
        }
        match (&self.terminal_state, &self.terminal_outcome) {
            (None, None)
                if self.final_consumption.is_none() && self.terminal_at_unix_millis.is_none() => {}
            (Some(state), Some(outcome))
                if self.final_consumption.is_some() && self.terminal_at_unix_millis.is_some() =>
            {
                terminal(state)?;
                let expected = match outcome {
                    invocation::activation_status::TerminalOutcome::Succeeded(_)
                    | invocation::activation_status::TerminalOutcome::DeclaredError(_) => {
                        "completed"
                    }
                    invocation::activation_status::TerminalOutcome::PlatformFailure(error) => {
                        terminal_for(platform(error)?)
                    }
                };
                if state != expected {
                    return Err(invalid());
                }
            }
            _ => return Err(invalid()),
        }
        Ok(true)
    }
}

fn terminal_for(code: PlatformErrorCode) -> &'static str {
    match code {
        PlatformErrorCode::DeadlineExceeded => "deadline_exceeded",
        PlatformErrorCode::Cancelled => "cancelled",
        PlatformErrorCode::ResourceExhausted => "resource_exhausted",
        PlatformErrorCode::GuestTrap => "guest_trap",
        PlatformErrorCode::StateConflict => "state_conflict",
        PlatformErrorCode::DependencyFailed
        | PlatformErrorCode::Unavailable
        | PlatformErrorCode::RouteUnavailable => "dependency_failed",
        PlatformErrorCode::AdmissionRejected
        | PlatformErrorCode::PermissionDenied
        | PlatformErrorCode::Unauthenticated
        | PlatformErrorCode::InvalidArgument
        | PlatformErrorCode::NotFound
        | PlatformErrorCode::AlreadyExists
        | PlatformErrorCode::IncompatibleContract
        | PlatformErrorCode::CorruptArtifact => "rejected",
        _ => "platform_failed",
    }
}

fn policy(value: &control::Policy, context: &Context, tenant: &str) -> Result<(), RpcFailure> {
    if !valid_id(&value.id)
        || context
            .record_id
            .as_ref()
            .is_some_and(|identity| identity != &value.id)
        || value
            .metadata
            .as_ref()
            .and_then(|metadata| metadata.tenant.as_deref())
            .is_some_and(|value| value != tenant)
    {
        return Err(invalid());
    }
    if context
        .record_kind
        .is_some_and(|kind| kind != value.record_kind)
    {
        return Err(RpcFailure::unsupported(
            "policy.record_kind",
            &value.record_kind.to_string(),
        ));
    }
    Ok(())
}

fn page(
    value: Option<&control::PageResponse>,
    count: usize,
    context: &Context,
) -> Result<(), RpcFailure> {
    let page = value.ok_or_else(invalid)?;
    if count > context.page_size
        || page
            .next_page_token
            .as_ref()
            .is_some_and(|token| token.is_empty() || token.len() > context.token_bytes)
    {
        return Err(invalid());
    }
    Ok(())
}

impl ResponseProfile for control::GetPolicyResponse {
    fn validate(&self, context: &Context, tenant: &str) -> Result<bool, RpcFailure> {
        if let Some(value) = &self.policy {
            policy(value, context, tenant)?;
        }
        Ok(true)
    }
}

impl ResponseProfile for control::ListPoliciesResponse {
    fn validate(&self, context: &Context, tenant: &str) -> Result<bool, RpcFailure> {
        page(self.page.as_ref(), self.policies.len(), context)?;
        for value in &self.policies {
            policy(value, context, tenant)?;
        }
        Ok(true)
    }
}

impl ResponseProfile for control::ListCapabilitiesResponse {
    fn validate(&self, context: &Context, _tenant: &str) -> Result<bool, RpcFailure> {
        page(self.page.as_ref(), self.capabilities.len(), context)?;
        if let Some(revision) = &self.revision {
            if context.deployment_id.as_deref() != Some(&revision.deployment_id) {
                return Err(invalid());
            }
            publication(revision.publication_id.as_deref())?;
        }
        Ok(true)
    }
}

impl ResponseProfile for control::ApplyPolicyResponse {
    fn validate(&self, context: &Context, tenant: &str) -> Result<bool, RpcFailure> {
        let document = self.policy.as_ref().ok_or_else(invalid)?;
        let receipt = self.receipt.as_ref().ok_or_else(invalid)?;
        policy(document, context, tenant)?;
        if context.recovery.operation_id.as_deref() != Some(&receipt.operation_id)
            || receipt.id != document.id
            || receipt.tenant != tenant
            || receipt.record_kind != document.record_kind
            || receipt.generation != document.generation
            || receipt.content_digest != document.content_digest
            || receipt.revoked != document.revoked
        {
            return Err(invalid());
        }
        Ok(true)
    }
}

impl ResponseProfile for control::GetPolicyOperationResponse {
    fn validate(&self, context: &Context, tenant: &str) -> Result<bool, RpcFailure> {
        let Some(receipt) = &self.receipt else {
            return Ok(false);
        };
        if context.recovery.operation_id.as_deref() != Some(&receipt.operation_id)
            || receipt.tenant != tenant
            || !valid_id(&receipt.id)
        {
            return Err(invalid());
        }
        Ok(true)
    }
}
