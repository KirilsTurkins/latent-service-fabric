use super::{convert, key_value as wit, port, staging, HostState};
use crate::host::service::{checkpoint, synchronize};
use latent_core::transaction_contract as contract;
use std::{sync::Arc, time::Instant};
use wasmtime::{
    component::{Accessor, HasSelf, Resource},
    AsContextMut,
};

type StoreAccess = Accessor<HostState, HasSelf<HostState>>;

impl wit::HostTransaction for HostState {
    async fn drop(&mut self, resource: Resource<wit::Transaction>) -> wasmtime::Result<()> {
        self.transaction
            .release(port::Mode::Command, resource.rep());
        Ok(())
    }
}
impl wit::HostQueryView for HostState {
    async fn drop(&mut self, resource: Resource<wit::QueryView>) -> wasmtime::Result<()> {
        self.transaction.release(port::Mode::Query, resource.rep());
        Ok(())
    }
}
impl wit::HostPage for HostState {
    async fn drop(&mut self, resource: Resource<wit::Page>) -> wasmtime::Result<()> {
        self.transaction.release_page(resource.rep());
        Ok(())
    }
}
impl wit::Host for HostState {
    async fn acquire_command(
        &mut self,
    ) -> wasmtime::Result<Result<Resource<wit::Transaction>, wit::StateError>> {
        let started = Instant::now();
        let result = self
            .transaction
            .acquire(port::Mode::Command)
            .map(Resource::new_own);
        self.record_host_call(started);
        Ok(result)
    }
    async fn acquire_query(
        &mut self,
    ) -> wasmtime::Result<Result<Resource<wit::QueryView>, wit::StateError>> {
        let started = Instant::now();
        let result = self
            .transaction
            .acquire(port::Mode::Query)
            .map(Resource::new_own);
        self.record_host_call(started);
        Ok(result)
    }
    async fn info(
        &mut self,
        transaction: Resource<wit::Transaction>,
    ) -> wasmtime::Result<Result<wit::CommandInfo, wit::StateError>> {
        let started = Instant::now();
        let result = (|| {
            let host = self
                .transaction
                .selected(port::Mode::Command, transaction.rep())?;
            let info = host.command_info().map_err(convert::state_error)?;
            self.transaction
                .reserve_lowering(host.as_ref(), convert::command_size(&info)?)?;
            Ok(wit::CommandInfo {
                view: convert::view(info.view),
                command_id: info.command_id,
                attempt_id: info.attempt_id,
                entity: info.entity,
            })
        })();
        self.record_host_call(started);
        Ok(result)
    }
    async fn query_info(
        &mut self,
        view: Resource<wit::QueryView>,
    ) -> wasmtime::Result<Result<wit::ViewIdentity, wit::StateError>> {
        let started = Instant::now();
        let result = (|| {
            let host = self.transaction.selected(port::Mode::Query, view.rep())?;
            let info = host.view_identity().map_err(convert::state_error)?;
            self.transaction
                .reserve_lowering(host.as_ref(), convert::view_size(&info)?)?;
            Ok(convert::view(info))
        })();
        self.record_host_call(started);
        Ok(result)
    }
    async fn describe_page(
        &mut self,
        page: Resource<wit::Page>,
    ) -> wasmtime::Result<Result<wit::PageInfo, wit::StateError>> {
        let started = Instant::now();
        let result = (|| {
            let host = self.transaction.host()?;
            host.authorize_read().map_err(convert::state_error)?;
            let info = &self.transaction.page(page.rep())?.page.info;
            let bytes = convert::view_size(&info.view)?
                + 128
                + info.next_cursor.as_ref().map_or(0, Vec::len);
            self.transaction.reserve_lowering(host.as_ref(), bytes)?;
            let info = self.transaction.page(page.rep())?.page.info.clone();
            Ok(convert::page_info(info))
        })();
        self.record_host_call(started);
        Ok(result)
    }
}

