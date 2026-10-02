use super::{
    bounds::{decimal, digest, required, Budget},
    request, Request, Response, ValidationError, MAX_PAGE_BYTES, MAX_PAGE_ENTRIES,
    MAX_RESPONSE_BYTES,
};
use crate::{control::v1 as c, invocation::v1 as i, transaction::v1 as t};

pub(super) fn validate(response: &Response, original: &Request) -> Result<(), ValidationError> {
    let mut b = Budget::new::<Response>(MAX_RESPONSE_BYTES)?;
    b.charge(response.native_message_bytes())?;
    match (response, original) {
        (Response::InspectNamespace(value), Request::InspectNamespace(original)) => {
            validate_inspect_namespace(&mut b, value, original)
        }
        (Response::MutateNamespace(value), Request::MutateNamespace(original)) => {
            validate_mutate_namespace(&mut b, value, original)
        }
        (
            Response::GetStateOperationReceipt(value),
            Request::GetStateOperationReceipt(original),
        ) => {
            let target = required(original.namespace.as_ref())?;
            match (&value.receipt, &value.namespace_receipt) {
                (Some(value), None) => state_receipt(&mut b, value, target, &original.operation_id),
                (None, Some(value)) => {
                    namespace_receipt(&mut b, value, target, &original.operation_id)
                }
                _ => Err(ValidationError::Shape),
            }
        }
        (Response::SelectEntity(value), Request::SelectEntity(original)) => {
            validate_select_entity(&mut b, value, original)
        }
        (Response::MutateState(value), Request::MutateState(original)) => {
            validate_mutate_state(&mut b, value, original)
        }
        (Response::LookupCommand(value), Request::LookupCommand(original)) => {
            validate_lookup_command(&mut b, value, original)
        }
        (Response::LookupCommit(value), Request::LookupCommit(original)) => {
            validate_lookup_commit(&mut b, value, original)
        }
        (Response::GetEffect(value), Request::GetEffect(original)) => effect(
            &mut b,
            required(value.effect.as_ref())?,
            &original.effect_id,
        ),
        (Response::ListEffectHistory(value), Request::ListEffectHistory(original)) => {
            validate_list_effect_history(&mut b, value, original)
        }
        (Response::CancelCommand(value), Request::CancelCommand(original)) => {
            validate_cancel_command(&mut b, value, original)
        }
        (Response::InvokeCommand(value), Request::InvokeCommand(original)) => {
            validate_invoke_command(&mut b, value, original)
        }
        (Response::Query(value), Request::Query(original)) => {
            validate_query(&mut b, value, original)
        }
        _ => Err(ValidationError::Association),
    }
}
use prost::Message;

