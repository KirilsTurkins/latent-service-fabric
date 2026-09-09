use std::future::poll_fn;
use std::task::{Context, Poll};
use std::time::Instant;

use latent_artifacts::content_digest;
use latent_core::{BoxFuture, BudgetConsumption};
use latent_executor::{ExecutionBackend, ExecutionCleanup, ExecutionReport, GuestOutcome};
use latent_wasmtime::WasmtimeBackend;
use serde_json::{json, Value};

use super::{
    context::Context as InputContext,
    observation,
    request::{self, Control, Template},
    Result, Writer,
};

/// Symbol-proved frame covering actual request and execution-future construction.
#[inline(never)]
pub(super) fn construct_invocation<'a>(
    backend: &'a WasmtimeBackend,
    template: &Template,
    context: &InputContext,
    payload: &[u8],
    control: &'a Control,
    function: &str,
) -> BoxFuture<'a, ExecutionReport> {
    let request = request::build(template, context, payload, control, function);
    // Keep this named attribution frame across the actual allocation; do not
    // permit the final call to become an unrepresented tail call.
    std::hint::black_box(backend.invoke_contained(request, control))
}

/// This exact monomorphic frame adds no allocation, observation or scheduling.
#[inline(never)]
pub(super) fn poll_invocation(
    future: &mut BoxFuture<'_, ExecutionReport>,
    cx: &mut Context<'_>,
) -> Poll<ExecutionReport> {
    std::hint::black_box(future.as_mut().poll(cx))
}

pub(super) struct Case<'a> {
    pub shape: &'a str,
    pub phase: &'a str,
    pub iteration: u32,
    pub ordinal: u32,
    pub context: &'a InputContext,
    pub payload: &'a [u8],
}

pub(super) async fn run(
    backend: &WasmtimeBackend,
    template: &Template,
    case: Case<'_>,
    writer: &mut Writer,
    origin: Instant,
) -> Result<()> {
    let control = Control::new(request::identifier(case.ordinal))?;
    let function = if case.shape.starts_with("context-") {
        "snapshot"
    } else {
        "echo"
    };
    let construction_started = observation::elapsed(origin);
    let mut future = construct_invocation(
        backend,
        template,
        case.context,
        case.payload,
        &control,
        function,
    );
    let construction_finished = observation::elapsed(origin);
    let invoke_started = observation::elapsed(origin);
    let report = poll_fn(|cx| poll_invocation(&mut future, cx)).await;
    drop(future);
    let invoke_finished = observation::elapsed(origin);
    let timing = backend
        .take_invocation_timing(&control.id)
        .map(super::super::evidence::timing);
    let (outcome, consumed) = report_value(&report);
    let valid = matches!(&report.outcome,Ok(GuestOutcome::Returned {output,output_media_type,..})
        if output_media_type==super::MEDIA && validate_output(output,&control,case.shape,case.payload).is_ok());
    let accounting = control.ledger.finalize_at(consumed, Instant::now());
    writer.sample(&json!({"kind":"invoke","ordinal":case.ordinal.to_string(),"shape":case.shape,
        "phase":case.phase,"iteration":case.iteration.to_string(),"activation_id":control.id.0,
        "fixture_id":template.fixture,"prepared":prepared(template),"payload_sha256":content_digest(case.payload).0,
        "payload_bytes":case.payload.len().to_string(),"context_fixture_id":case.context.shape,
        "budget":observation::budget(control.ledger.granted()),
        "deadline_unix_millis":control.ledger.deadline().unix_millis().map(|v|v.to_string()),
        "construction_started_nanos":construction_started,"construction_finished_nanos":construction_finished,
        "invoke_started_nanos":invoke_started,"invoke_finished_nanos":invoke_finished,"result":outcome,
        "backend_timing":timing,"accounting_after":observation::consumption(accounting.consumption()),
        "outstanding_reservations":control.ledger.outstanding_reservations().to_string(),
        "resources_after":observation::resources(backend.resource_snapshot())}))?;
    if !valid || report.cleanup != ExecutionCleanup::Reusable {
        return Err("ownership normal invocation failed".into());
    }
    observation::idle(backend)
}