// WIT async imports receive an Accessor. Only owned host jobs cross suspension;
// no mutable Store reference or guest handle is retained by native IO.
impl wit::HostWithStore<HostState> for HasSelf<HostState> {
    async fn get(
        access: &StoreAccess,
        transaction: Resource<wit::Transaction>,
        key: Vec<u8>,
    ) -> wasmtime::Result<Result<Option<wit::VersionedValue>, wit::StateError>> {
        get(access, port::Mode::Command, transaction.rep(), key).await
    }
    async fn get_query(
        access: &StoreAccess,
        view: Resource<wit::QueryView>,
        key: Vec<u8>,
    ) -> wasmtime::Result<Result<Option<wit::VersionedValue>, wit::StateError>> {
        get(access, port::Mode::Query, view.rep(), key).await
    }
    async fn scan(
        access: &StoreAccess,
        transaction: Resource<wit::Transaction>,
        prefix: Vec<u8>,
        limit: u32,
        cursor: Option<Vec<u8>>,
    ) -> wasmtime::Result<Result<Resource<wit::Page>, wit::StateError>> {
        scan(
            access,
            port::Mode::Command,
            transaction.rep(),
            prefix,
            limit,
            cursor,
        )
        .await
    }
    async fn scan_query(
        access: &StoreAccess,
        view: Resource<wit::QueryView>,
        prefix: Vec<u8>,
        limit: u32,
        cursor: Option<Vec<u8>>,
    ) -> wasmtime::Result<Result<Resource<wit::Page>, wit::StateError>> {
        scan(access, port::Mode::Query, view.rep(), prefix, limit, cursor).await
    }
    async fn page_next(
        access: &StoreAccess,
        page: Resource<wit::Page>,
    ) -> wasmtime::Result<Result<Option<wit::Entry>, wit::StateError>> {
        let started = Instant::now();
        with_state(access, |state| {
            let result = (|| {
                let host = state.transaction.host()?;
                host.authorize_read().map_err(convert::state_error)?;
                let slot = state.transaction.page(page.rep())?;
                let Some(entry) = slot.page.entries.get(slot.next) else {
                    return Ok(None);
                };
                let bytes = convert::value_size(&entry.value)? + entry.key.len() + 128;
                state.transaction.reserve_lowering(host.as_ref(), bytes)?;
                let slot = state.transaction.page(page.rep())?;
                let entry = slot.page.entries[slot.next].clone();
                slot.next += 1;
                Ok(Some(wit::Entry {
                    key: entry.key,
                    value: convert::versioned(entry.value),
                }))
            })();
            state.record_host_call(started);
            result
        })
    }
    async fn put(
        access: &StoreAccess,
        transaction: Resource<wit::Transaction>,
        key: Vec<u8>,
        value: wit::Value,
    ) -> wasmtime::Result<Result<(), wit::StateError>> {
        let started = Instant::now();
        let prepared = with_state(access, |state| {
            check_key(&key)?;
            let host = state
                .transaction
                .selected(port::Mode::Command, transaction.rep())?;
            let value = convert::input_value(value)?;
            let retained = host
                .retain_transfer(key.len() + convert::input_size(&value)?)
                .map_err(convert::state_error)?;
            Ok((host, value, retained))
        })?;
        let result = match prepared {
            Ok((host, value, _retained)) => {
                host.put(key, value).await.map_err(convert::state_error)
            }
            Err(error) => Err(error),
        };
        finish_write(access, transaction.rep(), result, started)
    }
    async fn delete(
        access: &StoreAccess,
        transaction: Resource<wit::Transaction>,
        key: Vec<u8>,
    ) -> wasmtime::Result<Result<(), wit::StateError>> {
        let started = Instant::now();
        let prepared = with_state(access, |state| {
            check_key(&key)?;
            selected(
                state,
                port::Mode::Command,
                transaction.rep(),
                key.len() + 128,
            )
        })?;
        let result = match prepared {
            Ok((host, _retained)) => host.delete(key).await.map_err(convert::state_error),
            Err(error) => Err(error),
        };
        finish_write(access, transaction.rep(), result, started)
    }
}

impl staging::Host for HostState {}
impl staging::HostWithStore<HostState> for HasSelf<HostState> {
    async fn stage(
        access: &StoreAccess,
        transaction: Resource<wit::Transaction>,
        intent: staging::Intent,
    ) -> wasmtime::Result<Result<staging::StagedIntent, staging::IntentError>> {
        let started = Instant::now();
        let prepared = with_state(access, |state| {
            let host = state
                .transaction
                .selected(port::Mode::Command, transaction.rep())
                .map_err(state_to_intent)?;
            contract::identity(&intent.binding)
                .map_err(|_| staging::IntentError::InvalidBinding)?;
            contract::identity(&intent.operation)
                .map_err(|_| staging::IntentError::InvalidOperation)?;
            let payload = convert::input_value(intent.payload)
                .map_err(|_| staging::IntentError::InvalidPayload)?;
            let bytes = convert::input_size(&payload)
                .map_err(|_| staging::IntentError::InvalidPayload)?
                + intent.binding.len()
                + intent.operation.len()
                + 128;
            let retained = host
                .retain_transfer(bytes)
                .map_err(|_| staging::IntentError::ByteLimit)?;
            Ok((
                host,
                port::Intent {
                    binding: intent.binding,
                    operation: intent.operation,
                    payload,
                    expires_at_unix_millis: intent.expires_at_unix_millis,
                },
                retained,
            ))
        })?;
        let result = match prepared {
            Ok((host, intent, _retained)) => {
                host.stage(intent).await.map_err(convert::intent_error)
            }
            Err(error) => Err(error),
        };
        with_state(access, |state| {
            let result = result.and_then(|sequence| {
                state
                    .transaction
                    .selected(port::Mode::Command, transaction.rep())
                    .map_err(state_to_intent)?;
                if sequence >= contract::MAX_INTENTS {
                    return Err(staging::IntentError::Unavailable);
                }
                Ok(staging::StagedIntent { sequence })
            });
            state.record_host_call(started);
            result
        })
    }
}