fn namespace_status(value: i32) -> Result<(), ValidationError> {
    match c::NamespaceStatus::try_from(value) {
        Ok(
            c::NamespaceStatus::Active
            | c::NamespaceStatus::Quiescing
            | c::NamespaceStatus::Retired
            | c::NamespaceStatus::Tombstone,
        ) => Ok(()),
        _ => Err(ValidationError::Shape),
    }
}
fn disposition(value: i32) -> Result<(), ValidationError> {
    match c::StateOperationDisposition::try_from(value) {
        Ok(
            c::StateOperationDisposition::Committed
            | c::StateOperationDisposition::Conflict
            | c::StateOperationDisposition::Rejected
            | c::StateOperationDisposition::Unknown
            | c::StateOperationDisposition::RecoveryRequired,
        ) => Ok(()),
        _ => Err(ValidationError::Shape),
    }
}
fn namespace_receipt(
    b: &mut Budget,
    value: &c::NamespaceOperationReceipt,
    target: &c::InspectNamespaceRequest,
    operation_id: &str,
) -> Result<(), ValidationError> {
    b.id(&value.operation_id)?;
    b.id(&value.receipt_id)?;
    b.id(&value.authenticated_operator)?;
    b.id(&value.state_schema)?;
    namespace_status(value.status)?;
    disposition(value.disposition)?;
    let actual = required(value.namespace.as_ref())?;
    request::namespace(b, actual)?;
    let original = required(target.namespace.as_ref())?;
    if actual.tenant != original.tenant
        || actual.namespace != original.namespace
        || value.operation_id != operation_id
    {
        return Err(ValidationError::Association);
    }
    match c::NamespaceMutationKind::try_from(value.mutation) {
        Ok(
            c::NamespaceMutationKind::Create
            | c::NamespaceMutationKind::Quiesce
            | c::NamespaceMutationKind::Retire
            | c::NamespaceMutationKind::Destroy
            | c::NamespaceMutationKind::Recreate,
        ) => {}
        _ => return Err(ValidationError::Shape),
    }
    if value.disposition == c::StateOperationDisposition::Committed as i32
        && value.after_generation == 0
    {
        return Err(ValidationError::Shape);
    }
    Ok(())
}
fn state_receipt(
    b: &mut Budget,
    value: &c::StateOperationReceipt,
    target: &c::InspectNamespaceRequest,
    operation_id: &str,
) -> Result<(), ValidationError> {
    b.id(&value.operation_id)?;
    b.id(&value.receipt_id)?;
    b.id(&value.authenticated_operator)?;
    b.optional_id(value.record_id.as_ref())?;
    b.opaque(&value.before_version)?;
    b.opaque(&value.after_version)?;
    b.string(&value.policy_digest, 71)?;
    digest(&value.policy_digest)?;
    disposition(value.disposition)?;
    let namespace = required(value.namespace.as_ref())?;
    request::namespace(b, namespace)?;
    if Some(namespace) != target.namespace.as_ref() || value.operation_id != operation_id {
        return Err(ValidationError::Association);
    }
    match c::StateMutationKind::try_from(value.mutation) {
        Ok(
            c::StateMutationKind::RetryKnownFailedEffect
            | c::StateMutationKind::TerminateEffect
            | c::StateMutationKind::PurgeExpiredPayload
            | c::StateMutationKind::CheckpointNamespace,
        ) => Ok(()),
        _ => Err(ValidationError::Shape),
    }
}
fn view(
    b: &mut Budget,
    value: &t::ViewIdentity,
    expected: &t::NamespaceSelector,
) -> Result<(), ValidationError> {
    request::namespace(b, required(value.namespace.as_ref())?)?;
    b.opaque(&value.version)?;
    b.id(&value.state_schema)?;
    if value.namespace.as_ref() != Some(expected) {
        return Err(ValidationError::Association);
    }
    Ok(())
}
fn source(b: &mut Budget, value: &t::SourceIdentity) -> Result<(), ValidationError> {
    b.string(&value.publication_id, 83)?;
    value
        .publication_id
        .parse::<latent_core::PublicationId>()
        .map_err(|_| ValidationError::Shape)?;
    for id in [
        &value.revision_id,
        &value.input_format,
        &value.result_format,
    ] {
        b.identity(id)?;
    }
    for value in [
        &value.release_digest,
        &value.component_digest,
        &value.contract_digest,
        &value.state_schema,
    ] {
        b.string(value, 71)?;
        digest(value)?;
    }
    if value.route_generation == 0 {
        return Err(ValidationError::Shape);
    }
    Ok(())
}
fn retention(b: &mut Budget, value: &t::LinkedRetention) -> Result<(), ValidationError> {
    b.id(&value.record_format)?;
    if value.record_version == 0 {
        return Err(ValidationError::Shape);
    }
    b.sequence(&value.required_record_ids, 256)?;
    for id in &value.required_record_ids {
        b.id(id)?;
    }
    Ok(())
}
fn command(
    b: &mut Budget,
    value: &t::CommandInspection,
    target: &t::CommandSelector,
) -> Result<(), ValidationError> {
    command_key(b, required(value.key.as_ref())?, target)?;
    let outcome = t::CommandOutcome::try_from(value.outcome).map_err(|_| ValidationError::Shape)?;
    if outcome == t::CommandOutcome::Unspecified {
        return Err(ValidationError::Shape);
    }
    command_details(b, value, outcome)?;
    command_disposition(value, outcome)
}
fn command_key(
    b: &mut Budget,
    key: &t::CommandKey,
    target: &t::CommandSelector,
) -> Result<(), ValidationError> {
    request::namespace(b, required(key.namespace.as_ref())?)?;
    for id in [&key.recovery_scope, &key.operation, &key.client_key] {
        b.identity(id)?;
    }
    if let Some(entity) = &key.entity {
        b.identity(entity)?;
    }
    if key.namespace != target.namespace
        || key.operation != target.operation
        || key.entity != target.entity
        || key.client_key != target.client_key
    {
        return Err(ValidationError::Association);
    }
    Ok(())
}
fn command_details(
    b: &mut Budget,
    value: &t::CommandInspection,
    outcome: t::CommandOutcome,
) -> Result<(), ValidationError> {
    let known = !matches!(
        outcome,
        t::CommandOutcome::Unknown | t::CommandOutcome::RecoveryRequired
    );
    if known || !value.command_id.is_empty() {
        b.id(&value.command_id)?;
    }
    if known || !value.attempt_id.is_empty() {
        b.id(&value.attempt_id)?;
    }
    b.bytes(&value.fingerprint_sha256, 32)?;
    if known && value.fingerprint_sha256.len() != 32 {
        return Err(ValidationError::Shape);
    }
    if let Some(value) = &value.source {
        source(b, value)?;
    } else if known {
        return Err(ValidationError::Shape);
    }
    if let Some(value) = &value.retention {
        retention(b, value)?;
    }
    if let Some(value) = &value.cleanup_failure {
        platform_error(b, value)?;
    }
    match &value.retained_result {
        Some(t::command_inspection::RetainedResult::Success(value)) => success(b, value)?,
        Some(t::command_inspection::RetainedResult::BusinessRejection(value)) => {
            rejection(b, value)?;
        }
        Some(t::command_inspection::RetainedResult::TechnicalFailure(value)) => {
            platform_error(b, value)?;
        }
        None => {}
    }
    validate_receipt_links(b, value)?;
    Ok(())
}
fn command_disposition(
    value: &t::CommandInspection,
    outcome: t::CommandOutcome,
) -> Result<(), ValidationError> {
    let success = matches!(
        value.retained_result,
        Some(t::command_inspection::RetainedResult::Success(_))
    );
    let rejected = matches!(
        value.retained_result,
        Some(t::command_inspection::RetainedResult::BusinessRejection(_))
    );
    let omitted_payload = value.retained_result.is_none()
        && value
            .retention
            .as_ref()
            .is_some_and(|r| !r.payload_available);
    match outcome {
        t::CommandOutcome::Committed
            if value.metadata_durable
                && value.application_state_committed
                && value.commit.is_some()
                && value.proven_abort.is_none()
                && (success || omitted_payload) => {}
        t::CommandOutcome::Rejected
            if value.metadata_durable
                && !value.application_state_committed
                && value.commit.is_none()
                && value.proven_abort.is_none()
                && (rejected || omitted_payload) => {}
        t::CommandOutcome::Aborted
            if value.metadata_durable
                && !value.application_state_committed
                && value.commit.is_none()
                && value.proven_abort.is_some()
                && !success
                && !rejected => {}
        t::CommandOutcome::Expired
            if value.metadata_durable
                && value.proven_abort.is_none()
                && value.retained_result.is_none()
                && value.application_state_committed == value.commit.is_some() => {}
        t::CommandOutcome::InProgress
        | t::CommandOutcome::Unknown
        | t::CommandOutcome::RecoveryRequired
            if !value.application_state_committed
                && value.commit.is_none()
                && value.proven_abort.is_none()
                && value.retained_result.is_none() => {}
        _ => return Err(ValidationError::Shape),
    }
    Ok(())
}
fn effect(
    b: &mut Budget,
    value: &t::EffectReceipt,
    effect_id: &str,
) -> Result<(), ValidationError> {
    for id in [
        &value.effect_id,
        &value.command_id,
        &value.command_attempt_id,
        &value.provider_profile,
    ] {
        b.id(id)?;
    }
    b.optional_id(value.provider_receipt.as_ref())?;
    b.optional_id(value.failure_code.as_ref())?;
    b.optional_id(value.management_operation_receipt_id.as_ref())?;
    if value.effect_id != effect_id {
        return Err(ValidationError::Association);
    }
    if let Some(value) = &value.retention {
        retention(b, value)?;
    }
    match t::EffectDisposition::try_from(value.disposition) {
        Ok(
            t::EffectDisposition::Pending
            | t::EffectDisposition::Dispatching
            | t::EffectDisposition::ProviderAcknowledged
            | t::EffectDisposition::KnownFailure
            | t::EffectDisposition::UncertainAfterDispatch
            | t::EffectDisposition::Expired
            | t::EffectDisposition::PolicyBlocked
            | t::EffectDisposition::AdministrativelyTerminated,
        ) => Ok(()),
        _ => Err(ValidationError::Shape),
    }
}
fn page(
    b: &mut Budget,
    value: &t::PageResponse,
    requested: &t::PageRequest,
    count: usize,
) -> Result<(), ValidationError> {
    if value.returned_count as usize != count
        || count > requested.limit as usize
        || value.encoded_bytes > MAX_PAGE_BYTES as u64
    {
        return Err(ValidationError::Association);
    }
    if let Some(cursor) = &value.next_cursor {
        b.opaque(cursor)?;
        if requested.cursor.as_ref() == Some(cursor) {
            return Err(ValidationError::Association);
        }
    }
    // Continuation is authoritative. A short (or filtered empty) bounded page
    // can have a new continuation; never infer exhaustion from row count.
    Ok(())
}
fn success(b: &mut Budget, value: &i::Success) -> Result<(), ValidationError> {
    b.bytes(&value.payload, 1024 * 1024)?;
    request::media_type(b, &value.media_type)?;
    if let Some(version) = &value.committed_state_version {
        b.id(version)?;
    }
    b.sequence(&value.effect_ids, 128)?;
    for id in &value.effect_ids {
        b.id(id)?;
    }
    b.metadata(&value.metadata, false)
}
fn rejection(b: &mut Budget, value: &i::DeclaredError) -> Result<(), ValidationError> {
    b.id(&value.code)?;
    b.string(&value.message, 4096)?;
    b.bytes(&value.payload, 1024 * 1024)?;
    request::media_type(b, &value.media_type)?;
    b.metadata(&value.metadata, false)
}
fn platform_error(b: &mut Budget, value: &i::PlatformError) -> Result<(), ValidationError> {
    b.id(&value.code)?;
    if latent_core::PlatformErrorCode::from_wire_code(&value.code).is_none() {
        return Err(ValidationError::Shape);
    }
    b.string(&value.message, 1024)?;
    b.sequence(&value.detail_items, 16)?;
    for detail in &value.detail_items {
        b.id(&detail.kind)?;
        b.metadata(&detail.fields, false)?;
    }
    // Public adapters apply the producer's closed diagnostic policy separately.
    Ok(())
}
fn invocation(b: &mut Budget, value: &i::InvokeResponse) -> Result<(), ValidationError> {
    b.id(&value.activation_id)?;
    for id in [&value.revision_id, &value.release_digest] {
        b.string(id, 256)?;
    }
    if let Some(id) = &value.publication_id {
        b.string(id, 83)?;
        id.parse::<latent_core::PublicationId>()
            .map_err(|_| ValidationError::Shape)?;
    }
    required(value.consumption.as_ref())?;
    match value.result.as_ref() {
        Some(i::invoke_response::Result::Success(value)) => success(b, value),
        Some(i::invoke_response::Result::DeclaredError(value)) => rejection(b, value),
        Some(i::invoke_response::Result::PlatformFailure(value)) => platform_error(b, value),
        None => Err(ValidationError::Shape),
    }
}
fn audit(_b: &mut Budget, value: Option<&c::AuditAck>) -> Result<(), ValidationError> {
    if let Some(value) = value {
        // Acknowledgement is a bounded typed durability fact, never inferred
        // from operation success. Its schema is validated by the audit owner.
        match c::AuditAckStatus::try_from(value.status) {
            Ok(
                c::AuditAckStatus::Durable
                | c::AuditAckStatus::OutcomeUnknown
                | c::AuditAckStatus::AuditUnavailable
                | c::AuditAckStatus::Disabled,
            ) => {}
            _ => return Err(ValidationError::Shape),
        }
    }
    Ok(())
}

