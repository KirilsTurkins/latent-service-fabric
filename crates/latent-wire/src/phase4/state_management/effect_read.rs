//! Read-only original effect status on the installed recovery and policy owners.
use super::{
    audit, authorization, capacity, contract, denied, expired, inspection, invalid, io_error,
    missing, protected_error, recovery_bindings, Arc, AuthenticatedInvocationContext, Inner,
    Instant, OwnedPhase4Response, PlatformError, StateManagementReservation, WORK_BYTES,
};
use latent_capabilities::namespace::CallerScope;
use latent_commit::atomic::{command_identity, command_row_key, CommandRecord, Outcome};
use latent_core::transaction_contract::CommandKey;
use latent_effects::dispatch::{
    effect_record_version, Disposition, EffectManagementFact, EffectRecord,
};
use latent_policy::capability::OwnedPolicyDecision;
use latent_rpc::transaction::v1 as t;
use latent_state::{
    embedded::{ReadView, StoreError},
    namespace::catalog::NamespaceRead,
    protected_store::ProtectedStoreView,
};
use prost::Message;
use sha2::{Digest, Sha256};
use std::sync::Mutex;

pub(super) fn original(request: &contract::Request) -> Option<&t::GetEffectRequest> {
    match request {
        contract::Request::GetEffect(value) => Some(value),
        contract::Request::ListEffectHistory(value) => value.effect.as_ref(),
        _ => None,
    }
}
pub(super) fn handles(request: &contract::Request) -> bool {
    original(request).is_some()
}

struct Keeper {
    inner: Arc<Inner>,
    access: authorization::Access,
    principal: latent_core::InvocationPrincipal,
    caller: CallerScope,
    entity: Option<String>,
    decision: OwnedPolicyDecision,
    permit: Arc<dyn StateManagementReservation>,
    deadline: Instant,
}
impl Keeper {
    fn before(&self) -> Result<(), PlatformError> {
        if self.inner.services.clock.monotonic_now() >= self.deadline {
            return Err(expired());
        }
        self.inner.services.policy.with_retained_decisions(&[&self.access.inspect, &self.decision],
            &mut |inputs| {
                let actual = inputs.get(1).ok_or_else(denied)?;
                let binding = &self.access.binding;
                if actual.principal.subject != self.principal.subject
                    || actual.principal.kind != self.principal.kind
                    || actual.principal.tenant != self.principal.tenant
                    || actual.principal.service != self.principal.service
                    || actual.service != binding.service.0
                    || actual.publication != binding.publication.id.as_str()
                    || actual.operation != "inspect-effect"
                    || actual.capability != latent_capabilities::namespace::STATE_CONTRACT
                    || !matches!(actual.resource, latent_policy::capability::ResourceTarget::State {
                        namespace, incarnation, entity, recovery_kind, recovery_scope, result_policy
                    } if namespace == binding.namespace.0 && incarnation == binding.incarnation
                        && entity == self.entity.as_deref() && recovery_kind == self.caller.kind
                        && recovery_scope == self.caller.scope && result_policy == binding.result_policy)
                { return Err(denied()); }
                self.permit.with_live(&mut || {})
            })
    }
    fn current(
        &self,
        read: &NamespaceRead,
        publish: &mut dyn FnMut(),
    ) -> Result<(), PlatformError> {
        self.before()?;
        inspection::inspection_gate(&self.inner, &self.access, read, None)?;
        self.inner.services.policy.with_retained_decisions(
            &[&self.access.inspect, &self.decision],
            &mut |_| {
                if read.record().state_schema != self.access.binding.state_schema {
                    return Err(denied());
                }
                self.inner
                    .services
                    .namespaces
                    .lifecycle()
                    .with_current_record(read, || {
                        let mut count = 0_u8;
                        let result = self.permit.with_live(&mut || {
                            count = count.saturating_add(1);
                            if count == 1 {
                                publish();
                            }
                        });
                        if count != 1 || result.is_err() {
                            return Err(latent_state::namespace::NamespaceError::PermissionDenied);
                        }
                        Ok(())
                    })
                    .map_err(super::namespace_error)
            },
        )
    }
}
struct Owner {
    read: NamespaceRead,
    _view: Mutex<Option<ProtectedStoreView>>,
    keeper: Arc<Keeper>,
}
impl crate::phase4::Phase4ResponseOwner for Owner {
    fn reserved_bytes(&self) -> usize {
        self.keeper.permit.reserved_response_bytes()
    }
    fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        self.keeper.current(&self.read, publish)
    }
}

