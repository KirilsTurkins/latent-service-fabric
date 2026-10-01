//! Trusted installed bindings meet the real pinned activation admission seam.
mod admission;
mod policy;
mod selection;
pub use selection::{TransactionInstallation, TransactionSelection};

use super::{authorization, CommandTimeSource, PolicyCallBinding, StateTransactionHost};
use latent_capabilities::namespace::RecoverySelection;
use latent_commit::atomic::{AdmittedCommand, AtomicError, CommandRecord, ResultPolicy};
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
}
impl TransactionAdmissionOwners {
    pub fn new(
        store: Arc<ProtectedStoreOwner>,
        namespaces: Arc<NamespaceCatalog>,
        policy: Arc<PolicyStore>,
        command: CommandAdmissionSource,
    ) -> Result<Self, PlatformError> {
        if !command.uses_store(&store) {
            return Err(authorization::denied());
        }
        Ok(Self {
            store,
            namespaces,
            policy,
            effects: command.effect_authority(),
            time: Arc::new(super::command_role::CommandClock(command.clone())),
            command,
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
    Existing(CommandRecord),
    /// Admission flushed Pending but no host was published. This original
    /// affine claim still owns cleanup/recovery; no second guest is admitted.
    Pending(super::PendingCommandAdmission),
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
        })
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
