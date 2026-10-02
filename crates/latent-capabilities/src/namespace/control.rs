//! Domain ports for fixed-worker management adapters. Historical outcomes never
//! substitute for current namespace-inspection permission.
use super::{denied, CallerScope, RecoverySelection, STATE_CONTRACT};
use latent_core::{PlatformError, TenantId};
use latent_policy::capability::{
    EvaluationInput, PolicyStore, ResourceTarget, SealedPolicyDecision,
};
mod retained;
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore},
    namespace::{
        catalog::{
            NamespaceCatalog, NamespaceMutation, NamespaceOperationContext,
            NamespaceOperationReceipt, NamespaceRead,
        },
        lifecycle::{NamespaceLifecycleCompletion, NamespaceLifecycleRegistry},
        NamespaceError, NamespaceRecord, NamespaceTransition,
    },
};
pub use retained::{
    PreparedRetainedNamespaceControl, RetainedNamespaceControlFence,
    RetainedNamespaceControlRequest,
};

pub struct NamespaceControl;
#[derive(Clone, Copy)]
pub struct NamespaceControlRequest<'a> {
    pub mutation: &'a NamespaceMutation,
    pub operation_id: &'a str,
    pub inspection: Option<&'a SealedPolicyDecision<'a>>,
}
pub struct PreparedNamespaceControl<'a> {
    batch: AtomicBatch,
    receipt: NamespaceOperationReceipt,
    replay: bool,
    fence: NamespaceControlFence<'a>,
}
impl<'a> PreparedNamespaceControl<'a> {
    #[must_use]
    pub fn into_parts(
        self,
    ) -> (
        AtomicBatch,
        NamespaceOperationReceipt,
        bool,
        NamespaceControlFence<'a>,
    ) {
        (self.batch, self.receipt, self.replay, self.fence)
    }
}
pub struct NamespaceControlFence<'a> {
    store: &'a PolicyStore,
    decision: &'a SealedPolicyDecision<'a>,
    inspection: Option<&'a SealedPolicyDecision<'a>>,
    lifecycle: &'a NamespaceLifecycleRegistry,
    tenant: TenantId,
    caller: CallerScope,
    publication: String,
    namespace: String,
    incarnation: u64,
    result_policy: String,
    operation: &'static str,
    requires_drain: bool,
    before: Option<NamespaceRead>,
    after: NamespaceRecord,
    replay: bool,
}
impl NamespaceControl {
    /// Check before receipt lookup and again before exposing metadata. A
    /// tombstone can be inspected with a current grant for its exact incarnation;
    /// a historical management receipt cannot reveal another caller's operation.
    /// The action is short and performs no IO.
    pub fn with_inspection(
        store: &PolicyStore,
        decision: &SealedPolicyDecision<'_>,
        lifecycle: &NamespaceLifecycleRegistry,
        current: &NamespaceRead,
        receipt: Option<&NamespaceOperationReceipt>,
        action: impl FnOnce() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let mut action = Some(action);
        store.with_current(decision, &mut |actual, _| {
            inspection_actual(
                actual,
                lifecycle,
                current,
                receipt,
                action.take().ok_or_else(denied)?,
            )
        })
    }

