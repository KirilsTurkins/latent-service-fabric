//! Namespace/current-result authority built on the existing policy intersection
//! and publication owner. Storage, guest execution and budget reservation remain
//! with their actual owners; this module neither opens files nor dispatches I/O.

mod control;
mod gate;
mod page;
mod scope;
#[cfg(test)]
mod tests;

pub use control::{
    NamespaceControl, NamespaceControlFence, NamespaceControlRequest, PreparedNamespaceControl,
};
pub use gate::{AcceptedCommit, CommitCancellation, CommitIoAcceptance};
pub use page::ScopedPage;
pub use scope::{CallerScope, RecoverySelection};

use latent_core::{ActivationId, PlatformError, PlatformErrorCode, TenantId};
use latent_policy::capability::{
    CapabilityCeiling, EvaluationInput, OwnedPolicyDecision, PolicyStore, RecoveryScopeKind,
    ResourceTarget, SealedPolicyDecision,
};
use latent_state::{
    embedded::AtomicBatch,
    namespace::{catalog::NamespaceRead, NamespaceStatus, NamespaceVersion},
};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

pub const STATE_CONTRACT: &str = "latent:state/key-value@0.2.0";
pub const INTENT_CONTRACT: &str = "latent:intents/staging@0.1.0";

/// Bounded durable ownership projection. This is not a credential or grant and
/// cannot construct `NamespaceAuthority` or bypass current result authorization.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResultOwnership {
    pub tenant: TenantId,
    pub namespace: String,
    pub incarnation: u64,
    pub entity: Option<String>,
    pub caller: CallerScope,
    pub result_policy: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Mode {
    Command,
    Query,
    Inspection,
}

/// Sealed activation authority. The original borrowed decision preserves exact
/// publication and policy generations; public copied descriptors cannot revive
/// it after current policy/publication revocation or namespace reincarnation.
pub struct NamespaceAuthority {
    initial: OwnedPolicyDecision,
    ownership: ResultOwnership,
    publication: String,
    version: NamespaceVersion,
    activation: ActivationId,
    mode: Mode,
    ceiling: CapabilityCeiling,
    deadline: Instant,
    gate: Arc<gate::Gate>,
    selection: RecoverySelection,
    lifecycle: latent_state::namespace::lifecycle::NamespaceLifecycleHandle,
}

/// Trusted activation/binding facts, without permission or storage ownership.
pub struct NamespaceAdmission<'a> {
    pub activation: ActivationId,
    pub deadline: Instant,
    pub recovery: &'a RecoverySelection,
    pub state_schema: &'a str,
}

impl NamespaceAuthority {
    /// The decision comes from the existing policy owner; the row comes from a
    /// coherent engine snapshot. `selection` is descriptive trusted binding
    /// configuration and is recomputed against the authenticated principal.
    pub fn seal(
        store: &PolicyStore,
        initial: &SealedPolicyDecision<'_>,
        namespace: &NamespaceRead,
        admission: NamespaceAdmission<'_>,
        lifecycle: latent_state::namespace::lifecycle::NamespaceLifecycleHandle,
    ) -> Result<Self, PlatformError> {
        Self::seal_retained(
            store,
            store.retain_decision(initial)?,
            namespace,
            admission,
            lifecycle,
        )
    }

    /// Seal against the coherent row observed after durable admission while
    /// consuming the exact originally retained policy/publication decision.
    /// Generation observation may advance; caller scope, authority and original
    /// deadline cannot be refreshed. This leaves final commit acceptance open.
    pub fn seal_retained(
        store: &PolicyStore,
        initial: OwnedPolicyDecision,
        namespace: &NamespaceRead,
        admission: NamespaceAdmission<'_>,
        lifecycle: latent_state::namespace::lifecycle::NamespaceLifecycleHandle,
    ) -> Result<Self, PlatformError> {
        let NamespaceAdmission {
            activation,
            deadline,
            recovery: selection,
            state_schema,
        } = admission;
        identity(&activation.0)?;
        if deadline <= Instant::now() {
            return Err(denied());
        }
        let mut captured = None;
        store.with_retained_decision(&initial, &mut |actual, ceiling| {
            let record = namespace.record();
            let ResourceTarget::State {
                namespace: id,
                incarnation,
                entity,
                recovery_kind,
                recovery_scope,
                result_policy,
            } = actual.resource
            else {
                return Err(denied());
            };
            let mode = match (actual.capability, actual.operation) {
                (STATE_CONTRACT, "acquire-command") => Mode::Command,
                (STATE_CONTRACT, "acquire-query") => Mode::Query,
                (
                    STATE_CONTRACT,
                    "read-result" | "inspect-effect" | "cancel-command" | "namespace-inspect",
                ) => Mode::Inspection,
                _ => return Err(denied()),
            };
            let caller = CallerScope::derive(actual.principal, selection)?;
            if actual.principal.tenant.as_ref() != Some(&record.tenant)
                || record.state_schema != state_schema
                || id != record.id.0
                || incarnation != record.version.incarnation
                || caller.kind != recovery_kind
                || caller.scope != recovery_scope
                || record.status == NamespaceStatus::Tombstone
                || (mode == Mode::Command && record.status != NamespaceStatus::Active)
            {
                return Err(denied());
            }
            lifecycle
                .with_current(namespace, mode == Mode::Command, || Ok(()))
                .map_err(|_| denied())?;
            captured = Some((
                ResultOwnership {
                    tenant: record.tenant.clone(),
                    namespace: id.into(),
                    incarnation,
                    entity: entity.map(str::to_owned),
                    caller,
                    result_policy: result_policy.into(),
                },
                actual.publication.to_owned(),
                mode,
                ceiling,
            ));
            Ok(())
        })?;
        let (ownership, publication, mode, ceiling) = captured.ok_or_else(denied)?;
        let deadline =
            deadline.min(Instant::now() + Duration::from_millis(ceiling.wall_time_millis));
        Ok(Self {
            initial,
            ownership,
            publication,
            version: namespace.record().version,
            activation,
            mode,
            ceiling,
            deadline,
            gate: gate::Gate::new(),
            selection: selection.clone(),
            lifecycle,
        })
    }

