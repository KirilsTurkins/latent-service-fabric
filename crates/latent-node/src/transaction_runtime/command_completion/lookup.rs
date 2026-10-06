use std::{sync::Arc, time::Instant};

use latent_activation::ActivationOutcome;
use latent_commit::atomic::{self, AtomicError, CommandRecord, DurableResult, Outcome};
use latent_core::{
    transaction_contract::CommandKey, BudgetConsumption, HostMemoryReservation, PlatformError,
};
use latent_state::{
    embedded::{ReadView, StoreError},
    namespace::{
        catalog::{NamespaceCatalog, NamespaceRead},
        NamespaceError,
    },
    store_io::StoreIoKind,
};

use super::super::StateAuthorization;
use super::{
    errors, CommandCoordinator, CommandObservation, CommandResultCodec, ResultDeliveryFence,
    TransactionCompletion,
};
use crate::{
    command_waiters::{CommandWaiterDecision, CommandWaiterError},
    CancellationToken,
};

const LOOKUP_BYTES: u64 = 4 * 1024 * 1024;

impl CommandCoordinator {
    pub(super) async fn read_namespace(
        &self,
        auth: &Arc<StateAuthorization>,
    ) -> Result<NamespaceRead, PlatformError> {
        self.read_namespace_observed(auth, None).await
    }

    async fn read_namespace_observed(
        &self,
        auth: &Arc<StateAuthorization>,
        original: Option<CommandRecord>,
    ) -> Result<NamespaceRead, PlatformError> {
        let operation = if auth.authority_mode() == latent_capabilities::namespace::Mode::Inspection
        {
            "read-result"
        } else {
            "acquire-command"
        };
        auth.authorize(operation, 0, 0, || Ok(()))?;
        let auth = Arc::clone(auth);
        let time = Arc::clone(&self.time);
        let job = self
            .store
            .with_store(StoreIoKind::Read, 8192, move |store| {
                let result = (|| {
                    let view = store.snapshot()?;
                    let ownership = auth.authority.ownership();
                    latent_state::recovery::require_namespace_ready(
                        &view,
                        &ownership.tenant,
                        &latent_core::StateNamespaceId(ownership.namespace.clone()),
                        ownership.incarnation,
                    )?;
                    if let Some(record) = &original {
                        super::history::require_result_record(&view, record, &auth)?;
                    }
                    match NamespaceCatalog::read_in(
                        &view,
                        &ownership.tenant,
                        &latent_core::StateNamespaceId(ownership.namespace.clone()),
                    ) {
                        Ok(Some(value)) => Ok(Ok(value)),
                        Ok(None) => Ok(Err(AtomicError::NotFound)),
                        Err(NamespaceError::Corrupt) => Err(StoreError::Corrupt),
                        Err(NamespaceError::UnsupportedFormat) => {
                            Err(StoreError::UnsupportedFormat)
                        }
                        Err(_) => Err(StoreError::Unavailable),
                    }
                })();
                Ok((result, time))
            })
            .map_err(errors::protected)?;
        let (result, _time) = job
            .await
            .map_err(|_| errors::atomic(AtomicError::RecoveryRequired))?
            .map_err(errors::protected)?;
        result.map_err(errors::store)?.map_err(errors::atomic)
    }

    /// Read or join the original command. No branch in this operation creates a
    /// claim, guest, retry, business mutation, abort proof or retained native view.
    pub async fn lookup(
        &self,
        key: CommandKey,
        read: Arc<StateAuthorization>,
        codec: Arc<dyn CommandResultCodec>,
        wait: bool,
        cancellation: Option<CancellationToken>,
    ) -> TransactionCompletion {
        match self
            .lookup_owned(&key, read, codec, wait, cancellation)
            .await
        {
            Ok(value) => value,
            Err(error) => {
                TransactionCompletion::ordinary(failed(error, BudgetConsumption::default()))
            }
        }
    }

