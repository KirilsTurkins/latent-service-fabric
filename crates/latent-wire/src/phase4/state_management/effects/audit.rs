use super::{
    contract, denied, error, input, invalid, state_audit, unsupported, Access, Action,
    AuthenticatedInvocationContext, Error, Outcome, PlatformError, PlatformErrorCode,
};
use latent_audit::{
    AuditControlAction, AuditIdentities, AuditOperationResult, AuditReason, AuditScope,
    AuditStateTarget,
};
use prost::Message;
use sha2::{Digest, Sha256};

pub(super) struct Completion {
    pending: Option<state_audit::Pending>,
    pub finish: Option<state_audit::Finish>,
}
pub(super) async fn begin(
    access: &Access,
    context: &AuthenticatedInvocationContext,
    request: &contract::Request,
) -> Result<state_audit::Pending, PlatformError> {
    if access.inner.services.audit.is_none() {
        return Err(error(
            PlatformErrorCode::Unavailable,
            "effect-management-audit-owner-required",
        ));
    }
    let original = input::original(request)?;
    let (action, bytes) = match request {
        contract::Request::PlanEffectMutation(value) => {
            (AuditControlAction::EffectPlan, value.encode_to_vec())
        }
        contract::Request::MutateState(value) => (
            match access.action {
                Action::Redrive => AuditControlAction::EffectRedrive,
                Action::Reconcile => AuditControlAction::EffectReconcile,
                Action::Terminate => AuditControlAction::EffectTerminate,
            },
            value.encode_to_vec(),
        ),
        contract::Request::GetStateOperationReceipt(value) => (
            AuditControlAction::StateOperationRead,
            value.encode_to_vec(),
        ),
        _ => return Err(unsupported()),
    };
    let binding = &access.namespace.binding;
    let mut hash = Sha256::new();
    hash.update(b"lsf-effect-management-audit-request-v1\0");
    hash.update(bytes);
    state_audit::begin_operation(
        &access.inner,
        context,
        state_audit::OperationAudit {
            scope: AuditScope::Tenant(access.principal.tenant.clone().ok_or_else(denied)?),
            identities: AuditIdentities {
                state: Some(AuditStateTarget {
                    namespace: binding.namespace.0.clone(),
                    incarnation: binding.incarnation,
                    state_schema: binding.state_schema.parse().map_err(|_| invalid())?,
                }),
                publication: Some(binding.publication.id.clone()),
                component: Some(binding.component.clone()),
                ..Default::default()
            },
            operation_id: original.operation_id.clone(),
            action,
            expected: None,
            request_digest: format!(
                "sha256:{:x}",
                latent_core::digest::HexDigest(hash.finalize())
            )
            .parse()
            .map_err(|_| invalid())?,
        },
    )
    .await
}

impl Completion {
    pub fn new(pending: state_audit::Pending) -> Self {
        Self {
            pending: Some(pending),
            finish: None,
        }
    }
    pub fn finish(
        &mut self,
        outcome: &Result<Outcome, Error>,
    ) -> Result<(), latent_state::embedded::StoreError> {
        let pending = self
            .pending
            .take()
            .ok_or(latent_state::embedded::StoreError::Corrupt)?;
        self.finish = Some(finish(pending, outcome.as_ref()));
        Ok(())
    }
}
pub(super) fn finish(
    pending: state_audit::Pending,
    outcome: Result<&Outcome, &Error>,
) -> state_audit::Finish {
    let (result, reason, digest, replayed) = match outcome {
        Ok(Outcome::Plan { plan, replayed }) => (
            AuditOperationResult::Committed,
            AuditReason::Committed,
            plan.digest().ok(),
            *replayed,
        ),
        Ok(Outcome::Mutation { receipt, replayed }) => (
            AuditOperationResult::Committed,
            AuditReason::Committed,
            receipt.digest().ok(),
            *replayed,
        ),
        Ok(Outcome::Receipt(Some(receipt))) => (
            AuditOperationResult::Committed,
            AuditReason::Verified,
            receipt.digest().ok(),
            true,
        ),
        Ok(Outcome::Receipt(None)) => (
            AuditOperationResult::NotStarted,
            AuditReason::Verified,
            None,
            true,
        ),
        Err(
            Error::RecoveryRequired
            | Error::Store(latent_state::embedded::StoreError::CommitUncertain),
        ) => (
            AuditOperationResult::Unknown,
            AuditReason::MutationUncertain,
            None,
            false,
        ),
        Err(_) => (
            AuditOperationResult::Rejected,
            AuditReason::Rejected,
            None,
            false,
        ),
    };
    pending.finish(result, reason, digest, replayed)
}