fn validate_inspect_namespace(
    b: &mut Budget,
    value: &c::InspectNamespaceResponse,
    original: &c::InspectNamespaceRequest,
) -> Result<(), ValidationError> {
    let value = required(value.namespace.as_ref())?;
    view(
        b,
        required(value.view.as_ref())?,
        required(original.namespace.as_ref())?,
    )?;
    namespace_status(value.status)?;
    if value.generation == 0 {
        return Err(ValidationError::Shape);
    }
    request::quota(required(value.quota.as_ref())?)?;
    b.id(&value.engine_profile)?;
    b.string(&value.engine_profile_digest, 71)?;
    digest(&value.engine_profile_digest)?;
    b.sequence(&value.retained_formats, 128)?;
    for value in &value.retained_formats {
        retention(b, value)?;
    }
    Ok(())
}

fn validate_mutate_namespace(
    b: &mut Budget,
    value: &c::MutateNamespaceResponse,
    original: &c::MutateNamespaceRequest,
) -> Result<(), ValidationError> {
    let receipt = required(value.receipt.as_ref())?;
    namespace_receipt(
        b,
        receipt,
        required(original.namespace.as_ref())?,
        &original.operation_id,
    )?;
    if receipt.mutation != original.mutation {
        return Err(ValidationError::Association);
    }
    let expected = original.expected_generation.ok_or(ValidationError::Shape)?;
    let create = original.mutation == c::NamespaceMutationKind::Create as i32;
    if receipt.before_generation != (!create).then_some(expected) {
        return Err(ValidationError::Association);
    }
    if receipt.disposition == c::StateOperationDisposition::Committed as i32 {
        let original_namespace =
            required(required(original.namespace.as_ref())?.namespace.as_ref())?;
        let before_incarnation = decimal(&original_namespace.incarnation, true)?;
        let expected_incarnation = if original.mutation == c::NamespaceMutationKind::Recreate as i32
        {
            before_incarnation
                .checked_add(1)
                .ok_or(ValidationError::Association)?
        } else {
            before_incarnation
        };
        if decimal(&required(receipt.namespace.as_ref())?.incarnation, true)?
            != expected_incarnation
        {
            return Err(ValidationError::Association);
        }
        if receipt.after_generation
            != expected
                .checked_add(1)
                .ok_or(ValidationError::Association)?
        {
            return Err(ValidationError::Association);
        }
        let status = match c::NamespaceMutationKind::try_from(original.mutation) {
            Ok(c::NamespaceMutationKind::Create | c::NamespaceMutationKind::Recreate) => {
                c::NamespaceStatus::Active
            }
            Ok(c::NamespaceMutationKind::Quiesce) => c::NamespaceStatus::Quiescing,
            Ok(c::NamespaceMutationKind::Retire) => c::NamespaceStatus::Retired,
            Ok(c::NamespaceMutationKind::Destroy) => c::NamespaceStatus::Tombstone,
            _ => return Err(ValidationError::Shape),
        };
        if receipt.status != status as i32
            || original
                .configuration
                .as_ref()
                .is_some_and(|config| config.state_schema != receipt.state_schema)
        {
            return Err(ValidationError::Association);
        }
    }
    audit(b, value.audit_ack.as_ref())
}

