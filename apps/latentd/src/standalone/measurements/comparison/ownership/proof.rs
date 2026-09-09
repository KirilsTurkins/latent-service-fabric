use std::future::poll_fn;
use std::task::Poll;
use std::time::Instant;

use latent_artifacts::content_digest;
use latent_executor::{ExecutionCleanup, GuestInterruptionKind, GuestOutcome};
use latent_wasmtime::{InvocationInputObserver, InvocationInputPhase, WasmtimeBackend};
use serde_json::{json, Value};

use super::{
    call,
    context::Context,
    observation,
    request::{self, Control, Template},
    Result, Writer,
};

pub(super) async fn run(
    backend: &WasmtimeBackend,
    template: &Template,
    observer: &InvocationInputObserver,
    ordinal: u32,
    drop_pending: bool,
    writer: &mut Writer,
    origin: Instant,
) -> Result<()> {
    let control = Control::new(request::identifier(ordinal))?;
    let context = Context::small();
    let mut payload = vec![b' '; 65_536];
    payload[..2].copy_from_slice(b"[]");
    let started = observation::elapsed(origin);
    let before = observation::input(observer, origin)?;
    let mut future =
        call::construct_invocation(backend, template, &context, &payload, &control, "spin");
    let mut polls = 0_u64;
    let mut early = None;
    poll_fn(|cx| {
        polls = polls.checked_add(1).expect("bounded proof poll count");
        match call::poll_invocation(&mut future, cx) {
            Poll::Ready(report) => {
                early = Some(report);
                Poll::Ready(())
            }
            Poll::Pending => {
                let snapshot = observer.snapshot();
                let token = snapshot
                    .identities
                    .iter()
                    .find(|v| v.activation_id == control.id)
                    .map(|v| v.token);
                if snapshot.records.iter().any(|r| {
                    Some(r.token) == token && r.phase == InvocationInputPhase::GuestCallStart
                }) {
                    Poll::Ready(())
                } else {
                    Poll::Pending
                }
            }
        }
    })
    .await;
    let pending = early.is_none();
    let pending_at = observation::elapsed(origin);
    let pending_input = observation::input(observer, origin)?;
    let pending_resources = observation::resources(backend.resource_snapshot());
    let action_at = observation::elapsed(origin);
    let report = if early.is_some() {
        early
    } else if drop_pending {
        None
    } else {
        control.cancel();
        Some(poll_fn(|cx| call::poll_invocation(&mut future, cx)).await)
    };
    drop(future);
    let destroyed_at = observation::elapsed(origin);
    let after = observation::input(observer, origin)?;
    let (result, consumed) = report
        .as_ref()
        .map_or((Value::Null, None), call::report_value);
    let finalization = control.ledger.finalize_at(consumed, Instant::now());
    let valid = pending
        && (drop_pending
            || report.as_ref().is_some_and(|r| {
                r.cleanup == ExecutionCleanup::Reusable
                    && matches!(
                        &r.outcome,
                        Ok(GuestOutcome::Interrupted {
                            kind: GuestInterruptionKind::Cancelled,
                            ..
                        })
                    )
            }));
    writer.sample(&json!({"kind":"proof","ordinal":ordinal.to_string(),
        "proof":if drop_pending {"drop-pending"} else {"cancel-pending"},"activation_id":control.id.0,
        "prepared":call::prepared(template),"payload_sha256":content_digest(&payload).0,"payload_bytes":"65536",
        "budget":observation::budget(control.ledger.granted()),
        "deadline_unix_millis":control.ledger.deadline().unix_millis().map(|v|v.to_string()),
        "started_nanos":started,"pending_observed_nanos":pending_at,"pending":pending,"polls":polls.to_string(),
        "action_nanos":action_at,"future_destroyed_nanos":destroyed_at,
        "before":before,"at_pending":pending_input,"after":after,"pending_resources":pending_resources,
        "result":result,"accounting_after":observation::consumption(finalization.consumption()),
        "outstanding_reservations":control.ledger.outstanding_reservations().to_string(),
        "resources_after":observation::resources(backend.resource_snapshot()),
        "backend_timing":backend.take_invocation_timing(&control.id).map(super::super::evidence::timing)}))?;
    if !valid {
        return Err("ownership proof did not reach expected boundary".into());
    }
    observation::idle(backend)
}
