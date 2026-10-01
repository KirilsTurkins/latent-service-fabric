use super::{
    bounds::{decimal, digest, required, Budget},
    Request, ValidationError, MAX_PAGE_ENTRIES, MAX_REQUEST_BYTES,
};
use crate::{control::v1 as c, invocation::v1 as i, transaction::v1 as t};
use std::collections::BTreeSet;

pub(super) fn validate(request: &Request) -> Result<(), ValidationError> {
    let mut b = Budget::new::<Request>(MAX_REQUEST_BYTES)?;
    b.charge(request.native_message_bytes())?;
    match request {
        Request::InspectDispatcher(value) => super::dispatcher::inspect(&mut b, value),
        Request::ControlDispatcher(value) => super::dispatcher::control(&mut b, value),
        Request::GetDispatcherOperation(value) => {
            super::dispatcher::control(&mut b, required(value.original.as_ref())?)
        }
        Request::InspectNamespace(value) => inspect(&mut b, value),
        Request::MutateNamespace(value) => validate_namespace_mutation(&mut b, value),
        Request::SelectEntity(value) => {
            inspect(&mut b, required(value.namespace.as_ref())?)?;
            if let Some(prefix) = &value.prefix {
                b.bytes(prefix, 256)?;
            }
            page(&mut b, required(value.page.as_ref())?)
        }
        Request::MutateState(value) => {
            inspect(&mut b, required(value.namespace.as_ref())?)?;
            b.id(&value.operation_id)?;
            b.optional_id(value.record_id.as_ref())?;
            b.opaque(&value.expected_version)?;
            b.string(&value.expected_policy_digest, 71)?;
            digest(&value.expected_policy_digest)?;
            reason(&mut b, &value.reason)?;
            match c::StateMutationKind::try_from(value.mutation) {
                Ok(c::StateMutationKind::CheckpointNamespace) => {
                    if value.record_id.is_some() {
                        Err(ValidationError::Shape)
                    } else {
                        Ok(())
                    }
                }
                Ok(
                    c::StateMutationKind::RetryKnownFailedEffect
                    | c::StateMutationKind::TerminateEffect
                    | c::StateMutationKind::PurgeExpiredPayload,
                ) => {
                    if value.record_id.is_none() {
                        Err(ValidationError::Shape)
                    } else {
                        Ok(())
                    }
                }
                _ => Err(ValidationError::Shape),
            }
        }
        Request::GetStateOperationReceipt(value) => {
            inspect(&mut b, required(value.namespace.as_ref())?)?;
            b.id(&value.operation_id)
        }
        Request::LookupCommand(value) => lookup(&mut b, value),
        Request::LookupCommit(value) => {
            profile(&mut b, required(value.profile.as_ref())?)?;
            command(&mut b, required(value.command.as_ref())?)?;
            publication(
                &mut b,
                required(value.authorization_publication.as_ref())?,
                &required(required(value.command.as_ref())?.namespace.as_ref())?.tenant,
            )?;
            b.id(&value.receipt_id)
        }
        Request::GetEffect(value) => effect(&mut b, value),
        Request::ListEffectHistory(value) => {
            effect(&mut b, required(value.effect.as_ref())?)?;
            page(&mut b, required(value.page.as_ref())?)
        }
        Request::CancelCommand(value) => {
            lookup(&mut b, required(value.command.as_ref())?)?;
            reason(&mut b, &value.reason)
        }
        Request::InvokeCommand(value) => validate_command_input(&mut b, value),
        Request::Query(value) => {
            profile(&mut b, required(value.profile.as_ref())?)?;
            let selector = required(value.namespace.as_ref())?;
            namespace(&mut b, selector)?;
            if let Some(entity) = &value.entity {
                b.identity(entity)?;
            }
            invocation(
                &mut b,
                required(value.invocation.as_ref())?,
                &selector.tenant,
            )?;
            if let Some(version) = &value.minimum_view_version {
                b.opaque(version)?;
            }
            Ok(())
        }
    }
}

