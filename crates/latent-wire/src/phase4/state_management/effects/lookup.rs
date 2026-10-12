use super::{
    c, capacity, contract, gate, input, io_error, native, projection, protected_error, Access, Arc,
    Catalog, EffectManagementAuthorization, Error, NamespaceRead, Phase, Plan, PlatformError,
    Receipt, Request,
};
use latent_commit::atomic::{
    command_identity, command_row_key, AtomicError, CommandRecord, Outcome as CommandOutcome,
};
use latent_core::transaction_contract::CommandKey;
use latent_effects::dispatch::EffectRecord;
use latent_effects::dispatch_store::effect_row_key;
use latent_state::{
    embedded::{ReadView, StoreError},
    namespace::catalog::NamespaceCatalog,
    store_io::StoreIoKind,
};

pub(super) struct Prepared {
    pub namespace: NamespaceRead,
    pub request: Request,
    pub plan: Option<Plan>,
    pub receipt: Option<Receipt>,
}
struct Completion {
    result: Result<Prepared, Error>,
    // Native values above retire before this exact original authorization.
    _access: Arc<Access>,
}
pub(super) async fn prepare(
    access: Arc<Access>,
    request: contract::Request,
) -> Result<Prepared, PlatformError> {
    let worker = Arc::clone(&access);
    let retained_bytes = u64::try_from(request.encoded_len())
        .ok()
        .and_then(|bytes| bytes.checked_mul(4))
        .and_then(|bytes| bytes.checked_add(512 * 1024))
        .ok_or_else(capacity)?;
    let job = access
        .inner
        .services
        .store
        .with_store_retaining(
            StoreIoKind::RecoveryRead,
            retained_bytes,
            Arc::new(Arc::clone(&access)),
            move |engine| {
                let result = (|| {
                    worker.before_lookup()?;
                    let view = engine.snapshot()?;
                    let namespace = NamespaceCatalog::read_in(
                        &view,
                        worker
                            .principal
                            .tenant
                            .as_ref()
                            .ok_or(Error::PermissionDenied)?,
                        &worker.namespace.binding.namespace,
                    )
                    .map_err(namespace_error)?
                    .ok_or(Error::NotFound)?;
                    worker.with_current(&namespace, Phase::Read, worker.action, &mut || Ok(()))?;
                    let original = input::original(&request).map_err(|error| gate(&error))?;
                    let command = command(&view, &worker, original)?;
                    let native_request = input::native_request(&worker, original, &command)?;
                    verify_effect(&view, &worker, original, &command)?;
                    let plan = Catalog::plan_for_actor(
                        &view,
                        &native_request.input().actor_tenant,
                        &native_request.input().actor_subject,
                        &native_request.input().operation_id,
                    )?;
                    if let Some(plan) = &plan {
                        if plan.request() != &native_request {
                            return Err(Error::Conflict);
                        }
                        if let Some(supplied) = input::supplied_plan(&request) {
                            let public =
                                projection::plan(plan, original).map_err(|error| gate(&error))?;
                            if &public != supplied {
                                return Err(Error::Conflict);
                            }
                        }
                    } else if input::supplied_plan(&request).is_some() {
                        return Err(Error::NotFound);
                    }
                    let receipt = plan
                        .as_ref()
                        .map(|plan| Catalog::lookup(&view, plan))
                        .transpose()?
                        .flatten();
                    worker.with_current(&namespace, Phase::Read, worker.action, &mut || {
                        worker.with_live(&mut || Ok(()))
                    })?;
                    Ok(Prepared {
                        namespace,
                        request: native_request,
                        plan,
                        receipt,
                    })
                })();
                if let Err(Error::Store(error)) = result {
                    return Err(error);
                }
                Ok(Completion {
                    result,
                    _access: worker,
                })
            },
        )
        .map_err(protected_error)?;
    let completion = job.await.map_err(io_error)?.map_err(protected_error)?;
    completion.result.map_err(native)
}

