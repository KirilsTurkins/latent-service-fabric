//! Fixed-worker controls retain the original policy owner across asynchronous I/O.
use super::{
    check_inspection, denied, inspection_actual, mutation_scope, platform, AtomicBatch,
    CallerScope, EmbeddedStore, EvaluationInput, NamespaceCatalog, NamespaceControl,
    NamespaceError, NamespaceLifecycleCompletion, NamespaceLifecycleRegistry, NamespaceMutation,
    NamespaceOperationContext, NamespaceOperationReceipt, NamespaceRead, NamespaceRecord,
    PlatformError, PolicyStore, RecoverySelection, ResourceTarget, TenantId, STATE_CONTRACT,
};
use latent_policy::capability::OwnedPolicyDecision;

#[derive(Clone, Copy)]
pub struct RetainedNamespaceControlRequest<'a> {
    pub mutation: &'a NamespaceMutation,
    pub operation_id: &'a str,
    pub inspection: Option<&'a OwnedPolicyDecision>,
}
pub struct PreparedRetainedNamespaceControl<'a> {
    batch: AtomicBatch,
    receipt: NamespaceOperationReceipt,
    replay: bool,
    fence: RetainedNamespaceControlFence<'a>,
}
impl<'a> PreparedRetainedNamespaceControl<'a> {
    #[must_use]
    pub fn into_parts(
        self,
    ) -> (
        AtomicBatch,
        NamespaceOperationReceipt,
        bool,
        RetainedNamespaceControlFence<'a>,
    ) {
        (self.batch, self.receipt, self.replay, self.fence)
    }
}
pub struct RetainedNamespaceControlFence<'a> {
    store: &'a PolicyStore,
    decision: &'a OwnedPolicyDecision,
    inspection: Option<&'a OwnedPolicyDecision>,
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
    /// Current approved host action and data inspection under one original
    /// policy -> namespace lifecycle fence. The callback must not perform I/O,
    /// await, flush audit, or recursively enter either owner.
    pub fn with_operation_retained(
        store: &PolicyStore,
        operation: &OwnedPolicyDecision,
        inspection: &OwnedPolicyDecision,
        lifecycle: &NamespaceLifecycleRegistry,
        current: &NamespaceRead,
        expected_operation: &str,
        action: impl FnOnce() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if !matches!(
            expected_operation,
            "effect-plan"
                | "effect-reconcile"
                | "effect-redrive"
                | "effect-terminate"
                | "state-checkpoint"
                | "purge-expired-payload"
        ) {
            return Err(denied());
        }
        let mut action = Some(action);
        store.with_retained_decisions(&[operation, inspection], &mut |inputs| {
            let actual = inputs[0];
            let inspect = inputs[1];
            if actual.capability != STATE_CONTRACT
                || actual.operation != expected_operation
                || actual.principal.subject != inspect.principal.subject
                || actual.principal.kind != inspect.principal.kind
                || actual.principal.tenant != inspect.principal.tenant
                || actual.publication != inspect.publication
                || actual.service != inspect.service
                || actual.resource != inspect.resource
            {
                return Err(denied());
            }
            inspection_actual(
                inspect,
                lifecycle,
                current,
                None,
                action.take().ok_or_else(denied)?,
            )
        })
    }

    /// Current metadata inspection with the original retained policy decision.
    /// This is the same policy -> lifecycle fence as the borrowed control path;
    /// the callback performs no I/O and cannot renew the acquisition.
    pub fn with_inspection_retained(
        store: &PolicyStore,
        decision: &OwnedPolicyDecision,
        lifecycle: &NamespaceLifecycleRegistry,
        current: &NamespaceRead,
        receipt: Option<&NamespaceOperationReceipt>,
        action: impl FnOnce() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let mut action = Some(action);
        store.with_retained_decision(decision, &mut |actual, _| {
            inspection_actual(
                actual,
                lifecycle,
                current,
                receipt,
                action.take().ok_or_else(denied)?,
            )
        })
    }

    /// Preparation runs on the actual protected worker. Final acceptance uses
    /// precisely these retained stamps inside the actual engine writer.
    pub fn prepare_retained<'a>(
        store: &'a PolicyStore,
        decision: &'a OwnedPolicyDecision,
        catalog: &'a NamespaceCatalog,
        engine: &EmbeddedStore,
        request: RetainedNamespaceControlRequest<'a>,
        active_commits: u64,
    ) -> Result<PreparedRetainedNamespaceControl<'a>, PlatformError> {
        super::super::identity(request.operation_id)?;
        let (namespace, incarnation, operation, requires_drain) = mutation_scope(request.mutation);
        let mut facts = None;
        store.with_retained_decision(decision, &mut |actual, _| {
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
        if prepared
            .observed
            .as_ref()
            .is_some_and(|read| read.record().version.incarnation != incarnation)
            || prepared.replay && prepared.observed.is_none()
        {
            return Err(denied());
        }
        if prepared.replay {
            let inspection = request.inspection.ok_or_else(denied)?;
            store.with_retained_decisions(&[decision, inspection], &mut |inputs| {
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
        let fence = RetainedNamespaceControlFence {
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
        Ok(PreparedRetainedNamespaceControl {
            batch: prepared.batch,
            receipt: prepared.receipt,
            replay: prepared.replay,
            fence,
        })
    }
}
impl RetainedNamespaceControlFence<'_> {
    /// Holds current policy/publication through lifecycle acceptance only.
    /// Resolve the returned completion from fresh durable engine bytes after
    /// commit; an uncertain flush leaves the lifecycle closed.
    pub fn accept(self) -> Result<Option<NamespaceLifecycleCompletion>, NamespaceError> {
        self.accept_with(|| Ok(()))
    }
    /// The actual management request gate runs under Policy -> Lifecycle after
    /// validated lifecycle checks. It performs no I/O, audit flush or await.
    pub fn accept_with(
        self,
        revalidate: impl FnOnce() -> Result<(), NamespaceError>,
    ) -> Result<Option<NamespaceLifecycleCompletion>, NamespaceError> {
        let mut revalidate = Some(revalidate);
        let mut completion = None;
        let mut failure = None;
        let mut action = |inputs: &[&EvaluationInput<'_>]| {
            check_control(
                inputs[0],
                &self.tenant,
                &self.caller,
                &self.publication,
                &self.namespace,
                self.incarnation,
                self.operation,
            )?;
            let gate = revalidate.take().ok_or_else(denied)?;
            let result = if self.replay {
                check_inspection(
                    *inputs.get(1).ok_or_else(denied)?,
                    &self.tenant,
                    &self.caller,
                    &self.publication,
                    &self.namespace,
                    self.incarnation,
                    &self.result_policy,
                )?;
                self.lifecycle
                    .with_current_record(self.before.as_ref().ok_or_else(denied)?, || {
                        gate()?;
                        Ok(None)
                    })
            } else if let Some(before) = &self.before {
                self.lifecycle
                    .begin_transition_with(before, &self.after, self.requires_drain, gate)
                    .map(Some)
            } else {
                self.lifecycle
                    .begin_create_with(&self.after, gate)
                    .map(Some)
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
            self.store.with_retained_decisions(
                &[
                    self.decision,
                    self.inspection.ok_or(NamespaceError::PermissionDenied)?,
                ],
                &mut action,
            )
        } else {
            self.store
                .with_retained_decisions(&[self.decision], &mut action)
        };
        result.map_err(|_| failure.unwrap_or(NamespaceError::PermissionDenied))?;
        Ok(completion)
    }
}

fn check_control(
    actual: &EvaluationInput<'_>,
    tenant: &TenantId,
    caller: &CallerScope,
    publication: &str,
    namespace: &str,
    incarnation: u64,
    operation: &str,
) -> Result<(), PlatformError> {
    let ResourceTarget::State {
        namespace: target,
        incarnation: actual_inc,
        entity,
        ..
    } = actual.resource
    else {
        return Err(denied());
    };
    if actual.capability != STATE_CONTRACT
        || actual.operation != operation
        || actual.principal.tenant.as_ref() != Some(tenant)
        || CallerScope::derive(actual.principal, &RecoverySelection::OriginalCaller)? != *caller
        || actual.publication != publication
        || target != namespace
        || actual_inc != incarnation
        || entity.is_some()
    {
        return Err(denied());
    }
    Ok(())
}
