use std::sync::{
    atomic::{AtomicU8, Ordering},
    Arc,
};

use latent_core::{ActivationId, PlatformError};
use latent_policy::capability::{PolicyStore, SealedPolicyDecision};
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
impl CommitCancellation {
    /// True means cancellation won before commit I/O acceptance. False means
    /// cancellation was already requested or the commit fence already accepted;
    /// neither branch is a durable outcome or permission to refund charges.
    #[must_use]
    pub fn request(&self) -> bool {
        self.gate
            .0
            .compare_exchange(OPEN, CANCELLED, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
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

impl CommitIoAcceptance<'_> {
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
        self.accept_with_final(revalidate, || Ok(()))
    }

    /// Retain the effect fence through namespace acceptance and the original
    /// activation cancellation CAS. Both callbacks are bounded metadata work;
    /// they must do no I/O or recursively acquire an ownership lock.
    pub fn accept_with_final<R>(
        self,
        revalidate: impl FnOnce() -> Result<R, NamespaceError>,
        accept_original: impl FnOnce() -> Result<(), NamespaceError>,
    ) -> Result<(), NamespaceError> {
        let mut revalidate = Some(revalidate);
        let mut accept_original = Some(accept_original);
        let mut detailed = None;
        let result = self.authority.with_operation(
            self.store,
            self.operation,
            self.namespace,
            "commit",
            || {
                let guard = match revalidate.take().ok_or_else(denied)?() {
                    Ok(guard) => guard,
                    Err(error) => {
                        detailed = Some(error);
                        return Err(denied());
                    }
                };
                let result = self.authority.gate.accept().and_then(|()| {
                    accept_original.take().ok_or_else(denied)?().map_err(|_| denied())
                });
                drop(guard);
                result
            },
        );
        result.map_err(|_| detailed.unwrap_or(NamespaceError::PermissionDenied))
    }
}