pub(super) async fn execute(
    inner: Arc<Inner>,
    context: AuthenticatedInvocationContext,
    request: contract::Request,
    access: authorization::Access,
    permit: Arc<dyn StateManagementReservation>,
    deadline: Instant,
) -> Result<OwnedPhase4Response, PlatformError> {
    let original = original(&request).ok_or_else(invalid)?.clone();
    let page = match &request {
        contract::Request::ListEffectHistory(value) => {
            Some(value.page.as_ref().ok_or_else(invalid)?.clone())
        }
        _ => None,
    };
    let command = original.command.as_ref().ok_or_else(invalid)?;
    let caller =
        recovery_bindings::scope(&inner, &context, command.shared_recovery_scope.as_deref())?;
    let decision = authorization::EffectDecision {
        services: &inner.services,
        binding: &access.binding,
        context: &context,
        caller: &caller,
        entity: command.entity.as_deref(),
        deadline,
        input_bytes: request.encoded_len(),
    }
    .seal("inspect-effect")?;
    if decision.requires_audit() && inner.services.audit.is_none() {
        return Err(super::unsupported());
    }
    let pending = audit::begin(&inner, &access, &context, &request).await?;
    let keeper = Arc::new(Keeper {
        inner: Arc::clone(&inner),
        access,
        principal: context.principal().clone(),
        caller,
        entity: command.entity.clone(),
        decision,
        permit,
        deadline,
    });
    keeper.before()?;
    let view = inner
        .services
        .store
        .open_recovery_view_retaining(keeper.clone())
        .map_err(protected_error)?
        .await
        .map_err(io_error)?
        .map_err(protected_error)?;
    let worker = Arc::clone(&keeper);
    let job = inner
        .services
        .store
        .with_view(view, WORK_BYTES as u64, move |view| {
            let result = inspect_in(view, &worker, &original).map(|result| match result {
                Ok((read, effect)) => {
                    let response = if let Some(page) = &page {
                        history_in(view, &worker, &read, &original, &effect, page)
                    } else {
                        Ok(t::GetEffectResponse {
                            effect: Some(effect),
                        }
                        .into())
                    };
                    response.map(|response| (read, response))
                }
                Err(error) => Err(error),
            });
            let finish = pending.finish(
                if result.as_ref().is_ok_and(Result::is_ok) {
                    latent_audit::AuditOperationResult::Committed
                } else {
                    latent_audit::AuditOperationResult::Rejected
                },
                latent_audit::AuditReason::Verified,
                None,
                false,
            );
            result.map(|value| (value, finish))
        })
        .map_err(protected_error)?;
    let (view, result) = job.await.map_err(io_error)?;
    let (result, finish) = result.map_err(protected_error)?;
    inspection::read_ack(finish).await?;
    let (read, response) = result?;
    let needed = response
        .encoded_len()
        .checked_mul(4)
        .and_then(|n| n.checked_add(16384))
        .ok_or_else(capacity)?;
    if needed > keeper.permit.reserved_response_bytes() {
        return Err(capacity());
    }
    let owner = Arc::new(Owner {
        read,
        _view: Mutex::new(Some(view)),
        keeper,
    });
    crate::phase4::Phase4ResponseOwner::with_current(owner.as_ref(), &mut || {})?;
    Ok(OwnedPhase4Response::new(response, owner))
}