fn command(
    view: &ReadView,
    access: &Access,
    original: &c::PlanEffectMutationRequest,
) -> Result<CommandRecord, Error> {
    let selector = original
        .effect
        .as_ref()
        .ok_or(Error::Invalid)?
        .command
        .as_ref()
        .ok_or(Error::Invalid)?;
    let namespace = selector.namespace.as_ref().ok_or(Error::Invalid)?;
    let key = CommandKey {
        tenant: access
            .principal
            .tenant
            .as_ref()
            .ok_or(Error::PermissionDenied)?
            .0
            .clone(),
        namespace: access.namespace.binding.namespace.0.clone(),
        incarnation: access.namespace.binding.incarnation.to_string(),
        recovery_scope: access.caller.scope.clone(),
        operation: selector.operation.clone(),
        entity: selector.entity.clone(),
        client_key: selector.client_key.clone(),
    };
    if namespace.tenant != key.tenant
        || namespace.namespace != key.namespace
        || namespace.incarnation != key.incarnation
    {
        return Err(Error::PermissionDenied);
    }
    let identity = command_identity(&key).map_err(atomic_error)?;
    let bytes = view
        .get(&command_row_key(identity))?
        .ok_or(Error::NotFound)?;
    let record = CommandRecord::decode(&bytes).map_err(atomic_error)?;
    if record.id() != identity || record.key() != &key {
        return Err(StoreError::Corrupt.into());
    }
    if record.result_read_policy() != access.namespace.binding.result_policy {
        return Err(Error::PermissionDenied);
    }
    if record.outcome() != CommandOutcome::Committed {
        return Err(Error::Conflict);
    }
    Ok(record)
}

fn verify_effect(
    view: &ReadView,
    access: &Access,
    original: &c::PlanEffectMutationRequest,
    record: &CommandRecord,
) -> Result<(), Error> {
    let effect = original.effect.as_ref().ok_or(Error::Invalid)?;
    let row = effect_row_key(&effect.effect_id)?;
    let bytes = view.get(&row)?.ok_or(Error::NotFound)?;
    latent_effects::dispatch_store::validate_row(&row, &bytes)?;
    let stored = EffectRecord::decode(&bytes)?;
    let authority = stored.authority()?;
    let scope = authority.scope();
    let link = authority.link();
    if scope.tenant != record.key().tenant
        || scope.namespace != record.key().namespace
        || scope.incarnation != access.namespace.binding.incarnation
        || scope.publication != record.source().publication
        || link.command != record.id().hex()
        || link.caller_scope != record.key().recovery_scope
        || link.attempt != record.attempt()
        || link.commit != record.disposition_id().hex()
        || link.effect != effect.effect_id
        || link.sequence >= 128
        || record.effect_id(link.sequence).hex() != effect.effect_id
        || !record
            .effect_ids()
            .contains(&record.effect_id(link.sequence))
    {
        return Err(Error::PermissionDenied);
    }
    Ok(())
}
fn atomic_error(error: AtomicError) -> Error {
    match error {
        AtomicError::UnsupportedFormat => Error::Store(StoreError::UnsupportedFormat),
        AtomicError::Unavailable => Error::Store(StoreError::Unavailable),
        AtomicError::RecoveryRequired => Error::Store(StoreError::CommitUncertain),
        AtomicError::Limit => Error::Capacity,
        _ => Error::Store(StoreError::Corrupt),
    }
}
fn namespace_error(error: latent_state::namespace::NamespaceError) -> Error {
    use latent_state::namespace::NamespaceError as E;
    match error {
        E::UnsupportedFormat => Error::Store(StoreError::UnsupportedFormat),
        E::Corrupt | E::Invalid => Error::Store(StoreError::Corrupt),
        E::Capacity => Error::Capacity,
        E::PermissionDenied => Error::PermissionDenied,
        E::Conflict | E::InUse => Error::Conflict,
        E::Unavailable | E::RecoveryRequired | E::Cancelled => Error::RecoveryRequired,
    }
}