pub(super) fn tenant(request: &Request) -> Option<&str> {
    fn inspect(value: &c::InspectNamespaceRequest) -> Option<&t::NamespaceSelector> {
        value.namespace.as_ref()
    }
    let namespace = match request {
        Request::InspectDispatcher(_)
        | Request::ControlDispatcher(_)
        | Request::GetDispatcherOperation(_) => None,
        Request::InspectNamespace(v) => inspect(v),
        Request::MutateNamespace(v) => v.namespace.as_ref().and_then(inspect),
        Request::SelectEntity(v) => v.namespace.as_ref().and_then(inspect),
        Request::MutateState(v) => v.namespace.as_ref().and_then(inspect),
        Request::GetStateOperationReceipt(v) => v.namespace.as_ref().and_then(inspect),
        Request::InvokeCommand(v) => v.command.as_ref().and_then(|v| v.namespace.as_ref()),
        Request::Query(v) => v.namespace.as_ref(),
        Request::LookupCommand(v) => v.command.as_ref().and_then(|v| v.namespace.as_ref()),
        Request::LookupCommit(v) => v.command.as_ref().and_then(|v| v.namespace.as_ref()),
        Request::GetEffect(v) => v.command.as_ref().and_then(|v| v.namespace.as_ref()),
        Request::ListEffectHistory(v) => v
            .effect
            .as_ref()
            .and_then(|v| v.command.as_ref())
            .and_then(|v| v.namespace.as_ref()),
        Request::CancelCommand(v) => v
            .command
            .as_ref()
            .and_then(|v| v.command.as_ref())
            .and_then(|v| v.namespace.as_ref()),
    };
    namespace.map(|value| value.tenant.as_str())
}

pub(super) fn profile(
    b: &mut Budget,
    value: &t::TransactionProfile,
) -> Result<(), ValidationError> {
    b.string(&value.profile, 64)?;
    b.string(&value.host_abi_digest, 71)?;
    b.string(&value.preparation_profile_digest, 71)?;
    if value != &super::current_profile() {
        return Err(ValidationError::UnsupportedProfile);
    }
    Ok(())
}
pub(super) fn namespace(
    b: &mut Budget,
    value: &t::NamespaceSelector,
) -> Result<(), ValidationError> {
    b.id(&value.tenant)?;
    b.id(&value.namespace)?;
    b.string(&value.incarnation, 20)?;
    decimal(&value.incarnation, true)?;
    Ok(())
}
pub(super) fn publication(
    b: &mut Budget,
    value: &c::PublicationRef,
    tenant: &str,
) -> Result<(), ValidationError> {
    b.id(&value.tenant)?;
    b.string(&value.id, 83)?;
    value
        .id
        .parse::<latent_core::PublicationId>()
        .map_err(|_| ValidationError::Shape)?;
    if value.tenant != tenant {
        return Err(ValidationError::Association);
    }
    Ok(())
}
pub(super) fn inspect(
    b: &mut Budget,
    value: &c::InspectNamespaceRequest,
) -> Result<(), ValidationError> {
    profile(b, required(value.profile.as_ref())?)?;
    let selector = required(value.namespace.as_ref())?;
    namespace(b, selector)?;
    publication(
        b,
        required(value.authorization_publication.as_ref())?,
        &selector.tenant,
    )
}
pub(super) fn command(b: &mut Budget, value: &t::CommandSelector) -> Result<(), ValidationError> {
    namespace(b, required(value.namespace.as_ref())?)?;
    b.identity(&value.operation)?;
    b.identity(&value.client_key)?;
    for value in [&value.entity, &value.shared_recovery_scope]
        .into_iter()
        .flatten()
    {
        b.identity(value)?;
    }
    Ok(())
}
pub(super) fn lookup(
    b: &mut Budget,
    value: &t::LookupCommandRequest,
) -> Result<(), ValidationError> {
    profile(b, required(value.profile.as_ref())?)?;
    command(b, required(value.command.as_ref())?)?;
    b.optional_id(value.attempt_id.as_ref())?;
    publication(
        b,
        required(value.authorization_publication.as_ref())?,
        &required(required(value.command.as_ref())?.namespace.as_ref())?.tenant,
    )
}
pub(super) fn effect(b: &mut Budget, value: &t::GetEffectRequest) -> Result<(), ValidationError> {
    profile(b, required(value.profile.as_ref())?)?;
    command(b, required(value.command.as_ref())?)?;
    publication(
        b,
        required(value.authorization_publication.as_ref())?,
        &required(required(value.command.as_ref())?.namespace.as_ref())?.tenant,
    )?;
    b.id(&value.effect_id)
}
pub(super) fn page(b: &mut Budget, value: &t::PageRequest) -> Result<(), ValidationError> {
    if value.limit == 0 || value.limit as usize > MAX_PAGE_ENTRIES {
        return Err(ValidationError::Capacity);
    }
    if let Some(cursor) = &value.cursor {
        b.opaque(cursor)?;
    }
    Ok(())
}
pub(super) fn abort_fence(b: &mut Budget, value: &t::AbortFence) -> Result<(), ValidationError> {
    b.id(&value.command_id)?;
    b.id(&value.attempt_id)?;
    b.id(&value.transaction_id)?;
    b.opaque(&value.owner_fence)
}
fn reason(b: &mut Budget, value: &String) -> Result<(), ValidationError> {
    b.string(value, 1024)?;
    if value.is_empty() || value.chars().any(char::is_control) {
        return Err(ValidationError::Shape);
    }
    Ok(())
}
pub(super) fn quota(value: &c::NamespaceQuota) -> Result<(), ValidationError> {
    if [value.state_keys, value.result_rows, value.effect_rows]
        .iter()
        .any(|v| *v == 0 || *v > 1_000_000)
        || [
            value.state_bytes,
            value.result_bytes,
            value.effect_bytes,
            value.payload_bytes,
            value.recovery_bytes,
        ]
        .iter()
        .any(|v| *v == 0 || *v > 1024 * 1024 * 1024)
        || value.recovery_bytes > value.result_bytes
    {
        return Err(ValidationError::Shape);
    }
    Ok(())
}
fn invocation(
    b: &mut Budget,
    value: &i::InvokeRequest,
    tenant: &str,
) -> Result<(), ValidationError> {
    for id in [
        value.activation_id.as_ref(),
        value.parent_activation_id.as_ref(),
        value.root_activation_id.as_ref(),
        value.idempotency_key.as_ref(),
    ]
    .into_iter()
    .flatten()
    {
        b.id(id)?;
    }
    if value.parent_activation_id.is_some() && value.root_activation_id.is_none() {
        return Err(ValidationError::Shape);
    }
    let target = required(value.target.as_ref())?;
    for id in [
        &target.tenant,
        &target.service,
        &target.contract,
        &target.function,
    ]
    .into_iter()
    .chain(target.route.iter())
    {
        b.id(id)?;
    }
    if target.tenant != tenant {
        return Err(ValidationError::Association);
    }
    b.bytes(&value.payload, 1024 * 1024)?;
    media_type(b, &value.media_type)?;
    b.metadata(&value.metadata, true)?;
    if value.priority > 255 {
        return Err(ValidationError::Shape);
    }
    // Numeric resource ceilings and imported-operation authority are enforced by
    // the actual admitted Phase 4 runtime; presence is still mandatory here.
    required(value.budget.as_ref())?;
    Ok(())
}
pub(super) fn media_type(b: &mut Budget, value: &String) -> Result<(), ValidationError> {
    b.string(value, 128)?;
    if value.is_empty() || !value.bytes().all(|byte| (32..=126).contains(&byte)) {
        return Err(ValidationError::Shape);
    }
    Ok(())
}