    /// Descriptive sealed activation identity; it creates no budget or access.
    #[must_use]
    pub const fn activation_id(&self) -> &ActivationId {
        &self.activation
    }

    /// Original admitted deadline narrowed by the original policy ceiling.
    /// Reading it never extends timing or creates a new execution reservation.
    #[must_use]
    pub const fn deadline(&self) -> Instant {
        self.deadline
    }

    #[must_use]
    pub fn ownership(&self) -> &ResultOwnership {
        &self.ownership
    }
    #[must_use]
    pub fn version(&self) -> NamespaceVersion {
        self.version
    }
    /// Descriptive intersected cap. The original activation ledger must reserve
    /// and charge real operations/bytes; this getter creates no budget owner.
    #[must_use]
    pub fn ceiling(&self) -> CapabilityCeiling {
        self.ceiling
    }
    /// The transaction/audit owner must honor this captured requirement and any
    /// stricter fresh operation requirement. This getter allocates no audit slot.
    #[must_use]
    pub const fn requires_audit(&self) -> bool {
        self.initial.requires_audit()
    }
    #[must_use]
    pub fn cancellation(&self) -> CommitCancellation {
        CommitCancellation {
            gate: Arc::clone(&self.gate),
        }
    }

    /// Short no-I/O currentness boundary for a host-derived operation. Read the
    /// engine outside this callback, then repeat it before exposing result bytes.
    /// Final writes additionally retain the exact namespace row CAS in the batch.
    pub fn with_operation(
        &self,
        store: &PolicyStore,
        operation: &SealedPolicyDecision<'_>,
        namespace: &NamespaceRead,
        expected_operation: &str,
        action: impl FnOnce() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.with_operation_fenced(
            store,
            operation,
            namespace,
            expected_operation,
            false,
            action,
        )
    }

    /// Current data permission for the original retained command/query response.
    /// An accepted commit closes execution, while these two read operations
    /// remain fenced by the original publication, scope and deadline. This port
    /// cannot stage work, accept another commit or renew execution authority.
    pub fn with_retained_response(
        &self,
        store: &PolicyStore,
        operation: &SealedPolicyDecision<'_>,
        namespace: &NamespaceRead,
        expected_operation: &str,
        action: impl FnOnce() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if !matches!(expected_operation, "read-result" | "query-info") {
            return Err(denied());
        }
        self.with_operation_fenced(
            store,
            operation,
            namespace,
            expected_operation,
            true,
            action,
        )
    }

    fn with_operation_fenced(
        &self,
        store: &PolicyStore,
        operation: &SealedPolicyDecision<'_>,
        namespace: &NamespaceRead,
        expected_operation: &str,
        retained_response: bool,
        action: impl FnOnce() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let mut action = Some(action);
        store.with_captured(&self.initial, operation, &mut |inputs| {
            if retained_response {
                self.gate.check_retained_response()?;
                self.check_namespace_scope(namespace, expected_operation)?;
            } else {
                self.check_namespace(namespace, expected_operation)?;
            }
            let actual = inputs.get(1).ok_or_else(denied)?;
            self.check_target(actual, expected_operation)?;
            let mut action_error = None;
            let write = matches!(expected_operation, "put" | "delete" | "stage" | "commit");
            let result = self.lifecycle.with_current(namespace, write, || {
                match action
                    .take()
                    .ok_or(latent_state::namespace::NamespaceError::PermissionDenied)?(
                ) {
                    Ok(()) => Ok(()),
                    Err(error) => {
                        action_error = Some(error);
                        Err(latent_state::namespace::NamespaceError::PermissionDenied)
                    }
                }
            });
            if let Some(error) = action_error {
                Err(error)
            } else {
                result.map_err(|_| denied())
            }
        })
    }