    /// Run inside `ProtectedStoreOwner.with_store` on its bounded worker. Snapshot
    /// preparation is outside policy locks; acceptance is in the actual writer.
    pub fn prepare<'a>(
        store: &'a PolicyStore,
        decision: &'a SealedPolicyDecision<'a>,
        catalog: &'a NamespaceCatalog,
        engine: &EmbeddedStore,
        request: NamespaceControlRequest<'a>,
        active_commits: u64,
    ) -> Result<PreparedNamespaceControl<'a>, PlatformError> {
        super::identity(request.operation_id)?;
        let (namespace, incarnation, operation, requires_drain) = mutation_scope(request.mutation);
        let mut facts = None;
        store.with_current(decision, &mut |actual, _| {
            let ResourceTarget::State {
                namespace: target,
                incarnation: actual_inc,
                entity,
                recovery_kind,
                recovery_scope,
                result_policy,
            } = actual.resource
            else {
                return Err(denied());
            };
            let caller = CallerScope::derive(actual.principal, &RecoverySelection::OriginalCaller)?;
            if actual.capability != STATE_CONTRACT
                || actual.operation != operation
                || target != namespace
                || actual_inc != incarnation
                || entity.is_some()
                || recovery_kind != caller.kind
                || recovery_scope != caller.scope
            {
                return Err(denied());
            }
            facts = Some((
                NamespaceOperationContext {
                    tenant: actual.principal.tenant.clone().ok_or_else(denied)?,
                    actor: format!("{}:{}", caller.owner_kind, caller.scope),
                    operation_id: request.operation_id.into(),
                },
                caller,
                actual.publication.to_owned(),
                result_policy.to_owned(),
            ));
            Ok(())
        })?;
        let (context, caller, publication, result_policy) = facts.ok_or_else(denied)?;
        let mut prepared = catalog
            .prepare(engine, context.clone(), request.mutation, active_commits)
            .map_err(platform)?;
        if let Some(current) = &prepared.observed {
            if current.record().version.incarnation != incarnation {
                return Err(denied());
            }
        } else if prepared.replay {
            return Err(denied());
        }
        if prepared.replay {
            let inspection = request.inspection.ok_or_else(denied)?;
            store.with_current_decisions(&[decision, inspection], &mut |inputs| {
                check_inspection(
                    inputs[1],
                    &context.tenant,
                    &caller,
                    &publication,
                    namespace,
                    incarnation,
                    &result_policy,
                )
            })?;
            prepared
                .batch
                .expectations
                .push(prepared.observed.as_ref().ok_or_else(denied)?.expectation());
        }
        let fence = NamespaceControlFence {
            store,
            decision,
            inspection: request.inspection,
            lifecycle: catalog.lifecycle(),
            tenant: context.tenant,
            caller,
            publication,
            namespace: namespace.into(),
            incarnation,
            result_policy,
            operation,
            requires_drain,
            before: prepared.observed,
            after: prepared.receipt.record.clone(),
            replay: prepared.replay,
        };
        Ok(PreparedNamespaceControl {
            batch: prepared.batch,
            receipt: prepared.receipt,
            replay: prepared.replay,
            fence,
        })
    }
}
fn mutation_scope(mutation: &NamespaceMutation) -> (&str, u64, &'static str, bool) {
    match mutation {
        NamespaceMutation::Create { id, .. } => (id.0.as_str(), 1, "namespace-create", false),
        NamespaceMutation::Transition {
            id,
            expected,
            action,
        } => (
            id.0.as_str(),
            expected.incarnation,
            match action {
                NamespaceTransition::Quiesce => "namespace-quiesce",
                NamespaceTransition::Retire => "namespace-retire",
                NamespaceTransition::Destroy => "namespace-destroy",
                NamespaceTransition::Recreate { .. } => "namespace-recreate",
            },
            !matches!(action, NamespaceTransition::Quiesce),
        ),
    }
}
impl NamespaceControlFence<'_> {
    /// Actual live ownership is read under the mutable fence. Resolve a returned
    /// completion from a fresh committed native row. Uncertainty keeps admission
    /// closed until explicit recovery; no guessed count can discard resources.
    pub fn accept(self) -> Result<Option<NamespaceLifecycleCompletion>, NamespaceError> {
        let mut completion = None;
        let mut failure = None;
        let mut callback = |inputs: &[&EvaluationInput<'_>]| {
            self.check(inputs[0])?;
            let result = if self.replay {
                let inspection = *inputs.get(1).ok_or_else(denied)?;
                check_inspection(
                    inspection,
                    &self.tenant,
                    &self.caller,
                    &self.publication,
                    &self.namespace,
                    self.incarnation,
                    &self.result_policy,
                )?;
                self.lifecycle
                    .with_current_record(self.before.as_ref().ok_or_else(denied)?, || Ok(None))
            } else if let Some(before) = &self.before {
                self.lifecycle
                    .begin_transition(before, &self.after, self.requires_drain)
                    .map(Some)
            } else {
                self.lifecycle.begin_create(&self.after).map(Some)
            };
            match result {
                Ok(value) => {
                    completion = value;
                    Ok(())
                }
                Err(error) => {
                    failure = Some(error);
                    Err(denied())
                }
            }
        };
        let result = if self.replay {
            self.store.with_current_decisions(
                &[
                    self.decision,
                    self.inspection.ok_or(NamespaceError::PermissionDenied)?,
                ],
                &mut callback,
            )
        } else {
            self.store
                .with_current_decisions(&[self.decision], &mut callback)
        };
        result.map_err(|_| failure.unwrap_or(NamespaceError::PermissionDenied))?;
        Ok(completion)
    }
    fn check(&self, actual: &EvaluationInput<'_>) -> Result<(), PlatformError> {
        let ResourceTarget::State {
            namespace,
            incarnation,
            entity,
            ..
        } = actual.resource
        else {
            return Err(denied());
        };
        if actual.capability != STATE_CONTRACT
            || actual.operation != self.operation
            || actual.principal.tenant.as_ref() != Some(&self.tenant)
            || CallerScope::derive(actual.principal, &RecoverySelection::OriginalCaller)?
                != self.caller
            || actual.publication != self.publication
            || namespace != self.namespace
            || incarnation != self.incarnation
            || entity.is_some()
        {
            return Err(denied());
        }
        Ok(())
    }
}
fn check_inspection(
    actual: &EvaluationInput<'_>,
    tenant: &TenantId,
    caller: &CallerScope,
    publication: &str,
    namespace: &str,
    incarnation: u64,
    result_policy: &str,
) -> Result<(), PlatformError> {
    let ResourceTarget::State {
        namespace: target,
        incarnation: actual_inc,
        entity,
        recovery_kind,
        recovery_scope,
        result_policy: actual_policy,
    } = actual.resource
    else {
        return Err(denied());
    };
    if actual.capability != STATE_CONTRACT
        || actual.operation != "namespace-inspect"
        || actual.principal.tenant.as_ref() != Some(tenant)
        || CallerScope::derive(actual.principal, &RecoverySelection::OriginalCaller)? != *caller
        || actual.publication != publication
        || target != namespace
        || actual_inc != incarnation
        || entity.is_some()
        || recovery_kind != caller.kind
        || recovery_scope != caller.scope
        || actual_policy != result_policy
    {
        return Err(denied());
    }
    Ok(())
}
fn platform(error: NamespaceError) -> PlatformError {
    let code = match error {
        NamespaceError::Conflict | NamespaceError::InUse => {
            latent_core::PlatformErrorCode::StateConflict
        }
        NamespaceError::Capacity => latent_core::PlatformErrorCode::ResourceExhausted,
        NamespaceError::Unavailable | NamespaceError::RecoveryRequired => {
            latent_core::PlatformErrorCode::Unavailable
        }
        _ => latent_core::PlatformErrorCode::PermissionDenied,
    };
    PlatformError {
        code,
        message: "namespace-operation-rejected".into(),
        retryable: false,
        details: vec![],
    }
}