    async fn lookup_owned(
        &self,
        key: &CommandKey,
        read: Arc<StateAuthorization>,
        codec: Arc<dyn CommandResultCodec>,
        wait: bool,
        cancellation: Option<CancellationToken>,
    ) -> Result<TransactionCompletion, PlatformError> {
        check_key(&read, key)?;
        let memory = Arc::new(
            read.budget
                .reserve_host_memory(LOOKUP_BYTES)
                .map_err(|_| errors::atomic(AtomicError::Limit))?,
        );
        loop {
            let current = Arc::new(read.rebind_result_read(self.read_namespace(&read).await?)?);
            let (record, result) = self
                .inspect_owned(key.clone(), Arc::clone(&current))
                .await?;
            if record.source().result_format != codec.format() {
                return Err(errors::atomic(AtomicError::PermissionDenied));
            }
            if record.outcome() != Outcome::Pending {
                return self.replay(record, result, &current, &*codec, memory).await;
            }
            let decision = self
                .waiters
                .attach(&record, |record| {
                    current
                        .accepts_record(record)
                        .map_err(|_| AtomicError::PermissionDenied)?;
                    current
                        .authorize("read-result", 0, 0, || Ok(()))
                        .map_err(|_| AtomicError::PermissionDenied)
                })
                .map_err(waiter_error)?;
            match decision {
                CommandWaiterDecision::ReloadDurableState => (),
                CommandWaiterDecision::RecoveryRequired => {
                    return observed(
                        &current,
                        record,
                        CommandObservation::RecoveryRequired,
                        memory,
                        Arc::clone(&self.time),
                    )
                }
                CommandWaiterDecision::Wait(notification) if wait => {
                    let original_deadline =
                        current.budget.deadline().monotonic().ok_or_else(|| {
                            errors::fixed(
                                latent_core::PlatformErrorCode::InvalidArgument,
                                "original-command-deadline-unavailable",
                            )
                        })?;
                    let deadline = original_deadline.min(current.authority.deadline());
                    let cancelled = async {
                        if let Some(token) = &cancellation {
                            token.cancelled().await;
                        } else {
                            std::future::pending::<()>().await;
                        }
                    };
                    let wake = tokio::select! {
                        result = notification => { result.map_err(waiter_error)?; true },
                        () = cancelled => false,
                        () = tokio::time::sleep_until(deadline.into()) => false,
                    };
                    if wake {
                        continue;
                    }
                    // The delivery stopped; the actual original driver is untouched.
                    return observed(
                        &current,
                        record,
                        CommandObservation::InProgress,
                        memory,
                        Arc::clone(&self.time),
                    );
                }
                CommandWaiterDecision::Wait(_) => {
                    return observed(
                        &current,
                        record,
                        CommandObservation::InProgress,
                        memory,
                        Arc::clone(&self.time),
                    )
                }
            }
        }
    }

    async fn inspect_owned(
        &self,
        key: CommandKey,
        read: Arc<StateAuthorization>,
    ) -> Result<(CommandRecord, Option<DurableResult>), PlatformError> {
        let time = Arc::clone(&self.time);
        let job = self
            .store
            .with_store(StoreIoKind::Read, LOOKUP_BYTES, move |store| {
                let result = (|| {
                    let view = store.snapshot()?;
                    if !same_namespace(&view, &read)? {
                        return Ok(Err(AtomicError::Conflict));
                    }
                    match atomic::inspect(&view, &key, time.sample(), |_, record| {
                        if let Some(record) = record {
                            super::history::require_result_record(&view, record, &read)
                                .map_err(super::history::atomic_error)?;
                            read.accepts_record(record)
                                .map_err(|_| AtomicError::PermissionDenied)?;
                        }
                        read.authorize("read-result", 0, 0, || Ok(()))
                            .map_err(|_| AtomicError::PermissionDenied)
                    }) {
                        Ok(result) => Ok(Ok(result)),
                        Err(error) => errors::storage(error).map(Err),
                    }
                })();
                Ok((result, time))
            })
            .map_err(errors::protected)?;
        let (result, _time) = job
            .await
            .map_err(|_| errors::atomic(AtomicError::RecoveryRequired))?
            .map_err(errors::protected)?;
        result.map_err(errors::store)?.map_err(errors::atomic)
    }