fn inspect_in(
    view: &ReadView,
    keeper: &Keeper,
    request: &t::GetEffectRequest,
) -> Result<Result<(NamespaceRead, t::EffectReceipt), PlatformError>, StoreError> {
    if let Err(error) = keeper.before() {
        return Ok(Err(error));
    }
    let Some(read) =
        inspection::read_in(view, &keeper.access).map_err(inspection::native_namespace)?
    else {
        return Ok(Err(missing()));
    };
    if let Err(error) = keeper.current(&read, &mut || {}) {
        return Ok(Err(error));
    }
    let selector = request.command.as_ref().ok_or(StoreError::Invalid)?;
    let binding = &keeper.access.binding;
    let key = CommandKey {
        tenant: keeper
            .principal
            .tenant
            .as_ref()
            .ok_or(StoreError::Invalid)?
            .0
            .clone(),
        namespace: binding.namespace.0.clone(),
        incarnation: binding.incarnation.to_string(),
        recovery_scope: keeper.caller.scope.clone(),
        operation: selector.operation.clone(),
        entity: selector.entity.clone(),
        client_key: selector.client_key.clone(),
    };
    let id = command_identity(&key).map_err(|_| StoreError::Invalid)?;
    let Some(raw) = view.get(&command_row_key(id))? else {
        return Ok(Err(missing()));
    };
    let command = CommandRecord::decode(&raw).map_err(|_| StoreError::Corrupt)?;
    if command.id() != id || command.key() != &key {
        return Err(StoreError::Corrupt);
    }
    if command.result_read_policy() != binding.result_policy
        || command.outcome() != Outcome::Committed
    {
        return Ok(Err(denied()));
    }
    let state_scope = latent_state::session::StateScope {
        tenant: keeper
            .principal
            .tenant
            .as_ref()
            .ok_or(StoreError::Invalid)?
            .clone(),
        namespace: binding.namespace.clone(),
        incarnation: binding.incarnation,
        state_schema: command.source().state_schema.clone(),
        entity: key.entity.clone(),
        mode: latent_state::session::StateMode::Query,
    };
    let current = latent_state::session::version::capture_view_identity(view, &state_scope)
        .map_err(|error| error.storage_error().unwrap_or(StoreError::Unavailable))?;
    if let Some(original) = command.committed_view_token() {
        current
            .require_minimum(&state_scope, original)
            .map_err(|error| error.storage_error().unwrap_or(StoreError::Unavailable))?;
    }
    let row = latent_effects::dispatch_store::effect_row_key(&request.effect_id)?;
    let Some(raw) = view.get(&row)? else {
        return Ok(Err(missing()));
    };
    latent_effects::dispatch_store::validate_row(&row, &raw)?;
    let record = EffectRecord::decode(&raw).map_err(|_| StoreError::Corrupt)?;
    if !valid_link(&command, &record, &request.effect_id, binding.incarnation)? {
        return Ok(Err(denied()));
    }
    let effect = effect_status(view, &command, &record, &raw, &request.effect_id)?;
    if let Err(error) = keeper.current(&read, &mut || {}) {
        return Ok(Err(error));
    }
    Ok(Ok((read, effect)))
}
fn effect_status(
    view: &ReadView,
    command: &CommandRecord,
    record: &EffectRecord,
    raw: &[u8],
    effect_id: &str,
) -> Result<t::EffectReceipt, StoreError> {
    let authority = record.authority().map_err(|_| StoreError::Corrupt)?;
    let payload_available = payload_available(view, record)?;
    let management_operation_receipt_id = management_receipt_id(view, record)?;
    let management = record.management();
    let latest = record.latest();
    let disposition =
        if management.is_some_and(|m| m.fact() == EffectManagementFact::AdministratorTerminated) {
            t::EffectDisposition::AdministrativelyTerminated
        } else {
            disposition(record.disposition())
        };
    let effect = t::EffectReceipt {
        effect_id: effect_id.into(),
        command_id: command.id().hex(),
        command_attempt_id: command.attempt_id().hex(),
        dispatch_attempt: record.attempts(),
        disposition: disposition as i32,
        provider_receipt: management
            .and_then(|stamp| stamp.provider_receipt().map(str::to_owned))
            .or_else(|| latest.and_then(|receipt| receipt.provider_receipt.clone())),
        failure_code: if management
            .is_some_and(|stamp| stamp.fact() == EffectManagementFact::ProviderConfirmed)
        {
            None
        } else {
            latest.map(|receipt| receipt.reason.clone())
        },
        occurred_at_unix_millis: management.map_or_else(
            || {
                latest.map_or(authority.committed_at_millis(), |receipt| {
                    receipt.observed_at_millis
                })
            },
            latent_effects::dispatch::EffectManagementStamp::observed_at_millis,
        ),
        retention: Some(t::LinkedRetention {
            record_format: "lsf-effect-record".into(),
            record_version: 1,
            payload_expires_at_unix_millis: Some(authority.expires_at_millis()),
            identity_expires_at_unix_millis: Some(command.identity_expires()),
            remaining_recovery_millis: None,
            required_record_ids: vec![command.id().hex()],
            payload_available,
        }),
        management_operation_receipt_id,
        provider_profile: authority.profile().adapter.clone(),
        record_version: effect_record_version(raw)
            .map_err(|_| StoreError::Corrupt)?
            .to_vec(),
        owner_epoch: (record.owner_epoch() != 0).then_some(record.owner_epoch()),
        claim_generation: (record.claim_generation() != 0).then_some(record.claim_generation()),
    };
    Ok(effect)
}

