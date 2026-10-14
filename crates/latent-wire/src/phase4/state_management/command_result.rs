//! Original-result reads share the protected store and recovery capacity owner.
mod audit;
mod authority;
mod cancellation;
mod effect;
mod projection;

use super::{
    authorization, capacity, contract, denied, expired, inspection, invalid, io_error, missing,
    namespace_error, protected_error, recovery_bindings, unsupported, Arc,
    AuthenticatedInvocationContext, Inner, Instant, OwnedPhase4Response, PlatformError,
    StateManagementBinding, StateManagementReservation, WORK_BYTES,
};
use authority::{ReadAuthority, ResponseOwner, ResultWindow};
use latent_audit::{AuditOperationResult, AuditReason};
use latent_commit::atomic::{
    self, AtomicError, CommandRecord, CommandTime, DurableResult, Outcome,
};
use latent_core::transaction_contract::CommandKey;
use latent_rpc::transaction::v1 as t;
use latent_state::{
    embedded::{EmbeddedStore, ReadView, StoreError},
    namespace::{catalog::NamespaceCatalog, NamespaceError},
    store_io::StoreIoKind,
};

enum ReadError {
    Store(StoreError),
    Refused(PlatformError),
}
impl From<PlatformError> for ReadError {
    fn from(error: PlatformError) -> Self {
        Self::Refused(error)
    }
}
impl From<StoreError> for ReadError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}
impl ReadError {
    fn public(self) -> PlatformError {
        match self {
            Self::Store(_) => unsupported(),
            Self::Refused(error) => error,
        }
    }
    fn namespace(error: NamespaceError) -> Self {
        match error {
            NamespaceError::Corrupt => Self::Store(StoreError::Corrupt),
            NamespaceError::UnsupportedFormat => Self::Store(StoreError::UnsupportedFormat),
            NamespaceError::Unavailable => Self::Store(StoreError::Unavailable),
            other => Self::Refused(namespace_error(other)),
        }
    }
}

pub(super) fn handles(request: &contract::Request) -> bool {
    matches!(
        request,
        contract::Request::LookupCommand(_)
            | contract::Request::LookupCommit(_)
            | contract::Request::GetEffect(_)
            | contract::Request::CancelCommand(_)
    )
}

