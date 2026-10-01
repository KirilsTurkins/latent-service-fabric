use super::{
    authorization::StateAuthorization, CommandHostSelection, CommandTimeSource, OwnedSession,
    Physical, StateTransactionHost,
};
use latent_core::{transaction_contract::Precondition, ActivationId, BudgetDimension};
use latent_effects::authority::EffectAuthorityOwner;
use latent_executor::transaction::StateFailure;
use latent_state::{
    embedded::ReadView,
    protected_store::{ProtectedStoreError, ProtectedStoreOwner},
    session::{StateError, StateScope, StateSession},
};
use std::sync::{
    atomic::{AtomicBool, AtomicU8, Ordering},
    Arc, Mutex,
};

impl StateTransactionHost {
    #[allow(
        clippy::too_many_arguments,
        clippy::too_many_lines,
        reason = "Keep every native error exit beside its retirement or quarantine proof"
    )]
    pub async fn open(
        store: Arc<ProtectedStoreOwner>,
        authorization: Arc<StateAuthorization>,
        activation: ActivationId,
        scope: StateScope,
        mut command: Option<CommandHostSelection>,
        effects: Option<EffectAuthorityOwner>,
        time: Arc<dyn CommandTimeSource>,
        conditions: Vec<Precondition>,
    ) -> Result<Arc<Self>, StateFailure> {
        let configured = super::initialization::configuration(
            &authorization,
            &activation,
            &scope,
            command.as_ref(),
            &conditions,
        );
        let (mode, limits, retained_bytes) = match configured {
            Ok(configuration) => configuration,
            Err(error) => {
                retire_unstarted(command.take());
                return Err(error);
            }
        };
        let budget = &authorization.budget;
        let memory = if let Ok(memory) = budget.reserve_host_memory(retained_bytes) {
            Arc::new(memory)
        } else {
            retire_unstarted(command.take());
            return Err(StateFailure::ReadBudgetExhausted);
        };
        let retained_memory = Arc::clone(&memory);
        let operation = match store.reserve_operation() {
            Ok(operation) => operation,
            Err(error) => {
                retire_unstarted(command.take());
                return Err(protected_error(error));
            }
        };
        let opening = match store.open_view() {
            Ok(opening) => opening,
            Err(error) => {
                operation.retire().await;
                retire_unstarted(command.take());
                return Err(protected_error(error));
            }
        };
        let opened = opening
            .await
            .map_err(|_| StateFailure::Unavailable)?
            .map_err(protected_error);
        let mut view = match opened {
            Ok(view) => view,
            Err(error) => {
                operation.retire().await;
                return Err(error);
            }
        };
        let witness = view.retirement_witness().ok_or(StateFailure::Unavailable)?;
        let auth = Arc::clone(&authorization);
        let selected = scope.clone();
        let job = store.with_view(view, retained_bytes, move |view| {
            super::initialization::initialize(
                view,
                selected,
                limits,
                mode,
                &conditions,
                &auth,
                memory,
            )
        });
        let result = match job {
            Ok(job) => job.await.map_err(|_| StateFailure::Unavailable),
            Err(error) => Err(protected_error(error)),
        };
        let owned = match result {
            Ok((view, Ok(Ok(payload)))) => OwnedSession { view, payload },
            Ok((view, Ok(Err(error)))) => {
                view.retire().await;
                operation.retire().await;
                retire_unstarted(command.take());
                return Err(error);
            }
            Ok((view, Err(error))) => {
                view.retire().await;
                operation.retire().await;
                retire_unstarted(command.take());
                return Err(protected_error(error));
            }
            Err(error) => {
                operation.retire().await;
                // A rejected/detached job may already own native retirement.
                // Its actual issued witness, never the waiter's failure, is
                // the only permission to retire this physical attempt guard.
                if witness.has_retired() {
                    retire_unstarted(command.take());
                }
                return Err(error);
            }
        };
        let (context, info, work) = command.map_or((None, None, None), |mut command| {
            let version = authorization.namespace.record().version;
            let mut bytes = Vec::with_capacity(16);
            bytes.extend_from_slice(&version.incarnation.to_le_bytes());
            bytes.extend_from_slice(&version.generation.to_le_bytes());
            command.info.view = latent_executor::transaction::ViewIdentity {
                namespace: scope.namespace.0.clone(),
                incarnation: scope.incarnation.to_string(),
                version: bytes,
                state_schema: scope.state_schema.clone(),
            };
            (
                Some(command.context),
                Some(command.info),
                Some(command.work),
            )
        });
        Ok(Arc::new(Self {
            activation,
            mode,
            scope,
            authorization,
            store,
            session: Mutex::new(Some(owned)),
            witness,
            physical: Mutex::new(Some(Physical { operation, work })),
            acquired: AtomicU8::new(0),
            released: AtomicBool::new(false),
            guest_closed: AtomicBool::new(false),
            technical_fault: AtomicBool::new(false),
            context,
            command: info,
            effects,
            time,
            retained_bytes,
            memory: retained_memory,
        }))
    }

    pub(super) async fn access<T: Send + 'static>(
        &self,
        operation: &'static str,
        input_bytes: usize,
        output_bytes: usize,
        call: impl FnOnce(&mut StateSession, &ReadView) -> Result<T, StateError> + Send + 'static,
    ) -> Result<T, StateFailure> {
        self.check_live()?;
        self.authorization
            .authorize(operation, input_bytes, output_bytes, || Ok(()))
            .map_err(|_| StateFailure::PermissionDenied)?;
        let owned = self
            .session
            .lock()
            .map_err(|_| StateFailure::Unavailable)?
            .take()
            .ok_or(StateFailure::Unavailable)?;
        let auth = Arc::clone(&self.authorization);
        let mut payload = owned.payload;
        let job = self
            .store
            .with_view(
                owned.view,
                self.retained_bytes + output_bytes as u64,
                move |view| {
                    if auth
                        .authorize(operation, input_bytes, output_bytes, || Ok(()))
                        .is_err()
                    {
                        return Ok((payload, Err(StateFailure::PermissionDenied), Ok(())));
                    }
                    let before = payload.session.charged_bytes();
                    let result = call(&mut payload.session, view);
                    if let Err(error) = &result {
                        if let Some(fatal) = error.storage_error() {
                            return Err(fatal);
                        }
                    }
                    let charged = charge(&auth.budget, before, payload.session.charged_bytes());
                    Ok((
                        payload,
                        result.map_err(|error| {
                            state_error(error, matches!(operation, "put" | "delete"))
                        }),
                        charged,
                    ))
                },
            )
            .map_err(protected_error)?;
        let (view, result) = job.await.map_err(|_| StateFailure::Unavailable)?;
        let (payload, result, charged) = result.map_err(protected_error)?;
        let replaced = self
            .session
            .lock()
            .map_err(|_| StateFailure::Unavailable)?
            .replace(OwnedSession { view, payload });
        if replaced.is_some() {
            self.technical_fault.store(true, Ordering::Release);
            return Err(StateFailure::Unavailable);
        }
        if let Err(error) = charged {
            self.technical_fault.store(true, Ordering::Release);
            return Err(error);
        }
        self.authorization
            .authorize(operation, 0, 0, || Ok(()))
            .map_err(|_| StateFailure::PermissionDenied)?;
        result
    }
}