fn payload_available(view: &ReadView, record: &EffectRecord) -> Result<bool, StoreError> {
    let authority = record.authority().map_err(|_| StoreError::Corrupt)?;
    match view.get(&latent_effects::dispatch_store::effect_payload_key(
        &authority.link().effect,
    )?)? {
        Some(bytes) => {
            latent_effects::payload::PayloadRecord::decode(&bytes)
                .map_err(|_| StoreError::Corrupt)?
                .verify(&authority)
                .map_err(|_| StoreError::Corrupt)?;
            Ok(true)
        }
        None if record.disposition().terminal() => Ok(false),
        None => Err(StoreError::Corrupt),
    }
}

fn management_receipt_id(
    view: &ReadView,
    record: &EffectRecord,
) -> Result<Option<String>, StoreError> {
    let receipt =
        latent_effects::dispatch_store::effect_management::EffectManagementCatalog::receipt_for_effect(
            view, record,
        )?;
    receipt
        .as_ref()
        .map(|receipt| {
            receipt
                .digest()
                .map(|digest| format!("effect-management:sha256:{}", super::response::hex(&digest)))
        })
        .transpose()
        .map_err(|_| StoreError::Corrupt)
}

fn valid_link(
    command: &CommandRecord,
    record: &EffectRecord,
    effect: &str,
    incarnation: u64,
) -> Result<bool, StoreError> {
    let authority = record.authority().map_err(|_| StoreError::Corrupt)?;
    let key = command.key();
    let link = authority.link();
    let scope = authority.scope();
    if scope.tenant != key.tenant
        || scope.namespace != key.namespace
        || scope.incarnation != incarnation
        || scope.publication != command.source().publication
        || link.command != command.id().hex()
        || link.caller_scope != key.recovery_scope
        || link.attempt != command.attempt()
        || link.commit != command.disposition_id().hex()
        || link.effect != effect
        || link.sequence >= 128
        || command.effect_id(link.sequence).hex() != effect
        || !command
            .effect_ids()
            .contains(&command.effect_id(link.sequence))
    {
        return Ok(false);
    }
    Ok(true)
}
fn disposition(value: Disposition) -> t::EffectDisposition {
    match value {
        Disposition::Pending => t::EffectDisposition::Pending,
        Disposition::Dispatching => t::EffectDisposition::Dispatching,
        Disposition::ProviderAcknowledged => t::EffectDisposition::ProviderAcknowledged,
        Disposition::KnownFailed => t::EffectDisposition::KnownFailure,
        Disposition::Uncertain => t::EffectDisposition::UncertainAfterDispatch,
        Disposition::RetryScheduled => t::EffectDisposition::RetryScheduled,
        Disposition::PolicyBlocked => t::EffectDisposition::PolicyBlocked,
        Disposition::Expired => t::EffectDisposition::Expired,
        Disposition::DeadLettered => t::EffectDisposition::DeadLettered,
    }
}

