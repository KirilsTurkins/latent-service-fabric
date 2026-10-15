//! One current management request may own metadata recovery of its original.
use super::{authorization, CommandCancellationIdentity, StateTransactionHost};
use crate::{cancellation::WeakCancellationOwner, TransactionCommitControl};
use latent_capabilities::namespace::STATE_CONTRACT;
use latent_commit::atomic::{CommandRecord, Outcome};
use latent_core::{
    native_capacity::{NativeCapacityOwner, NativeReservation},
    PlatformError,
};
use latent_policy::capability::{
    EvaluationInput, OwnedPolicyDecision, PolicyStore, ResourceTarget,
};
use latent_state::namespace::catalog::{NamespaceCatalog, NamespaceRead};
use std::{
    sync::{Arc, Mutex},
    time::Instant,
};

/// Trusted installed management ownership; no request descriptor implements it.
/// The retained decision and reservation must be from the original real owners.
pub trait CommandCancellationAuthority: Send + Sync {
    fn policy(&self) -> &PolicyStore;
    fn decision(&self) -> &Arc<OwnedPolicyDecision>;
    fn namespace(&self) -> &NamespaceRead;
    fn namespaces(&self) -> &NamespaceCatalog;
    fn cutoff(&self) -> Result<Instant, PlatformError>;
    fn uses_native_capacity(&self, owner: &NativeCapacityOwner) -> bool;
    fn with_native_until(
        &self,
        cutoff: Instant,
        action: &mut dyn FnMut(),
    ) -> Result<(), PlatformError>;
    fn with_native_pair_until(
        &self,
        other: &NativeReservation,
        cutoff: Instant,
        action: &mut dyn FnMut(),
    ) -> Result<(), PlatformError>;
}

#[derive(Default)]
pub(crate) struct CancellationAbortSlot(Mutex<Option<Slot>>);
struct Slot {
    identity: Arc<CommandCancellationIdentity>,
    deadline: Instant,
    policy: Arc<PolicyStore>,
    namespaces: Arc<NamespaceCatalog>,
    native: NativeCapacityOwner,
    kind: latent_core::PrincipalKind,
    subject: String,
    service: String,
    accepted: Option<PendingCancellationAbort>,
}

/// Not authorization: only the protected writer's original affine proof may
/// promote this request into metadata authority. It retains no manager/guest.
pub(crate) struct PendingCancellationAbort {
    identity: Arc<CommandCancellationIdentity>,
    authority: Arc<dyn CommandCancellationAuthority>,
    deadline: Instant,
    owner: Option<WeakCancellationOwner>,
    original: Option<crate::activation_manager::OriginalCancellationMetadataFence>,
}
pub(crate) struct CancellationAbortPermit {
    authority: Arc<dyn CommandCancellationAuthority>,
    deadline: Instant,
    original: crate::activation_manager::OriginalCancellationMetadataFence,
}

impl CancellationAbortSlot {
    pub(crate) fn eligible(
        identity: &CommandCancellationIdentity,
        host: &StateTransactionHost,
    ) -> bool {
        if !host
            .authorization
            .budget
            .descendant_snapshot()
            .is_ok_and(|snapshot| snapshot.depth == 0)
            || host.authorization.budget.granted().child_calls != 0
            || host.authorization.budget.granted().outbound_requests != 0
        {
            return false;
        }
        let bytes = identity
            .retained_bytes()
            .and_then(|bytes| bytes.checked_add(prepaid_bytes()))
            .and_then(|bytes| bytes.checked_add(host.authorization.subject().len()))
            .and_then(|bytes| bytes.checked_add(host.authorization.service().len()))
            .and_then(|bytes| bytes.checked_add(128));
        bytes.is_some_and(|bytes| bytes <= super::CANCELLATION_RECORD_BYTES)
    }
    pub(crate) fn bind(
        &self,
        identity: Arc<CommandCancellationIdentity>,
        host: &StateTransactionHost,
        policy: Arc<PolicyStore>,
        namespaces: Arc<NamespaceCatalog>,
        native: NativeCapacityOwner,
    ) -> Result<Option<Arc<CommandCancellationIdentity>>, PlatformError> {
        if !Self::eligible(&identity, host) {
            return Ok(None);
        }
        let bytes = identity
            .retained_bytes()
            .and_then(|bytes| bytes.checked_add(prepaid_bytes()))
            .and_then(|bytes| bytes.checked_add(host.authorization.subject().len()))
            .and_then(|bytes| bytes.checked_add(host.authorization.service().len()))
            .and_then(|bytes| bytes.checked_add(128));
        if bytes.is_none_or(|bytes| bytes > super::CANCELLATION_RECORD_BYTES) {
            return Ok(None);
        }
        let mut slot = self.0.lock().map_err(|_| authorization::denied())?;
        if let Some(prior) = &*slot {
            if !prior.identity.same_identity(&identity) {
                return Err(authorization::denied());
            }
            return Ok(Some(prior.identity.clone()));
        }
        *slot = Some(Slot {
            identity: identity.clone(),
            deadline: host.authorization.authority.deadline().min(
                host.authorization
                    .budget
                    .deadline()
                    .monotonic()
                    .ok_or_else(authorization::denied)?,
            ),
            policy,
            namespaces,
            native,
            kind: host.authorization.principal_kind(),
            subject: host.authorization.subject().into(),
            service: host.authorization.service().into(),
            accepted: None,
        });
        Ok(Some(identity))
    }