    /// Authorize BEFORE result/effect/inbox lookup and AGAIN before response
    /// release. Outcomes cannot substitute for current entity/result permission;
    /// an unavailable guest-only visibility hook fails closed instead of replaying
    /// a mutator. `result_policy` names an approved bounded read-only policy path.
    pub fn with_recovery_access(
        &self,
        store: &PolicyStore,
        operation: &SealedPolicyDecision<'_>,
        namespace: &NamespaceRead,
        expected_operation: &str,
        historical: &ResultOwnership,
        action: impl FnOnce() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if !matches!(
            expected_operation,
            "read-result" | "inspect-effect" | "cancel-command"
        ) || !self.same_result_scope(historical)
        {
            return Err(denied());
        }
        self.with_operation(store, operation, namespace, expected_operation, action)
    }

    pub fn prepare_commit_io<'owner>(
        &'owner self,
        store: &'owner PolicyStore,
        operation: &'owner SealedPolicyDecision<'owner>,
        namespace: &'owner NamespaceRead,
        batch: &AtomicBatch,
    ) -> Result<CommitIoAcceptance<'owner>, PlatformError> {
        let expected = namespace.expectation();
        if self.mode != Mode::Command
            || !batch
                .expectations
                .iter()
                .any(|row| row.key == expected.key && row.value == expected.value)
        {
            return Err(denied());
        }
        Ok(CommitIoAcceptance {
            authority: self,
            store,
            operation,
            namespace,
        })
    }

    fn same_result_scope(&self, historical: &ResultOwnership) -> bool {
        self.ownership.tenant == historical.tenant
            && self.ownership.namespace == historical.namespace
            && self.ownership.incarnation == historical.incarnation
            && self.ownership.entity == historical.entity
            && self.ownership.caller.kind == historical.caller.kind
            && self.ownership.caller.scope == historical.caller.scope
            && self.ownership.result_policy == historical.result_policy
            && (self.ownership.caller.kind == RecoveryScopeKind::Shared
                || (self.ownership.caller.owner_kind == historical.caller.owner_kind
                    && self.ownership.caller.owner_subject == historical.caller.owner_subject))
    }

    fn check_namespace(
        &self,
        namespace: &NamespaceRead,
        operation: &str,
    ) -> Result<(), PlatformError> {
        self.gate.check()?;
        self.check_namespace_scope(namespace, operation)
    }

    fn check_namespace_scope(
        &self,
        namespace: &NamespaceRead,
        operation: &str,
    ) -> Result<(), PlatformError> {
        let current = namespace.record();
        if Instant::now() >= self.deadline
            || current.tenant != self.ownership.tenant
            || current.id.0 != self.ownership.namespace
            || current.version != self.version
            || current.status == NamespaceStatus::Tombstone
            || (matches!(operation, "put" | "delete" | "stage" | "commit")
                && (self.mode != Mode::Command || current.status != NamespaceStatus::Active))
            || (self.mode == Mode::Inspection
                && !matches!(
                    operation,
                    "read-result" | "inspect-effect" | "cancel-command" | "namespace-inspect"
                ))
        {
            return Err(denied());
        }
        if (self.mode == Mode::Query
            && !matches!(
                operation,
                "query-info" | "get-query" | "scan-query" | "describe-page" | "page-next"
            ))
            || (self.mode == Mode::Command
                && matches!(operation, "query-info" | "get-query" | "scan-query"))
        {
            return Err(denied());
        }
        Ok(())
    }

    fn check_target(
        &self,
        actual: &EvaluationInput<'_>,
        operation: &str,
    ) -> Result<(), PlatformError> {
        let ResourceTarget::State {
            namespace,
            incarnation,
            entity,
            recovery_kind,
            recovery_scope,
            result_policy,
        } = actual.resource
        else {
            return Err(denied());
        };
        let contract = if operation == "stage" {
            INTENT_CONTRACT
        } else {
            STATE_CONTRACT
        };
        if actual.capability != contract
            || actual.operation != operation
            || actual.publication != self.publication
            || actual.principal.tenant.as_ref() != Some(&self.ownership.tenant)
            || actual.principal.subject != self.ownership.caller.owner_subject
            || CallerScope::derive(actual.principal, &self.selection)? != self.ownership.caller
            || namespace != self.ownership.namespace
            || incarnation != self.ownership.incarnation
            || entity != self.ownership.entity.as_deref()
            || recovery_kind != self.ownership.caller.kind
            || recovery_scope != self.ownership.caller.scope
            || result_policy != self.ownership.result_policy
        {
            return Err(denied());
        }
        Ok(())
    }
}

fn identity(value: &str) -> Result<(), PlatformError> {
    if value.is_empty()
        || value.len() > 256
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_.:/@".contains(&byte))
    {
        Err(denied())
    } else {
        Ok(())
    }
}
fn denied() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::PermissionDenied,
        message: "namespace-access-denied".into(),
        retryable: false,
        details: vec![],
    }
}
