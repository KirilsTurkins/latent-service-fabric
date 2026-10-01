//! Trusted installed bindings meet the real pinned activation admission seam.
mod admission;
mod completion;
mod policy;
mod selection;
pub use selection::{TransactionInstallation, TransactionSelection};

use super::{
    authorization, CommandTimeSource, PolicyCallBinding, StateTransactionHost, TransactionRetention,
};
use latent_capabilities::namespace::RecoverySelection;
use latent_commit::atomic::{AdmittedCommand, AtomicError, CommandRecord, ResultPolicy};
use latent_core::native_capacity::{NativeCapacityOwner, NativeReservation};
use latent_core::PlatformError;
use latent_effects::authority::EffectAuthorityOwner;
use latent_effects::runtime::CommandAdmissionSource;
use latent_policy::capability::PolicyStore;
use latent_state::{namespace::catalog::NamespaceCatalog, protected_store::ProtectedStoreOwner};
use std::sync::{Arc, Mutex};

pub struct TransactionAdmissionOwners {
    store: Arc<ProtectedStoreOwner>,
    namespaces: Arc<NamespaceCatalog>,
    policy: Arc<PolicyStore>,
    effects: EffectAuthorityOwner,
    time: Arc<dyn CommandTimeSource>,
    command: CommandAdmissionSource,
    native: NativeCapacityOwner,
}
impl TransactionAdmissionOwners {
    /// Prepay the original global slot and finite physical byte envelope before
    /// transport dispatch returns a future or starts the activation manager.
    /// The affine reservation must be transferred into the same admission.
    pub fn reserve_ingress(
        &self,
        encoded_request_bytes: usize,
        deadline: std::time::Instant,
    ) -> Result<NativeReservation, PlatformError> {
        super::capacity::reserve_ingress(&self.native, encoded_request_bytes, deadline)
    }

    pub fn new(
        store: Arc<ProtectedStoreOwner>,
        namespaces: Arc<NamespaceCatalog>,
        policy: Arc<PolicyStore>,
        command: CommandAdmissionSource,
    ) -> Result<Self, PlatformError> {
        let native = command
            .native_capacity()
            .map_err(|_| authorization::denied())?;
        if !command.uses_store(&store) || !store.uses_native_capacity(&native) {
            return Err(authorization::denied());
        }
        Ok(Self {
            store,
            namespaces,
            policy,
            effects: command.effect_authority(),
            time: Arc::new(super::command_role::CommandClock(command.clone())),
            command,
            native,
        })
    }
}

/// Retained by the fixed node completion worker, independently of RPC delivery.
pub enum TransactionAdmissionResult {
    Command {
        claim: AdmittedCommand,
        host: Arc<StateTransactionHost>,
    },
    Query {
        host: Arc<StateTransactionHost>,
    },
    Existing {
        command: CommandRecord,
        retained: Arc<TransactionRetention>,
    },
    /// Admission flushed Pending but no host was published. This original
    /// affine claim still owns cleanup/recovery; no second guest is admitted.
    Pending(super::PendingCommandAdmission),
}

/// Affine native completion retained by the fixed driver. Large guest/result
/// bodies live here, rather than being copied into the activation journal.
pub enum TransactionCompletionResult {
    Command(super::CommandCompletionDisposition),
    Query {
        outcome: latent_activation::ActivationOutcome,
        view: latent_executor::transaction::ViewIdentity,
        retained: Arc<latent_core::HostMemoryReservation>,
        native: Arc<TransactionRetention>,
    },
    Existing {
        command: CommandRecord,
        retained: Arc<TransactionRetention>,
    },
    PendingRetired {
        command: CommandRecord,
        proof: Result<Box<latent_commit::atomic::RetiredAttempt>, AtomicError>,
        retained: Arc<TransactionRetention>,
    },
}
enum State {
    Fresh(Option<TransactionSelection>),
    Pending {
        claim: Option<AdmittedCommand>,
        role: Arc<super::command_role::CommandRole>,
    },
    Ready(Option<TransactionAdmissionResult>),
    Failed,
}
pub struct NativeTransactionAdmission {
    owners: Arc<TransactionAdmissionOwners>,
    installation: Arc<TransactionInstallation>,
    state: Mutex<State>,
    completion: Mutex<Option<TransactionCompletionResult>>,
    response: Mutex<Option<Arc<super::TransactionResponseAuthority>>>,
    retention: Mutex<Option<Arc<TransactionRetention>>>,
    ingress: Mutex<Option<NativeReservation>>,
}
impl NativeTransactionAdmission {
    pub fn new(
        owners: Arc<TransactionAdmissionOwners>,
        installation: Arc<TransactionInstallation>,
        selection: TransactionSelection,
    ) -> Result<Self, PlatformError> {
        selection.validate(&installation)?;
        Ok(Self {
            owners,
            installation,
            state: Mutex::new(State::Fresh(Some(selection))),
            completion: Mutex::new(None),
            response: Mutex::new(None),
            retention: Mutex::new(None),
            ingress: Mutex::new(None),
        })
    }