#[expect(
    clippy::too_many_lines,
    reason = "Keep original read authority, physical audit completion and response custody in one scope"
)]
pub(super) async fn execute(
    inner: Arc<Inner>,
    context: AuthenticatedInvocationContext,
    request: contract::Request,
    binding: Arc<StateManagementBinding>,
    deadline: Instant,
    permit: Arc<dyn StateManagementReservation>,
    command_manager: Option<latent_node::LocalActivationManager>,
) -> Result<OwnedPhase4Response, PlatformError> {
    let selector = selector(&request)?;
    let caller =
        recovery_bindings::scope(&inner, &context, selector.shared_recovery_scope.as_deref())?;
    let started = inner.services.clock.monotonic_now();
    let decision = authorization::EffectDecision {
        services: &inner.services,
        binding: &binding,
        context: &context,
        caller: &caller,
        entity: selector.entity.as_deref(),
        deadline,
        input_bytes: request.encoded_len(),
    }
    .seal(operation(&request))?;
    let mut policy_deadline = None;
    inner
        .services
        .policy
        .with_retained_decision(&decision, &mut |_, ceiling| {
            policy_deadline =
                started.checked_add(std::time::Duration::from_millis(ceiling.wall_time_millis));
            Ok(())
        })?;
    let deadline = deadline.min(policy_deadline.ok_or_else(expired)?);
    if decision.requires_audit() && inner.services.audit.is_none() {
        return Err(unsupported());
    }
    if inner.command_source.is_none() {
        return Err(unsupported());
    }
    let key = CommandKey {
        tenant: context
            .principal()
            .tenant
            .as_ref()
            .ok_or_else(denied)?
            .0
            .clone(),
        namespace: binding.namespace.0.clone(),
        incarnation: binding.incarnation.to_string(),
        recovery_scope: caller.scope,
        operation: selector.operation.clone(),
        entity: selector.entity.clone(),
        client_key: selector.client_key.clone(),
    };
    let mut pending = audit::begin(&inner, &context, &binding, &request).await?;
    let read = Arc::new(ReadAuthority {
        inner: Arc::clone(&inner),
        binding,
        decision: Arc::new(decision),
        permit,
        key,
        deadline,
        command_manager,
    });
    read.before_lookup()?;
    let keeper = Arc::clone(&read);
    let job = inner
        .services
        .store
        .with_store_retaining(
            StoreIoKind::RecoveryRead,
            WORK_BYTES as u64,
            read,
            move |engine| {
                let result = lookup(Arc::clone(&keeper), &request, engine, &mut pending);
                let (conclusion, reason) = match &result {
                    Ok(_) => (AuditOperationResult::Committed, AuditReason::Verified),
                    Err(ReadError::Store(_)) => (
                        AuditOperationResult::Unknown,
                        AuditReason::MutationUncertain,
                    ),
                    Err(ReadError::Refused(error))
                        if error.code == latent_core::PlatformErrorCode::Unavailable =>
                    {
                        (
                            AuditOperationResult::Unknown,
                            AuditReason::MutationUncertain,
                        )
                    }
                    Err(_) => (AuditOperationResult::Rejected, AuditReason::Rejected),
                };
                let finish = pending.finish(
                    conclusion,
                    reason,
                    None,
                    !matches!(request, contract::Request::CancelCommand(_)),
                );
                if let Err(ReadError::Store(error)) = &result {
                    return Err(*error);
                }
                let result = result.map_err(ReadError::public);
                Ok((result, finish, keeper))
            },
        )
        .map_err(protected_error)?;
    let (result, finish, _keeper) = tokio::time::timeout_at(deadline.into(), job)
        .await
        .map_err(|_| expired())?
        .map_err(io_error)?
        .map_err(protected_error)?;
    inspection::read_ack(finish).await?;
    let (response, owner) = result?;
    let needed = response
        .encoded_len()
        .checked_mul(4)
        .and_then(|bytes| bytes.checked_add(16384))
        .ok_or_else(capacity)?;
    if needed > owner.read.permit.reserved_response_bytes() {
        return Err(capacity());
    }
    super::super::Phase4ResponseOwner::with_current(owner.as_ref(), &mut || {})?;
    Ok(OwnedPhase4Response::new(response, owner))
}

fn selector(request: &contract::Request) -> Result<&t::CommandSelector, PlatformError> {
    match request {
        contract::Request::LookupCommand(value) => value.command.as_ref().ok_or_else(invalid),
        contract::Request::LookupCommit(value) => value.command.as_ref().ok_or_else(invalid),
        contract::Request::GetEffect(value) => value.command.as_ref().ok_or_else(invalid),
        contract::Request::CancelCommand(value) => value
            .command
            .as_ref()
            .ok_or_else(invalid)?
            .command
            .as_ref()
            .ok_or_else(invalid),
        _ => Err(invalid()),
    }
}

fn operation(request: &contract::Request) -> &'static str {
    match request {
        contract::Request::CancelCommand(_) => "cancel-command",
        contract::Request::GetEffect(_) => "inspect-effect",
        _ => "read-result",
    }
}