    async fn replay(
        &self,
        record: CommandRecord,
        result: Option<DurableResult>,
        read: &Arc<StateAuthorization>,
        codec: &dyn CommandResultCodec,
        memory: Arc<HostMemoryReservation>,
    ) -> Result<TransactionCompletion, PlatformError> {
        let consumption = read.budget.snapshot_at(Instant::now());
        let outcome = match &result {
            Some(result) if result.outcome() != Outcome::Aborted => codec
                .replay(&record, result, consumption.clone())
                .unwrap_or_else(|error| failed(error, consumption.clone())),
            Some(_) => failed(
                errors::fixed(
                    latent_core::PlatformErrorCode::Unavailable,
                    "original-command-aborted",
                ),
                consumption,
            ),
            None => failed(errors::atomic(AtomicError::Expired), consumption),
        };
        let fence = self.release_permission(read, &record).await?;
        let mut completion = match result {
            Some(result) => {
                TransactionCompletion::confirmed(outcome, record, &result, true, Some(memory))
            }
            None => Ok(TransactionCompletion::observed(
                outcome,
                record,
                CommandObservation::Terminal,
                true,
                Some(memory),
            )),
        }?;
        completion.delivery_fence = Some(Arc::new(fence));
        Ok(completion)
    }

    pub(super) async fn release_permission(
        &self,
        read: &Arc<StateAuthorization>,
        record: &CommandRecord,
    ) -> Result<ResultDeliveryFence, PlatformError> {
        let current = read.rebind_result_read(
            self.read_namespace_observed(read, Some(record.clone()))
                .await?,
        )?;
        ResultDeliveryFence::command(Arc::new(current), record, Arc::clone(&self.time))
    }
}

pub(super) fn check_key(read: &StateAuthorization, key: &CommandKey) -> Result<(), PlatformError> {
    let ownership = read.authority.ownership();
    if read.authority_mode() != latent_capabilities::namespace::Mode::Inspection
        || key.tenant != ownership.tenant.0
        || key.namespace != ownership.namespace
        || key.incarnation != ownership.incarnation.to_string()
        || key.entity != ownership.entity
        || key.recovery_scope != ownership.caller.scope
    {
        return Err(errors::atomic(AtomicError::PermissionDenied));
    }
    Ok(())
}
fn same_namespace(view: &ReadView, read: &StateAuthorization) -> Result<bool, StoreError> {
    let expected = read.namespace.expectation();
    Ok(view.get(&expected.key)? == expected.value)
}
fn observed(
    read: &Arc<StateAuthorization>,
    record: CommandRecord,
    observation: CommandObservation,
    memory: Arc<HostMemoryReservation>,
    time: Arc<dyn super::super::CommandTimeSource>,
) -> Result<TransactionCompletion, PlatformError> {
    let fence = ResultDeliveryFence::command(Arc::clone(read), &record, time)?;
    let error = match observation {
        CommandObservation::RecoveryRequired => AtomicError::RecoveryRequired,
        _ => AtomicError::InProgress,
    };
    let mut completion = TransactionCompletion::observed(
        failed(
            errors::atomic(error),
            read.budget.snapshot_at(Instant::now()),
        ),
        record,
        observation,
        true,
        Some(memory),
    );
    completion.delivery_fence = Some(Arc::new(fence));
    Ok(completion)
}
pub(super) fn failed(error: PlatformError, consumption: BudgetConsumption) -> ActivationOutcome {
    crate::activation_runner::failure_for_platform_error(error, consumption)
}
fn waiter_error(error: CommandWaiterError) -> PlatformError {
    errors::atomic(match error {
        CommandWaiterError::Capacity | CommandWaiterError::Exhausted => AtomicError::Limit,
        CommandWaiterError::Authorization(error) => error,
        _ => AtomicError::RecoveryRequired,
    })
}