    pub(crate) fn with_authorized_request<T>(
        &self,
        record: &CommandRecord,
        authority: &Arc<dyn CommandCancellationAuthority>,
        action: impl FnOnce(Option<PendingCancellationAbort>) -> Result<T, PlatformError>,
    ) -> Result<T, PlatformError> {
        // Ineligible metadata never prevents the existing authorized request.
        let requested = authority.cutoff()?;
        let candidate = {
            let guard = self.0.lock().map_err(|_| authorization::denied())?;
            guard.as_ref().and_then(|slot| {
                let deadline = slot.deadline.min(requested);
                (Instant::now() < deadline
                    && std::ptr::eq(authority.policy(), slot.policy.as_ref())
                    && std::ptr::eq(authority.namespaces(), slot.namespaces.as_ref())
                    && authority.uses_native_capacity(&slot.native)
                    && slot.identity.matches_identity(record))
                .then(|| {
                    (
                        slot.identity.clone(),
                        deadline,
                        slot.kind,
                        slot.subject.clone(),
                        slot.service.clone(),
                    )
                })
            })
        };
        with_request_authority(record, authority.as_ref(), |input| {
            let request = candidate
                .filter(|(_, _, kind, subject, service)| {
                    input.principal.kind == *kind
                        && input.principal.subject == *subject
                        && input.service == *service
                })
                .map(|(identity, deadline, _, _, _)| PendingCancellationAbort {
                    identity,
                    authority: authority.clone(),
                    deadline,
                    owner: None,
                    original: None,
                });
            action(request)
        })
    }

    pub(crate) fn retained_scope_bytes(&self) -> usize {
        self.0
            .lock()
            .ok()
            .and_then(|slot| {
                slot.as_ref()
                    .map(|slot| slot.subject.capacity() + slot.service.capacity())
            })
            .unwrap_or(0)
    }

    pub(crate) fn install(
        &self,
        mut request: PendingCancellationAbort,
        owner: WeakCancellationOwner,
    ) -> Result<(), PlatformError> {
        let mut slot = self.0.lock().map_err(|_| authorization::denied())?;
        let slot = slot.as_mut().ok_or_else(authorization::denied)?;
        if slot.accepted.is_some() || !slot.identity.same_identity(&request.identity) {
            return Err(authorization::denied());
        }
        request.owner = Some(owner);
        slot.accepted = Some(request);
        Ok(())
    }

    pub(crate) fn take_original(
        &self,
        command: &CommandRecord,
        host: &StateTransactionHost,
        control: &TransactionCommitControl,
    ) -> Option<PendingCancellationAbort> {
        // Cancellation is monotonic; never enter Lifecycle while holding Slot.
        if !control.matches(&host.activation, &host.authorization.budget) {
            return None;
        }
        let original = control.cancelled_metadata_fence()?;
        let mut guard = self.0.lock().ok()?;
        let slot = guard.as_mut()?;
        if !slot.identity.matches_record(command, host.store.as_ref())
            || !slot
                .accepted
                .as_ref()?
                .owner
                .as_ref()
                .is_some_and(|owner| control.matches_cancellation_owner(owner))
        {
            return None;
        }
        let mut request = slot.accepted.take()?;
        request.original = Some(original);
        Some(request)
    }
}

