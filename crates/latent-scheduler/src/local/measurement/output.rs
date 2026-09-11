use std::io::{self, Write};

use latent_core::PlatformError;
use serde_json::{json, Value};

use crate::CellClass;

use super::fixture::Fixture;
use super::input::Input;
use super::offer::Row;
use super::{Clock, Result};

pub(super) fn event(input: &Input, clock: Clock, complete: bool) -> Value {
    json!({
        "schema": if complete { "latent.optimization.scheduler-complete.v1" } else { "latent.optimization.scheduler-ready.v1" },
        "event": if complete { "measurement-complete" } else { "ready" },
        "process_id": std::process::id(),
        "plan_sha256": input.plan_sha256, "identity_sha256": input.identity_sha256,
        "case": input.plan.case, "mode": input.plan.mode, "variant": input.plan.variant,
        "observation_hold_millis": input.plan.observation_hold_millis,
        "elapsed_nanos": clock.now().to_string(),
    })
}

pub(super) fn emit(value: &Value) -> Result<()> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.len() > 65_536 {
        return Err("scheduler event bound".into());
    }
    let mut output = io::stdout().lock();
    // Isolate the event from libtest's non-newline test-name prefix.
    output.write_all(b"\n")?;
    output.write_all(&bytes)?;
    output.write_all(b"\n")?;
    output.flush()?;
    Ok(())
}

fn error(value: &PlatformError) -> Value {
    json!({"code": value.code.wire_code(), "message": value.message,
        "retryable": value.retryable,
        "details": value.details.iter().map(|detail| json!({"kind":detail.kind,"fields":detail.fields})).collect::<Vec<_>>()})
}

pub(super) fn row(value: &Row) -> Value {
    let decimal = |value: Option<u64>| value.map(|number| number.to_string());
    json!({
        "ordinal": value.ordinal.to_string(), "tenant": value.tenant.to_string(),
        "activation_id": super::fixture::id(value.ordinal).0, "role": value.role,
        "scheduled_nanos": value.scheduled.to_string(), "dispatched_nanos": value.dispatched.to_string(),
        "admission_started_nanos": decimal(value.admission_started),
        "admission_finished_nanos": decimal(value.admission_finished),
        "admitted_nanos": decimal(value.admitted), "deadline_nanos": decimal(value.deadline),
        "deadline_unix_millis": decimal(value.deadline_unix_millis),
        "enqueue_called_nanos": decimal(value.enqueue_called), "result_nanos": decimal(value.result),
        "release_started_nanos": decimal(value.release_started), "released_nanos": decimal(value.released),
        "cancel_requested_nanos": decimal(value.cancel_requested),
        "cancel_finished_nanos": decimal(value.cancel_finished), "cancel_accepted": value.cancel_accepted,
        "cancel_error": value.cancel_error.as_ref().map(error),
        "outcome": value.outcome, "error": value.error.as_ref().map(error),
        "cleanup_reclaimed": value.cleanup_reclaimed,
    })
}

pub(super) fn checkpoint(fixture: &Fixture, label: &str, clock: Clock) -> Result<Value> {
    let started = clock.now();
    let state = fixture.scheduler.observations(CellClass::Standard);
    let quota = fixture.quotas.usage().map_err(super::platform)?;
    let tenants = fixture
        .quotas
        .retained_tenant_count()
        .map_err(super::platform)?;
    let work = fixture
        .scheduler
        .work_snapshot(CellClass::Standard)
        .ok_or("missing work class")?;
    Ok(json!({
        "label":label, "started_nanos":started.to_string(), "finished_nanos":clock.now().to_string(),
        "scheduler":{
            "accepting":state.accepting,"capacity":state.capacity.to_string(),"available":state.available.to_string(),
            "active_leases":state.active_leases.to_string(),"quarantined":state.quarantined.to_string(),
            "queue_depth":state.queue_depth.to_string(),"queued_tenants":state.queued_tenants.to_string(),
            "rejected":state.rejected.to_string(),"cancellations":state.cancellations.to_string(),
            "expired":state.expired.to_string(),"granted":state.granted.to_string(),
            "total_wait_micros":state.total_wait_micros.to_string(),"max_wait_micros":state.max_wait_micros.to_string(),
            "oldest_lease_age_micros":state.oldest_lease_age_micros.to_string(),
        },
        "quota":{
            "active_activations":quota.active_activations.to_string(),"queued_activations":quota.queued_activations.to_string(),
            "reserved_cpu_fuel":quota.reserved_cpu_fuel.to_string(),"reserved_memory_bytes":quota.reserved_memory_bytes.to_string(),
            "retained_tenants":tenants.to_string(),
        },
        "work":{
            "enabled":work.enabled,"overflowed":work.overflowed,
            "tenant_linear_visits":work.tenant_linear_visits.to_string(),"winner_comparisons":work.winner_comparisons.to_string(),
            "cancel_entry_visits":work.cancel_entry_visits.to_string(),"entry_shifted_slots":work.entry_shifted_slots.to_string(),
            "tenant_shifted_slots":work.tenant_shifted_slots.to_string(),"entry_unlinks":work.entry_unlinks.to_string(),
            "tenant_index_lookups":work.tenant_index_lookups.to_string(),
        },
    }))
}

pub(super) fn counts(rows: &[Row], shutdown_calls: u32) -> Value {
    let count =
        |predicate: fn(&Row) -> bool| rows.iter().filter(|row| predicate(row)).count().to_string();
    json!({
        "offers":rows.len().to_string(),
        "admission_calls":count(|row|row.admission_started.is_some()),
        "admitted":count(|row|row.admitted.is_some()),
        "enqueue_calls":count(|row|row.enqueue_called.is_some()),
        "enqueue_results":count(|row|row.result.is_some()),
        "cancel_calls":count(|row|row.cancel_requested.is_some()),
        "cancel_accepted":count(|row|row.cancel_accepted==Some(true)),
        "release_calls":count(|row|row.release_started.is_some()),
        "released":count(|row|row.released.is_some()),
        "cleanup_reclaims":count(|row|row.cleanup_reclaimed),
        "shutdown_calls":shutdown_calls.to_string(),
    })
}
