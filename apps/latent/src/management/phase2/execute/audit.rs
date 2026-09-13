use crate::management::phase2::{invalid_input, invalid_response, projection::Project, proto};
use crate::{client::Session, error::Failure, output::Outcome};
use proto::audit_service_client::AuditServiceClient;
pub(super) async fn query(
    request: proto::QueryPhase2AuditRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let scope = request.scope.as_ref().ok_or_else(invalid_input)?.clone();
    let filter = request.filter.clone().unwrap_or_default();
    let count = request.page.as_ref().map_or(0, |p| p.page_size);
    let value = call!(session, AuditServiceClient, query_phase2_audit, request);
    let coverage = value.coverage.as_ref().ok_or_else(invalid_response)?;
    if value.page.is_none() || coverage.epoch.is_empty() {
        return Err(invalid_response());
    }
    crate::management::association::page_count(value.records.len(), count)?;
    let mut previous = 0;
    for record in &value.records {
        check_kind(record, filter.kind)?;
        if record.format_version != 1
            || record.scope.as_ref() != Some(&scope)
            || record.epoch != coverage.epoch
            || record.sequence <= previous
            || record.sequence > coverage.high_watermark
            || filter
                .from_unix_millis
                .is_some_and(|v| record.accepted_at_unix_millis < v)
            || filter
                .to_unix_millis
                .is_some_and(|v| record.accepted_at_unix_millis > v)
            || filter
                .actor_subject
                .as_ref()
                .is_some_and(|actor| record.actor.as_ref().is_none_or(|v| &v.subject != actor))
        {
            return Err(invalid_response());
        }
        previous = record.sequence;
    }
    // Coverage and unresolved/lost observations remain explicit; a completed
    // scan never becomes a claim that the historical journal is complete.
    Ok(Outcome::success(value.project()))
}

fn check_kind(record: &proto::Phase2AuditRecord, expected: Option<i32>) -> Result<(), Failure> {
    if expected.is_some_and(|expected| {
        !matches!(&record.data,
        Some(proto::phase2_audit_record::Data::Observation(value)) if value.kind == expected)
    }) {
        return Err(invalid_response());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn kind_filter_rejects_other_observations_and_critical_records() {
        let mut record = proto::Phase2AuditRecord {
            data: Some(proto::phase2_audit_record::Data::Observation(
                proto::Phase2AuditObservation {
                    kind: proto::Phase2AuditEventKind::CacheHit as i32,
                    ..proto::Phase2AuditObservation::default()
                },
            )),
            ..proto::Phase2AuditRecord::default()
        };
        assert!(check_kind(&record, Some(proto::Phase2AuditEventKind::CacheHit as i32)).is_ok());
        assert!(check_kind(&record, Some(proto::Phase2AuditEventKind::CacheMiss as i32)).is_err());
        record.data = Some(proto::phase2_audit_record::Data::Attempt(
            proto::Phase2AuditAttempt::default(),
        ));
        assert!(check_kind(&record, Some(proto::Phase2AuditEventKind::CacheHit as i32)).is_err());
        assert!(check_kind(&record, None).is_ok());
    }
}