fn validate_namespace_mutation(
    b: &mut Budget,
    value: &c::MutateNamespaceRequest,
) -> Result<(), ValidationError> {
    let target = required(value.namespace.as_ref())?;
    inspect(b, target)?;
    b.id(&value.operation_id)?;
    let kind =
        c::NamespaceMutationKind::try_from(value.mutation).map_err(|_| ValidationError::Shape)?;
    let generation = value.expected_generation.ok_or(ValidationError::Shape)?;
    if kind == c::NamespaceMutationKind::Unspecified
        || (kind == c::NamespaceMutationKind::Create) != (generation == 0)
        || (kind == c::NamespaceMutationKind::Create
            && required(target.namespace.as_ref())?.incarnation != "1")
    {
        return Err(ValidationError::Shape);
    }
    match (kind, value.configuration.as_ref()) {
        (c::NamespaceMutationKind::Create | c::NamespaceMutationKind::Recreate, Some(config)) => {
            b.id(&config.state_schema)?;
            quota(required(config.quota.as_ref())?)
        }
        (c::NamespaceMutationKind::Create | c::NamespaceMutationKind::Recreate, None) => {
            Err(ValidationError::Shape)
        }
        (_, None) => Ok(()),
        (_, Some(_)) => Err(ValidationError::Shape),
    }
}

fn validate_command_input(
    b: &mut Budget,
    value: &t::InvokeCommandRequest,
) -> Result<(), ValidationError> {
    profile(b, required(value.profile.as_ref())?)?;
    let selector = required(value.command.as_ref())?;
    command(b, selector)?;
    invocation(
        b,
        required(value.invocation.as_ref())?,
        &required(selector.namespace.as_ref())?.tenant,
    )?;
    b.identity(&value.input_format)?;
    b.sequence(&value.expected_versions, 128)?;
    let mut keys = BTreeSet::new();
    for expected in &value.expected_versions {
        b.bytes(&expected.key, 1024)?;
        if !keys.insert(&expected.key) {
            return Err(ValidationError::Shape);
        }
        match &expected.expectation {
            Some(t::expected_version::Expectation::Absent(true)) => {}
            Some(t::expected_version::Expectation::Version(version)) => {
                b.opaque(version)?;
            }
            _ => return Err(ValidationError::Shape),
        }
    }
    if let Some(retry) = &value.retry_attempt {
        b.id(&retry.request_id)?;
        let abort = required(retry.expected_abort.as_ref())?;
        abort_fence(b, abort)?;
    }
    Ok(())
}
