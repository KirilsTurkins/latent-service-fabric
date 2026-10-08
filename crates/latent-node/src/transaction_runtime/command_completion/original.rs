//! Authorized original-source metadata, before any retained result disclosure.
use super::super::StateAuthorization;
use super::{errors, CommandCoordinator};
use latent_commit::atomic::{command_identity, command_row_key, AtomicError, CommandRecord};
use latent_core::{transaction_contract::CommandKey, PlatformError};
use latent_state::{
    embedded::StoreError,
    namespace::catalog::{NamespaceCatalog, NamespaceRead},
    store_io::StoreIoKind,
};
use std::sync::Arc;

/// Produced only by the same-store authorized metadata read. This grants no
/// replay or commit; the factory separately seals the ORIGINAL publication.
pub struct OriginalCommandMetadata {
    pub(super) record: CommandRecord,
    pub(super) current: Arc<StateAuthorization>,
    namespace: Option<NamespaceRead>,
    pub(super) expected: latent_state::embedded::ExpectedRow,
    pub(super) command_expected: latent_state::embedded::ExpectedRow,
    result_history: Option<Box<latent_capabilities::namespace::ReviewedResultHistory>>,
}
impl OriginalCommandMetadata {
    #[must_use]
    pub fn original_command(&self) -> &CommandRecord {
        &self.record
    }
    pub fn take_namespace(&mut self) -> Result<NamespaceRead, PlatformError> {
        self.namespace
            .take()
            .ok_or_else(|| errors::atomic(AtomicError::PermissionDenied))
    }
    /// The actual same-store observation can seal only historical result-read
    /// authority, never a query minimum, retry or another execution source.
    pub fn take_result_history(
        &mut self,
    ) -> Option<latent_capabilities::namespace::ReviewedResultHistory> {
        self.result_history.take().map(|history| *history)
    }
}
impl CommandCoordinator {
    /// Check the current installed read scope before bounded metadata lookup.
    /// The returned metadata cannot deliver result bytes or authorize retry.
    pub async fn original_metadata(
        &self,
        key: CommandKey,
        current: Arc<StateAuthorization>,
    ) -> Result<Option<OriginalCommandMetadata>, PlatformError> {
        super::lookup::check_key(&current, &key)?;
        current.authorize("read-result", 0, 0, || Ok(()))?;
        let time = Arc::clone(&self.time);
        let job = self
            .store
            .with_store(StoreIoKind::RecoveryRead, 131_072, move |store| {
                let result = (|| {
                    let view = store.snapshot()?;
                    let ownership = current.authority.ownership();
                    let id = latent_core::StateNamespaceId(ownership.namespace.clone());
                    latent_state::recovery::require_namespace_ready(
                        &view,
                        &ownership.tenant,
                        &id,
                        ownership.incarnation,
                    )?;
                    let namespace = NamespaceCatalog::read_in(&view, &ownership.tenant, &id)
                        .map_err(|_| StoreError::Unavailable)?
                        .ok_or(StoreError::Unavailable)?;
                    if !same_expected(&namespace.expectation(), &current.namespace.expectation()) {
                        return Err(StoreError::Unavailable);
                    }
                    let command_key =
                        command_row_key(command_identity(&key).map_err(|_| StoreError::Invalid)?);
                    let Some(bytes) = view.get(&command_key)? else {
                        return Ok(None);
                    };
                    let record = CommandRecord::decode(&bytes).map_err(|_| StoreError::Corrupt)?;
                    current
                        .authorize("read-result", 0, 0, || Ok(()))
                        .map_err(|_| StoreError::Unavailable)?;
                    if record.key() != &key {
                        return Err(StoreError::Corrupt);
                    }
                    let result_history =
                        if record.outcome() == latent_commit::atomic::Outcome::Pending {
                            super::history::require_record(&view, &record)?;
                            None
                        } else {
                            Some(Box::new(
                                latent_capabilities::namespace::ReviewedResultHistory::capture(
                                    &view, &namespace, &record,
                                )?,
                            ))
                        };
                    let expected = namespace.expectation();
                    let command_expected = latent_state::embedded::ExpectedRow {
                        key: command_key,
                        value: Some(bytes),
                    };
                    Ok(Some(OriginalCommandMetadata {
                        record,
                        current,
                        expected,
                        command_expected,
                        namespace: Some(namespace),
                        result_history,
                    }))
                })();
                // Accepted work and its returned metadata retain this original
                // global native owner after a dropped awaiting caller.
                Ok((result, time))
            })
            .map_err(errors::protected)?;
        let (result, _time) = job
            .await
            .map_err(|_| errors::atomic(AtomicError::RecoveryRequired))?
            .map_err(errors::protected)?;
        result.map_err(errors::store)
    }
}

pub(super) fn same_expected(
    left: &latent_state::embedded::ExpectedRow,
    right: &latent_state::embedded::ExpectedRow,
) -> bool {
    left.key == right.key && left.value == right.value
}