fn inspection_actual(
    actual: &EvaluationInput<'_>,
    lifecycle: &NamespaceLifecycleRegistry,
    current: &NamespaceRead,
    receipt: Option<&NamespaceOperationReceipt>,
    action: impl FnOnce() -> Result<(), PlatformError>,
) -> Result<(), PlatformError> {
    let mut action = Some(action);
    let ResourceTarget::State {
        namespace,
        incarnation,
        entity,
        recovery_kind,
        recovery_scope,
        ..
    } = actual.resource
    else {
        return Err(denied());
    };
    let caller = CallerScope::derive(actual.principal, &RecoverySelection::OriginalCaller)?;
    let record = current.record();
    if actual.capability != STATE_CONTRACT
        || actual.operation != "namespace-inspect"
        || actual.principal.tenant.as_ref() != Some(&record.tenant)
        || namespace != record.id.0
        || incarnation != record.version.incarnation
        || entity.is_some()
        || recovery_kind != caller.kind
        || recovery_scope != caller.scope
    {
        return Err(denied());
    }
    if receipt.is_some_and(|value| {
        value.context.tenant != record.tenant
            || value.record.tenant != record.tenant
            || value.record.id != record.id
            || value.record.version.incarnation != incarnation
            || value.context.actor != format!("{}:{}", caller.owner_kind, caller.scope)
    }) {
        return Err(denied());
    }
    let mut failure = None;
    let result = lifecycle.with_current_record(current, || {
        action.take().ok_or(NamespaceError::PermissionDenied)?().map_err(|error| {
            failure = Some(error);
            NamespaceError::PermissionDenied
        })
    });
    if let Some(error) = failure {
        Err(error)
    } else {
        result.map_err(platform)
    }
}
