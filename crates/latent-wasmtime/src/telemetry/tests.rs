use super::*;
use crate::bindings::latent::log::log;
use crate::host::{ActivationHostContext, InvocationLogBuffer};
use crate::BoundedLogSink;
use latent_core::{
    ActivationBudget, ActivationId, ClockSample, EffectiveActivationBudget, InvocationPrincipal,
    Metadata, PlatformError, PlatformErrorCode, PrincipalKind, ResourceBudget,
    SystemActivationClock,
};
use std::time::Instant;

struct FaultObserver {
    panic: bool,
}
impl GuestLogObserver for FaultObserver {
    fn on_guest_log(&self, _: GuestLogRecord<'_>) -> Result<(), PlatformError> {
        assert!(!self.panic, "observer test panic");
        Err(PlatformError {
            code: PlatformErrorCode::Unavailable,
            message: "explicit strict rejection".into(),
            retryable: false,
            details: Vec::new(),
        })
    }
}
fn context() -> ActivationHostContext {
    ActivationHostContext::new(
        ActivationId("bridge".into()),
        ActivationId("root".into()),
        None,
        InvocationPrincipal {
            subject: "principal".into(),
            kind: PrincipalKind::User,
            tenant: None,
            service: None,
            claims: Metadata::new(),
        },
        "trace".into(),
        "span".into(),
        1,
        Metadata::new(),
        None,
        Metadata::new(),
    )
}
fn budget() -> ActivationBudget {
    let grant = ResourceBudget {
        cpu_fuel: 1000,
        memory_bytes: 65_536,
        log_bytes: 4096,
        wall_time_limit_millis: None,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        effect_count: 0,
    };
    ActivationBudget::new(
        EffectiveActivationBudget::admit_at(
            &grant,
            &grant,
            &grant,
            None,
            ClockSample::new(1000, Instant::now()),
        )
        .unwrap(),
    )
}

#[test]
fn observer_panic_is_counted_without_changing_accepted_log_or_budget() {
    let bridge = Arc::new(TelemetryLogSink::new(
        Arc::new(FaultObserver { panic: true }),
        Arc::new(SystemActivationClock),
    ));
    let capture = BoundedLogSink::with_target(1, 4096, Some(bridge.clone()));
    let accounting = budget();
    let mut logs = InvocationLogBuffer::new(2, 4096, accounting.clone(), capture.clone());
    assert!(logs
        .write(&context(), log::Level::Info, "accepted".into(), &[])
        .unwrap());
    assert_eq!(bridge.observer_panics(), 1);
    let entries = capture.snapshot();
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].message, "accepted");
    let encoded_bytes = u64::try_from(serde_json::to_vec(&entries[0]).unwrap().len()).unwrap();
    assert_eq!(
        accounting.snapshot_at(Instant::now()).log_bytes,
        encoded_bytes
    );
    assert_eq!(accounting.outstanding_reservations(), 0);
}

#[test]
fn explicit_observer_error_becomes_host_unavailable_and_refunds_reservation() {
    let bridge = Arc::new(TelemetryLogSink::new(
        Arc::new(FaultObserver { panic: false }),
        Arc::new(SystemActivationClock),
    ));
    let capture = BoundedLogSink::with_target(1, 4096, Some(bridge.clone()));
    let accounting = budget();
    let mut logs = InvocationLogBuffer::new(2, 4096, accounting.clone(), capture.clone());
    assert!(matches!(
        logs.write(&context(), log::Level::Info, "rejected".into(), &[]),
        Err(log::LogError::Unavailable)
    ));
    assert_eq!(bridge.observer_panics(), 0);
    assert!(capture.snapshot().is_empty());
    assert_eq!(accounting.snapshot_at(Instant::now()).log_bytes, 0);
    assert_eq!(accounting.outstanding_reservations(), 0);
}