fn validate_select_entity(
    b: &mut Budget,
    value: &c::SelectEntityResponse,
    original: &c::SelectEntityRequest,
) -> Result<(), ValidationError> {
    let requested = required(original.page.as_ref())?;
    b.sequence(&value.entities, MAX_PAGE_ENTRIES)?;
    let mut seen = std::collections::BTreeSet::new();
    for entity in &value.entities {
        b.identity(&entity.entity)?;
        b.opaque(&entity.version)?;
        if !seen.insert(&entity.entity) {
            return Err(ValidationError::Shape);
        }
    }
    page(
        b,
        required(value.page.as_ref())?,
        requested,
        value.entities.len(),
    )
}

fn validate_mutate_state(
    b: &mut Budget,
    value: &c::MutateStateResponse,
    original: &c::MutateStateRequest,
) -> Result<(), ValidationError> {
    let receipt = required(value.receipt.as_ref())?;
    state_receipt(
        b,
        receipt,
        required(original.namespace.as_ref())?,
        &original.operation_id,
    )?;
    if receipt.mutation != original.mutation
        || receipt.record_id != original.record_id
        || receipt.before_version != original.expected_version
        || receipt.policy_digest != original.expected_policy_digest
    {
        return Err(ValidationError::Association);
    }
    audit(b, value.audit_ack.as_ref())
}

