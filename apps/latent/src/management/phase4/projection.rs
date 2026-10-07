use base64::{engine::general_purpose::STANDARD, Engine};
use latent_rpc::{control::v1 as c, invocation::v1 as i, phase4::Response, transaction::v1 as t};
use serde_json::{json, Value};
mod dispatcher;
mod effect_management;
pub(super) use dispatcher::generation as dispatcher_generation;
pub(super) use effect_management::plan as effect_plan;

pub(super) fn bytes(value: &[u8]) -> Value {
    json!({"encoding":"base64","data":STANDARD.encode(value)})
}
pub(super) fn namespace(value: &t::NamespaceSelector) -> Value {
    json!({"tenant":value.tenant,"namespace":value.namespace,"incarnation":value.incarnation})
}
pub(super) fn selector(value: &t::CommandSelector) -> Value {
    json!({"namespace":value.namespace.as_ref().map(namespace),"operation":value.operation,"entity":value.entity,
        "clientKey":value.client_key,"sharedRecoveryScope":value.shared_recovery_scope})
}
fn source(value: &t::SourceIdentity) -> Value {
    json!({"publicationId":value.publication_id,"revisionId":value.revision_id,"releaseDigest":value.release_digest,
        "componentDigest":value.component_digest,"routeGeneration":value.route_generation.to_string(),
        "contractDigest":value.contract_digest,"stateSchema":value.state_schema,"inputFormat":value.input_format,"resultFormat":value.result_format})
}
fn view(value: &t::ViewIdentity) -> Value {
    json!({"namespace":value.namespace.as_ref().map(namespace),"version":bytes(&value.version),"stateSchema":value.state_schema})
}
fn retention(value: &t::LinkedRetention) -> Value {
    json!({"recordFormat":value.record_format,"recordVersion":value.record_version,
        "payloadExpiresAtUnixMillis":value.payload_expires_at_unix_millis.map(|v|v.to_string()),
        "identityExpiresAtUnixMillis":value.identity_expires_at_unix_millis.map(|v|v.to_string()),
        "remainingRecoveryMillis":value.remaining_recovery_millis.map(|v|v.to_string()),
        "requiredRecordIds":value.required_record_ids,"payloadAvailable":value.payload_available})
}
fn success(value: &i::Success) -> Value {
    json!({"payload":bytes(&value.payload),"mediaType":value.media_type,"committedStateVersion":value.committed_state_version,
        "effectIds":value.effect_ids,"metadata":value.metadata})
}
fn rejection(value: &i::DeclaredError) -> Value {
    json!({"code":value.code,"message":value.message,"payload":bytes(&value.payload),"mediaType":value.media_type,"metadata":value.metadata})
}
fn platform(value: &i::PlatformError) -> Value {
    json!({"code":value.code,"message":value.message,"retryable":value.retryable,
        "details":value.detail_items.iter().map(|v|json!({"kind":v.kind,"fields":v.fields})).collect::<Vec<_>>()})
}
fn commit(value: &t::CommitReceipt) -> Value {
    json!({"commandId":value.command_id,"attemptId":value.attempt_id,"transactionId":value.transaction_id,
        "committedVersion":bytes(&value.committed_version),"committedAtUnixMillis":value.committed_at_unix_millis.to_string(),
        "effectIds":value.effect_ids,"receiptId":value.receipt_id,"source":value.source.as_ref().map(source)})
}
fn abort(value: &t::AbortFence) -> Value {
    json!({"commandId":value.command_id,"attemptId":value.attempt_id,"transactionId":value.transaction_id,"ownerFence":bytes(&value.owner_fence)})
}
pub(super) fn command(value: &t::CommandInspection) -> Value {
    let retained = match &value.retained_result {
        Some(t::command_inspection::RetainedResult::Success(value)) => {
            json!({"kind":"success","value":success(value)})
        }
        Some(t::command_inspection::RetainedResult::BusinessRejection(value)) => {
            json!({"kind":"business-rejection","value":rejection(value)})
        }
        Some(t::command_inspection::RetainedResult::TechnicalFailure(value)) => {
            json!({"kind":"technical-failure","value":platform(value)})
        }
        None => Value::Null,
    };
    json!({"key":value.key.as_ref().map(|v|json!({"namespace":v.namespace.as_ref().map(namespace),"recoveryScope":v.recovery_scope,
        "operation":v.operation,"entity":v.entity,"clientKey":v.client_key})),"commandId":value.command_id,"attemptId":value.attempt_id,
        "fingerprintSha256":bytes(&value.fingerprint_sha256),"outcome":t::CommandOutcome::try_from(value.outcome).expect("validated enum").as_str_name(),
        "metadataDurable":value.metadata_durable,"applicationStateCommitted":value.application_state_committed,
        "source":value.source.as_ref().map(source),"retainedResult":retained,"commit":value.commit.as_ref().map(commit),
        "provenAbort":value.proven_abort.as_ref().map(abort),"retention":value.retention.as_ref().map(retention),
        "cleanupFailure":value.cleanup_failure.as_ref().map(platform)})
}
fn quota(value: &c::NamespaceQuota) -> Value {
    json!({"stateKeys":value.state_keys.to_string(),"stateBytes":value.state_bytes.to_string(),"resultRows":value.result_rows.to_string(),
        "resultBytes":value.result_bytes.to_string(),"effectRows":value.effect_rows.to_string(),"effectBytes":value.effect_bytes.to_string(),
        "payloadBytes":value.payload_bytes.to_string(),"recoveryBytes":value.recovery_bytes.to_string()})
}
fn namespace_receipt(value: &c::NamespaceOperationReceipt) -> Value {
    json!({"operationId":value.operation_id,"receiptId":value.receipt_id,"mutation":c::NamespaceMutationKind::try_from(value.mutation).expect("validated enum").as_str_name(),
        "namespace":value.namespace.as_ref().map(namespace),"authenticatedOperator":value.authenticated_operator,
        "beforeGeneration":value.before_generation.map(|v|v.to_string()),"afterGeneration":value.after_generation.to_string(),
        "status":c::NamespaceStatus::try_from(value.status).expect("validated enum").as_str_name(),"stateSchema":value.state_schema,
        "disposition":c::StateOperationDisposition::try_from(value.disposition).expect("validated enum").as_str_name()})
}
fn state_receipt(value: &c::StateOperationReceipt) -> Value {
    json!({"operationId":value.operation_id,"receiptId":value.receipt_id,"mutation":c::StateMutationKind::try_from(value.mutation).expect("validated enum").as_str_name(),
        "namespace":value.namespace.as_ref().map(namespace),"authenticatedOperator":value.authenticated_operator,"beforeVersion":bytes(&value.before_version),
        "afterVersion":bytes(&value.after_version),"completedAtUnixMillis":value.completed_at_unix_millis.to_string(),
        "recordId":value.record_id,"policyDigest":value.policy_digest,
        "disposition":c::StateOperationDisposition::try_from(value.disposition).expect("validated enum").as_str_name(),
        "effect":value.effect.as_ref().map(effect_management::receipt)})
}
fn audit(value: &c::AuditAck) -> Value {
    json!({"status":c::AuditAckStatus::try_from(value.status).expect("validated enum").as_str_name(),"attemptSequence":value.attempt_sequence.map(|v|v.to_string())})
}
fn effect(value: &t::EffectReceipt) -> Value {
    json!({"effectId":value.effect_id,"commandId":value.command_id,"commandAttemptId":value.command_attempt_id,"dispatchAttempt":value.dispatch_attempt,
        "disposition":t::EffectDisposition::try_from(value.disposition).expect("validated enum").as_str_name(),"providerReceipt":value.provider_receipt,
        "failureCode":value.failure_code,"occurredAtUnixMillis":value.occurred_at_unix_millis.to_string(),"retention":value.retention.as_ref().map(retention),
        "managementOperationReceiptId":value.management_operation_receipt_id,"providerProfile":value.provider_profile,
        "recordVersion":bytes(&value.record_version),"ownerEpoch":value.owner_epoch.map(|v|v.to_string()),"claimGeneration":value.claim_generation.map(|v|v.to_string())})
}
fn page(value: &t::PageResponse) -> Value {
    json!({"nextCursor":value.next_cursor.as_ref().map(|v|bytes(v)),"returnedCount":value.returned_count,"encodedBytes":value.encoded_bytes.to_string(),
        "exhausted":value.next_cursor.is_none()})
}
fn invocation(value: &i::InvokeResponse) -> Value {
    let result = match &value.result {
        Some(i::invoke_response::Result::Success(value)) => {
            json!({"kind":"success","value":success(value)})
        }
        Some(i::invoke_response::Result::DeclaredError(value)) => {
            json!({"kind":"business-rejection","value":rejection(value)})
        }
        Some(i::invoke_response::Result::PlatformFailure(value)) => {
            json!({"kind":"technical-failure","value":platform(value)})
        }
        None => Value::Null,
    };
    json!({"activationId":value.activation_id,"revisionId":value.revision_id,"componentDigest":value.release_digest,"routeGeneration":value.route_generation.to_string(),
        "publicationId":value.publication_id,"result":result,"consumption":value.consumption.as_ref().map(|v|json!({
            "cpuFuel":v.cpu_fuel.to_string(),"peakMemoryBytes":v.peak_memory_bytes.to_string(),"wallTimeMicros":v.wall_time_micros.to_string(),
            "childCalls":v.child_calls,"outboundRequests":v.outbound_requests,"stateReadBytes":v.state_read_bytes.to_string(),"stateWriteBytes":v.state_write_bytes.to_string(),
            "blobReadBytes":v.blob_read_bytes.to_string(),"blobWriteBytes":v.blob_write_bytes.to_string(),"logBytes":v.log_bytes.to_string(),"effectCount":v.effect_count}))})
}
pub(super) fn response(value: &Response) -> Value {
    match value {
        Response::InspectDispatcher(value) => {
            json!({"dispatcher":value.dispatcher.as_ref().map(dispatcher::snapshot),
            "auditAcknowledgement":value.audit_ack.as_ref().map(audit)})
        }
        Response::ControlDispatcher(value) => {
            json!({"receipt":value.receipt.as_ref().map(dispatcher::receipt),
            "replayed":value.replayed,"published":value.published,"paused":value.paused,
            "auditAcknowledgement":value.audit_ack.as_ref().map(audit)})
        }
        Response::GetDispatcherOperation(value) => {
            json!({"receipt":value.receipt.as_ref().map(dispatcher::receipt),
            "auditAcknowledgement":value.audit_ack.as_ref().map(audit)})
        }
        Response::InspectNamespace(value) => {
            json!({"namespace":value.namespace.as_ref().map(|v|json!({"view":v.view.as_ref().map(view),
            "encodedStateBytes":v.encoded_state_bytes.to_string(),"commandCount":v.command_count.to_string(),"pendingEffectCount":v.pending_effect_count.to_string(),
            "retainedFormats":v.retained_formats.iter().map(retention).collect::<Vec<_>>(),"engineProfile":v.engine_profile,"engineProfileDigest":v.engine_profile_digest,
            "status":c::NamespaceStatus::try_from(v.status).expect("validated enum").as_str_name(),"quota":v.quota.as_ref().map(quota),"generation":v.generation.to_string(),"namespacePolicyDigest":v.namespace_policy_digest}))})
        }
        Response::MutateNamespace(value) => {
            json!({"receipt":value.receipt.as_ref().map(namespace_receipt),"replayed":value.replayed,"auditAcknowledgement":value.audit_ack.as_ref().map(audit)})
        }
        Response::MutateState(value) => {
            json!({"receipt":value.receipt.as_ref().map(state_receipt),"replayed":value.replayed,"auditAcknowledgement":value.audit_ack.as_ref().map(audit)})
        }
        Response::PlanEffectMutation(value) => {
            json!({"plan":value.plan.as_ref().map(effect_management::plan),"replayed":value.replayed,"auditAcknowledgement":value.audit_ack.as_ref().map(audit)})
        }
        Response::GetStateOperationReceipt(value) => {
            json!({"stateReceipt":value.receipt.as_ref().map(state_receipt),"namespaceReceipt":value.namespace_receipt.as_ref().map(namespace_receipt),"auditAcknowledgement":value.audit_ack.as_ref().map(audit)})
        }
        Response::SelectEntity(value) => {
            json!({"entities":value.entities.iter().map(|v|json!({"entity":v.entity,"version":bytes(&v.version)})).collect::<Vec<_>>(),"page":value.page.as_ref().map(page)})
        }
        Response::LookupCommand(value) => json!({"command":value.command.as_ref().map(command)}),
        Response::LookupCommit(value) => json!({"command":value.command.as_ref().map(command)}),
        Response::InvokeCommand(value) => {
            json!({"command":value.command.as_ref().map(command),"invocation":value.invocation.as_ref().map(invocation),"replayed":value.replayed})
        }
        Response::Query(value) => {
            json!({"view":value.view.as_ref().map(view),"source":value.source.as_ref().map(source),"invocation":value.invocation.as_ref().map(invocation),
            "observedAtUnixMillis":value.observed_at_unix_millis.to_string()})
        }
        Response::GetEffect(value) => json!({"effect":value.effect.as_ref().map(effect)}),
        Response::ListEffectHistory(value) => {
            json!({"receipts":value.receipts.iter().map(effect).collect::<Vec<_>>(),"page":value.page.as_ref().map(page)})
        }
        Response::CancelCommand(value) => {
            json!({"cancellationDisposition":t::CommandCancelDisposition::try_from(value.disposition).expect("validated enum").as_str_name(),
            "command":value.command.as_ref().map(command)})
        }
    }
}