fn cursor_binding(keeper: &Keeper, request: &t::GetEffectRequest) -> [u8; 32] {
    let mut hash = Sha256::new();
    hash.update(b"lsf-effect-history-rpc-cursor-v1\0");
    hash.update(request.encode_to_vec());
    for text in [
        &keeper.caller.owner_kind,
        &keeper.caller.scope,
        &keeper.access.binding.result_policy,
        &keeper.access.binding.state.configuration_digest,
    ] {
        hash.update((text.len() as u64).to_le_bytes());
        hash.update(text.as_bytes());
    }
    hash.update(
        keeper
            .access
            .binding
            .state
            .configuration_epoch
            .to_le_bytes(),
    );
    hash.finalize().into()
}
fn history_in(
    view: &ReadView,
    keeper: &Keeper,
    read: &NamespaceRead,
    original: &t::GetEffectRequest,
    current: &t::EffectReceipt,
    page: &t::PageRequest,
) -> Result<contract::Response, PlatformError> {
    let version =
        inspection::namespace_view(view, read.record()).map_err(|_| super::unsupported())?;
    let binding = cursor_binding(keeper, original);
    let after = if let Some(raw) = &page.cursor {
        let length = 3 + 32 + version.len() + 8;
        if raw.len() != length
            || &raw[..3] != b"EH\x01"
            || raw[3..35] != binding
            || raw[35..35 + version.len()] != version
        {
            return Err(invalid());
        }
        let sequence = u64::from_be_bytes(
            raw[35 + version.len()..]
                .try_into()
                .map_err(|_| invalid())?,
        );
        let key = latent_effects::dispatch_store::HistoryRecord {
            sequence,
            effect: original.effect_id.clone(),
            attempt: None,
            receipt: latent_effects::dispatch::AttemptReceipt {
                disposition: Disposition::Pending,
                reason: "cursor-position".into(),
                provider_receipt: None,
                observed_at_millis: 1,
            },
        }
        .key()
        .map_err(|_| invalid())?;
        Some(key.key)
    } else {
        None
    };
    keeper.current(read, &mut || {})?;
    let history = latent_effects::dispatch_store::DispatchCatalog::history_page(
        view,
        &original.effect_id,
        after.as_deref(),
        page.limit as usize,
        contract::MAX_PAGE_BYTES,
    )
    .map_err(|_| super::unsupported())?;
    let mut rows = Vec::with_capacity(history.rows.len());
    for row in history.rows {
        if row.effect != original.effect_id {
            return Err(super::unsupported());
        }
        if let Some(attempt) = &row.attempt {
            if attempt.effect() != original.effect_id
                || attempt.attempt() > current.dispatch_attempt
                || attempt.owner_epoch() == 0
                || attempt.claim_generation() == 0
            {
                return Err(super::unsupported());
            }
        }
        let mut item = current.clone();
        item.disposition = disposition(row.receipt.disposition) as i32;
        item.provider_receipt = row.receipt.provider_receipt;
        item.failure_code = Some(row.receipt.reason);
        item.occurred_at_unix_millis = row.receipt.observed_at_millis;
        item.record_version.clear();
        item.management_operation_receipt_id = None;
        item.dispatch_attempt = row
            .attempt
            .as_ref()
            .map_or(0, latent_effects::dispatch::AttemptIdentity::attempt);
        item.owner_epoch = row
            .attempt
            .as_ref()
            .map(latent_effects::dispatch::AttemptIdentity::owner_epoch);
        item.claim_generation = row
            .attempt
            .as_ref()
            .map(latent_effects::dispatch::AttemptIdentity::claim_generation);
        rows.push(item);
    }
    let next = history
        .resume
        .map(|after| -> Result<Vec<u8>, PlatformError> {
            let sequence = after
                .get(after.len().checked_sub(8).ok_or_else(invalid)?..)
                .ok_or_else(invalid)?;
            let mut raw = Vec::with_capacity(3 + 32 + version.len() + 8);
            raw.extend_from_slice(b"EH\x01");
            raw.extend_from_slice(&binding);
            raw.extend_from_slice(&version);
            raw.extend_from_slice(sequence);
            Ok(raw)
        })
        .transpose()?;
    let encoded = rows.iter().try_fold(0usize, |sum, row| {
        sum.checked_add(row.encoded_len()).ok_or_else(capacity)
    })?;
    if encoded > contract::MAX_PAGE_BYTES {
        return Err(capacity());
    }
    keeper.current(read, &mut || {})?;
    Ok(t::ListEffectHistoryResponse {
        page: Some(t::PageResponse {
            next_cursor: next,
            returned_count: u32::try_from(rows.len()).map_err(|_| capacity())?,
            encoded_bytes: encoded as u64,
        }),
        receipts: rows,
    }
    .into())
}