fn validate_lookup_command(
    b: &mut Budget,
    value: &t::LookupCommandResponse,
    original: &t::LookupCommandRequest,
) -> Result<(), ValidationError> {
    let value = required(value.command.as_ref())?;
    command(b, value, required(original.command.as_ref())?)?;
    if original
        .attempt_id
        .as_ref()
        .is_some_and(|id| id != &value.attempt_id)
    {
        return Err(ValidationError::Association);
    }
    Ok(())
}

fn validate_lookup_commit(
    b: &mut Budget,
    value: &t::LookupCommitResponse,
    original: &t::LookupCommitRequest,
) -> Result<(), ValidationError> {
    let value = required(value.command.as_ref())?;
    command(b, value, required(original.command.as_ref())?)?;
    if value
        .commit
        .as_ref()
        .is_none_or(|receipt| receipt.receipt_id != original.receipt_id)
    {
        return Err(ValidationError::Association);
    }
    Ok(())
}

fn validate_list_effect_history(
    b: &mut Budget,
    value: &t::ListEffectHistoryResponse,
    original: &t::ListEffectHistoryRequest,
) -> Result<(), ValidationError> {
    let requested = required(original.page.as_ref())?;
    let target = required(original.effect.as_ref())?;
    b.sequence(&value.receipts, MAX_PAGE_ENTRIES)?;
    for receipt in &value.receipts {
        effect(b, receipt, &target.effect_id)?;
    }
    page(
        b,
        required(value.page.as_ref())?,
        requested,
        value.receipts.len(),
    )?;
    if value.encoded_len() > MAX_PAGE_BYTES {
        return Err(ValidationError::Capacity);
    }
    Ok(())
}