fn retire_unstarted(command: Option<CommandHostSelection>) {
    if let Some(command) = command {
        command.work.retire();
    }
}
pub(super) fn charge(
    budget: &latent_core::ActivationBudget,
    before: (usize, usize),
    after: (usize, usize),
) -> Result<(), StateFailure> {
    let mut charges = Vec::with_capacity(2);
    if after.0 > before.0 {
        charges.push((BudgetDimension::StateReadBytes, (after.0 - before.0) as u64));
    }
    if after.1 > before.1 {
        charges.push((
            BudgetDimension::StateWriteBytes,
            (after.1 - before.1) as u64,
        ));
    }
    if charges.is_empty() {
        return Ok(());
    }
    budget
        .reserve_group(&charges)
        .and_then(latent_core::BudgetReservationGroup::commit)
        .map_err(|error| match error {
            latent_core::BudgetError::Exhausted {
                dimension: BudgetDimension::StateWriteBytes,
                ..
            } => StateFailure::WriteBudgetExhausted,
            latent_core::BudgetError::Exhausted {
                dimension: BudgetDimension::StateReadBytes,
                ..
            } => StateFailure::ReadBudgetExhausted,
            latent_core::BudgetError::DeadlineExceeded { .. } => StateFailure::Cancelled,
            _ => StateFailure::Unavailable,
        })
}
pub(super) fn protected_error(_: ProtectedStoreError) -> StateFailure {
    StateFailure::Unavailable
}
pub(super) fn state_error(error: StateError, write: bool) -> StateFailure {
    match error {
        StateError::Invalid => StateFailure::InvalidValue,
        StateError::InvalidCursor => StateFailure::InvalidCursor,
        StateError::Conflict => StateFailure::Conflict,
        StateError::PermissionDenied => StateFailure::PermissionDenied,
        StateError::Closed => StateFailure::HandleClosed,
        StateError::Expired => StateFailure::Cancelled,
        StateError::Limit => {
            if write {
                StateFailure::WriteBudgetExhausted
            } else {
                StateFailure::ReadBudgetExhausted
            }
        }
        StateError::UnsupportedFormat => StateFailure::UnsupportedVersion,
        StateError::Corrupt | StateError::Unavailable | StateError::RecoveryRequired => {
            StateFailure::Unavailable
        }
    }
}
