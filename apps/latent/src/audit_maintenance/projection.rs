use latent_audit::{AuditArchiveCoverage, AuditArchivePage, AuditCustodyStatus, AuditJournalStatus,
    AuditPageStop, AuditRolloverReceipt, AuditTransferReceipt};
use latent_core::{PlatformError, PlatformErrorCode};
use serde_json::{json, Value};

pub(super) fn status(value: AuditJournalStatus) -> Value {
    json!({"epoch":value.epoch,"journalId":value.journal_id,
        "retainedFloor":value.retained_floor.to_string(),"highWatermark":value.high_watermark.to_string(),
        "nextSequence":value.next_sequence.to_string(),"headDigest":value.head_digest,
        "retainedRecords":value.retained_records.to_string(),"retainedBytes":value.retained_bytes.to_string(),
        "pendingAttempts":value.pending_attempts.to_string(),"unknownOutcomes":value.unknown_outcomes.to_string(),
        "previousEpoch":value.previous_epoch,"previousSeal":value.previous_seal,
        "advisory":true,"nextStep":if value.pending_attempts == 0 {"plan-stopped-node-rollover-before-headroom-exhaustion"}
            else {"restart-original-node-and-reconcile-original-operation-without-replay"}})
}
pub(super) fn coverage(value: AuditArchiveCoverage) -> Value {
    json!({"journalId":value.journal_id,"epoch":value.epoch,"successorEpoch":value.successor_epoch,
        "operationId":value.operation_id,"retainedFloor":value.first_sequence.to_string(),
        "highWatermark":value.high_watermark.to_string(),"records":value.records.to_string(),
        "recordBytes":value.record_bytes.to_string(),"headDigest":value.head_digest,
        "sealDigest":value.seal_digest,"predecessorSealDigest":value.predecessor_seal_digest,
        "unknownOutcomes":value.unknown_outcomes.to_string(),"previousSessionLossUnknown":value.previous_session_loss_unknown,
        "historyComplete":false,"coverage":"exactly-one-sealed-epoch"})
}
pub(super) fn custody(value: AuditCustodyStatus) -> Value {
    json!({"journalId":value.journal_id,"custodyId":value.custody_id,
        "archives":value.archives.into_iter().map(coverage).collect::<Vec<_>>(),
        "transferredThrough":value.transferred_through.to_string(),"transferredHeadSeal":value.transferred_head,
        "transferredHistoryAvailability":"not-observed","maximumArchives":"4","maximumArchiveRecordBytes":"1073741824",
        "nextStep":"transfer-oldest-archive-before-local-custody-exhaustion"})
}
pub(super) fn rollover(value: AuditRolloverReceipt) -> Value {
    json!({"receipt":{"operationId":value.operation_id,"previousEpoch":value.previous_epoch,"epoch":value.epoch,
        "nextSequence":value.next_sequence.to_string(),"archiveSeal":value.archive_seal},
        "durability":"confirmed","alreadyCompleted":value.already_completed,
        "nextStep":"restart-with-audit-enabled-and-recover-original-application-operations-without-replay"})
}
pub(super) fn transfer(value: AuditTransferReceipt) -> Value {
    json!({"receipt":{"operationId":value.operation_id,"epoch":value.epoch,"archiveSeal":value.archive_seal,
        "transferredThrough":value.transferred_through.to_string(),"destinationDigest":value.destination_digest},
        "durability":"confirmed","externalCustodyResponsibility":"operator",
        "nextStep":"retain-verified-external-history-and-continue-explicit-maintenance"})
}
pub(super) fn page(value: AuditArchivePage) -> Result<Value, PlatformError> {
    let mut records = Vec::with_capacity(value.records.len());
    for record in value.records {
        let mut encoded = serde_json::to_value(record).map_err(|_| invalid())?;
        decimal_counters(&mut encoded, 0)?;
        records.push(encoded);
    }
    let stop = match value.coverage.stop {
        AuditPageStop::End => "end", AuditPageStop::PageLimit => "page-limit",
        AuditPageStop::ByteLimit => "byte-limit", AuditPageStop::ScanLimit => "scan-limit",
    };
    Ok(json!({"archive":coverage(value.archive),"records":records,
        "recordFormat":"latent.audit.stored-record.decimal-counters.v1",
        "coverage":{"epoch":value.coverage.epoch,"retainedFloor":value.coverage.retained_floor.to_string(),
            "highWatermark":value.coverage.high_watermark.to_string(),"scanned":value.coverage.scanned.to_string(),
            "stop":stop,"droppedObservations":value.coverage.dropped_observations.to_string(),
            "unknownOutcomes":value.coverage.unknown_outcomes.to_string(),
            "previousSessionLossUnknown":value.coverage.previous_session_loss_unknown},
        "nextPageToken":value.next_cursor.map(|cursor| cursor.0)}))
}
/// Offline archive records retain the closed stored-record graph, converting
/// every unsigned numeric field to a decimal string, including formatVersion.
/// This is an explicitly named format, not a lossy copy of the RPC projection.
fn decimal_counters(value: &mut Value, depth: usize) -> Result<(), PlatformError> {
    if depth > 16 { return Err(invalid()); }
    match value {
        Value::Number(number) => { *value = Value::String(number.as_u64().ok_or_else(invalid)?.to_string()); }
        Value::Object(fields) => for value in fields.values_mut() { decimal_counters(value, depth + 1)?; },
        Value::Array(values) => for value in values { decimal_counters(value, depth + 1)?; },
        _ => {}
    }
    Ok(())
}
fn invalid() -> PlatformError {
    PlatformError { code: PlatformErrorCode::CorruptArtifact, message: "audit-corrupt".into(), retryable: false, details: Vec::new() }
}