fn validate_cancel_command(
    b: &mut Budget,
    value: &t::CancelCommandResponse,
    original: &t::CancelCommandRequest,
) -> Result<(), ValidationError> {
    let disposition = t::CommandCancelDisposition::try_from(value.disposition)
        .map_err(|_| ValidationError::Shape)?;
    if disposition == t::CommandCancelDisposition::Unspecified {
        return Err(ValidationError::Shape);
    }
    if let Some(command_value) = &value.command {
        command(
            b,
            command_value,
            required(required(original.command.as_ref())?.command.as_ref())?,
        )?;
        if disposition == t::CommandCancelDisposition::AlreadyCommitted
            && command_value.outcome != t::CommandOutcome::Committed as i32
        {
            return Err(ValidationError::Association);
        }
    } else if disposition != t::CommandCancelDisposition::NotFound {
        return Err(ValidationError::Shape);
    }
    Ok(())
}

fn validate_invoke_command(
    b: &mut Budget,
    value: &t::InvokeCommandResponse,
    original: &t::InvokeCommandRequest,
) -> Result<(), ValidationError> {
    let command_value = required(value.command.as_ref())?;
    command(b, command_value, required(original.command.as_ref())?)?;
    invocation(b, required(value.invocation.as_ref())?)?;
    let invocation = required(value.invocation.as_ref())?;
    if let Some(source) = &command_value.source {
        if invocation.publication_id.as_ref() != Some(&source.publication_id)
            || invocation.revision_id != source.revision_id
            || invocation.release_digest != source.component_digest
            || invocation.route_generation != source.route_generation
        {
            return Err(ValidationError::Association);
        }
    }
    match (&command_value.retained_result, &invocation.result) {
        (
            Some(t::command_inspection::RetainedResult::Success(left)),
            Some(i::invoke_response::Result::Success(right)),
        ) if left == right => {}
        (
            Some(t::command_inspection::RetainedResult::BusinessRejection(left)),
            Some(i::invoke_response::Result::DeclaredError(right)),
        ) if left == right => {}
        (
            Some(t::command_inspection::RetainedResult::TechnicalFailure(left)),
            Some(i::invoke_response::Result::PlatformFailure(right)),
        ) if left == right => {}
        (None, Some(i::invoke_response::Result::PlatformFailure(_))) => {}
        _ => return Err(ValidationError::Association),
    }
    Ok(())
}

