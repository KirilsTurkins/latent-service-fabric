use std::sync::{
    atomic::{AtomicU8, Ordering},
    Arc,
};

use latent_core::{ActivationId, PlatformError};
use latent_policy::capability::{OwnedPolicyDecision, PolicyStore, SealedPolicyDecision};
use latent_state::namespace::{catalog::NamespaceRead, NamespaceError};

use super::{denied, NamespaceAuthority};

const OPEN: u8 = 0;
const CANCELLED: u8 = 1;
const ACCEPTED: u8 = 2;

pub(super) struct Gate(pub AtomicU8);
impl Gate {
    pub(super) fn new() -> Arc<Self> {
        Arc::new(Self(AtomicU8::new(OPEN)))
    }
    pub(super) fn check(&self) -> Result<(), PlatformError> {
        if self.0.load(Ordering::Acquire) == OPEN {
            Ok(())
        } else {
            Err(denied())
        }
    }
    fn accept(&self) -> Result<(), PlatformError> {
        self.0
            .compare_exchange(OPEN, ACCEPTED, Ordering::AcqRel, Ordering::Acquire)
            .map(|_| ())
            .map_err(|_| denied())
    }
}

/// Cancellation control belongs to the already authenticated command owner.
/// A control RPC must authorize its caller before obtaining/using this handle.
#[derive(Clone)]
pub struct CommitCancellation {
    pub(super) gate: Arc<Gate>,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommitCancellationDisposition {
    Installed,
    AlreadyInstalled,
    CommitIoAccepted,
}
impl CommitCancellation {
    #[must_use]
    pub fn is_same_instance(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.gate, &other.gate)
    }

    /// True means cancellation won before commit I/O acceptance. False means
    /// cancellation was already requested or the commit fence already accepted;
    /// neither branch is a durable outcome or permission to refund charges.
    #[must_use]
    pub fn request(&self) -> bool {
        self.request_disposition() == CommitCancellationDisposition::Installed
    }

    /// This observes logical acceptance only. None of these states proves
    /// durable commitment, abort or physical retirement.
    #[must_use]
    pub fn request_disposition(&self) -> CommitCancellationDisposition {
        match self
            .gate
            .0
            .compare_exchange(OPEN, CANCELLED, Ordering::AcqRel, Ordering::Acquire)
        {
            Ok(_) => CommitCancellationDisposition::Installed,
            Err(CANCELLED) => CommitCancellationDisposition::AlreadyInstalled,
            Err(_) => CommitCancellationDisposition::CommitIoAccepted,
        }
    }
}

/// Affine final acceptance. Constructed only by sealed namespace authority after
/// checking the actual batch keeps the coherent namespace expectation. Invoke
/// `accept` ONLY from `EmbeddedStore::apply_fenced`, after engine staging/OCC and
/// before `tx.commit()`. No policy lock survives this method into physical I/O.
pub struct CommitIoAcceptance<'owner> {
    pub(super) authority: &'owner NamespaceAuthority,
    pub(super) store: &'owner PolicyStore,
    pub(super) operation: &'owner SealedPolicyDecision<'owner>,
    pub(super) namespace: &'owner NamespaceRead,
    pub(super) retained: Vec<&'owner OwnedPolicyDecision>,
}

/// Logical acceptance observation, distinct from the durable command receipt.
/// Dropping it never infers an abort; the storage/activation owner must preserve
/// accepted resources until actual completion or explicit recovery resolution.
pub struct AcceptedCommit {
    activation: ActivationId,
}
impl AcceptedCommit {
    #[must_use]
    pub fn activation_id(&self) -> &ActivationId {
        &self.activation
    }
}

impl<'owner> CommitIoAcceptance<'owner> {
    /// Retain an additional original sealed purpose for final cancellation and
    /// commit acceptance. This metadata adds no grant, budget or namespace.
    pub fn retain_policy(
        mut self,
        original: &'owner OwnedPolicyDecision,
    ) -> Result<Self, PlatformError> {
        if self.retained.len() >= 7 {
            return Err(denied());
        }
        self.retained.push(original);
        Ok(self)
    }

    pub fn accept(self) -> Result<AcceptedCommit, NamespaceError> {
        let activation = self.authority.activation.clone();
        self.accept_with(|| Ok(()))?;
        Ok(AcceptedCommit { activation })
    }

    /// The effect/provider owner returns a bounded read guard held through the
    /// cancellation CAS. Required order is Policy -> Namespace -> `EffectRules`
    /// -> Cancellation. The callback must do no IO, guest work or blocking wait.
    pub fn accept_with<R>(
        self,
        revalidate: impl FnOnce() -> Result<R, NamespaceError>,
    ) -> Result<(), NamespaceError> {
        let mut revalidate = Some(revalidate);
        let mut detailed = None;
        let result = self.authority.with_operation_retained(
            self.store,
            self.operation,
            self.namespace,
            "commit",
            &self.retained,
            || {
                let guard = match revalidate.take().ok_or_else(denied)?() {
                    Ok(guard) => guard,
                    Err(error) => {
                        detailed = Some(error);
                        return Err(denied());
                    }
                };
                let result = self.authority.gate.accept();
                drop(guard);
                result
            },
        );
        result.map_err(|_| detailed.unwrap_or(NamespaceError::PermissionDenied))
    }
}