fn lookup(
    read: Arc<ReadAuthority>,
    request: &contract::Request,
    engine: &EmbeddedStore,
    pending: &mut super::audit::Pending,
) -> Result<(contract::Response, Arc<ResponseOwner>), ReadError> {
    let source = read.inner.command_source.as_ref().ok_or_else(unsupported)?;
    // Original command time is sampled outside Policy/Namespace/Native fences.
    let time = source.command_time().map_err(|_| unsupported())?;
    read.before_lookup()?;
    let view = engine.snapshot()?;
    let tenant = latent_core::TenantId(read.key.tenant.clone());
    let namespace = NamespaceCatalog::read_in(&view, &tenant, &read.binding.namespace)
        .map_err(ReadError::namespace)?
        .ok_or_else(missing)?;
    if namespace.record().version.incarnation != read.binding.incarnation
        || namespace.record().state_schema != read.binding.state_schema
    {
        return Err(denied().into());
    }
    let lifecycle = read
        .inner
        .services
        .namespaces
        .lifecycle()
        .pin(&namespace)
        .map_err(namespace_error)?;
    let time = CommandTime {
        unix_millis: time.unix_millis,
        continuity_proven: time.continuity_proven,
    };
    let (record, result) = atomic::inspect(&view, &read.key, time, |_, record| {
        if record.is_some_and(|record| record.key() != &read.key) {
            return Err(AtomicError::Corrupt);
        }
        if record.is_some_and(|record| !record_matches(&read, record)) {
            return Err(AtomicError::PermissionDenied);
        }
        read.with_namespace(&namespace, &lifecycle, read.deadline, &mut || {})
            .map_err(|_| AtomicError::PermissionDenied)
    })
    .map_err(native_error)?;
    let (record, result) = match request {
        contract::Request::LookupCommand(value) => historical(
            &view,
            &read,
            record,
            result,
            value.attempt_id.as_deref(),
            time,
        )?,
        contract::Request::CancelCommand(value) => historical(
            &view,
            &read,
            record,
            result,
            value
                .command
                .as_ref()
                .ok_or_else(invalid)?
                .attempt_id
                .as_deref(),
            time,
        )?,
        _ => (record, result),
    };
    let payload = matches!(request, contract::Request::LookupCommand(_));
    let window = ResultWindow::capture(&record, result.as_ref().filter(|_| payload));
    let owner = Arc::new(ResponseOwner {
        namespace: Arc::new(namespace),
        lifecycle,
        window,
        read,
    });
    let response = match request {
        contract::Request::GetEffect(value) => effect::response(&view, &record, value, time)?,
        contract::Request::CancelCommand(value) => {
            cancellation::response(value, &record, &owner, pending)?
        }
        _ => projection::response(request, &record, result.as_ref())?,
    };
    Ok((response, owner))
}

fn record_matches(read: &ReadAuthority, record: &CommandRecord) -> bool {
    record.key() == &read.key
        && record.result_read_policy() == read.binding.result_policy
        && record.source().state_schema == read.binding.state_schema
}

fn historical(
    view: &ReadView,
    read: &ReadAuthority,
    current: CommandRecord,
    current_result: Option<DurableResult>,
    requested: Option<&str>,
    time: CommandTime,
) -> Result<(CommandRecord, Option<DurableResult>), ReadError> {
    let Some(requested) = requested else {
        return Ok((current, current_result));
    };
    let attempt: u64 = requested.parse().map_err(|_| invalid())?;
    if !(1..=16).contains(&attempt) || attempt.to_string() != requested {
        return Err(invalid().into());
    }
    if attempt == current.attempt() {
        return Ok((current, current_result));
    }
    let row = atomic::attempt_row_key(current.id(), attempt);
    let bytes = view.get(&row)?.ok_or_else(missing)?;
    atomic::validate_linked_row(view, &row, &bytes)?;
    let record = CommandRecord::decode(&bytes).map_err(native_error)?;
    if record.id() != current.id() || record.attempt() != attempt {
        return Err(StoreError::Corrupt.into());
    }
    if !record_matches(read, &record) {
        return Err(denied().into());
    }
    if !time.continuity_proven || time.unix_millis < record.clock_floor() {
        return Err(unsupported().into());
    }
    if time.unix_millis >= record.identity_expires() {
        return Err(expired().into());
    }
    let result =
        if record.outcome() != Outcome::Pending && time.unix_millis < record.result_expires() {
            let row = atomic::result_row_key(record.id(), attempt);
            let bytes = view
                .get(&row)?
                .ok_or(ReadError::Store(StoreError::Corrupt))?;
            atomic::validate_linked_row(view, &row, &bytes)?;
            let result = DurableResult::decode(&bytes).map_err(native_error)?;
            result.verify(&record).map_err(native_error)?;
            Some(result)
        } else {
            None
        };
    Ok((record, result))
}

fn native_error(error: AtomicError) -> ReadError {
    match error {
        AtomicError::Corrupt => return ReadError::Store(StoreError::Corrupt),
        AtomicError::UnsupportedFormat => return ReadError::Store(StoreError::UnsupportedFormat),
        AtomicError::Unavailable => return ReadError::Store(StoreError::Unavailable),
        AtomicError::NotFound => missing(),
        AtomicError::Expired => expired(),
        AtomicError::PermissionDenied => denied(),
        AtomicError::Invalid => invalid(),
        AtomicError::Limit => capacity(),
        _ => unsupported(),
    }
    .into()
}