pub(crate) fn with_request_authority<T>(
    record: &CommandRecord,
    authority: &dyn CommandCancellationAuthority,
    action: impl FnOnce(&EvaluationInput<'_>) -> Result<T, PlatformError>,
) -> Result<T, PlatformError> {
    let deadline = authority.cutoff()?;
    if Instant::now() >= deadline {
        return Err(authorization::denied());
    }
    let lifecycle = authority
        .namespaces()
        .lifecycle()
        .pin(authority.namespace())
        .map_err(|_| authorization::denied())?;
    let mut action = Some(action);
    let mut result = None;
    authority
        .policy()
        .with_retained_decision(authority.decision(), &mut |input, _| {
            request_scope(input, record, authority.namespace())?;
            let mut error = None;
            lifecycle
                .with_current(authority.namespace(), false, || {
                    match authority.with_native_until(deadline, &mut || {
                        result = Some(
                            action
                                .take()
                                .ok_or_else(authorization::denied)
                                .and_then(|action| action(input)),
                        );
                    }) {
                        Ok(()) => Ok(()),
                        Err(failure) => {
                            error = Some(failure);
                            Err(latent_state::namespace::NamespaceError::PermissionDenied)
                        }
                    }
                })
                .map_err(|_| error.unwrap_or_else(authorization::denied))?;
            Ok(())
        })?;
    result.ok_or_else(authorization::denied)?
}

impl PendingCancellationAbort {
    pub(crate) fn promote(
        self,
        original: &CommandRecord,
        aborted: &CommandRecord,
    ) -> Result<Arc<CancellationAbortPermit>, PlatformError> {
        // Called ONLY after the writer consumes the original affine RetiredAttempt.
        let original_fence = self.original.ok_or_else(authorization::denied)?;
        // Observe the actual covered clock before entering any role/policy/native
        // fence. Final acceptance uses the role's already-fenced time instead.
        let deadline = self.deadline.min(self.authority.cutoff()?);
        if !self.identity.matches_identity(original)
            || !self.identity.matches_identity(aborted)
            || original.outcome() != Outcome::Pending
            || aborted.outcome() != Outcome::Aborted
            || aborted.abort_proof().is_none()
            || Instant::now() >= deadline
            || !original_fence.is_current()
        {
            return Err(authorization::denied());
        }
        Ok(Arc::new(CancellationAbortPermit {
            authority: self.authority,
            deadline,
            original: original_fence,
        }))
    }
}
impl CancellationAbortPermit {
    pub(crate) fn decision(&self) -> Arc<OwnedPolicyDecision> {
        self.authority.decision().clone()
    }
    pub(crate) fn cutoff(&self) -> Result<Instant, PlatformError> {
        let cutoff = self.deadline;
        if Instant::now() >= cutoff || !self.original.is_current() {
            return Err(authorization::denied());
        }
        Ok(cutoff)
    }
    pub(crate) fn with_native_pair(
        &self,
        other: &NativeReservation,
        action: &mut dyn FnMut(),
    ) -> Result<(), PlatformError> {
        self.with_native_pair_until(other, self.deadline, action)
    }
    pub(crate) fn with_native_pair_until(
        &self,
        other: &NativeReservation,
        cutoff: Instant,
        action: &mut dyn FnMut(),
    ) -> Result<(), PlatformError> {
        let mut accepted = false;
        self.authority
            .with_native_pair_until(other, cutoff.min(self.cutoff()?), &mut || {
                if self.original.is_current() {
                    accepted = true;
                    action();
                }
            })?;
        if accepted {
            Ok(())
        } else {
            Err(authorization::denied())
        }
    }
}

fn request_scope(
    input: &EvaluationInput<'_>,
    record: &CommandRecord,
    namespace: &NamespaceRead,
) -> Result<(), PlatformError> {
    let ResourceTarget::State {
        namespace: id,
        incarnation,
        entity,
        recovery_scope,
        result_policy,
        ..
    } = input.resource
    else {
        return Err(authorization::denied());
    };
    if input.capability != STATE_CONTRACT
        || input.operation != "cancel-command"
        || input.publication != record.source().publication
        || input
            .principal
            .tenant
            .as_ref()
            .map(|tenant| tenant.0.as_str())
            != Some(record.key().tenant.as_str())
        || id != record.key().namespace
        || incarnation.to_string() != record.key().incarnation
        || entity != record.key().entity.as_deref()
        || recovery_scope != record.key().recovery_scope
        || result_policy != record.result_read_policy()
        || namespace.record().tenant.0 != record.key().tenant
        || namespace.record().id.0 != record.key().namespace
        || namespace.record().version.incarnation != incarnation
        || namespace.record().state_schema != record.source().state_schema
    {
        return Err(authorization::denied());
    }
    Ok(())
}

pub(crate) fn prepaid_bytes() -> usize {
    std::mem::size_of::<CancellationAbortSlot>()
        + std::mem::size_of::<Slot>()
        + std::mem::size_of::<PendingCancellationAbort>()
        + std::mem::size_of::<CancellationAbortPermit>()
        + 4 * 2 * std::mem::size_of::<usize>()
}
