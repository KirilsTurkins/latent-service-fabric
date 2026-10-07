//! Original command-linked effect status over the same protected recovery owner.
use super::{errors, history, lookup, CommandCoordinator, ResultDeliveryFence};
use crate::transaction_runtime::StateAuthorization;
use latent_commit::atomic::{
    command_identity, command_row_key, AtomicError, CommandRecord, Outcome,
};
use latent_core::{transaction_contract::CommandKey, HostMemoryReservation, PlatformError};
use latent_effects::{
    dispatch::EffectRecord,
    dispatch_store::{effect_row_key, DispatchCatalog, HistoryPage},
};
use latent_state::{embedded::StoreError, store_io::StoreIoKind};
use std::sync::Arc;

/// Native observations plus their actual current-purpose delivery owner.
/// No provider request, administrative acknowledgement or business mutation exists.
pub struct CommandEffectInspection {
    command: CommandRecord,
    effect: EffectRecord,
    history: HistoryPage,
    delivery: Arc<ResultDeliveryFence>,
    _memory: Arc<HostMemoryReservation>,
}
impl CommandEffectInspection {
    /// Observe bounded metadata only under the retained current inspect-effect
    /// delivery gate. Callers cannot detach records from their original owner.
    pub fn with_current<T>(
        &self,
        output_bytes: usize,
        inspect: impl FnOnce(&CommandRecord, &EffectRecord, &HistoryPage) -> Result<T, PlatformError>,
    ) -> Result<T, PlatformError> {
        self.delivery.with_current(output_bytes, || {
            inspect(&self.command, &self.effect, &self.history)
        })
    }
    #[must_use]
    pub fn delivery(&self) -> &Arc<ResultDeliveryFence> {
        &self.delivery
    }
}

struct Retention {
    authorization: Arc<StateAuthorization>,
    time: Arc<dyn crate::transaction_runtime::CommandTimeSource>,
    memory: Arc<HostMemoryReservation>,
}
impl CommandCoordinator {
    /// Inspect one original effect and its bounded native history. Callers supply
    /// current inspect-effect authority, not an execution grant or known ID.
    pub async fn inspect_effect(
        &self,
        key: CommandKey,
        effect: String,
        read: Arc<StateAuthorization>,
    ) -> Result<CommandEffectInspection, PlatformError> {
        lookup::check_key(&read, &key)?;
        read.authorize("inspect-effect", 0, 0, || Ok(()))?;
        let memory = Arc::new(
            read.budget
                .reserve_host_memory(2 * 1024 * 1024)
                .map_err(|_| errors::atomic(AtomicError::Limit))?,
        );
        let retained = Arc::new(Retention {
            authorization: Arc::clone(&read),
            time: Arc::clone(&self.time),
            memory,
        });
        let worker = Arc::clone(&retained);
        let job = self
            .store
            .with_store_retaining(
                StoreIoKind::RecoveryRead,
                2 * 1024 * 1024,
                retained,
                move |store| {
                    let view = store.snapshot()?;
                    let ownership = worker.authorization.authority.ownership();
                    latent_state::recovery::require_namespace_ready(
                        &view,
                        &ownership.tenant,
                        &latent_core::StateNamespaceId(ownership.namespace.clone()),
                        ownership.incarnation,
                    )?;
                    let expected = worker.authorization.namespace.expectation();
                    if view.get(&expected.key)? != expected.value {
                        return Err(StoreError::Unavailable);
                    }
                    let command_key =
                        command_row_key(command_identity(&key).map_err(|_| StoreError::Invalid)?);
                    let bytes = view.get(&command_key)?.ok_or(StoreError::Unavailable)?;
                    let command = CommandRecord::decode(&bytes).map_err(|_| StoreError::Corrupt)?;
                    history::require_result_record(&view, &command, &worker.authorization)?;
                    if command.key() != &key || command.outcome() != Outcome::Committed {
                        return Err(StoreError::Unavailable);
                    }
                    worker
                        .authorization
                        .accepts_record(&command)
                        .map_err(|_| StoreError::Unavailable)?;
                    worker
                        .authorization
                        .authorize("inspect-effect", 0, 0, || Ok(()))
                        .map_err(|_| StoreError::Unavailable)?;
                    let row = effect_row_key(&effect)?;
                    let bytes = view.get(&row)?.ok_or(StoreError::Unavailable)?;
                    latent_effects::dispatch_store::validate_row(&row, &bytes)?;
                    let record = EffectRecord::decode(&bytes).map_err(|_| StoreError::Corrupt)?;
                    verify_link(&command, &effect, &record)?;
                    let page =
                        DispatchCatalog::history_page(&view, &effect, None, 128, 1024 * 1024)?;
                    if page.rows.iter().any(|row| row.effect != effect) {
                        return Err(StoreError::Corrupt);
                    }
                    worker
                        .authorization
                        .authorize("inspect-effect", 0, 0, || Ok(()))
                        .map_err(|_| StoreError::Unavailable)?;
                    Ok((command, record, page, worker))
                },
            )
            .map_err(errors::protected)?;
        let (command, effect, history, retained) = job
            .await
            .map_err(|_| errors::atomic(AtomicError::RecoveryRequired))?
            .map_err(errors::protected)?
            .map_err(errors::protected)?;
        let delivery = Arc::new(ResultDeliveryFence::effect(
            Arc::clone(&retained.authorization),
            &command,
            Arc::clone(&retained.time),
        )?);
        Ok(CommandEffectInspection {
            command,
            effect,
            history,
            delivery,
            _memory: Arc::clone(&retained.memory),
        })
    }
}
pub(super) fn verify_link(
    command: &CommandRecord,
    effect: &str,
    record: &EffectRecord,
) -> Result<(), StoreError> {
    let authority = record.authority().map_err(|_| StoreError::Corrupt)?;
    let scope = authority.scope();
    let link = authority.link();
    if scope.tenant != command.key().tenant
        || scope.namespace != command.key().namespace
        || scope.incarnation.to_string() != command.key().incarnation
        || scope.publication != command.source().publication
        || link.command != command.id().hex()
        || link.caller_scope != command.key().recovery_scope
        || link.attempt != command.attempt()
        || link.commit != command.disposition_id().hex()
        || link.effect != effect
        || link.sequence >= 128
        || command.effect_id(link.sequence).hex() != effect
        || !command
            .effect_ids()
            .contains(&command.effect_id(link.sequence))
    {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}