    /// Consume the transport's already accepted reservation. No second global
    /// slot, byte allowance, or original deadline is created at guest admission.
    pub fn with_ingress_reservation(
        owners: Arc<TransactionAdmissionOwners>,
        installation: Arc<TransactionInstallation>,
        selection: TransactionSelection,
        native: NativeReservation,
    ) -> Result<Self, PlatformError> {
        TransactionRetention::validate_ingress(&owners.native, &native)?;
        let mut admission = Self::new(owners, installation, selection)?;
        admission.ingress = Mutex::new(Some(native));
        Ok(admission)
    }

    fn reserve_retention(
        &self,
        envelope: &latent_activation::ActivationEnvelope,
        budget: &latent_core::ActivationBudget,
    ) -> Result<Arc<TransactionRetention>, PlatformError> {
        let ingress = self
            .ingress
            .lock()
            .map_err(|_| authorization::denied())?
            .take();
        match ingress {
            Some(native) => {
                TransactionRetention::from_ingress(&self.owners.native, native, envelope, budget)
            }
            None => TransactionRetention::reserve(&self.owners.native, envelope, budget),
        }
    }

    /// Called only after the exact activation handle has completed physical
    /// guest cleanup. Taking twice cannot duplicate a command or native view.
    pub fn take_result(&self) -> Result<Option<TransactionAdmissionResult>, PlatformError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| super::authorization::denied())?;
        Ok(match &mut *state {
            State::Ready(result) => result.take(),
            State::Pending { claim, role } => claim.take().map(|claim| {
                TransactionAdmissionResult::Pending(super::PendingCommandAdmission {
                    claim,
                    role: Arc::clone(role),
                })
            }),
            State::Fresh(_) | State::Failed => None,
        })
    }

    pub fn take_completion(&self) -> Result<Option<TransactionCompletionResult>, PlatformError> {
        let completion = self
            .completion
            .lock()
            .map_err(|_| authorization::denied())?
            .take();
        if completion.is_some() {
            let authority = self
                .response
                .lock()
                .map_err(|_| authorization::denied())?
                .take();
            drop(authority);
        }
        Ok(completion)
    }

    /// Transfer the actual terminal result and its original data permission
    /// together. A transport must retain this authority through all body/frames.
    pub fn take_owned_completion(
        &self,
    ) -> Result<Option<super::OwnedTransactionCompletion>, PlatformError> {
        let mut completion = self
            .completion
            .lock()
            .map_err(|_| authorization::denied())?;
        if completion.is_none() {
            return Ok(None);
        }
        let authority = self
            .response
            .lock()
            .map_err(|_| authorization::denied())?
            .take()
            .ok_or_else(authorization::denied)?;
        Ok(completion
            .take()
            .map(|result| super::OwnedTransactionCompletion { result, authority }))
    }

    fn retain_response_authority(
        &self,
        authorization: Arc<super::StateAuthorization>,
        query: bool,
    ) -> Result<(), PlatformError> {
        let retained = self.retained_capacity()?;
        *self
            .response
            .lock()
            .map_err(|_| super::authorization::denied())? = Some(Arc::new(
            super::TransactionResponseAuthority::new(authorization, retained, query),
        ));
        Ok(())
    }

    fn retained_capacity(&self) -> Result<Arc<TransactionRetention>, PlatformError> {
        self.retention
            .lock()
            .map_err(|_| authorization::denied())?
            .as_ref()
            .cloned()
            .ok_or_else(authorization::denied)
    }
}

fn error(code: latent_core::PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}
fn atomic(error: AtomicError) -> PlatformError {
    use latent_core::PlatformErrorCode as Code;
    let code = match error {
        AtomicError::Conflict => Code::StateConflict,
        AtomicError::PermissionDenied => Code::PermissionDenied,
        AtomicError::Limit => Code::ResourceExhausted,
        AtomicError::Invalid | AtomicError::UnsupportedFormat => Code::InvalidArgument,
        _ => Code::Unavailable,
    };
    self::error(code, "transaction-admission-failed")
}
