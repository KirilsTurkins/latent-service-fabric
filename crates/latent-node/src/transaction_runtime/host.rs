use super::StateTransactionHost;
use latent_core::{
    transaction_contract::{self as contract, Value},
    BoxFuture, BudgetDimension,
};
use latent_executor::transaction::{
    CommandInfo, Entry, Intent, IntentFailure, Mode, Page, PageInfo, RetainedTransfer,
    StateFailure, TransactionHost, VersionedValue, ViewIdentity,
};
use std::sync::atomic::Ordering;

impl StateTransactionHost {
    pub(super) fn check_live(&self) -> Result<(), StateFailure> {
        if self.guest_closed.load(Ordering::Acquire)
            || self.released.load(Ordering::Acquire)
            || self.acquired.load(Ordering::Acquire) != 1
        {
            return Err(StateFailure::HandleClosed);
        }
        if self.technical_fault.load(Ordering::Acquire) {
            return Err(StateFailure::Unavailable);
        }
        if std::time::Instant::now() >= self.authorization.authority.deadline()
            || self
                .authorization
                .budget
                .deadline()
                .is_expired_at(std::time::Instant::now())
        {
            return Err(StateFailure::Cancelled);
        }
        Ok(())
    }
    fn identity(&self) -> Result<ViewIdentity, StateFailure> {
        Ok(ViewIdentity {
            namespace: self.scope.namespace.0.clone(),
            incarnation: self.scope.incarnation.to_string(),
            version: self
                .view_identity
                .token(&self.scope)
                .map_err(|error| super::io::state_error(error, false))?,
            state_schema: self.scope.state_schema.clone(),
        })
    }
}
impl TransactionHost for StateTransactionHost {
    fn activation_id(&self) -> &latent_core::ActivationId {
        &self.activation
    }
    fn mode(&self) -> Mode {
        self.mode
    }
    fn budget(&self) -> &latent_core::ActivationBudget {
        &self.authorization.budget
    }
    fn acquire(&self, mode: Mode) -> Result<(), StateFailure> {
        if mode != self.mode {
            return Err(StateFailure::WrongMode);
        }
        if self.guest_closed.load(Ordering::Acquire) {
            return Err(StateFailure::HandleClosed);
        }
        self.authorization
            .authorize(
                if mode == Mode::Command {
                    "info"
                } else {
                    "query-info"
                },
                0,
                0,
                || Ok(()),
            )
            .map_err(|_| StateFailure::PermissionDenied)?;
        self.acquired
            .compare_exchange(0, 1, Ordering::AcqRel, Ordering::Acquire)
            .map(|_| ())
            .map_err(|_| StateFailure::HandleClosed)
    }
    fn release(&self, mode: Mode) {
        if mode == self.mode {
            self.released.store(true, Ordering::Release);
        }
    }
    fn view_identity(&self) -> Result<ViewIdentity, StateFailure> {
        self.authorize_read()?;
        self.budget()
            .consume(
                BudgetDimension::StateReadBytes,
                (self.scope.namespace.0.len()
                    + self.scope.state_schema.len()
                    + latent_state::session::version::VIEW_TOKEN_BYTES) as u64,
            )
            .map_err(|_| StateFailure::ReadBudgetExhausted)?;
        self.identity()
    }
    fn command_info(&self) -> Result<CommandInfo, StateFailure> {
        if self.mode != Mode::Command {
            return Err(StateFailure::WrongMode);
        }
        self.authorize_read()?;
        let info = self.command.as_ref().ok_or(StateFailure::Unavailable)?;
        self.budget()
            .consume(
                BudgetDimension::StateReadBytes,
                (info.command_id.len()
                    + info.attempt_id.len()
                    + self.scope.namespace.0.len()
                    + self.scope.state_schema.len()
                    + info.entity.as_ref().map_or(0, String::len)
                    + 128) as u64,
            )
            .map_err(|_| StateFailure::ReadBudgetExhausted)?;
        Ok(info.clone())
    }
    fn authorize_read(&self) -> Result<(), StateFailure> {
        self.check_live()?;
        self.authorization
            .authorize(
                if self.mode == Mode::Command {
                    "info"
                } else {
                    "query-info"
                },
                0,
                0,
                || Ok(()),
            )
            .map_err(|_| StateFailure::PermissionDenied)
    }
    fn retain_transfer(&self, bytes: usize) -> Result<RetainedTransfer, StateFailure> {
        self.check_live()?;
        let memory = self
            .budget()
            .reserve_host_memory(
                u64::try_from(bytes.max(1)).map_err(|_| StateFailure::ReadBudgetExhausted)?,
            )
            .map_err(|_| StateFailure::ReadBudgetExhausted)?;
        Ok(RetainedTransfer::new(Box::new(memory)))
    }
    fn read(&self, key: Vec<u8>) -> BoxFuture<'_, Result<Option<VersionedValue>, StateFailure>> {
        Box::pin(async move {
            check_key(&key)?;
            let op = if self.mode == Mode::Command {
                "get"
            } else {
                "get-query"
            };
            self.access(
                op,
                key.len(),
                contract::VALUE_BYTES,
                move |session, view| session.get(view, &key, |_, _| Ok(())),
            )
            .await
            .map(|value| {
                value.map(|value| VersionedValue {
                    value: value.value,
                    version: value.version,
                })
            })
        })
    }
    fn scan(
        &self,
        prefix: Vec<u8>,
        limit: u32,
        cursor: Option<Vec<u8>>,
    ) -> BoxFuture<'_, Result<Page, StateFailure>> {
        Box::pin(async move {
            if prefix.len() > contract::KEY_BYTES {
                return Err(StateFailure::InvalidKey);
            }
            if limit == 0 || limit > contract::PAGE_ENTRIES {
                return Err(StateFailure::InvalidLimit);
            }
            let op = if self.mode == Mode::Command {
                "scan"
            } else {
                "scan-query"
            };
            let page = self
                .access(
                    op,
                    prefix.len() + cursor.as_ref().map_or(0, Vec::len),
                    contract::PAGE_BYTES,
                    move |session, view| {
                        let cursor = cursor
                            .as_ref()
                            .map(|bytes| session.cursor(bytes))
                            .transpose()?;
                        session.scan(
                            view,
                            &prefix,
                            cursor.as_ref(),
                            limit,
                            contract::PAGE_BYTES,
                            |_, _| Ok(()),
                        )
                    },
                )
                .await?;
            let entries: Vec<Entry> = page
                .entries
                .into_iter()
                .map(|entry| Entry {
                    key: entry.key,
                    value: VersionedValue {
                        value: entry.value.value,
                        version: entry.value.version,
                    },
                })
                .collect();
            let encoded_bytes = entries
                .iter()
                .map(|entry| {
                    entry.key.len()
                        + value_bytes(&entry.value.value)
                        + entry.value.version.len()
                        + 16
                })
                .sum::<usize>();
            if encoded_bytes > contract::PAGE_BYTES {
                return Err(StateFailure::ReadBudgetExhausted);
            }
            let next_cursor = page.continuation.map(|cursor| cursor.bytes().to_vec());
            Ok(Page {
                info: PageInfo {
                    view: self.identity()?,
                    entry_count: u32::try_from(entries.len())
                        .map_err(|_| StateFailure::InvalidLimit)?,
                    encoded_bytes: encoded_bytes as u64,
                    has_more: next_cursor.is_some(),
                    next_cursor,
                },
                entries,
            })
        })
    }
    fn put(&self, key: Vec<u8>, value: Value) -> BoxFuture<'_, Result<(), StateFailure>> {
        Box::pin(async move {
            if self.mode != Mode::Command {
                return Err(StateFailure::WrongMode);
            }
            check_key(&key)?;
            value.validate().map_err(|_| StateFailure::InvalidValue)?;
            self.access(
                "put",
                key.len() + value_bytes(&value),
                0,
                move |session, view| session.put(view, key, value, |_, _| Ok(())),
            )
            .await
        })
    }
    fn delete(&self, key: Vec<u8>) -> BoxFuture<'_, Result<(), StateFailure>> {
        Box::pin(async move {
            if self.mode != Mode::Command {
                return Err(StateFailure::WrongMode);
            }
            check_key(&key)?;
            self.access("delete", key.len(), 0, move |session, view| {
                session.delete(view, key, |_, _| Ok(()))
            })
            .await
        })
    }
    fn stage(&self, intent: Intent) -> BoxFuture<'_, Result<u32, IntentFailure>> {
        Box::pin(async move {
            if self.mode != Mode::Command {
                return Err(IntentFailure::WrongMode);
            }
            self.check_live().map_err(intent_state_error)?;
            contract::identity(&intent.binding).map_err(|_| IntentFailure::InvalidBinding)?;
            contract::identity(&intent.operation).map_err(|_| IntentFailure::InvalidOperation)?;
            intent
                .payload
                .validate()
                .map_err(|_| IntentFailure::InvalidPayload)?;
            let bytes = value_bytes(&intent.payload)
                + intent.binding.len()
                + intent.operation.len()
                + 16_384;
            let mut session = self
                .session
                .lock()
                .map_err(|_| IntentFailure::Unavailable)?;
            let payload = &mut session.as_mut().ok_or(IntentFailure::Unavailable)?.payload;
            let sequence =
                u32::try_from(payload.intents.len()).map_err(|_| IntentFailure::CountLimit)?;
            if sequence >= self.budget().granted().effect_count.min(128) {
                return Err(IntentFailure::CountLimit);
            }
            let reserved = self
                .budget()
                .reserve_group(&[
                    (BudgetDimension::EffectCount, 1),
                    (BudgetDimension::StateWriteBytes, bytes as u64),
                ])
                .map_err(|error| intent_budget_error(&error))?;
            let context = self.context.as_ref().ok_or(IntentFailure::WrongMode)?;
            let effects = self
                .effects
                .as_ref()
                .ok_or(IntentFailure::UnsupportedProfile)?;
            let mut captured = None;
            let time = self.time.sample();
            if intent
                .expires_at_unix_millis
                .is_some_and(|expires| expires <= time.unix_millis)
            {
                return Err(IntentFailure::InvalidExpiry);
            }
            self.authorization
                .authorize("stage", bytes, 0, || {
                    captured = Some(context.capture(
                        sequence,
                        latent_commit::atomic::StagedIntent {
                            binding: intent.binding,
                            operation: intent.operation,
                            payload: intent.payload,
                            expires_at_millis: intent.expires_at_unix_millis,
                        },
                        effects,
                        time,
                    ));
                    Ok(())
                })
                .map_err(|_| IntentFailure::PermissionDenied)?;
            let captured = captured
                .ok_or(IntentFailure::Unavailable)?
                .map_err(intent_capture_error)?;
            reserved
                .commit()
                .map_err(|error| intent_budget_error(&error))?;
            payload.intents.push(captured);
            Ok(sequence)
        })
    }
    fn finish_guest_access(&self) {
        self.guest_closed.store(true, Ordering::Release);
    }
}
fn intent_budget_error(error: &latent_core::BudgetError) -> IntentFailure {
    match error {
        latent_core::BudgetError::Exhausted {
            dimension: BudgetDimension::EffectCount,
            ..
        } => IntentFailure::CountLimit,
        latent_core::BudgetError::Exhausted {
            dimension: BudgetDimension::StateWriteBytes,
            ..
        } => IntentFailure::ByteLimit,
        latent_core::BudgetError::DeadlineExceeded { .. } => IntentFailure::Cancelled,
        _ => IntentFailure::Unavailable,
    }
}
fn intent_capture_error(error: latent_commit::atomic::AtomicError) -> IntentFailure {
    use latent_commit::atomic::AtomicError;
    match error {
        AtomicError::PermissionDenied | AtomicError::Conflict => IntentFailure::PermissionDenied,
        AtomicError::Limit => IntentFailure::ByteLimit,
        AtomicError::Expired | AtomicError::Invalid => IntentFailure::InvalidExpiry,
        AtomicError::UnsupportedFormat => IntentFailure::UnsupportedProfile,
        _ => IntentFailure::Unavailable,
    }
}
fn check_key(key: &[u8]) -> Result<(), StateFailure> {
    if key.is_empty() || key.len() > contract::KEY_BYTES {
        Err(StateFailure::InvalidKey)
    } else {
        Ok(())
    }
}
fn value_bytes(value: &Value) -> usize {
    value.bytes.len()
        + value.media_type.len()
        + value
            .metadata
            .iter()
            .map(|(k, v)| k.len() + v.len() + 4)
            .sum::<usize>()
        + 13
}
fn intent_state_error(error: StateFailure) -> IntentFailure {
    match error {
        StateFailure::HandleClosed => IntentFailure::HandleClosed,
        StateFailure::WrongMode => IntentFailure::WrongMode,
        StateFailure::Cancelled => IntentFailure::Cancelled,
        StateFailure::PermissionDenied => IntentFailure::PermissionDenied,
        _ => IntentFailure::Unavailable,
    }
}