fn validate_query(
    b: &mut Budget,
    value: &t::QueryResponse,
    original: &t::QueryRequest,
) -> Result<(), ValidationError> {
    view(
        b,
        required(value.view.as_ref())?,
        required(original.namespace.as_ref())?,
    )?;
    source(b, required(value.source.as_ref())?)?;
    invocation(b, required(value.invocation.as_ref())?)?;
    let source_value = required(value.source.as_ref())?;
    let invocation_value = required(value.invocation.as_ref())?;
    if invocation_value.publication_id.as_ref() != Some(&source_value.publication_id)
        || invocation_value.revision_id != source_value.revision_id
        || invocation_value.release_digest != source_value.component_digest
        || invocation_value.route_generation != source_value.route_generation
    {
        return Err(ValidationError::Association);
    }
    Ok(())
}

fn validate_receipt_links(
    b: &mut Budget,
    value: &t::CommandInspection,
) -> Result<(), ValidationError> {
    if let Some(receipt) = &value.commit {
        for id in [
            &receipt.command_id,
            &receipt.attempt_id,
            &receipt.transaction_id,
            &receipt.receipt_id,
        ] {
            b.id(id)?;
        }
        b.opaque(&receipt.committed_version)?;
        b.sequence(&receipt.effect_ids, 128)?;
        let mut unique = std::collections::BTreeSet::new();
        for id in &receipt.effect_ids {
            b.id(id)?;
            if !unique.insert(id) {
                return Err(ValidationError::Shape);
            }
        }
        source(b, required(receipt.source.as_ref())?)?;
        if receipt.command_id != value.command_id
            || receipt.attempt_id != value.attempt_id
            || receipt.source != value.source
        {
            return Err(ValidationError::Association);
        }
    }
    if let Some(abort) = &value.proven_abort {
        request::abort_fence(b, abort)?;
        if abort.command_id != value.command_id || abort.attempt_id != value.attempt_id {
            return Err(ValidationError::Association);
        }
    }
    Ok(())
}