fn with_state<T>(
    access: &StoreAccess,
    call: impl FnOnce(&mut HostState) -> T,
) -> wasmtime::Result<T> {
    access.with(|mut access| {
        let mut store = access.as_context_mut();
        checkpoint(&mut store)?;
        let result = call(store.data_mut());
        synchronize(&mut store)?;
        Ok(result)
    })
}
fn selected(
    state: &HostState,
    mode: port::Mode,
    rep: u32,
    bytes: usize,
) -> Result<(Arc<dyn port::TransactionHost>, port::RetainedTransfer), wit::StateError> {
    let host = state.transaction.selected(mode, rep)?;
    let retained = host.retain_transfer(bytes).map_err(convert::state_error)?;
    Ok((host, retained))
}
fn finish_write(
    access: &StoreAccess,
    rep: u32,
    result: Result<(), wit::StateError>,
    started: Instant,
) -> wasmtime::Result<Result<(), wit::StateError>> {
    with_state(access, |state| {
        let result = result.and_then(|()| {
            state
                .transaction
                .selected(port::Mode::Command, rep)
                .map(|_| ())
        });
        state.record_host_call(started);
        result
    })
}
async fn get(
    access: &StoreAccess,
    mode: port::Mode,
    rep: u32,
    key: Vec<u8>,
) -> wasmtime::Result<Result<Option<wit::VersionedValue>, wit::StateError>> {
    let started = Instant::now();
    let prepared = with_state(access, |state| {
        check_key(&key)?;
        selected(state, mode, rep, key.len() + 128)
    })?;
    let result = match prepared {
        Ok((host, _retained)) => host.read(key).await.map_err(convert::state_error),
        Err(error) => Err(error),
    };
    with_state(access, |state| {
        let result = result.and_then(|result| {
            let host = state.transaction.selected(mode, rep)?;
            if let Some(value) = &result {
                state
                    .transaction
                    .reserve_lowering(host.as_ref(), convert::value_size(value)?)?;
            }
            Ok(result.map(convert::versioned))
        });
        state.record_host_call(started);
        result
    })
}
async fn scan(
    access: &StoreAccess,
    mode: port::Mode,
    rep: u32,
    prefix: Vec<u8>,
    limit: u32,
    cursor: Option<Vec<u8>>,
) -> wasmtime::Result<Result<Resource<wit::Page>, wit::StateError>> {
    let started = Instant::now();
    let prepared = with_state(access, |state| {
        if prefix.len() > contract::KEY_BYTES {
            return Err(wit::StateError::InvalidKey);
        }
        if limit == 0 || limit > contract::PAGE_ENTRIES {
            return Err(wit::StateError::InvalidLimit);
        }
        if cursor
            .as_ref()
            .is_some_and(|c| c.len() > contract::VERSION_BYTES)
        {
            return Err(wit::StateError::InvalidCursor);
        }
        selected(
            state,
            mode,
            rep,
            prefix.len() + cursor.as_ref().map_or(0, Vec::len) + 128,
        )
    })?;
    let result = match prepared {
        Ok((host, _retained)) => host
            .scan(prefix, limit, cursor)
            .await
            .map_err(convert::state_error),
        Err(error) => Err(error),
    };
    with_state(access, |state| {
        let result = result.and_then(|page| {
            let host = state.transaction.selected(mode, rep)?;
            state
                .transaction
                .insert_page(host.as_ref(), page)
                .map(Resource::new_own)
        });
        state.record_host_call(started);
        result
    })
}
fn check_key(key: &[u8]) -> Result<(), wit::StateError> {
    if key.is_empty() || key.len() > contract::KEY_BYTES {
        Err(wit::StateError::InvalidKey)
    } else {
        Ok(())
    }
}
fn state_to_intent(error: wit::StateError) -> staging::IntentError {
    match error {
        wit::StateError::HandleClosed => staging::IntentError::HandleClosed,
        wit::StateError::WrongActivation => staging::IntentError::WrongActivation,
        wit::StateError::WrongMode => staging::IntentError::WrongMode,
        wit::StateError::Cancelled => staging::IntentError::Cancelled,
        wit::StateError::ReadBudgetExhausted => staging::IntentError::ByteLimit,
        wit::StateError::PermissionDenied => staging::IntentError::PermissionDenied,
        _ => staging::IntentError::Unavailable,
    }
}