pub(super) fn prepared(template: &Template) -> Value {
    let v = &template.prepared;
    json!({"backend":v.backend,"opaque_handle":v.opaque_handle,"metadata":v.metadata,
        "key":{"release":v.key.release.0,"engine_version":v.key.engine_version,
        "engine_configuration_digest":v.key.engine_configuration_digest,"target_triple":v.key.target_triple,
        "cpu_feature_set":v.key.cpu_feature_set}})
}

pub(super) fn report_value(report: &ExecutionReport) -> (Value, Option<&BudgetConsumption>) {
    let cleanup = match &report.cleanup {
        ExecutionCleanup::Reusable => json!({"disposition":"reusable","reason":null}),
        ExecutionCleanup::Quarantine { reason } => {
            json!({"disposition":"quarantine","reason":reason})
        }
    };
    let (kind, code, output, consumed) = match &report.outcome {
        Ok(GuestOutcome::Returned {
            output,
            output_media_type,
            consumption,
        }) => (
            "success",
            None,
            json!({"sha256":content_digest(output).0,"bytes":output.len().to_string(),"media_type":output_media_type,
                "utf8":if output.len()<=16_384 {std::str::from_utf8(output).ok()} else {None}}),
            Some(consumption),
        ),
        Ok(GuestOutcome::DeclaredError { error, consumption }) => (
            "declared-error",
            Some(error.code.clone()),
            Value::Null,
            Some(consumption),
        ),
        Ok(GuestOutcome::Trapped { consumption, .. }) => (
            "trap",
            Some("guest-trap".into()),
            Value::Null,
            Some(consumption),
        ),
        Ok(GuestOutcome::Interrupted {
            kind, consumption, ..
        }) => (
            "interrupted",
            Some(format!("{kind:?}")),
            Value::Null,
            Some(consumption),
        ),
        Err(error) => (
            "platform-failure",
            Some(format!("{:?}", error.code)),
            Value::Null,
            None,
        ),
    };
    (
        json!({"outcome":kind,"code":code,"output":output,"consumption":consumed.map(observation::consumption),"cleanup":cleanup}),
        consumed,
    )
}

fn validate_output(bytes: &[u8], control: &Control, shape: &str, payload: &[u8]) -> Result<()> {
    if !shape.starts_with("context-") {
        if bytes != payload {
            return Err("ownership echo parity".into());
        }
        return Ok(());
    }
    if bytes.len() > 16_384 {
        return Err("ownership context output bound".into());
    }
    let values: Vec<Value> = serde_json::from_slice(bytes)?;
    let value = values
        .first()
        .filter(|_| values.len() == 1)
        .ok_or("ownership context output frame")?;
    let id = &control.id.0;
    if value["activation"] != *id
        || value["root"] != *id
        || value["parent"] != json!({"some":id})
        || value["principal"]["subject"] != *id
        || value["principal"]["kind"] != "service"
        || value["principal"]["tenant"] != json!({"some":"tests"})
        || value["principal"]["service"] != json!({"some":"ownership-caller"})
        || value["principal"]["claims"] != json!([["role", "reader"]])
        || value["trace"]["trace-id"] != "11111111111111111111111111111111"
        || value["trace"]["span-id"] != "1111111111111111"
        || value["trace"]["trace-flags"] != 1
        || value["trace"]["baggage"] != json!([["locale", "en"]])
        || value["metadata"] != json!([["guest.visible", id]])
        || value["deadline"]
            != json!({"some":control.ledger.deadline().unix_millis().map(|v|v.to_string())})
    {
        return Err("ownership context semantic projection".into());
    }
    let remaining = &value["remaining"];
    let grant = control.ledger.granted();
    for (field, maximum, strictly_used) in [
        ("cpu-fuel", grant.cpu_fuel, true),
        ("memory-bytes", grant.memory_bytes, true),
        ("log-bytes", grant.log_bytes, false),
    ] {
        let text = remaining[field]
            .as_str()
            .ok_or("ownership remaining budget type")?;
        let actual: u64 = text.parse()?;
        if actual.to_string() != text || actual > maximum || strictly_used && actual == maximum {
            return Err("ownership remaining budget range".into());
        }
    }
    Ok(())
}
